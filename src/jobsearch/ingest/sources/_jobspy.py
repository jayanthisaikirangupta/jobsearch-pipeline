"""Shared JobSpy invocation helper. JobSpy backs Indeed/Glassdoor/LinkedIn."""
from __future__ import annotations

import hashlib
import logging

import pandas as pd

from ...config import get_settings
from ..base import Query


# Silence JobSpy's loud ERROR logs. JobSpy uses logging.basicConfig() at
# import time which adds a root handler — setting per-logger level alone
# isn't enough, we also need disable + propagate=False so the records never
# escape. The runner already prints a clean failure message per source.
def _silence_jobspy() -> None:
    import jobspy  # noqa: F401  triggers JobSpy's basicConfig()
    for name in ("JobSpy", "JobSpy:Glassdoor", "JobSpy:Indeed",
                 "JobSpy:Linkedin", "JobSpy:LinkedIn", "JobSpy:Bayt", "JobSpy:Naukri"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.CRITICAL + 1)  # higher than CRITICAL = nothing gets through
        lg.propagate = False
        lg.handlers.clear()


_silence_jobspy()


# Glassdoor's findPopularLocationAjax endpoint is fragile + anti-bot. It
# rejects country-only strings AND many "City, Country" forms — it really
# only accepts bare city names like "London". Map the common country aliases
# to a bare city; per-query location_overrides in queries.yaml take precedence.
_COUNTRY_TO_CITY = {
    "united kingdom": "London",
    "uk": "London",
    "great britain": "London",
    "england": "London",
    "united states": "New York",
    "usa": "New York",
}


def _glassdoor_safe_location(loc: str) -> str:
    if not loc:
        return loc
    key = loc.strip().lower()
    if key in _COUNTRY_TO_CITY:
        return _COUNTRY_TO_CITY[key]
    # Strip a trailing country suffix on "City, Country" -> just "City"
    # because findPopularLocationAjax frequently 400s on the longer form.
    if "," in loc:
        first = loc.split(",", 1)[0].strip()
        if first:
            return first
    return loc


def _row_id(site: str, url: str | None, title: str, company: str) -> str:
    base = f"{site}|{url or ''}|{title}|{company}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def fetch_via_jobspy(site: str, query: Query) -> pd.DataFrame:
    """Call JobSpy's `scrape_jobs` for a single site and return a normalized frame."""
    from jobspy import scrape_jobs  # imported lazily so the module loads without it

    settings = get_settings()
    location = query.location_for(site)
    if site == "glassdoor":
        location = _glassdoor_safe_location(location)

    kwargs = dict(
        site_name=[site],
        search_term=query.search_term,
        location=location,
        country_indeed=query.country_indeed,
        hours_old=query.hours_old,
        results_wanted=query.results_wanted,
        description_format=query.description_format,
        distance=query.distance,
        verbose=0,
    )
    if query.is_remote is not None:
        kwargs["is_remote"] = query.is_remote
    if settings.jobspy_proxy:
        kwargs["proxies"] = [settings.jobspy_proxy]

    raw = scrape_jobs(**kwargs)
    if raw is None or raw.empty:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "id": [
                _row_id(site, r.get("job_url"), r.get("title", ""), r.get("company", ""))
                for _, r in raw.iterrows()
            ],
            "title": raw.get("title"),
            "company": raw.get("company"),
            "location": raw.get("location"),
            "description": raw.get("description"),
            "url": raw.get("job_url"),
            "posted_at": raw.get("date_posted"),
            "min_amount": raw.get("min_amount"),
            "max_amount": raw.get("max_amount"),
            "currency": raw.get("currency"),
            "interval": raw.get("interval"),
        }
    )
    return out

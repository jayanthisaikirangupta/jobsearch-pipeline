"""Lever public Postings API source.

Lever hosts careers for UK companies that aren't on Greenhouse — Plaid,
Mastercard's tech orgs, several FinTech and AI startups (9fin, Capsa).
The Postings API is unauthenticated and documented at
github.com/lever/postings-api. Per-site endpoint:

    GET https://api.lever.co/v0/postings/{site}?mode=json

Site list lives in config/sponsor_tokens.yaml under ``lever:``. Discovery
is the same script as Greenhouse — careers.<co>.com → jobs.lever.co/<X>.

Lever returns more structured fields than Greenhouse (salaryRange,
workplaceType, commitment) which we surface to the scorer where present.
"""
from __future__ import annotations

import hashlib
import html as _html
import re

import httpx
import pandas as pd
import yaml

from ...config import _PROJECT_ROOT
from ..base import BaseSource, Query


_API = "https://api.lever.co/v0/postings/{site}"
_TIMEOUT = 15.0
_TOKENS_PATH = _PROJECT_ROOT / "config" / "sponsor_tokens.yaml"


def _load_sites() -> list[str]:
    if not _TOKENS_PATH.exists():
        return []
    cfg = yaml.safe_load(_TOKENS_PATH.read_text(encoding="utf-8")) or {}
    raw = cfg.get("lever") or []
    seen, out = set(), []
    for s in raw:
        s = str(s).strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _row_id(site: str, internal_id: str | None,
            title: str, company: str) -> str:
    base = f"lever|{site}|{internal_id or ''}|{title}|{company}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    decoded = _html.unescape(text)
    return re.sub(r"<[^>]+>", " ", decoded)


def _matches_search(title: str, content: str, search_term: str) -> bool:
    if not search_term:
        return True
    needles = [s.strip().lower() for s in search_term.split(" OR ") if s.strip()]
    haystack = (title + " " + content).lower()
    return any(n in haystack for n in needles) if needles else True


def _matches_location(loc: str, target: str) -> bool:
    """True if a job's posted location matches the user's target.

    UK-generic targets ("United Kingdom", "UK") match any UK city/region.
    City-specific targets ("Edinburgh, Scotland") match the city name.
    """
    if not target:
        return True
    target_lower = target.lower()
    loc_lower = (loc or "").lower()

    # UK-generic targets: match any UK location keyword
    if "united kingdom" in target_lower or target_lower.strip() in ("uk", "gb"):
        return any(uk in loc_lower for uk in
                   ("united kingdom", "uk", " gb", "england", "scotland",
                    "wales", "london", "manchester", "edinburgh", "cambridge",
                    "bristol", "leeds", "glasgow", "milton keynes"))

    # City-specific: extract meaningful tokens (drop "united", "kingdom", etc)
    target_words = {w.strip(",.").lower()
                    for w in re.split(r"[\s,/]+", target)
                    if len(w) > 2 and w.lower() not in {"united", "kingdom", "uk", "gb"}}
    if not target_words:
        return target_lower in loc_lower
    return any(w in loc_lower for w in target_words)


def _amount(salary: dict | None, key: str) -> int | float:
    if not salary:
        return pd.NA
    v = salary.get(key)
    return v if isinstance(v, (int, float)) else pd.NA


class Source(BaseSource):
    key = "lever"

    def fetch(self, query: Query) -> pd.DataFrame:
        sites = _load_sites()
        if not sites:
            return self.normalize(pd.DataFrame(), self.key)

        records: list[dict] = []
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "jobsearch-pipeline/0.1"}) as c:
            for site in sites:
                try:
                    r = c.get(_API.format(site=site), params={"mode": "json"})
                    if r.status_code != 200:
                        continue
                    payload = r.json()
                except (httpx.HTTPError, ValueError):
                    continue

                # Lever returns either a list of postings OR a list of groups
                # (when ?group=team etc). The default mode=json gives a flat list.
                postings = payload if isinstance(payload, list) else []

                for p in postings:
                    title = str(p.get("text") or "")
                    cats = p.get("categories") or {}
                    location = str(cats.get("location") or "")
                    description = _strip_html(
                        p.get("descriptionPlain") or p.get("description") or ""
                    )

                    if not _matches_location(location, query.location):
                        continue
                    if not _matches_search(title, description, query.search_term):
                        continue

                    salary = p.get("salaryRange") or {}
                    records.append({
                        "id": _row_id(site, p.get("id"), title, site),
                        "title": title,
                        "company": site.replace("-", " ").title(),
                        "location": location,
                        "description": description,
                        "url": str(p.get("hostedUrl") or ""),
                        "posted_at": str(p.get("createdAt") or ""),
                        "min_amount": _amount(salary, "min"),
                        "max_amount": _amount(salary, "max"),
                        "currency": str(salary.get("currency") or "") or pd.NA,
                        "interval": str(salary.get("interval") or "") or pd.NA,
                    })

        df = pd.DataFrame(records)
        return self.normalize(df, self.key)

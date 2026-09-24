"""Greenhouse public Job Board API source.

Greenhouse hosts the careers page for ~30% of UK tech sponsors (Monzo,
Stripe, Cloudflare, MongoDB, Octopus Energy, GitHub, Notion, …). The
Job Board API is unauthenticated, returns full job descriptions, and
is documented at developers.greenhouse.io. Per-token endpoint:

    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Token list lives in config/sponsor_tokens.yaml under the ``greenhouse:``
key. Discovered via scripts/discover_ats_tokens.py against the gov.uk
sponsor register; manually-verified entries committed in seed YAML.

Why this matters: jobs land in Greenhouse hours-to-days BEFORE Indeed/
LinkedIn scrape them, so this source surfaces fresh sponsor roles that
the existing JobSpy ingest misses. Sponsorship is implicit (we only
query companies on the gov.uk register).
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from pathlib import Path

import httpx
import pandas as pd
import yaml

from ...config import _PROJECT_ROOT
from ..base import BaseSource, Query
from ._ats_common import load_tokens as _shared_load_tokens


_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_TIMEOUT = 15.0
_TOKENS_PATH = _PROJECT_ROOT / "config" / "sponsor_tokens.yaml"


def _load_tokens() -> list[str]:
    # Delegates to the shared loader so both the curated AND the
    # auto-discovered token files feed this source. Lower-cases because
    # Greenhouse board tokens are always lower-case.
    return [t.lower() for t in _shared_load_tokens("greenhouse")]


def _row_id(token: str, internal_id: int | str | None,
            title: str, company: str) -> str:
    base = f"greenhouse|{token}|{internal_id or ''}|{title}|{company}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    # Greenhouse 'content' is HTML-encoded HTML. Decode entities, then
    # strip tags. Good enough for keyword scoring; we don't need a perfect
    # render here.
    decoded = _html.unescape(text)
    return re.sub(r"<[^>]+>", " ", decoded)


def _matches_search(title: str, content: str, search_term: str) -> bool:
    if not search_term:
        return True
    # Treat the search term as a list of OR'd phrases separated by " OR "
    # (mirrors how queries.yaml writes them, e.g. "GenAI Engineer OR LLM Engineer").
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

    target_words = {w.strip(",.").lower()
                    for w in re.split(r"[\s,/]+", target)
                    if len(w) > 2 and w.lower() not in {"united", "kingdom", "uk", "gb"}}
    if not target_words:
        return target_lower in loc_lower
    # Multi-word cities (Milton Keynes, Hemel Hempstead) need ALL tokens to
    # match, otherwise "Milton Park, London" leaks into a Milton Keynes search.
    return all(w in loc_lower for w in target_words)


class Source(BaseSource):
    key = "greenhouse"

    def fetch(self, query: Query) -> pd.DataFrame:
        tokens = _load_tokens()
        if not tokens:
            return self.normalize(pd.DataFrame(), self.key)

        records: list[dict] = []
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "jobsearch-pipeline/0.1"}) as c:
            for token in tokens:
                try:
                    r = c.get(_API.format(token=token), params={"content": "true"})
                    if r.status_code != 200:
                        continue
                    payload = r.json()
                except (httpx.HTTPError, ValueError):
                    continue

                for job in payload.get("jobs", []):
                    title = str(job.get("title") or "")
                    location = str((job.get("location") or {}).get("name") or "")
                    content = _strip_html(job.get("content"))

                    if not _matches_location(location, query.location):
                        continue
                    if not _matches_search(title, content, query.search_term):
                        continue

                    records.append({
                        "id": _row_id(token, job.get("id"), title, token),
                        "title": title,
                        "company": token.replace("-", " ").title(),
                        "location": location,
                        "description": content,
                        "url": str(job.get("absolute_url") or ""),
                        "posted_at": str(job.get("updated_at") or ""),
                        "min_amount": pd.NA,
                        "max_amount": pd.NA,
                        "currency": pd.NA,
                        "interval": pd.NA,
                    })

        df = pd.DataFrame(records)
        return self.normalize(df, self.key)

"""SmartRecruiters public Posting API source.

SmartRecruiters hosts careers for large UK-present enterprises (Experian,
Visa, Bosch, IKEA, ...). Endpoints, unauthenticated:

    GET https://api.smartrecruiters.com/v1/companies/{company}/postings
        ?limit=100&offset=N                      (paginated listing)
    GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}
        (per-posting detail with full jobAd description sections)

The listing does NOT include descriptions, so this source filters the
listing to UK postings first (location.country == "gb"), then fetches
details only for those — capped per company to bound request volume.
Verified 2026-07-04 by direct probes.

IMPORTANT: company identifiers are case-sensitive ("Experian" works,
"experian" may 404). Token list lives in config/sponsor_tokens.yaml
under ``smartrecruiters:`` and is used verbatim.
"""
from __future__ import annotations

import httpx
import pandas as pd

from ..base import BaseSource, Query
from ._ats_common import (
    TIMEOUT, USER_AGENT, load_tokens, matches_location, matches_search,
    row_id, strip_html,
)

_LIST_API = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
_DETAIL_API = "https://api.smartrecruiters.com/v1/companies/{token}/postings/{pid}"
_PAGE_SIZE = 100
_MAX_PAGES = 5           # up to 500 listings scanned per company
_MAX_DETAILS = 60        # detail fetches per company, keeps runs bounded


def _loc_str(loc: dict | None) -> str:
    loc = loc or {}
    full = str(loc.get("fullLocation") or "")
    if full.strip(", "):
        return full
    return ", ".join(x for x in (str(loc.get("city") or ""),
                                 str(loc.get("country") or "")) if x)


def _is_uk(loc: dict | None) -> bool:
    return ((loc or {}).get("country") or "").lower() in ("gb", "uk", "united kingdom")


def _description(detail: dict) -> str:
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation",
                "companyDescription"):
        sec = sections.get(key) or {}
        parts.append(strip_html(sec.get("text")))
    return "\n".join(p for p in parts if p)


class Source(BaseSource):
    key = "smartrecruiters"

    def fetch(self, query: Query) -> pd.DataFrame:
        tokens = load_tokens("smartrecruiters")
        if not tokens:
            return self.normalize(pd.DataFrame(), self.key)

        records: list[dict] = []
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            for token in tokens:
                # 1) paginate the listing, keep UK postings only
                uk_postings: list[dict] = []
                for page in range(_MAX_PAGES):
                    try:
                        r = c.get(_LIST_API.format(token=token),
                                  params={"limit": _PAGE_SIZE,
                                          "offset": page * _PAGE_SIZE})
                        if r.status_code != 200:
                            break
                        payload = r.json()
                    except (httpx.HTTPError, ValueError):
                        break
                    content = payload.get("content") or []
                    uk_postings.extend(p for p in content if _is_uk(p.get("location")))
                    if len(content) < _PAGE_SIZE:
                        break

                # 2) detail-fetch UK postings for descriptions (bounded)
                for p in uk_postings[:_MAX_DETAILS]:
                    title = str(p.get("name") or "")
                    location = _loc_str(p.get("location"))
                    if not matches_location(location, query.location):
                        continue
                    # Cheap title-level prefilter before spending a detail call
                    if query.search_term and not matches_search(title, "", query.search_term):
                        # Title alone may miss description-only matches; fetch
                        # details anyway only when the title is generic enough
                        # to plausibly hide a match ("Engineer", "Developer").
                        if not any(w in title.lower() for w in ("engineer", "developer", "software", "data", "ai")):
                            continue

                    pid = p.get("id")
                    try:
                        d = c.get(_DETAIL_API.format(token=token, pid=pid))
                        detail = d.json() if d.status_code == 200 else {}
                    except (httpx.HTTPError, ValueError):
                        detail = {}
                    description = _description(detail)

                    if not matches_search(title, description, query.search_term):
                        continue

                    records.append({
                        "id": row_id(self.key, token, pid, title),
                        "title": title,
                        "company": str((p.get("company") or {}).get("name") or token),
                        "location": location,
                        "description": description,
                        "url": str(detail.get("postingUrl") or detail.get("applyUrl")
                                   or (p.get("ref") or "")),
                        "posted_at": str(p.get("releasedDate") or ""),
                        "min_amount": pd.NA,
                        "max_amount": pd.NA,
                        "currency": pd.NA,
                        "interval": pd.NA,
                    })

        return self.normalize(pd.DataFrame(records), self.key)

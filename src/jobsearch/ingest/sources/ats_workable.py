"""Workable public widget API source.

Workable is heavily used by UK SMEs and scale-ups — exactly the mid-size
licensed-sponsor tier this pipeline targets. Endpoint, unauthenticated:

    GET https://apply.workable.com/api/v1/widget/accounts/{account}?details=true

Note on API choice: the v3 endpoint (apply.workable.com/api/v3/accounts/
{account}/jobs) paginates but does NOT return descriptions, forcing one
extra HTTP call per job. The v1 widget endpoint with ``details=true``
returns every published job WITH its full description in a single call,
so it is strictly better for this pipeline. Verified 2026-07-04.

Token list lives in config/sponsor_tokens.yaml under ``workable:``.
Discovery: careers pages hosted at apply.workable.com/<ACCOUNT>.
"""
from __future__ import annotations

import httpx
import pandas as pd

from ..base import BaseSource, Query
from ._ats_common import (
    TIMEOUT, USER_AGENT, load_tokens, matches_location, matches_search,
    row_id, strip_html,
)

_API = "https://apply.workable.com/api/v1/widget/accounts/{token}"


def _location(job: dict) -> str:
    locs = job.get("locations") or []
    parts = []
    for l in locs:
        city, country = str(l.get("city") or ""), str(l.get("country") or "")
        parts.append(", ".join(x for x in (city, country) if x))
    if parts:
        return "; ".join(parts)
    return ", ".join(x for x in (str(job.get("city") or ""),
                                 str(job.get("country") or "")) if x)


class Source(BaseSource):
    key = "workable"

    def fetch(self, query: Query) -> pd.DataFrame:
        tokens = load_tokens("workable")
        if not tokens:
            return self.normalize(pd.DataFrame(), self.key)

        records: list[dict] = []
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            for token in tokens:
                try:
                    r = c.get(_API.format(token=token),
                              params={"details": "true"})
                    if r.status_code != 200:
                        continue
                    payload = r.json()
                except (httpx.HTTPError, ValueError):
                    continue

                for job in payload.get("jobs", []):
                    title = str(job.get("title") or "")
                    location = _location(job)
                    description = strip_html(job.get("description"))

                    if not matches_location(location, query.location):
                        continue
                    if not matches_search(title, description, query.search_term):
                        continue

                    records.append({
                        "id": row_id(self.key, token, job.get("shortcode"), title),
                        "title": title,
                        "company": token.replace("-", " ").title(),
                        "location": location,
                        "description": description,
                        "url": str(job.get("url") or job.get("application_url") or ""),
                        "posted_at": str(job.get("published_on") or job.get("created_at") or ""),
                        "min_amount": pd.NA,
                        "max_amount": pd.NA,
                        "currency": pd.NA,
                        "interval": pd.NA,
                    })

        return self.normalize(pd.DataFrame(records), self.key)

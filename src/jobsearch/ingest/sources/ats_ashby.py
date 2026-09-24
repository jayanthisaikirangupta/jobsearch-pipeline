"""Ashby public Job Board API source.

Ashby hosts careers for a fast-growing slice of UK AI/fintech scale-ups
(Elliptic, Quantexa, Synthesia, Thought Machine, Wayve, ...). Endpoint,
unauthenticated:

    GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true

Returns full descriptions inline (descriptionPlain), so search matching
needs no per-job follow-up calls. Verified 2026-07-04 by direct probes.

Token list lives in config/sponsor_tokens.yaml under ``ashby:``.
Discovery: careers pages that redirect to jobs.ashbyhq.com/<BOARD>.
"""
from __future__ import annotations

import httpx
import pandas as pd

from ..base import BaseSource, Query
from ._ats_common import (
    TIMEOUT, USER_AGENT, load_tokens, matches_location, matches_search,
    row_id, strip_html,
)

_API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def _salary(job: dict) -> tuple:
    """Best-effort (min, max, currency) from Ashby's compensation block."""
    comp = job.get("compensation") or {}
    tiers = comp.get("compensationTiers") or []
    for tier in tiers:
        for c in tier.get("components") or []:
            if (c.get("compensationType") or "").lower() == "salary":
                mn, mx = c.get("minValue"), c.get("maxValue")
                cur = c.get("currencyCode") or ""
                if mn or mx:
                    return (mn if mn else pd.NA, mx if mx else pd.NA,
                            cur or pd.NA, "yearly")
    return (pd.NA, pd.NA, pd.NA, pd.NA)


class Source(BaseSource):
    key = "ashby"

    def fetch(self, query: Query) -> pd.DataFrame:
        tokens = load_tokens("ashby")
        if not tokens:
            return self.normalize(pd.DataFrame(), self.key)

        records: list[dict] = []
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            for token in tokens:
                try:
                    r = c.get(_API.format(token=token),
                              params={"includeCompensation": "true"})
                    if r.status_code != 200:
                        continue
                    payload = r.json()
                except (httpx.HTTPError, ValueError):
                    continue

                for job in payload.get("jobs", []):
                    if job.get("isListed") is False:
                        continue
                    title = str(job.get("title") or "")
                    # Primary + secondary locations, so a "London" secondary
                    # on a "Remote" primary still matches UK targets.
                    secondaries = ", ".join(
                        str(s.get("location") or "")
                        for s in (job.get("secondaryLocations") or [])
                    )
                    location = ", ".join(x for x in
                                         (str(job.get("location") or ""), secondaries) if x)
                    description = strip_html(
                        job.get("descriptionPlain") or job.get("descriptionHtml")
                    )

                    if not matches_location(location, query.location):
                        continue
                    if not matches_search(title, description, query.search_term):
                        continue

                    mn, mx, cur, interval = _salary(job)
                    records.append({
                        "id": row_id(self.key, token, job.get("id"), title),
                        "title": title,
                        "company": token.replace("-", " ").title(),
                        "location": location,
                        "description": description,
                        "url": str(job.get("jobUrl") or job.get("applyUrl") or ""),
                        "posted_at": str(job.get("publishedAt") or ""),
                        "min_amount": mn,
                        "max_amount": mx,
                        "currency": cur,
                        "interval": interval,
                    })

        return self.normalize(pd.DataFrame(records), self.key)

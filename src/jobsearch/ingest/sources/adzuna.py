"""Adzuna Jobs API source (UK).

Adzuna is a UK-based job aggregator with a clean, lawful, free-tier
JSON API. Free tier: 250 calls/day per app_id (developer.adzuna.com).
Endpoint pattern:

    GET https://api.adzuna.com/v1/api/jobs/gb/search/{page}
        ?app_id=...&app_key=...&what=...&where=...&results_per_page=50

Why include this on top of Greenhouse + Lever: Adzuna covers the long
tail of UK sponsors that don't host on Greenhouse or Lever — Capgemini,
NTT DATA, Wavestone, law firms, consultancies. Salary fields are clean
(`salary_min`, `salary_max`, `salary_is_predicted`).

Set ADZUNA_APP_ID + ADZUNA_APP_KEY in .env (free signup at
https://developer.adzuna.com). Without them this source returns 0 rows.
"""
from __future__ import annotations

import hashlib
import os

import httpx
import pandas as pd

from ..base import BaseSource, Query


_API = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
_TIMEOUT = 15.0
_PAGES = 3                 # 3 pages * 50 = 150 results per query
_RESULTS_PER_PAGE = 50


def _row_id(internal_id: str | None, title: str, company: str) -> str:
    base = f"adzuna|{internal_id or ''}|{title}|{company}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


class Source(BaseSource):
    key = "adzuna"

    def fetch(self, query: Query) -> pd.DataFrame:
        app_id = os.getenv("ADZUNA_APP_ID", "").strip()
        app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
        if not app_id or not app_key:
            return self.normalize(pd.DataFrame(), self.key)

        records: list[dict] = []
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "jobsearch-pipeline/0.1"}) as c:
            for page in range(1, _PAGES + 1):
                try:
                    r = c.get(
                        _API.format(page=page),
                        params={
                            "app_id": app_id,
                            "app_key": app_key,
                            "what": query.search_term,
                            "where": query.location,
                            "results_per_page": _RESULTS_PER_PAGE,
                            "max_days_old": max(1, query.hours_old // 24),
                            "sort_by": "date",
                        },
                    )
                    if r.status_code != 200:
                        break
                    payload = r.json()
                except (httpx.HTTPError, ValueError):
                    break

                results = payload.get("results", [])
                if not results:
                    break

                for job in results:
                    company = (job.get("company") or {}).get("display_name") or ""
                    location_obj = job.get("location") or {}
                    location = (
                        location_obj.get("display_name")
                        or ", ".join(location_obj.get("area") or [])
                    )

                    records.append({
                        "id": _row_id(str(job.get("id")), job.get("title", ""), company),
                        "title": str(job.get("title") or ""),
                        "company": str(company),
                        "location": str(location),
                        "description": str(job.get("description") or ""),
                        "url": str(job.get("redirect_url") or ""),
                        "posted_at": str(job.get("created") or ""),
                        "min_amount": job.get("salary_min") or pd.NA,
                        "max_amount": job.get("salary_max") or pd.NA,
                        "currency": "GBP" if job.get("salary_min") else pd.NA,
                        "interval": "yearly" if job.get("salary_min") else pd.NA,
                    })

                if len(results) < _RESULTS_PER_PAGE:
                    break

        df = pd.DataFrame(records)
        return self.normalize(df, self.key)

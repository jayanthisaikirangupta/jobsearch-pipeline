"""UK council / local-government jobs source (wmjobs.co.uk).

WMJobs is the West Midlands Employers' shared job board and syndicates
council, NHS-adjacent, and public-sector vacancies from ~30 English
councils plus schools and combined authorities. Its listing pages are
plain HTML with no bot challenge, unlike jobsgopublic.com and lgjobs.com
(both behind a jobiqo botchallenge stub).

Endpoint pattern (documented by their public search UI):

    GET https://www.wmjobs.co.uk/jobs/
        ?keywords=<term>&locations=<city>&page=<n>

Each card renders as ``<li class="lister__item" id="item-<numeric>">``
with a nested ``<a href="/job/<id>/<slug>/">``. The detail page carries
a ``<div class="mds-tabs__panel__content">`` block for the description
and a ``<dt>/<dd>`` pair grid for employer / location / salary /
closing-date / sector.

Set nothing in .env — this source is free and unauthenticated. It
returns 0 rows if the network / wmjobs.co.uk is unreachable.

The pipeline (dedup, score, tailor, review, dashboard) picks these rows
up like any other source once ``councils`` is registered.
"""
from __future__ import annotations

import hashlib
import re
import time

import httpx
import pandas as pd

from ..base import BaseSource, Query


_BASE = "https://www.wmjobs.co.uk"
_LIST_URL = f"{_BASE}/jobs/"
_TIMEOUT = 15.0
_PAGES = 3  # 3 * ~20 cards per page = ~60 rows / query
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) jobsearch-pipeline/0.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-GB,en;q=0.9",
}


_CARD_RE = re.compile(
    r'<li[^>]+class="lister__item[^"]*"[^>]* id="item-(\d+)"(.*?)</li>\s*'
    r'(?=<li class="lister__item|</ul>)',
    re.S,
)
_HREF_RE = re.compile(r'href="\s*(/job/\d+/[^"\s]+/)', re.S)
_TITLE_RE = re.compile(r'<h3 class="lister__header">.*?<span>([^<]+)</span>', re.S)
_META_RE = re.compile(
    r'<li class="lister__meta-item lister__meta-item--(\w+)"[^>]*>'
    r'([^<]+)</li>',
    re.S,
)
_DETAIL_META_RE = re.compile(
    r'<dt[^>]*>\s*([^<]+?)\s*</dt>\s*<dd[^>]*>(.*?)</dd>',
    re.S,
)
_DETAIL_CONTENT_RE = re.compile(
    r'<div[^>]*class="[^"]*mds-tabs__panel__content[^"]*"[^>]*>(.*?)</div>\s*</div>',
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SALARY_RE = re.compile(
    r"£\s*([\d,]+(?:\.\d+)?)(?:\s*[-–to]+\s*£?\s*([\d,]+(?:\.\d+)?))?",
    re.I,
)


def _row_id(job_id: str, title: str, company: str) -> str:
    base = f"councils|{job_id}|{title}|{company}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def _parse_salary(text: str) -> tuple[float | pd._libs.missing.NAType,
                                       float | pd._libs.missing.NAType]:
    if not text:
        return pd.NA, pd.NA
    m = _SALARY_RE.search(text)
    if not m:
        return pd.NA, pd.NA
    lo = float(m.group(1).replace(",", ""))
    hi = float(m.group(2).replace(",", "")) if m.group(2) else lo
    return lo, hi


def _matches_location(job_location: str, target: str) -> bool:
    """UK-generic targets pass everything; city targets need a token match."""
    if not target:
        return True
    target_lower = target.lower().strip()
    loc_lower = (job_location or "").lower()
    if target_lower in ("united kingdom", "uk", "gb"):
        return True
    target_words = {
        w.strip(",.").lower()
        for w in re.split(r"[\s,/]+", target)
        if len(w) > 2 and w.lower() not in {"united", "kingdom", "uk", "gb"}
    }
    if not target_words:
        return target_lower in loc_lower
    return all(w in loc_lower for w in target_words)


def _matches_search(title: str, description: str, search_term: str) -> bool:
    if not search_term:
        return True
    needles = [s.strip().lower() for s in search_term.split(" OR ") if s.strip()]
    # Title-only match. Full-text hits pull in "Homeless Prevention Officer"
    # rows that mention "AI" once in the JD body — noise the scorer then
    # promotes on unrelated keyword overlap.
    haystack = title.lower()
    return any(n in haystack for n in needles) if needles else True


# Titles that mean "actually a tech role", not a non-tech role that happens
# to name-drop AI / data / software once in the JD. Applied AFTER the search
# term match so we still respect the user's query intent.
_TECH_TITLE_TOKENS = (
    # engineering / development
    "engineer", "developer", "programmer",
    "software", "python", "java ", "javascript",
    "backend", "back-end", "back end",
    "frontend", "front-end", "front end",
    "full stack", "full-stack",
    "devops", "sre", "site reliability", "platform", "cloud",
    # data / analytics / BI (broad — this is where councils actually hire)
    "data ", " data", "data,",
    "analyst", "analytics",
    "business intelligence", " bi ",
    "insight", "insights",
    "reporting", "reports officer",
    "information governance", "information manager",
    # ai / ml / research
    "data scientist", "machine learning", "ml ", " ai ",
    # architecture / systems
    "architect", "systems architect", "solution architect",
    # digital transformation is often the umbrella term councils use
    "digital transformation", "digital lead", "digital manager",
    "digital delivery",
)

# Anti-matches: titles containing these are dropped even if the search
# term matched, because they're non-tech council roles that happened to
# mention a tech keyword in the JD.
_NON_TECH_TITLE_TOKENS = (
    # social / care / education
    "social worker", "childcare", "residential care",
    "occupational therapist", "reablement", "homeless",
    "teaching", "teacher", "tutor", "lecturer", "nurse",
    "sen teaching", "send teaching", "early years",
    # housing / property / estates / planning
    "housing officer", "housing &", "housing and welfare", "housing development",
    "tenancy", "estates surveyor", "planning officer", "planning ",
    "property", "site manager",
    # non-tech "developer" / "engineer" false positives
    "development officer", "development assistant", "development nurse",
    "housing development", "green space development",
    "community development", "highways engineer", "civil engineer",
    "structural engineer", "mechanical engineer", "electrical engineer",
    "sessional lecturer", "training unit",
    # legal / comms / policy / hr
    "communications business partner", "diversity and inclusion",
    "edi officer", "sustainability officer", "welfare",
    "registration officer", "legal officer", "chief of staff",
    "customer experience", "customer intelligence", "trainee programme",
    "gallery", "leisure", "environmental health",
    "civil enforcement", "team leader",
    # non-tech "systems" false positives
    "highways operations systems", "practice and systems",
    "building safety",
    # non-tech "digital" false positives
    "digital marketing", "digital skills",
    # bare IT support / schools ICT — not our shape
    "it technician", "ict technician", "service desk",
    "network technician", "ict cluster",
    # analysts that aren't data
    "policy analyst", "planning analyst", "finance analyst",
    "business support",
    # apprenticeships — you're not a junior
    "apprentice", "apprenticeship",
)


def _is_tech_title(title: str) -> bool:
    t = (title or "").lower()
    if any(bad in t for bad in _NON_TECH_TITLE_TOKENS):
        return False
    return any(tok in t for tok in _TECH_TITLE_TOKENS)


def _fetch_detail(client: httpx.Client, path: str) -> tuple[str, dict[str, str]]:
    """Return (description, meta dict) for one job detail page."""
    try:
        r = client.get(f"{_BASE}{path}")
    except httpx.HTTPError:
        return "", {}
    if r.status_code != 200:
        return "", {}
    html = r.text
    meta: dict[str, str] = {}
    for m in _DETAIL_META_RE.finditer(html):
        key = m.group(1).strip().rstrip(":").lower()
        val = _clean(m.group(2))
        if key and val:
            meta[key] = val
    body = ""
    m = _DETAIL_CONTENT_RE.search(html)
    if m:
        body = _clean(m.group(1))
    return body, meta


class Source(BaseSource):
    key = "councils"

    def fetch(self, query: Query) -> pd.DataFrame:
        records: list[dict] = []
        seen_ids: set[str] = set()

        params_base = {"keywords": query.search_term}
        if query.location:
            loc = query.location.lower().strip()
            if loc not in {"united kingdom", "uk", "gb", ""}:
                params_base["locations"] = query.location

        with httpx.Client(
            timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS
        ) as c:
            for page in range(1, _PAGES + 1):
                params = {**params_base, "page": str(page)}
                try:
                    r = c.get(_LIST_URL, params=params)
                except httpx.HTTPError:
                    break
                if r.status_code != 200:
                    break

                cards = list(_CARD_RE.finditer(r.text))
                if not cards:
                    break

                for m in cards:
                    job_id = m.group(1)
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    card_html = m.group(2)
                    href_m = _HREF_RE.search(card_html)
                    if not href_m:
                        continue
                    path = href_m.group(1).strip()

                    title_m = _TITLE_RE.search(card_html)
                    title = _clean(title_m.group(1)) if title_m else ""

                    meta_bits = {
                        k.strip(): _clean(v)
                        for k, v in _META_RE.findall(card_html)
                    }
                    company = meta_bits.get("recruiter", "")
                    location = meta_bits.get("location", "")
                    salary_txt = meta_bits.get("salary", "")

                    description, detail_meta = _fetch_detail(c, path)
                    if detail_meta:
                        company = company or detail_meta.get("employer", "")
                        location = location or detail_meta.get("location", "")
                        salary_txt = salary_txt or detail_meta.get("salary", "")

                    if not _matches_location(location, query.location):
                        continue
                    if not _matches_search(title, description, query.search_term):
                        continue
                    if not _is_tech_title(title):
                        continue

                    lo, hi = _parse_salary(salary_txt)

                    records.append({
                        "id": _row_id(job_id, title, company),
                        "title": title,
                        "company": company,
                        "location": location,
                        "description": description or salary_txt,
                        "url": f"{_BASE}{path}",
                        "posted_at": detail_meta.get("closing date", ""),
                        "min_amount": lo,
                        "max_amount": hi,
                        "currency": "GBP" if lo is not pd.NA else pd.NA,
                        "interval": "yearly" if lo is not pd.NA else pd.NA,
                    })

                    # Be polite — brief pause between detail hits.
                    time.sleep(0.15)

                if len(cards) < 15:
                    break

        df = pd.DataFrame(records)
        return self.normalize(df, self.key)

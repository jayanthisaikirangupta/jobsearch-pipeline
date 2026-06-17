"""Single-URL extractor.

Turns one job-posting URL into a normalized dict that matches the same
REQUIRED_COLUMNS schema the multi-source ingest emits, so downstream code
(score, tailor, review, tracker, dashboard) doesn't care whether a row
came from a batch ingest or an ad-hoc URL paste.

Resolution order, first hit wins:
  1. Lever URL  (jobs.lever.co/<site>/<id>)        -> Lever public API
  2. Greenhouse URL (boards.greenhouse.io/...)     -> Greenhouse public API
  3. Generic URL                                   -> JSON-LD JobPosting
  4. All fail                                      -> URLExtractionError

Manual fallback lives one level up in pipeline/single_url.py — this
module never prompts; it just extracts or fails.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from .base import REQUIRED_COLUMNS


_TIMEOUT = 15.0
_USER_AGENT = "jobsearch-pipeline/0.1"

# Compiled URL patterns. Each captures the bits we need for the API call.
_LEVER_RE = re.compile(
    r"^https?://jobs\.lever\.co/(?P<site>[^/]+)/(?P<id>[^/?#]+)",
    re.IGNORECASE,
)
_GREENHOUSE_RE = re.compile(
    r"^https?://(?:job-)?boards(?:-api)?\.greenhouse\.io/(?P<token>[^/]+)/jobs/(?P<id>\d+)",
    re.IGNORECASE,
)
# Some companies embed Greenhouse on their own subdomain (e.g.
# boards.greenhouse.io/embed/job_app?for=<token>&token=<id>) — keep the
# common shapes only; weirder embeds fall through to the JSON-LD path.


class URLExtractionError(RuntimeError):
    """Raised when none of the extraction paths produce a usable row."""


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    decoded = _html.unescape(text)
    return re.sub(r"<[^>]+>", " ", decoded)


def _row_id(source: str, *parts: str) -> str:
    base = "|".join([source, *(p or "" for p in parts)]).lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _empty() -> dict:
    """Return a blank row with all REQUIRED_COLUMNS set to pd.NA."""
    return {col: pd.NA for col in REQUIRED_COLUMNS}


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )


# ---- Lever ----------------------------------------------------------------

def _try_lever(url: str) -> dict | None:
    m = _LEVER_RE.match(url)
    if not m:
        return None
    site = m.group("site").lower()
    posting_id = m.group("id")
    api = f"https://api.lever.co/v0/postings/{site}/{posting_id}"
    with _client() as c:
        try:
            r = c.get(api, params={"mode": "json"})
            if r.status_code != 200:
                return None
            payload = r.json()
        except (httpx.HTTPError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("text") or "")
    cats = payload.get("categories") or {}
    location = str(cats.get("location") or "")
    description = _strip_html(
        payload.get("descriptionPlain") or payload.get("description") or ""
    )
    salary = payload.get("salaryRange") or {}

    row = _empty()
    row.update({
        "id": _row_id("lever", site, posting_id, title),
        "source": "lever",
        "title": title,
        "company": site.replace("-", " ").title(),
        "location": location,
        "description": description,
        "url": str(payload.get("hostedUrl") or url),
        "posted_at": str(payload.get("createdAt") or ""),
        "min_amount": salary.get("min") if isinstance(salary.get("min"), (int, float)) else pd.NA,
        "max_amount": salary.get("max") if isinstance(salary.get("max"), (int, float)) else pd.NA,
        "currency": str(salary.get("currency") or "") or pd.NA,
        "interval": str(salary.get("interval") or "") or pd.NA,
    })
    return row if title and description else None


# ---- Greenhouse -----------------------------------------------------------

def _try_greenhouse(url: str) -> dict | None:
    m = _GREENHOUSE_RE.match(url)
    if not m:
        return None
    token = m.group("token").lower()
    job_id = m.group("id")
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
    with _client() as c:
        try:
            r = c.get(api, params={"content": "true"})
            if r.status_code != 200:
                return None
            payload = r.json()
        except (httpx.HTTPError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title") or "")
    location = str((payload.get("location") or {}).get("name") or "")
    description = _strip_html(payload.get("content"))

    row = _empty()
    row.update({
        "id": _row_id("greenhouse", token, job_id, title),
        "source": "greenhouse",
        "title": title,
        "company": token.replace("-", " ").title(),
        "location": location,
        "description": description,
        "url": str(payload.get("absolute_url") or url),
        "posted_at": str(payload.get("updated_at") or ""),
    })
    return row if title and description else None


# ---- JSON-LD --------------------------------------------------------------

def _walk_jobposting(node: Any) -> dict | None:
    """JSON-LD payloads can be a single dict, a list, or a @graph wrapper.
    Walk the structure and return the first node whose @type is JobPosting."""
    if isinstance(node, list):
        for item in node:
            found = _walk_jobposting(item)
            if found:
                return found
        return None
    if not isinstance(node, dict):
        return None
    type_field = node.get("@type")
    if isinstance(type_field, list):
        types = [str(t).lower() for t in type_field]
    else:
        types = [str(type_field or "").lower()]
    if "jobposting" in types:
        return node
    if "@graph" in node:
        return _walk_jobposting(node["@graph"])
    return None


def _flatten_location(loc: Any) -> str:
    """JobPosting jobLocation can be a dict, list, or string. Normalize to
    'City, Region' if possible, else whatever string we can build."""
    if isinstance(loc, list):
        for item in loc:
            s = _flatten_location(item)
            if s:
                return s
        return ""
    if isinstance(loc, str):
        return loc
    if not isinstance(loc, dict):
        return ""
    addr = loc.get("address") or {}
    if isinstance(addr, dict):
        bits = [addr.get("addressLocality"), addr.get("addressRegion"),
                addr.get("addressCountry")]
        clean = [str(b).strip() for b in bits if b]
        return ", ".join(clean)
    return str(loc.get("name") or "")


def _flatten_org(org: Any) -> str:
    if isinstance(org, dict):
        return str(org.get("name") or "")
    if isinstance(org, list) and org:
        return _flatten_org(org[0])
    return str(org or "")


def _flatten_salary(salary: Any) -> tuple[Any, Any, Any, Any]:
    """Return (min_amount, max_amount, currency, interval) from baseSalary."""
    if not isinstance(salary, dict):
        return pd.NA, pd.NA, pd.NA, pd.NA
    currency = salary.get("currency") or pd.NA
    value = salary.get("value")
    if isinstance(value, dict):
        min_a = value.get("minValue") or value.get("value")
        max_a = value.get("maxValue") or value.get("value")
        unit = value.get("unitText") or pd.NA
    else:
        min_a = max_a = value
        unit = pd.NA
    def _n(v):
        return v if isinstance(v, (int, float)) else pd.NA
    return _n(min_a), _n(max_a), currency, unit


def _try_jsonld(url: str) -> dict | None:
    with _client() as c:
        try:
            r = c.get(url)
            if r.status_code != 200:
                return None
            html_body = r.text
        except httpx.HTTPError:
            return None

    soup = BeautifulSoup(html_body, "lxml")
    posting: dict | None = None
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Some sites wrap the JSON in CDATA or have trailing junk;
            # try the loosest possible extraction
            try:
                data = json.loads(raw.strip().rstrip(";"))
            except json.JSONDecodeError:
                continue
        posting = _walk_jobposting(data)
        if posting:
            break
    if not posting:
        return None

    title = str(posting.get("title") or "")
    company = _flatten_org(posting.get("hiringOrganization"))
    location = _flatten_location(posting.get("jobLocation"))
    description = _strip_html(posting.get("description"))
    posted_at = str(posting.get("datePosted") or "")
    min_a, max_a, currency, interval = _flatten_salary(posting.get("baseSalary"))

    if not title or not description:
        return None

    row = _empty()
    row.update({
        "id": _row_id("jsonld", url, title, company),
        "source": "jsonld",
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
        "posted_at": posted_at,
        "min_amount": min_a,
        "max_amount": max_a,
        "currency": currency,
        "interval": interval,
    })
    return row


# ---- Public entrypoints ---------------------------------------------------

def extract(url: str) -> dict:
    """Extract a single job-posting row from a URL. Raises URLExtractionError
    if none of the strategies succeed."""
    url = (url or "").strip()
    if not url:
        raise URLExtractionError("empty URL")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLExtractionError(f"unsupported URL scheme: {parsed.scheme!r}")

    for fn, label in ((_try_lever, "Lever"),
                      (_try_greenhouse, "Greenhouse"),
                      (_try_jsonld, "JSON-LD")):
        try:
            row = fn(url)
        except Exception as e:  # noqa: BLE001 — extractors must not fight each other
            row = None
            last_err = f"{label}: {e}"
        else:
            last_err = None
        if row:
            return row

    raise URLExtractionError(
        f"could not extract job data from {url} "
        f"(tried Lever, Greenhouse, JSON-LD)"
    )


def manual_row(url: str, *, title: str, company: str,
               location: str, description: str) -> dict:
    """Build a row from user-supplied fields. The `manual` source keeps
    the row visible in downstream tools so you can spot ad-hoc entries."""
    url = (url or "").strip()
    title = title.strip()
    company = company.strip()
    if not (title and company and description.strip()):
        raise ValueError("title, company, and description are required")
    row = _empty()
    row.update({
        "id": _row_id("manual", url, title, company),
        "source": "manual",
        "title": title,
        "company": company,
        "location": location.strip(),
        "description": description.strip(),
        "url": url,
        "posted_at": "",
    })
    return row

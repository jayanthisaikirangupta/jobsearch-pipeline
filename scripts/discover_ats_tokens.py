"""Auto-discover Greenhouse / Lever tokens from the gov.uk sponsor register.

For each sponsor company, try a few likely careers URLs (`careers.<slug>.com`,
`<slug>.com/careers`, `jobs.<slug>.com`). Follow redirects and look for the
ATS markers:

    https://boards.greenhouse.io/<TOKEN>/...
    https://job-boards.greenhouse.io/<TOKEN>/...
    https://jobs.lever.co/<SITE>/...

Then VALIDATE each candidate by hitting the public API and confirming at
least one UK-located posting exists today. Outputs an updated YAML.

Run:
    python scripts/discover_ats_tokens.py
        --register data/sponsor_register.csv
        --out config/sponsor_tokens.yaml
        --max-companies 200       # cap for a fast run; remove for full scan

This is slow (~1-2 hours for the full register because of network) and
should be run once or whenever you want to refresh. Output is committed.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
import yaml


_GH_RE = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_-]+)", re.IGNORECASE)
_LV_RE = re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.IGNORECASE)
_TIMEOUT = 8.0
_UK_KEYWORDS = (
    "united kingdom", "uk", "england", "scotland", "wales",
    "london", "manchester", "edinburgh", "cambridge", "bristol",
)


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[\(\)]", "", s)
    s = re.sub(
        r"\b(ltd|limited|llp|plc|inc|corp|corporation|holdings?|group|company|the|uk|gb|llc)\b\.?",
        "",
        s,
    )
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", "", s).strip()
    return s


def _candidate_urls(company: str) -> list[str]:
    slug = _slugify(company)
    if not slug:
        return []
    return [
        f"https://careers.{slug}.com",
        f"https://www.{slug}.com/careers",
        f"https://{slug}.com/careers",
        f"https://jobs.{slug}.com",
        f"https://careers.{slug}.co.uk",
    ]


def _detect_tokens(client: httpx.Client, urls: list[str]) -> tuple[str | None, str | None]:
    """Try each candidate URL, follow redirects, return (gh_token, lever_site)."""
    gh_token: str | None = None
    lv_site: str | None = None
    for url in urls:
        try:
            r = client.get(url, follow_redirects=True, timeout=_TIMEOUT)
        except (httpx.HTTPError, ssl_err()):  # type: ignore[misc]
            continue
        if r.status_code >= 400:
            continue
        body = (str(r.url) + "\n" + r.text).lower()
        m_gh = _GH_RE.search(body)
        if m_gh and not gh_token:
            gh_token = m_gh.group(1).lower()
        m_lv = _LV_RE.search(body)
        if m_lv and not lv_site:
            lv_site = m_lv.group(1).lower()
        if gh_token and lv_site:
            break
    return gh_token, lv_site


def ssl_err():  # tolerate older httpx without dedicated SSL exception class
    return Exception


def _validate_greenhouse(client: httpx.Client, token: str) -> int:
    try:
        r = client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return 0
        jobs = r.json().get("jobs", [])
        return sum(
            1
            for j in jobs
            if any(k in (j.get("location", {}).get("name", "") or "").lower() for k in _UK_KEYWORDS)
        )
    except (httpx.HTTPError, ValueError):
        return 0


def _validate_lever(client: httpx.Client, site: str) -> int:
    try:
        r = client.get(
            f"https://api.lever.co/v0/postings/{site}",
            params={"mode": "json"},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return 0
        postings = r.json()
        if not isinstance(postings, list):
            return 0
        return sum(
            1
            for p in postings
            if any(k in (p.get("categories", {}).get("location", "") or "").lower() for k in _UK_KEYWORDS)
        )
    except (httpx.HTTPError, ValueError):
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", default="data/sponsor_register.csv")
    ap.add_argument("--out", default="config/sponsor_tokens.yaml")
    ap.add_argument("--max-companies", type=int, default=200,
                    help="Limit how many register rows to probe (default 200).")
    ap.add_argument("--merge", action="store_true",
                    help="Merge with existing YAML rather than overwrite.")
    args = ap.parse_args()

    register_path = Path(args.register)
    out_path = Path(args.out)
    if not register_path.exists():
        print(f"register CSV missing: {register_path}", file=sys.stderr)
        return 1

    df = pd.read_csv(register_path, dtype=str, encoding="utf-8", on_bad_lines="skip")
    cols = {c.lower().strip(): c for c in df.columns}
    org_col = cols.get("organisation name") or cols.get("organisation_name")
    if not org_col:
        # Banner-row CSV — retry with skiprows
        df = pd.read_csv(register_path, dtype=str, encoding="utf-8", skiprows=1,
                         on_bad_lines="skip")
        cols = {c.lower().strip(): c for c in df.columns}
        org_col = cols.get("organisation name") or cols.get("organisation_name")
    if not org_col:
        print("could not find Organisation Name column", file=sys.stderr)
        return 1

    companies = df[org_col].dropna().astype(str).str.strip().unique().tolist()
    print(f"Register has {len(companies)} unique sponsors. Probing first {args.max_companies}.")

    gh_seen: dict[str, int] = {}
    lv_seen: dict[str, int] = {}

    if args.merge and out_path.exists():
        existing = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
        for t in existing.get("greenhouse", []) or []:
            gh_seen.setdefault(t, 0)
        for s in existing.get("lever", []) or []:
            lv_seen.setdefault(s, 0)

    with httpx.Client(headers={"User-Agent": "jobsearch-discovery/0.1"},
                      verify=True) as c:
        for i, company in enumerate(companies[: args.max_companies], 1):
            urls = _candidate_urls(company)
            if not urls:
                continue
            gh, lv = _detect_tokens(c, urls)
            if gh:
                count = _validate_greenhouse(c, gh)
                if count > 0:
                    if gh not in gh_seen or gh_seen[gh] < count:
                        gh_seen[gh] = count
                        print(f"  [{i:3}] GH  {gh:<25} ({count} UK)  ← {company[:40]}")
            if lv:
                count = _validate_lever(c, lv)
                if count > 0:
                    if lv not in lv_seen or lv_seen[lv] < count:
                        lv_seen[lv] = count
                        print(f"  [{i:3}] LV  {lv:<25} ({count} UK)  ← {company[:40]}")
            # be polite, free APIs don't rate-limit but careers pages might
            time.sleep(0.05)

    # Sort by UK count desc and emit YAML
    gh_sorted = sorted(gh_seen.items(), key=lambda kv: -kv[1])
    lv_sorted = sorted(lv_seen.items(), key=lambda kv: -kv[1])

    out = {
        "greenhouse": [t for t, _ in gh_sorted],
        "lever": [s for s, _ in lv_sorted],
    }
    yaml_text = "# Auto-generated by scripts/discover_ats_tokens.py\n"
    yaml_text += f"# Probed {min(args.max_companies, len(companies))} sponsors\n\n"
    yaml_text += "greenhouse:\n"
    for t, count in gh_sorted:
        yaml_text += f"  - {t}    # {count} UK roles\n"
    yaml_text += "\nlever:\n"
    for s, count in lv_sorted:
        yaml_text += f"  - {s}    # {count} UK roles\n"

    out_path.write_text(yaml_text, encoding="utf-8")
    print()
    print(f"Wrote {out_path}: {len(gh_sorted)} Greenhouse, {len(lv_sorted)} Lever tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

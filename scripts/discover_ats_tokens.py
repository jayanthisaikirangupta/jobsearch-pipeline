"""Auto-discover hosted-ATS tokens for UK sponsor companies — all five ATSs.

Supports: Greenhouse, Lever, Ashby, Workable, SmartRecruiters.

STRATEGY (v2, 2026-07):
  1. DIRECT API PROBING (primary). Each ATS has an unauthenticated public
     API keyed by a company slug. Guess 3-5 slug variants per company name
     and hit the APIs directly — either it returns jobs or it 404s. No HTML
     scraping, no anti-bot issues, one cheap GET per (ATS, variant).
  2. CAREERS-PAGE FINGERPRINTING (fallback). When no direct probe hits,
     fetch likely careers URLs and regex-scan for ATS board URLs. Catches
     companies whose board slug differs from their name slug.

Every hit is validated with a UK-posting count; only tokens with >= 1 UK
posting are written.

INPUTS (any combination):
  --register data/sponsor_register.csv     gov.uk register CSV
  --cities "Milton Keynes,Northampton"     filter register rows by Town/City
  --companies my_companies.txt             plain list, one company name per line
  --max-companies 300                      cap (applies after filtering)
  --offset 0 / --shuffle                   don't always probe A-companies

OUTPUT:
  config/sponsor_tokens.discovered.yaml — owned by this script, safe to
  regenerate. The hand-curated config/sponsor_tokens.yaml is NEVER touched.
  Ingest sources merge both files at run time (see _ats_common.load_tokens).
  Re-runs MERGE with the discovered file's previous contents by default.

Run examples:
    python scripts/discover_ats_tokens.py --companies config/target_companies.txt
    python scripts/discover_ats_tokens.py --cities "Milton Keynes,Northampton,Cambridge" --max-companies 400
    python scripts/discover_ats_tokens.py --shuffle --max-companies 500
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
import yaml

# Load .env BEFORE any httpx client is created: on the corporate network,
# SSL_CERT_FILE must point at the Zscaler-aware CA bundle or every HTTPS
# probe fails silently with CERTIFICATE_VERIFY_FAILED.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass

_TIMEOUT = 8.0
_SLEEP = 0.05
_UA = {"User-Agent": "jobsearch-discovery/0.2"}

_UK_KEYWORDS = (
    "united kingdom", "uk", "england", "scotland", "wales", "northern ireland",
    "london", "manchester", "edinburgh", "cambridge", "bristol", "leeds",
    "glasgow", "birmingham", "milton keynes", "northampton", "nottingham",
    "belfast", "cardiff", "remote",
)


def _is_uk_text(loc: str) -> bool:
    loc = (loc or "").lower()
    return any(k in loc for k in _UK_KEYWORDS)


# --------------------------------------------------------------------------
# Slug variants
# --------------------------------------------------------------------------

_SUFFIX = re.compile(
    r"\b(ltd|limited|llp|plc|inc|corp|corporation|holdings?|group|company"
    r"|the|uk|gb|llc|international|technologies|technology|solutions"
    r"|services|systems|software|consulting|digital)\b\.?",
    re.IGNORECASE,
)


def slug_variants(name: str) -> list[str]:
    """Generate plausible board slugs for a company name, most-likely first."""
    base = re.sub(r"[\(\)\[\]'.,&]", " ", name.lower()).strip()
    stripped = _SUFFIX.sub(" ", base)
    words_full = [w for w in re.split(r"[\s/-]+", base) if w]
    words = [w for w in re.split(r"[\s/-]+", stripped) if w]

    variants: list[str] = []

    def add(v: str) -> None:
        v = v.strip("-")
        if v and len(v) >= 3 and v not in variants:
            variants.append(v)

    if words:
        add("".join(words))          # thoughtmachine
        add("-".join(words))         # thought-machine
        add(words[0])                # thought (first word only — risky but cheap)
    if words_full and words_full != words:
        add("".join(words_full))     # keep suffix version too
        add("-".join(words_full))
    return variants[:5]


# --------------------------------------------------------------------------
# Direct API probes + validation (returns UK posting count, 0 = no/invalid)
# --------------------------------------------------------------------------

def probe_greenhouse(c: httpx.Client, slug: str) -> int:
    try:
        r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                  timeout=_TIMEOUT)
        if r.status_code != 200:
            return 0
        jobs = r.json().get("jobs", [])
        return sum(1 for j in jobs
                   if _is_uk_text((j.get("location") or {}).get("name", "")))
    except (httpx.HTTPError, ValueError):
        return 0


def probe_lever(c: httpx.Client, slug: str) -> int:
    try:
        r = c.get(f"https://api.lever.co/v0/postings/{slug}",
                  params={"mode": "json"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return 0
        postings = r.json()
        if not isinstance(postings, list):
            return 0
        return sum(1 for p in postings
                   if _is_uk_text((p.get("categories") or {}).get("location", "")))
    except (httpx.HTTPError, ValueError):
        return 0


def probe_ashby(c: httpx.Client, slug: str) -> int:
    try:
        r = c.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                  timeout=_TIMEOUT)
        if r.status_code != 200:
            return 0
        jobs = r.json().get("jobs", [])
        def _loc(j):
            secondary = " ".join(str(s.get("location") or "")
                                 for s in (j.get("secondaryLocations") or []))
            return f"{j.get('location') or ''} {secondary}"
        return sum(1 for j in jobs if _is_uk_text(_loc(j)))
    except (httpx.HTTPError, ValueError):
        return 0


def probe_workable(c: httpx.Client, slug: str) -> int:
    try:
        r = c.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
                  timeout=_TIMEOUT)
        if r.status_code != 200:
            return 0
        jobs = r.json().get("jobs", [])
        return sum(1 for j in jobs
                   if _is_uk_text(f"{j.get('city') or ''} {j.get('country') or ''}"))
    except (httpx.HTTPError, ValueError):
        return 0


def probe_smartrecruiters(c: httpx.Client, slug: str) -> int:
    try:
        r = c.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                  params={"limit": 100}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return 0
        content = r.json().get("content", [])
        return sum(1 for p in content
                   if ((p.get("location") or {}).get("country") or "").lower()
                   in ("gb", "uk", "united kingdom"))
    except (httpx.HTTPError, ValueError):
        return 0


PROBES = {
    "greenhouse": probe_greenhouse,
    "lever": probe_lever,
    "ashby": probe_ashby,
    "workable": probe_workable,
    "smartrecruiters": probe_smartrecruiters,
}

# SmartRecruiters slugs are case-sensitive and usually CamelCase; try the
# name with spaces removed but original casing as an extra variant.
def sr_extra_variants(name: str) -> list[str]:
    cleaned = re.sub(r"[\(\)\[\]'.,&]", " ", name)
    cleaned = _SUFFIX.sub(" ", cleaned)
    camel = "".join(w.capitalize() for w in cleaned.split())
    return [camel] if len(camel) >= 3 else []


# --------------------------------------------------------------------------
# Careers-page fingerprinting (fallback)
# --------------------------------------------------------------------------

_FINGERPRINTS = {
    "greenhouse": re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_-]+)", re.I),
    "lever": re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+)", re.I),
    "workable": re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I),
    "smartrecruiters": re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([a-zA-Z0-9_-]+)", re.I),
}


def fingerprint_careers_pages(c: httpx.Client, name: str) -> dict[str, str]:
    """Fetch likely careers URLs, regex-scan for ATS board slugs."""
    found: dict[str, str] = {}
    for slug in slug_variants(name)[:2]:
        for url in (f"https://www.{slug}.com/careers",
                    f"https://careers.{slug}.com",
                    f"https://{slug}.com/careers",
                    f"https://www.{slug}.co.uk/careers"):
            try:
                r = c.get(url, timeout=_TIMEOUT, follow_redirects=True)
            except httpx.HTTPError:
                continue
            if r.status_code >= 400:
                continue
            body = str(r.url) + "\n" + r.text
            for ats, rx in _FINGERPRINTS.items():
                if ats in found:
                    continue
                m = rx.search(body)
                if m:
                    found[ats] = m.group(1)
            if len(found) == len(_FINGERPRINTS):
                return found
        if found:
            break
    return found


# --------------------------------------------------------------------------
# Company list assembly
# --------------------------------------------------------------------------

def companies_from_register(path: Path, cities: list[str]) -> list[str]:
    df = pd.read_csv(path, dtype=str, encoding="utf-8", on_bad_lines="skip")
    cols = {c.lower().strip(): c for c in df.columns}
    org = cols.get("organisation name") or cols.get("organisation_name")
    if not org:
        df = pd.read_csv(path, dtype=str, encoding="utf-8", skiprows=1,
                         on_bad_lines="skip")
        cols = {c.lower().strip(): c for c in df.columns}
        org = cols.get("organisation name") or cols.get("organisation_name")
    if not org:
        raise SystemExit("could not find Organisation Name column in register")

    if cities:
        town = cols.get("town/city") or cols.get("town") or cols.get("city")
        if town:
            wanted = {c.strip().lower() for c in cities}
            df = df[df[town].fillna("").str.strip().str.lower().isin(wanted)]
        else:
            print("warning: no Town/City column, --cities ignored", file=sys.stderr)
    return df[org].dropna().astype(str).str.strip().unique().tolist()


def companies_from_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--register", default=None,
                    help="gov.uk sponsor register CSV (e.g. data/sponsor_register.csv)")
    ap.add_argument("--cities", default="",
                    help="Comma-separated Town/City filter for register rows")
    ap.add_argument("--companies", default=None,
                    help="Plain text file: one company name per line")
    ap.add_argument("--out", default="config/sponsor_tokens.discovered.yaml")
    ap.add_argument("--max-companies", type=int, default=200)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--shuffle", action="store_true",
                    help="Randomise order so re-runs cover different companies")
    ap.add_argument("--no-fingerprint", action="store_true",
                    help="Skip the slow careers-page fallback")
    ap.add_argument("--fresh", action="store_true",
                    help="Ignore previous discovered file instead of merging")
    args = ap.parse_args()

    names: list[str] = []
    if args.companies:
        names += companies_from_file(Path(args.companies))
    if args.register:
        cities = [c for c in args.cities.split(",") if c.strip()]
        names += companies_from_register(Path(args.register), cities)
    if not names:
        raise SystemExit("provide --companies and/or --register")

    # de-dupe preserving order
    seen: set[str] = set()
    names = [n for n in names if not (n.lower() in seen or seen.add(n.lower()))]
    if args.shuffle:
        random.shuffle(names)
    names = names[args.offset: args.offset + args.max_companies]
    print(f"Probing {len(names)} companies across 5 ATSs...")

    out_path = Path(args.out)
    results: dict[str, dict[str, int]] = {k: {} for k in PROBES}
    if out_path.exists() and not args.fresh:
        prev = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
        for ats in PROBES:
            for t in prev.get(ats) or []:
                results[ats].setdefault(str(t), 1)

    # Curated tokens: skip re-probing those (already covered by ingest)
    curated_path = out_path.parent / "sponsor_tokens.yaml"
    curated: dict[str, set[str]] = {k: set() for k in PROBES}
    if curated_path.exists():
        cur = yaml.safe_load(curated_path.read_text(encoding="utf-8")) or {}
        for ats in PROBES:
            curated[ats] = {str(t).lower() for t in (cur.get(ats) or [])}

    with httpx.Client(headers=_UA, follow_redirects=True) as c:
        for i, name in enumerate(names, 1):
            variants = slug_variants(name)
            hits: dict[str, tuple[str, int]] = {}

            for ats, probe in PROBES.items():
                cand = variants + (sr_extra_variants(name)
                                   if ats == "smartrecruiters" else [])
                for slug in cand:
                    if slug.lower() in curated[ats] or slug in results[ats]:
                        hits[ats] = (slug, results[ats].get(slug, 1))
                        break
                    count = probe(c, slug)
                    time.sleep(_SLEEP)
                    if count > 0:
                        hits[ats] = (slug, count)
                        break

            if not hits and not args.no_fingerprint:
                fp = fingerprint_careers_pages(c, name)
                for ats, slug in fp.items():
                    if slug.lower() in curated[ats] or slug in results[ats]:
                        continue
                    count = PROBES[ats](c, slug)
                    if count > 0:
                        hits[ats] = (slug, count)

            for ats, (slug, count) in hits.items():
                if slug.lower() in curated[ats]:
                    continue
                if slug not in results[ats] or results[ats][slug] < count:
                    results[ats][slug] = count
                    print(f"  [{i:4}] {ats:<16} {slug:<28} ({count:>3} UK) <- {name[:45]}")

    total = sum(len(v) for v in results.values())
    lines = [
        "# Auto-generated by scripts/discover_ats_tokens.py — DO NOT hand-edit.",
        "# Curated tokens live in sponsor_tokens.yaml; ingest merges both files.",
        f"# {total} tokens across 5 ATSs. Counts = UK postings at probe time.",
        "",
    ]
    for ats in PROBES:
        lines.append(f"{ats}:")
        for slug, count in sorted(results[ats].items(), key=lambda kv: -kv[1]):
            lines.append(f"  - {slug}    # {count} UK")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out_path}: " +
          ", ".join(f"{len(results[a])} {a}" for a in PROBES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

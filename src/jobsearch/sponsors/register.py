"""Fetch + cache the gov.uk Register of Licensed Sponsors CSV.

The page lists a daily-updated CSV at a stable, scrape-discoverable URL. We resolve
it via the gov.uk publication page rather than hardcoding a fragile filename.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import httpx
import pandas as pd
from rich.console import Console

from ..config import get_settings

console = Console()

PUBLICATION_URL = (
    "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
)
CACHE_FILE = "sponsor_register.csv"
CACHE_TTL_HOURS = 24


def _resolve_csv_url() -> str:
    """Scrape the gov.uk publication page for the latest CSV link."""
    r = httpx.get(PUBLICATION_URL, follow_redirects=True, timeout=30)
    r.raise_for_status()
    # Page links to "...assets.publishing.service.gov.uk/.../Worker_and_Temporary_Worker.csv"
    m = re.search(
        r"https://[^\"']+\.csv",
        r.text,
    )
    if not m:
        raise RuntimeError("Could not find CSV link on gov.uk register page")
    return m.group(0)


def fetch(force: bool = False) -> Path:
    settings = get_settings()
    out = settings.data_dir / CACHE_FILE

    if not force and out.exists():
        age_hours = (
            _dt.datetime.now().timestamp() - out.stat().st_mtime
        ) / 3600
        if age_hours < CACHE_TTL_HOURS:
            console.print(f"[dim]Sponsor register cache is {age_hours:.1f}h old, reusing.[/]")
            return out

    url = _resolve_csv_url()
    console.print(f"Fetching sponsor register from {url}")
    r = httpx.get(url, follow_redirects=True, timeout=60)
    r.raise_for_status()
    out.write_bytes(r.content)
    console.print(f"[green]Wrote {len(r.content):,} bytes -> {out}[/]")
    return out


def load() -> pd.DataFrame:
    """Load the cached register as a DataFrame."""
    settings = get_settings()
    path = settings.data_dir / CACHE_FILE
    if not path.exists():
        path = fetch()
    # The CSV's first row is sometimes a header banner. Try standard parse first.
    df = pd.read_csv(path, dtype=str, encoding="utf-8", on_bad_lines="skip")
    # Normalize the 'Organisation Name' column regardless of casing
    cols = {c.lower().strip(): c for c in df.columns}
    org_col = cols.get("organisation name") or cols.get("organisation_name")
    if not org_col:
        # CSV starts with a banner line; retry skipping it
        df = pd.read_csv(path, dtype=str, encoding="utf-8", skiprows=1, on_bad_lines="skip")
        cols = {c.lower().strip(): c for c in df.columns}
        org_col = cols.get("organisation name") or cols.get("organisation_name")
    if not org_col:
        raise RuntimeError(f"Could not locate 'Organisation Name' column. Got: {list(df.columns)}")
    df = df.rename(columns={org_col: "organisation_name"})
    df["organisation_name_normalized"] = (
        df["organisation_name"].fillna("").str.lower().str.strip()
    )
    return df

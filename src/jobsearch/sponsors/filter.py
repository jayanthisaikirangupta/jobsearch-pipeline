"""Fuzzy-match each job's company against the sponsor register."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from rapidfuzz import process, fuzz
from rich.console import Console

from ..config import get_settings
from . import register

console = Console()

# Minimum fuzzy ratio (0-100) for a sponsor match. Set conservatively because
# false positives mean wasted tailoring time, false negatives just mean missed apps.
MATCH_THRESHOLD = 90

SUFFIX_TRIM = re.compile(
    r"\b(ltd|limited|llp|plc|inc|incorporated|corp|corporation|"
    r"(uk)|holdings?|group|company|co\.?)\b\.?",
    re.IGNORECASE,
)


def _norm(name: str) -> str:
    s = (name or "").lower().strip()
    s = SUFFIX_TRIM.sub("", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def filter_jobs() -> Path:
    settings = get_settings()
    raw_path = settings.data_dir / "jobs_raw.parquet"
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        raise FileNotFoundError(f"Run ingest first: {raw_path} missing")

    jobs = pd.read_parquet(raw_path)
    if jobs.empty:
        out = settings.data_dir / "jobs_filtered.parquet"
        jobs.to_parquet(out, index=False)
        return out

    sponsors_df = register.load()
    sponsor_names = sponsors_df["organisation_name"].tolist()
    sponsor_norm = [_norm(n) for n in sponsor_names]

    # Build a lookup from normalized -> original
    norm_to_original: dict[str, str] = dict(zip(sponsor_norm, sponsor_names))
    choices = list({n for n in sponsor_norm if n})

    matches: list[dict] = []
    for company in jobs["company"].fillna("").astype(str):
        c_norm = _norm(company)
        if not c_norm:
            matches.append({"sponsor_match": None, "sponsor_score": 0})
            continue
        result = process.extractOne(c_norm, choices, scorer=fuzz.WRatio, score_cutoff=MATCH_THRESHOLD)
        if result is None:
            matches.append({"sponsor_match": None, "sponsor_score": 0})
        else:
            matched_norm, score, _ = result
            matches.append(
                {
                    "sponsor_match": norm_to_original.get(matched_norm, matched_norm),
                    "sponsor_score": int(score),
                }
            )

    jobs = jobs.assign(**pd.DataFrame(matches))

    # Council rows bypass the private-sector sponsor register — councils are
    # public bodies with their own Skilled Worker arrangements (rare for tech,
    # but they exist), and their names won't fuzzy-match private-sector
    # sponsor names anyway. Let them through so the user can see them scored
    # and decide per row.
    if "source" in jobs.columns:
        council_mask = jobs["source"] == "councils"
        jobs.loc[council_mask, "sponsor_match"] = jobs.loc[
            council_mask, "company"
        ].fillna("")
        jobs.loc[council_mask, "sponsor_score"] = 100

    filtered = jobs[jobs["sponsor_match"].notna()].copy()

    out = settings.data_dir / "jobs_filtered.parquet"
    filtered.to_parquet(out, index=False)
    console.print(
        f"[green]Sponsor filter: {len(filtered)} / {len(jobs)} rows kept "
        f"(threshold={MATCH_THRESHOLD}) -> {out}[/]"
    )
    return out

"""Post-ingest dedup.

Same role posted via different URLs / sources / agencies all collapse to one
row. Dedup key is the normalized (company, title, location) tuple — strong
enough to catch the real duplicates we see in production, weak enough to keep
genuinely different roles at the same company (e.g. "Senior AI Engineer -
Knowledge Graphs" vs "- Recommendation").

The picked-representative row gets two new columns:
  * dup_count   — how many duplicate rows collapsed into this one
  * dup_sources — comma-separated list of distinct sources that posted it

These are surfaced on the Top_Picks Excel sheet so a high dup_count is a
soft signal that the role is real (not a one-off scrape glitch).
"""
from __future__ import annotations

import re

import pandas as pd

# Cheap normalizers. We don't want to be clever — being too aggressive merges
# distinct roles, being too loose leaves duplicates. (company, title, location)
# is the sweet spot in the data we've measured.

_SUFFIX_TRIM = re.compile(
    r"\b(ltd|limited|llp|plc|inc|incorporated|corp|corporation|"
    r"holdings?|group|company|co|uk)\b\.?",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")


def _safe_str(s) -> str:
    """Coerce a value (str | None | NaN) to a clean lowercased string.

    pandas NaN is a float, and `(NaN or '')` returns NaN because NaN is
    truthy in a boolean context. Use pd.isna() for the missing-value check.
    """
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return str(s).lower().strip()


def _norm_company(s) -> str:
    s = _safe_str(s)
    s = _SUFFIX_TRIM.sub(" ", s)
    s = _NON_ALNUM.sub(" ", s)
    return _WHITESPACE.sub(" ", s).strip()


def _norm_title(s) -> str:
    s = _safe_str(s)
    s = _NON_ALNUM.sub(" ", s)
    return _WHITESPACE.sub(" ", s).strip()


def _norm_location(s) -> str:
    """Drop the verbose tail ('London, ENG, GB' vs 'London, England, UK' vs
    'London, United Kingdom') so the same city-level role collapses."""
    s = _safe_str(s)
    s = _NON_ALNUM.sub(" ", s)
    parts = [p.strip() for p in s.split(" ") if p.strip()]
    # Keep only the first 1-2 tokens — usually the city
    return " ".join(parts[:2])


def _representative_index(group: pd.DataFrame, tracked_ids: set[str] | None = None) -> int:
    """Pick the best row out of a duplicate group. Tiebreakers, in order:
      1. id is already in the tracker (preserves tailored work)
      2. has any salary info
      3. longest description (proxy for richest source)
      4. most recent posted_at
      5. preferred source order (indeed > glassdoor > linkedin)
    """
    SOURCE_RANK = {"indeed": 0, "glassdoor": 1, "linkedin": 2}
    tracked_ids = tracked_ids or set()
    is_tracked = group["id"].isin(tracked_ids)
    has_salary = group[["min_amount", "max_amount"]].notna().any(axis=1)
    desc_len = group["description"].fillna("").str.len()
    posted = pd.to_datetime(group["posted_at"], errors="coerce")
    src_rank = group["source"].map(SOURCE_RANK).fillna(99)

    ranked = pd.DataFrame({
        "is_tracked": is_tracked.astype(int),
        "has_salary": has_salary.astype(int),
        "desc_len": desc_len,
        "posted": posted,
        "src_rank": -src_rank,  # smaller rank = better, so flip sign
    }, index=group.index).sort_values(
        ["is_tracked", "has_salary", "desc_len", "posted", "src_rank"],
        ascending=[False, False, False, False, False],
        na_position="last",
    )
    return ranked.index[0]


def _load_tracked_ids() -> set[str]:
    """Load tracker job_ids so dedup can prefer rows we've already tailored."""
    try:
        from ..tracker import db
        return {a["job_id"] for a in db.list_apps(limit=10_000)}
    except Exception:
        return set()


def deduplicate(df: pd.DataFrame, tracked_ids: set[str] | None = None) -> pd.DataFrame:
    """Collapse duplicate rows. Returns a new DataFrame with dup_count +
    dup_sources columns added. Idempotent — safe to run on already-deduped data.

    ``tracked_ids`` (optional) tells dedup which ids are already in the tracker
    so it preserves them when picking the duplicate-group representative. If
    omitted, loads from the SQLite tracker.
    """
    if df.empty:
        df = df.copy()
        df["dup_count"] = 1
        df["dup_sources"] = ""
        return df

    if tracked_ids is None:
        tracked_ids = _load_tracked_ids()

    work = df.copy()
    work["_norm_company"] = work["company"].map(_norm_company)
    work["_norm_title"] = work["title"].map(_norm_title)
    work["_norm_location"] = work["location"].map(_norm_location)

    keep_indices: list = []
    dup_counts: dict = {}
    dup_sources: dict = {}

    grouped = work.groupby(
        ["_norm_company", "_norm_title", "_norm_location"], dropna=False, sort=False
    )
    for _, group in grouped:
        idx = _representative_index(group, tracked_ids=tracked_ids)
        keep_indices.append(idx)
        dup_counts[idx] = len(group)
        dup_sources[idx] = ",".join(sorted(set(group["source"].dropna().astype(str))))

    out = work.loc[keep_indices].copy()
    out["dup_count"] = out.index.map(dup_counts)
    out["dup_sources"] = out.index.map(dup_sources)
    out = out.drop(columns=["_norm_company", "_norm_title", "_norm_location"])
    out = out.reset_index(drop=True)
    return out

"""Post-ingest dedup.

Same role posted via different URLs / sources / cities all collapse to one
row. Dedup key is the normalized (company, title) tuple — different titles
at the same company stay distinct (e.g. "Senior AI Engineer - Knowledge
Graphs" vs "- Recommendation") but the same title scraped under multiple
city searches (LinkedIn returns "Arup Enterprise Architect" for every UK
city query with a different location string each time) collapses into one.

The picked-representative row gets three new columns:
  * dup_count       — how many duplicate rows collapsed into this one
  * dup_sources     — comma-separated list of distinct sources that posted it
  * dup_locations   — comma-separated distinct location strings observed

A high dup_count is a soft signal that the role is real (not a one-off
scrape glitch) and that it's listed broadly enough to plausibly be remote/
UK-wide rather than tied to the representative row's specific location.
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
      3. has a non-empty location string (since location is no longer in
         the dedup key, prefer a row that actually names the place)
      4. longest description (proxy for richest source)
      5. most recent posted_at
      6. preferred source order (adzuna > indeed > glassdoor > linkedin)
    """
    SOURCE_RANK = {"adzuna": 0, "indeed": 1, "glassdoor": 2, "linkedin": 3}
    tracked_ids = tracked_ids or set()
    is_tracked = group["id"].isin(tracked_ids)
    has_salary = group[["min_amount", "max_amount"]].notna().any(axis=1)
    has_loc = group["location"].fillna("").astype(str).str.strip().ne("")
    desc_len = group["description"].fillna("").str.len()
    # format="mixed" parses each element by its own format without the
    # dateutil-fallback warning; utc=True normalises the tz-aware ISO
    # timestamps (Ashby/Greenhouse) against naive dates (Workable) so the
    # recency sort below never compares aware vs naive.
    posted = pd.to_datetime(group["posted_at"], errors="coerce",
                            format="mixed", utc=True)
    src_rank = group["source"].map(SOURCE_RANK).fillna(99)

    ranked = pd.DataFrame({
        "is_tracked": is_tracked.astype(int),
        "has_salary": has_salary.astype(int),
        "has_loc": has_loc.astype(int),
        "desc_len": desc_len,
        "posted": posted,
        "src_rank": -src_rank,  # smaller rank = better, so flip sign
    }, index=group.index).sort_values(
        ["is_tracked", "has_salary", "has_loc", "desc_len", "posted", "src_rank"],
        ascending=[False, False, False, False, False, False],
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

    keep_indices: list = []
    dup_counts: dict = {}
    dup_sources: dict = {}
    dup_locations: dict = {}

    grouped = work.groupby(
        ["_norm_company", "_norm_title"], dropna=False, sort=False
    )
    for _, group in grouped:
        idx = _representative_index(group, tracked_ids=tracked_ids)
        keep_indices.append(idx)
        dup_counts[idx] = len(group)
        dup_sources[idx] = ",".join(sorted(set(group["source"].dropna().astype(str))))
        locs = sorted({str(x).strip() for x in group["location"].dropna() if str(x).strip()})
        dup_locations[idx] = ",".join(locs)

    out = work.loc[keep_indices].copy()
    out["dup_count"] = out.index.map(dup_counts)
    out["dup_sources"] = out.index.map(dup_sources)
    out["dup_locations"] = out.index.map(dup_locations)
    out = out.drop(columns=["_norm_company", "_norm_title"])
    out = out.reset_index(drop=True)
    return out

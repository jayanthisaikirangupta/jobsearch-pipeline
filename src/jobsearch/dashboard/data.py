"""Data assembly for the dashboard.

Reads the SAME sources every other module reads (jobs_scored.parquet +
tracker.sqlite), so the dashboard never goes stale: every page render is a
fresh pull. No caching, no Excel intermediate.

Action Queue ranking — reviewer-first:
  1. Rows you've reviewed sort by reviewer_score DESC (most-vetted first).
  2. Unreviewed rows sort by score_total DESC within their grade band.
  3. Already-applied/rejected/expired rows are hidden entirely.

Tracker view shows everything you've engaged with, sorted by last-touched
DESC so the most recent activity is at the top.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import get_settings
from ..tracker import db


# Statuses that mean "I'm done with this row" — hidden from Action Queue
DONE_STATUSES = {"applied", "interview", "offer", "rejected", "withdrawn", "expired"}

# Statuses shown on the Tracker panel. Only post-application states; the
# pre-application 'discovered'/'scored'/'tailored' states live in the
# Action Queue where they have actionable buttons (Tailor, Review, Apply).
# 'expired' is also hidden so the trash button truly removes from default
# view — recover via the 'expired (hidden)' filter dropdown if needed.
TRACKER_VISIBLE_STATUSES = {
    "applied", "interview", "offer", "rejected", "withdrawn",
}


@dataclass
class QueueRow:
    job_id: str
    grade: str           # scorer A/B/C/D/F
    score_total: int
    company: str
    title: str
    location: str
    url: str
    annual_gbp: int | None
    dup_count: int
    dup_sources: str
    tracker_status: str  # discovered/scored/tailored/'' (no row yet)
    reviewer_grade: str  # A/B/C/D/F or ''
    reviewer_score: int | None
    reviewer_verdict: str
    resume_path: str
    review_md_path: str  # derived from resume_path
    cover_letter_path: str = ""  # derived: output/CV/{job_id}_{Company}_CoverLetter.docx
    retailor_instructions: str = ""  # reviewer-produced; empty = no retailor needed

    @property
    def has_review(self) -> bool:
        return self.reviewer_score is not None

    @property
    def has_resume(self) -> bool:
        return bool(self.resume_path)

    @property
    def has_cover_letter(self) -> bool:
        return bool(self.cover_letter_path)

    @property
    def needs_retailor(self) -> bool:
        return bool(self.retailor_instructions)


@dataclass
class TrackerRow:
    job_id: str
    company: str
    title: str
    url: str
    status: str
    grade: str
    score: int
    reviewer_grade: str
    reviewer_score: int | None
    notes: str
    updated_at: str
    resume_path: str


# Status workflow for the dashboard's action buttons. Order matters — first
# action shown gets primary styling.
STATUS_ACTIONS = {
    # from -> [list of sensible next states]
    "": ["tailored", "applied", "skipped"],
    "discovered": ["tailored", "applied", "skipped"],
    "scored": ["tailored", "applied", "skipped"],
    "tailored": ["applied", "skipped", "discovered"],
    "applied": ["interview", "rejected", "withdrawn"],
    "interview": ["offer", "rejected", "withdrawn"],
    "offer": ["interview", "withdrawn"],
    "rejected": ["applied"],   # allow undo if mis-clicked
    "withdrawn": ["applied"],
    "expired": ["applied"],
}


def _scored_df() -> pd.DataFrame:
    settings = get_settings()
    p = settings.data_dir / "jobs_scored.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def _tracker_index() -> dict[str, dict[str, Any]]:
    rows = db.list_apps(limit=10_000)
    return {r["job_id"]: r for r in rows}


def _row_from(scored_row: pd.Series, tracker_rec: dict[str, Any] | None) -> QueueRow:
    rec = tracker_rec or {}
    resume = rec.get("resume_path", "") or ""
    review_md = ""
    if resume and resume.endswith(".docx"):
        review_md = resume[:-5] + ".review.md"

    def _int_or_none(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    # Cover letter — derive expected path; only set if file actually exists.
    cl_path = ""
    job_id = str(scored_row["id"])
    company = str(scored_row.get("company", "") or "")
    if company:
        from pathlib import Path
        safe = "".join(c if c.isalnum() else "_" for c in company)[:40]
        candidate = (
            get_settings().output_dir / "CV" / f"{job_id}_{safe}_CoverLetter.docx"
        )
        if candidate.exists():
            cl_path = str(candidate)

    return QueueRow(
        job_id=job_id,
        grade=str(scored_row.get("grade", "") or ""),
        score_total=int(scored_row.get("score_total", 0) or 0),
        company=company,
        title=str(scored_row.get("title", "") or ""),
        location=str(scored_row.get("location", "") or ""),
        url=str(scored_row.get("url", "") or ""),
        annual_gbp=_int_or_none(scored_row.get("annual_gbp")),
        dup_count=int(scored_row.get("dup_count", 1) or 1),
        dup_sources=str(scored_row.get("dup_sources", "") or ""),
        tracker_status=str(rec.get("status", "") or ""),
        reviewer_grade=str(rec.get("reviewer_grade", "") or ""),
        reviewer_score=_int_or_none(rec.get("reviewer_score")),
        reviewer_verdict=str(rec.get("reviewer_verdict", "") or ""),
        resume_path=resume,
        review_md_path=review_md,
        cover_letter_path=cl_path,
        retailor_instructions=str(rec.get("retailor_instructions", "") or ""),
    )


def action_queue(grade_filter: str | None = None,
                 location_filter: str | None = None,
                 limit: int = 200) -> list[QueueRow]:
    """Reviewer-first ranking of A/B picks not yet acted on.

    grade_filter: 'A', 'B', or None (both)
    location_filter: substring match on the location column (case-insensitive)
    """
    scored = _scored_df()
    if scored.empty:
        return []
    tracker = _tracker_index()

    # A/B only — Action Queue is the shortlist
    ab = scored[scored["grade"].isin(["A", "B"])]
    if grade_filter and grade_filter in ("A", "B"):
        ab = ab[ab["grade"] == grade_filter]
    if location_filter:
        ab = ab[ab["location"].fillna("").str.contains(location_filter, case=False, na=False)]

    rows = [_row_from(r, tracker.get(str(r["id"]))) for _, r in ab.iterrows()]
    # Hide rows we're done with
    rows = [r for r in rows if r.tracker_status not in DONE_STATUSES]

    # Reviewer-first ranking — but only PROMOTE rows the reviewer actually
    # liked. Reviewed-bad rows DEMOTE so we don't waste time on confirmed
    # mismatches. Three buckets:
    #   tier 0: reviewed and reviewer_score >= 60  → most-vetted A/B picks
    #   tier 1: not reviewed yet                    → unknown but promising
    #   tier 2: reviewed and reviewer_score < 60   → reviewer flagged as weak
    # Within a tier: reviewer_score (or score_total) DESC.
    def _tier(r: QueueRow) -> int:
        if r.reviewer_score is not None and r.reviewer_score >= 60:
            return 0
        if r.reviewer_score is None:
            return 1
        return 2

    rows.sort(
        key=lambda r: (
            _tier(r),                                        # ascending: 0 first
            -(r.reviewer_score if r.reviewer_score is not None else r.score_total),
            -r.score_total,
        ),
    )
    return rows[:limit]


def tracker_view(status_filter: str | None = None,
                 limit: int = 500) -> list[TrackerRow]:
    """Tracker panel: only post-application states (applied/interview/offer/
    rejected/withdrawn/expired). Pre-application states (discovered/scored/
    tailored) live in the Action Queue where they have actionable buttons.

    status_filter (optional) further narrows to one specific state. If a
    user filters to 'tailored' explicitly, we honour it for debugging.
    """
    if status_filter:
        rows = db.list_apps(status=status_filter, limit=limit)
    else:
        # Pull a generous slice; we'll filter in-Python so the index covers
        # the multiple visible statuses without N round-trips.
        rows = [
            r for r in db.list_apps(limit=limit * 4)
            if r.get("status") in TRACKER_VISIBLE_STATUSES
        ][:limit]
    out: list[TrackerRow] = []
    for r in rows:
        def _int_or_none(v: Any) -> int | None:
            if v is None:
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None

        out.append(TrackerRow(
            job_id=str(r["job_id"]),
            company=str(r.get("company", "") or ""),
            title=str(r.get("title", "") or ""),
            url=str(r.get("url", "") or ""),
            status=str(r.get("status", "") or ""),
            grade=str(r.get("grade", "") or ""),
            score=int(r.get("score") or 0),
            reviewer_grade=str(r.get("reviewer_grade", "") or ""),
            reviewer_score=_int_or_none(r.get("reviewer_score")),
            notes=str(r.get("notes", "") or ""),
            updated_at=str(r.get("updated_at", "") or ""),
            resume_path=str(r.get("resume_path", "") or ""),
        ))
    # Sort by updated_at DESC
    out.sort(key=lambda r: r.updated_at, reverse=True)
    return out


def stats() -> dict[str, int]:
    """Top-of-page counters: how many in each state."""
    scored = _scored_df()
    if scored.empty:
        return {"total_scored": 0, "top_picks": 0, "queue": 0,
                "tailored": 0, "applied": 0, "interview": 0, "offer": 0}
    ab = scored[scored["grade"].isin(["A", "B"])]
    queue = action_queue(limit=10_000)
    tracker = db.list_apps(limit=10_000)
    by_status: dict[str, int] = {}
    for r in tracker:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {
        "total_scored": len(scored),
        "top_picks": len(ab),
        "queue": len(queue),
        "tailored": by_status.get("tailored", 0),
        "applied": by_status.get("applied", 0),
        "interview": by_status.get("interview", 0),
        "offer": by_status.get("offer", 0),
        "rejected": by_status.get("rejected", 0),
    }

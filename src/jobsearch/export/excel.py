"""Render every pipeline artifact into a single jobs.xlsx workbook.

Sheets (in tab order):
  * Action_Queue - what to apply to next: Top_Picks minus anything already
                   applied/rejected/expired/etc. Sorted by reviewer_score where
                   available, else score_total. This is the daily-driver sheet.
  * Top_Picks    - A/B graded jobs joined with tracker_status + reviewer_score
                   so you can see "which of these have I already applied to?"
                   without flipping sheets.
  * Scored       - full scored frame.
  * Filtered     - sponsor-licensed jobs (pre-scoring).
  * Raw          - everything ingested (pre-sponsor-filter).
  * Tracker      - SQLite tracker (status + reviewer columns + resume_path).

Why a single file: openable on a Kindle, on a phone, on the K+N work laptop
without Python; recruiters/career coaches can be sent a sheet without sharing
the whole repo.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rich.console import Console

from ..config import get_settings
from ..tracker import db


def export_quietly() -> Path | None:
    """Best-effort sidecar export. Errors are swallowed so they never break
    a successful pipeline step."""
    try:
        return export()
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Excel sidecar export skipped: {e}[/]")
        return None

console = Console()

# Columns + display order for each sheet. Anything not in this list is hidden so
# the workbook stays scanable instead of dumping every parquet column.

# Top_Picks now leads with state (status + reviewer_score) so you can see at
# a glance what's been done with each row. Status sorts before everything else.
TOP_PICKS_COLS = [
    "tracker_status", "reviewer_grade", "reviewer_score", "reviewer_verdict",
    "grade", "score_total", "company", "title", "location",
    "annual_gbp", "url", "dup_count", "dup_sources",
    "sponsor_match", "sponsor_score",
    "score_salary", "score_soc", "score_skills", "score_location",
    "score_sponsor_signal", "source", "query_label", "id",
]
ACTION_QUEUE_COLS = TOP_PICKS_COLS  # same shape; just filtered to undone work
SCORED_COLS = [
    "grade", "score_total", "company", "title", "location",
    "annual_gbp", "url", "dup_count", "dup_sources",
    "sponsor_match", "sponsor_score",
    "score_salary", "score_soc", "score_skills", "score_location",
    "score_sponsor_signal", "source", "query_label", "id",
]
FILTERED_COLS = [
    "company", "title", "location", "min_amount", "max_amount", "currency",
    "interval", "url", "sponsor_match", "sponsor_score", "source", "query_label", "id",
]
RAW_COLS = [
    "source", "query_label", "company", "title", "location", "url",
    "min_amount", "max_amount", "currency", "interval", "posted_at", "id",
]
TRACKER_COLS = [
    "status", "reviewer_grade", "reviewer_score", "reviewer_verdict",
    "grade", "score", "company", "title", "url",
    "resume_path", "notes", "reviewer_at", "updated_at", "created_at", "job_id",
]

# Statuses meaning "I'm done with this row" — Action_Queue hides these.
DONE_STATUSES = {"applied", "interview", "offer", "rejected", "withdrawn", "expired"}

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)


def _select_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    keep = [c for c in cols if c in df.columns]
    return df[keep].copy() if keep else df.copy()


def _autosize_and_style(writer: pd.ExcelWriter, sheet: str) -> None:
    ws = writer.sheets[sheet]
    # Header row styling
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="left", vertical="center")
    # Freeze header
    ws.freeze_panes = "A2"
    # Auto-fit-ish: cap at 60 chars to keep the workbook usable
    for col_idx, col_cells in enumerate(ws.columns, start=1):
        max_len = max((len(str(c.value)) for c in col_cells if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 10), 60)
    # URL column hyperlinks
    for header_cell in ws[1]:
        if header_cell.value == "url":
            for row_cell in ws[get_column_letter(header_cell.column)][1:]:
                if row_cell.value and isinstance(row_cell.value, str) and row_cell.value.startswith("http"):
                    row_cell.hyperlink = row_cell.value
                    row_cell.font = Font(color="2E75B6", underline="single")


def _join_state(top_picks: pd.DataFrame, tracker: pd.DataFrame) -> pd.DataFrame:
    """Left-join tracker_status + reviewer_* columns onto Top_Picks by id.
    Rows with no tracker entry get blank state columns (treated as 'new')."""
    if top_picks.empty:
        return top_picks
    state_cols = ["tracker_status", "reviewer_grade", "reviewer_score", "reviewer_verdict"]
    if tracker.empty:
        for col in state_cols:
            top_picks[col] = ""
        return top_picks
    sub = tracker[["job_id", "status", "reviewer_grade", "reviewer_score", "reviewer_verdict"]].copy()
    sub = sub.rename(columns={"job_id": "id", "status": "tracker_status"})
    merged = top_picks.merge(sub, on="id", how="left")
    for col in state_cols:
        if col in merged.columns:
            merged[col] = merged[col].fillna("")
    return merged


def _action_queue(top_picks_with_state: pd.DataFrame) -> pd.DataFrame:
    """Top_Picks minus anything you're done with. Sorted by reviewer_score
    where available (most-vetted matches first), else score_total."""
    if top_picks_with_state.empty:
        return top_picks_with_state
    df = top_picks_with_state.copy()
    df = df[~df["tracker_status"].astype(str).str.lower().isin(DONE_STATUSES)]
    if df.empty:
        return df
    # Sort by reviewer_score desc (NaN treated as -1 so unscored rows come
    # AFTER reviewed ones at the same score_total). Tiebreak on score_total.
    df["_rev_sort"] = pd.to_numeric(df.get("reviewer_score"), errors="coerce").fillna(-1)
    df = df.sort_values(
        by=["_rev_sort", "score_total"],
        ascending=[False, False],
    ).drop(columns=["_rev_sort"])
    return df


def export(out_path: Path | None = None) -> Path:
    """Write every pipeline artifact to one xlsx. Missing inputs become empty sheets."""
    settings = get_settings()
    out_path = out_path or settings.output_dir / "jobs.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_p = settings.data_dir / "jobs_raw.parquet"
    filtered_p = settings.data_dir / "jobs_filtered.parquet"
    scored_p = settings.data_dir / "jobs_scored.parquet"

    raw = pd.read_parquet(raw_p) if raw_p.exists() else pd.DataFrame()
    filtered = pd.read_parquet(filtered_p) if filtered_p.exists() else pd.DataFrame()
    scored = pd.read_parquet(scored_p) if scored_p.exists() else pd.DataFrame()
    tracker_rows = db.list_apps(limit=10_000)
    tracker = pd.DataFrame(tracker_rows)

    top_picks = (
        scored[scored["grade"].isin(["A", "B"])].copy()
        if not scored.empty and "grade" in scored.columns
        else pd.DataFrame()
    )
    top_picks_with_state = _join_state(top_picks, tracker)
    action_queue = _action_queue(top_picks_with_state)

    sheets: list[tuple[str, pd.DataFrame, list[str]]] = [
        ("Action_Queue", _select_cols(action_queue, ACTION_QUEUE_COLS), ACTION_QUEUE_COLS),
        ("Top_Picks", _select_cols(top_picks_with_state, TOP_PICKS_COLS), TOP_PICKS_COLS),
        ("Scored", _select_cols(scored, SCORED_COLS), SCORED_COLS),
        ("Filtered", _select_cols(filtered, FILTERED_COLS), FILTERED_COLS),
        ("Raw", _select_cols(raw, RAW_COLS), RAW_COLS),
        ("Tracker", _select_cols(tracker, TRACKER_COLS), TRACKER_COLS),
    ]

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        wrote_any = False
        for name, df, _cols in sheets:
            if df.empty:
                # Write an empty sheet with just headers so the workbook is consistent
                pd.DataFrame(columns=_cols).to_excel(writer, sheet_name=name, index=False)
            else:
                df.to_excel(writer, sheet_name=name, index=False)
            _autosize_and_style(writer, name)
            wrote_any = True

        if not wrote_any:
            pd.DataFrame({"info": ["pipeline has not produced any data yet"]}).to_excel(
                writer, sheet_name="Empty", index=False
            )

    counts = {n: (0 if d.empty else len(d)) for n, d, _ in sheets}
    console.print(f"[green]Wrote {out_path}[/]")
    console.print(f"  rows per sheet: {counts}")
    return out_path

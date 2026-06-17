"""Single-URL driver: extract -> sponsor-match -> score -> append to parquet
-> upsert tracker -> tailor -> review -> re-export Excel.

Both the CLI (`tailor add-url`) and the dashboard (POST /add-url) call into
``add()`` here so behavior matches across surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process
from rich.console import Console

from ..config import get_profile, get_settings
from ..ingest import url as url_extract
from ..score import scorer
from ..sponsors import filter as sponsor_filter
from ..sponsors import register as sponsor_register
from ..tailor import review_runner, runner as tailor_runner
from ..tracker import db as tracker_db


console = Console()


@dataclass
class AddResult:
    job_id: str
    row: dict
    resume_path: Path | None = None
    review: dict | None = None
    notes: list[str] = field(default_factory=list)


def _sponsor_match(company: str) -> tuple[str | None, int]:
    """Reuse the same fuzzy-match logic as sponsors/filter.py for a single
    company. Returns (matched_name_or_None, score_0_100)."""
    if not company:
        return None, 0
    try:
        sponsors_df = sponsor_register.load()
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Sponsor register unavailable ({e}); sponsor_score=0.[/]")
        return None, 0
    sponsor_names = sponsors_df["organisation_name"].tolist()
    sponsor_norm = [sponsor_filter._norm(n) for n in sponsor_names]
    norm_to_original = dict(zip(sponsor_norm, sponsor_names))
    choices = list({n for n in sponsor_norm if n})
    c_norm = sponsor_filter._norm(company)
    if not c_norm:
        return None, 0
    result = process.extractOne(
        c_norm, choices, scorer=fuzz.WRatio,
        score_cutoff=sponsor_filter.MATCH_THRESHOLD,
    )
    if result is None:
        return None, 0
    matched_norm, score, _ = result
    return norm_to_original.get(matched_norm, matched_norm), int(score)


def _upsert_parquet(scored_row: dict) -> Path:
    """Append-or-replace this id in jobs_scored.parquet, re-sort by
    score_total, and write back."""
    settings = get_settings()
    path = settings.data_dir / "jobs_scored.parquet"
    new_df = pd.DataFrame([scored_row])
    if path.exists():
        existing = pd.read_parquet(path)
        existing = existing[existing["id"] != scored_row["id"]]
        # Align columns: missing-on-existing become NA, missing-on-new become NA.
        all_cols = list(dict.fromkeys(list(existing.columns) + list(new_df.columns)))
        existing = existing.reindex(columns=all_cols)
        new_df = new_df.reindex(columns=all_cols)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined = combined.sort_values("score_total", ascending=False)
    combined.to_parquet(path, index=False)
    return path


def add(
    url: str,
    *,
    tailor: bool = True,
    review: bool = True,
    manual_overrides: dict[str, str] | None = None,
    export_excel: bool = True,
) -> AddResult:
    """Pull one URL through the full pipeline. Returns an AddResult with
    the new tracker job_id and any artifacts produced.

    manual_overrides is a dict of {title, company, location, description}
    used when auto-extraction has already failed and the caller is
    supplying the JD body directly.
    """
    profile = get_profile()
    notes: list[str] = []

    # 1. Extract -------------------------------------------------------------
    if manual_overrides:
        row = url_extract.manual_row(
            url,
            title=manual_overrides.get("title", ""),
            company=manual_overrides.get("company", ""),
            location=manual_overrides.get("location", ""),
            description=manual_overrides.get("description", ""),
        )
        notes.append("manual extraction")
    else:
        row = url_extract.extract(url)  # may raise URLExtractionError
        notes.append(f"extracted via {row.get('source')}")

    # 2. Sponsor match -------------------------------------------------------
    sponsor_match, sponsor_score = _sponsor_match(str(row.get("company") or ""))
    row["sponsor_match"] = sponsor_match
    row["sponsor_score"] = sponsor_score

    # 3. Score ---------------------------------------------------------------
    scored_extra = scorer.score_row(row, profile)
    row.update(scored_extra)
    # Mirror the dedup columns batch ingest produces — defaults are fine for ad-hoc.
    row.setdefault("dup_count", 1)
    row.setdefault("dup_sources", str(row.get("source") or ""))
    if "query_label" not in row:
        row["query_label"] = "ad-hoc-url"

    # 4. Persist to parquet --------------------------------------------------
    parquet_path = _upsert_parquet(row)
    notes.append(f"upserted -> {parquet_path.name}")

    # 5. Upsert tracker row at status=scored --------------------------------
    job_id = str(row["id"])
    existing_tracker = tracker_db.get(job_id)
    # If the row already exists with a "later" status (tailored/applied/...),
    # don't regress it back to "scored". upsert_application overwrites
    # unconditionally, so guard here.
    target_status = "scored"
    if existing_tracker:
        cur = (existing_tracker.get("status") or "").lower()
        rank = tracker_db.STATUS_RANK.get(cur, 0)
        if rank >= tracker_db.STATUS_RANK.get("scored", 1):
            target_status = cur
    tracker_db.upsert_application(
        job_id=job_id,
        title=str(row.get("title") or ""),
        company=str(row.get("company") or ""),
        url=str(row.get("url") or url),
        grade=str(row.get("grade") or ""),
        score=int(row.get("score_total") or 0),
        resume_path=str((existing_tracker or {}).get("resume_path") or ""),
        status=target_status,
    )
    console.print(
        f"[green]Added[/] {row.get('grade')} {row.get('company')} "
        f"({row.get('title')}) -> {job_id}"
    )

    result = AddResult(job_id=job_id, row=row, notes=notes)

    # 6. Tailor --------------------------------------------------------------
    if tailor:
        try:
            # tailor_one accepts any object with .get() — pd.Series or dict.
            resume_path = tailor_runner.tailor_one(pd.Series(row), force=False)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Tailor failed: {e}[/]")
            resume_path = None
            notes.append(f"tailor error: {e}")
        result.resume_path = resume_path
        if resume_path:
            notes.append(f"tailored -> {Path(resume_path).name}")

    # 7. Review --------------------------------------------------------------
    if review and tailor and result.resume_path:
        try:
            results = review_runner.review_ids([job_id])
            if results:
                result.review = results[0]
                notes.append("reviewed")
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Review failed: {e}[/]")
            notes.append(f"review error: {e}")

    # 8. Excel sidecar -------------------------------------------------------
    if export_excel:
        try:
            from ..export import excel
            excel.export_quietly()
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]Excel export skipped: {e}[/]")

    result.notes = notes
    return result

"""Tailor the top-N scored jobs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from rich.console import Console

from ..config import get_profile, get_settings
from ..tracker.db import get as tracker_get, upsert_application
from . import claude_tailor, picker, writer

console = Console()


def _safe_filename(s: str, fallback: str = "co") -> str:
    safe = "".join(c if c.isalnum() else "_" for c in (s or fallback))[:40]
    return safe or fallback


def tailor_one(row: "pd.Series", *, force: bool = False) -> Path | None:
    """Tailor a single scored-parquet row. Returns the .docx path or None
    on skip/failure. Used by both the slice-driver run() loop and the
    dashboard's per-row Tailor button.

    force=True bypasses the skip_existing check (re-tailor over the top).
    """
    settings = get_settings()
    profile = get_profile()
    job_id = str(row["id"])

    if not force:
        existing = tracker_get(job_id)
        if existing and existing.get("status") == "tailored":
            rp = Path(existing.get("resume_path") or "")
            if rp.exists() and rp.stat().st_size > 0:
                return rp  # idempotent skip

    variant = picker.pick(str(row.get("title", "")), str(row.get("description", "")))
    if variant is None:
        raise RuntimeError("No resume variants in RESUMES_DIR; check .env")

    tailored = claude_tailor.tailor(
        resume_text=variant.text,
        job_title=str(row.get("title", "")),
        company=str(row.get("company", "")),
        jd=str(row.get("description", "")),
    )

    safe_company = _safe_filename(str(row.get("company", "co")))
    out_path = settings.output_dir / "resumes" / f"{job_id}_{safe_company}.docx"
    writer.render(tailored, profile.candidate, out_path)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"Render reported success but {out_path} missing/empty")

    upsert_application(
        job_id=job_id,
        title=str(row.get("title", "")),
        company=str(row.get("company", "")),
        url=str(row.get("url", "")),
        grade=str(row.get("grade", "")),
        score=int(row.get("score_total", 0)),
        resume_path=str(out_path),
        status="tailored",
    )
    return out_path


def run_for_id(job_id: str, *, force: bool = False) -> Path | None:
    """Tailor a single job by id. Used by the dashboard's per-row button."""
    settings = get_settings()
    src = settings.data_dir / "jobs_scored.parquet"
    if not src.exists():
        raise FileNotFoundError(f"Run score first: {src} missing")
    df = pd.read_parquet(src)
    match = df[df["id"] == job_id]
    if match.empty:
        raise KeyError(f"job_id {job_id} not in jobs_scored.parquet")
    return tailor_one(match.iloc[0], force=force)


def run(top_n: int = 10, offset: int = 0, skip_existing: bool = True) -> list[Path]:
    """Tailor a slice of the scored jobs ranked by score_total descending.

    offset=0, top_n=10  -> ranks 1-10
    offset=10, top_n=15 -> ranks 11-25

    skip_existing=True (default) treats a job as already done if its tracker
    row points to a real file on disk. Cuts re-run cost when adding new jobs.
    """
    settings = get_settings()
    profile = get_profile()
    src = settings.data_dir / "jobs_scored.parquet"
    if not src.exists():
        raise FileNotFoundError(f"Run score first: {src} missing")

    df = pd.read_parquet(src)
    if df.empty:
        console.print("[yellow]No scored jobs to tailor.[/]")
        return []

    top = df.iloc[offset : offset + top_n]
    if top.empty:
        console.print(
            f"[yellow]No rows in slice offset={offset} top_n={top_n} "
            f"(scored has {len(df)} rows).[/]"
        )
        return []
    console.print(f"[dim]Tailoring ranks {offset + 1}-{offset + len(top)} of {len(df)}.[/]")
    out_paths: list[Path] = []
    for _, r in top.iterrows():
        job_id = str(r["id"])
        try:
            path = tailor_one(r, force=not skip_existing)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Tailor failed for {job_id}: {e}[/]")
            continue
        if path is None:
            continue
        # Was this an idempotent skip vs a fresh tailor?
        existing = tracker_get(job_id)
        if existing and existing.get("status") == "tailored" and skip_existing:
            console.print(f"  [dim]skip[/] {r.get('company')} (already tailored: {path.name})")
        else:
            console.print(
                f"  [green]tailored[/] {r.get('grade')} {r.get('company')} -> {path.name}"
            )
        out_paths.append(path)

    console.print(f"[green]Wrote {len(out_paths)} tailored resumes.[/]")
    return out_paths

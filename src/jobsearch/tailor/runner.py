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

        # Idempotency: skip if a tailored file already exists on disk
        if skip_existing:
            existing = tracker_get(job_id)
            if existing and existing.get("status") == "tailored":
                rp = Path(existing.get("resume_path") or "")
                if rp.exists() and rp.stat().st_size > 0:
                    console.print(f"  [dim]skip[/] {r.get('company')} (already tailored: {rp.name})")
                    out_paths.append(rp)
                    continue

        variant = picker.pick(str(r.get("title", "")), str(r.get("description", "")))
        if variant is None:
            console.print("[yellow]No resume variants found in RESUMES_DIR; skipping.[/]")
            break

        try:
            tailored = claude_tailor.tailor(
                resume_text=variant.text,
                job_title=str(r.get("title", "")),
                company=str(r.get("company", "")),
                jd=str(r.get("description", "")),
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Tailor failed for {job_id}: {e}[/]")
            continue

        safe_company = _safe_filename(str(r.get("company", "co")))
        out_path = settings.output_dir / "resumes" / f"{job_id}_{safe_company}.docx"

        # Render with tracker integrity: only upsert "tailored" if the file
        # actually landed on disk. Word file locks or OneDrive sync conflicts
        # used to leave the tracker pointing at files that never got written.
        try:
            writer.render(tailored, profile.candidate, out_path)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Render failed for {job_id} ({out_path.name}): {e}[/]")
            continue
        if not out_path.exists() or out_path.stat().st_size == 0:
            console.print(f"[red]Render reported success but {out_path} missing/empty — tracker NOT updated[/]")
            continue

        out_paths.append(out_path)
        upsert_application(
            job_id=job_id,
            title=str(r.get("title", "")),
            company=str(r.get("company", "")),
            url=str(r.get("url", "")),
            grade=str(r.get("grade", "")),
            score=int(r.get("score_total", 0)),
            resume_path=str(out_path),
            status="tailored",
        )
        console.print(
            f"  [green]tailored[/] {r.get('grade')} {r.get('company')} -> {out_path.name}"
        )

    console.print(f"[green]Wrote {len(out_paths)} tailored resumes.[/]")
    return out_paths

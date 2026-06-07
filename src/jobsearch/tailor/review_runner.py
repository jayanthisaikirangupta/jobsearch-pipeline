"""Run the reviewer over recently-tailored resumes."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from ..config import get_settings
from ..tracker import db
from . import reviewer

console = Console()


# Statuses that mean "I'm done with this row" — skipped from review by
# default to avoid wasting Bedrock tokens on rows you've already decided
# about. Override with include_done=True (CLI: --include-done).
_DONE_STATUSES = frozenset({"withdrawn", "expired", "rejected", "applied",
                            "interview", "offer"})


def _load_scored() -> pd.DataFrame:
    settings = get_settings()
    src = settings.data_dir / "jobs_scored.parquet"
    if not src.exists():
        raise FileNotFoundError(f"Run score first: {src} missing")
    return pd.read_parquet(src)


def review_top(top_n: int = 10, offset: int = 0,
               include_done: bool = False) -> list[dict]:
    """Review a slice of jobs by their score-rank in jobs_scored.parquet.

    Ranking source is the SAME parquet ``tailor run`` uses, so a fresh
    ``tailor run --offset N --top M`` followed by ``tailor review --offset N
    --top M`` reviews exactly the rows you just tailored.

    offset=0,  top_n=10 -> ranks 1-10
    offset=10, top_n=15 -> ranks 11-25

    By default rows already past the engagement gate
    (withdrawn / expired / rejected / applied / interview / offer) are
    skipped to save Bedrock tokens. Pass ``include_done=True`` to force
    re-review (e.g. after a major tailor-prompt change).
    """
    scored = _load_scored()
    slice_df = scored.iloc[offset : offset + top_n]
    if slice_df.empty:
        console.print(
            f"[yellow]No rows in slice offset={offset} top_n={top_n} "
            f"(scored has {len(scored)} rows).[/]"
        )
        return []

    apps: list[dict] = []
    skipped_done = 0
    for job_id in slice_df["id"].tolist():
        rec = db.get(str(job_id))
        if not rec:
            console.print(
                f"[yellow]Skipping {job_id}: not in tracker (run `tailor run` first).[/]"
            )
            continue
        status = (rec.get("status") or "").lower()
        if (not include_done) and status in _DONE_STATUSES:
            skipped_done += 1
            console.print(
                f"[dim]Skipping {job_id}: status={status} "
                f"(use --include-done to re-review).[/]"
            )
            continue
        if not rec.get("resume_path"):
            console.print(f"[yellow]Skipping {job_id}: no resume_path on tracker row.[/]")
            continue
        apps.append(rec)

    if not apps:
        msg = "No reviewable rows in this slice."
        if skipped_done:
            msg += f" ({skipped_done} done, hidden by default; --include-done to override.)"
        else:
            msg += " Did you `tailor run` over the same range?"
        console.print(f"[yellow]{msg}[/]")
        return []

    extra = f", {skipped_done} done-status hidden" if skipped_done else ""
    console.print(
        f"[dim]Reviewing ranks {offset + 1}-{offset + len(slice_df)} "
        f"of {len(scored)} ({len(apps)} reviewable{extra}).[/]"
    )
    return _review_each(apps, scored)


def review_one(job_id: str) -> dict | None:
    """Back-compat wrapper. Prefer review_ids() for one or more ids."""
    results = review_ids([job_id])
    return results[0] if results else None


def review_ids(job_ids: list[str]) -> list[dict]:
    """Review the specified job_ids. Order is preserved. Missing rows are
    skipped with a yellow warning rather than aborting the batch."""
    scored = _load_scored()
    apps: list[dict] = []
    for jid in job_ids:
        jid = str(jid).strip()
        if not jid:
            continue
        rec = db.get(jid)
        if not rec:
            console.print(f"[red]Skipping {jid}: not in tracker.[/]")
            continue
        if not rec.get("resume_path"):
            console.print(f"[red]Skipping {jid}: no tailored resume on file.[/]")
            continue
        apps.append(rec)

    if not apps:
        console.print("[yellow]Nothing to review.[/]")
        return []
    console.print(f"[dim]Reviewing {len(apps)} job(s) by id.[/]")
    return _review_each(apps, scored)


def _review_each(apps: list[dict], scored: pd.DataFrame) -> list[dict]:
    results: list[dict] = []
    table = Table(show_lines=False)
    for col in ("job_id", "grade", "score", "company", "role", "review"):
        table.add_column(col)

    for app in apps:
        resume_path = Path(app.get("resume_path") or "")
        if not resume_path.exists():
            console.print(f"[yellow]Skipping {app['job_id']}: {resume_path} missing[/]")
            continue
        match = scored[scored["id"] == app["job_id"]]
        if match.empty:
            console.print(f"[yellow]Skipping {app['job_id']}: not in scored parquet[/]")
            continue
        row = match.iloc[0]
        jd_text = str(row.get("description", ""))
        if not jd_text.strip():
            console.print(f"[yellow]Skipping {app['job_id']}: no JD text on file[/]")
            continue

        try:
            result = reviewer.review_resume(
                resume_docx=resume_path,
                jd_text=jd_text,
                role_title=str(row.get("title", "")),
                company=str(row.get("company", "")),
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Reviewer failed for {app['job_id']}: {e}[/]")
            continue

        results.append(result)
        c = result["critique"]

        # Persist reviewer output to the tracker so it shows up in jobs.xlsx
        # alongside the deterministic score, and you can sort by it.
        try:
            score_val = c.get("score")
            db.set_review(
                app["job_id"],
                score=int(score_val) if score_val is not None else None,
                grade=str(c.get("overall_grade") or "") or None,
                verdict=str(c.get("verdict") or "") or None,
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]Could not persist review for {app['job_id']}: {e}[/]")

        table.add_row(
            str(app["job_id"]),
            str(c.get("overall_grade", "?")),
            str(c.get("score", "?")),
            str(result["company"])[:30],
            str(result["role"])[:35],
            str(c.get("verdict", ""))[:60],
        )

    console.print(table)
    if results:
        first_md = Path(results[0]["resume"]).with_suffix(".review.md")
        console.print(f"[dim]Per-resume markdown reviews written next to each .docx (e.g. {first_md.name})[/]")
    return results

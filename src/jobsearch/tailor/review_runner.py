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
               include_done: bool = False,
               target: int | None = None) -> list[dict]:
    """Review a slice of jobs by their score-rank in jobs_scored.parquet.

    Ranking source is the SAME parquet ``tailor run`` uses, so a fresh
    ``tailor run --offset N --top M`` followed by ``tailor review --offset N
    --top M`` reviews exactly the rows you just tailored.

    Two modes (mutually exclusive — ``target`` wins if both passed):

    1. Positional slice (``top_n``). Default. Reviews the first ``top_n``
       ranks starting at ``offset``. Done rows in that slice are auto-
       skipped but the slice does NOT extend past ``offset + top_n``. So
       --top 25 with 4 done rows reviews 21 — not 25.

    2. Auto-fill (``target``). Walks the parquet from ``offset`` onwards
       and reviews until ``target`` actual reviews complete (or end of
       parquet). Done rows and missing-resume rows are silently skipped
       from the count. Use this when you want "my next N actionable
       reviews" regardless of how many rows have already been touched.

    By default done-status rows (withdrawn/expired/rejected/applied/
    interview/offer) are skipped to save Bedrock tokens. Pass
    ``include_done=True`` to force re-review.
    """
    scored = _load_scored()
    if scored.empty:
        console.print("[yellow]No scored jobs.[/]")
        return []

    if target is not None and target > 0:
        # Auto-fill mode
        candidate_df = scored.iloc[offset:]
        return _review_collected(
            candidate_df, scored,
            limit=target, include_done=include_done,
            mode_label=f"target={target} (auto-advance from rank {offset + 1})",
        )

    # Positional-slice mode (legacy / current default)
    slice_df = scored.iloc[offset : offset + top_n]
    if slice_df.empty:
        console.print(
            f"[yellow]No rows in slice offset={offset} top_n={top_n} "
            f"(scored has {len(scored)} rows).[/]"
        )
        return []
    return _review_collected(
        slice_df, scored,
        limit=None, include_done=include_done,
        mode_label=f"ranks {offset + 1}-{offset + len(slice_df)}",
    )


def _review_collected(candidate_df: "pd.DataFrame", scored: "pd.DataFrame", *,
                      limit: int | None,
                      include_done: bool,
                      mode_label: str) -> list[dict]:
    """Walk candidate_df in order. Collect tracker records that are
    reviewable (have a resume + not done by default). If ``limit`` is set,
    stop after that many. If None, walk the whole frame."""
    apps: list[dict] = []
    skipped_done = 0
    skipped_no_resume = 0
    skipped_untracked = 0
    walked = 0

    for job_id in candidate_df["id"].tolist():
        if limit is not None and len(apps) >= limit:
            break
        walked += 1
        rec = db.get(str(job_id))
        if not rec:
            skipped_untracked += 1
            if limit is None:
                console.print(
                    f"[yellow]Skipping {job_id}: not in tracker (run `tailor run` first).[/]"
                )
            continue
        status = (rec.get("status") or "").lower()
        if (not include_done) and status in _DONE_STATUSES:
            skipped_done += 1
            if limit is None:
                console.print(
                    f"[dim]Skipping {job_id}: status={status} "
                    f"(use --include-done to re-review).[/]"
                )
            continue
        if not rec.get("resume_path"):
            skipped_no_resume += 1
            if limit is None:
                console.print(
                    f"[yellow]Skipping {job_id}: no resume_path on tracker row.[/]"
                )
            continue
        apps.append(rec)

    if not apps:
        bits = []
        if skipped_done: bits.append(f"{skipped_done} done")
        if skipped_no_resume: bits.append(f"{skipped_no_resume} no-resume")
        if skipped_untracked: bits.append(f"{skipped_untracked} untracked")
        detail = " (" + ", ".join(bits) + ")" if bits else ""
        console.print(f"[yellow]No reviewable rows in {mode_label}{detail}.[/]")
        return []

    extras: list[str] = []
    if skipped_done: extras.append(f"{skipped_done} done")
    if skipped_no_resume: extras.append(f"{skipped_no_resume} no-resume")
    if skipped_untracked: extras.append(f"{skipped_untracked} untracked")
    extra_str = " (" + ", ".join(extras) + " skipped)" if extras else ""
    console.print(
        f"[dim]Reviewing {len(apps)} of {walked} walked in {mode_label}{extra_str}.[/]"
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

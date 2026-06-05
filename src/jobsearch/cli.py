"""Top-level CLI."""
from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli() -> None:
    """Sponsor-licensed UK job search pipeline."""


# ----- sponsors --------------------------------------------------------------
@cli.group()
def sponsors() -> None:
    """gov.uk Register of Licensed Sponsors."""


@sponsors.command("fetch")
@click.option("--force", is_flag=True, help="Bypass the 24h cache.")
def sponsors_fetch(force: bool) -> None:
    from .sponsors import register
    register.fetch(force=force)


# ----- ingest ----------------------------------------------------------------
@cli.group()
def ingest() -> None:
    """Scrape configured boards."""


@ingest.command("run")
@click.option("--config", "config_path", default="config/queries.yaml", show_default=True)
def ingest_run(config_path: str) -> None:
    from .ingest import runner
    runner.run(config_path)


# ----- filter ----------------------------------------------------------------
@cli.group()
def filter() -> None:
    """Sponsor filter."""


@filter.command("run")
@click.option("--no-export", is_flag=True, help="Skip the Excel sidecar.")
def filter_run(no_export: bool) -> None:
    from .sponsors import filter as sf
    sf.filter_jobs()
    if not no_export:
        from .export import excel
        excel.export_quietly()


# ----- score -----------------------------------------------------------------
@cli.group()
def score() -> None:
    """A-F grading."""


@score.command("run")
@click.option("--no-export", is_flag=True, help="Skip the Excel sidecar.")
def score_run(no_export: bool) -> None:
    from .score import scorer
    scorer.score_jobs()
    if not no_export:
        from .export import excel
        excel.export_quietly()


# ----- tailor ----------------------------------------------------------------
@cli.group()
def tailor() -> None:
    """Resume tailoring with Claude."""


@tailor.command("run")
@click.option("--top", type=int, default=10, show_default=True,
              help="How many ranks to tailor.")
@click.option("--offset", type=int, default=0, show_default=True,
              help="Skip this many top ranks before tailoring (e.g. --offset 10 --top 15 = ranks 11-25).")
@click.option("--no-export", is_flag=True, help="Skip the Excel sidecar.")
def tailor_run(top: int, offset: int, no_export: bool) -> None:
    from .tailor import runner
    runner.run(top_n=top, offset=offset)
    if not no_export:
        from .export import excel
        excel.export_quietly()


@tailor.command("review")
@click.option("--top", type=int, default=10, show_default=True,
              help="How many tailored applications to review.")
@click.option("--offset", type=int, default=0, show_default=True,
              help="Skip this many top ranks before reviewing (e.g. --offset 10 --top 15 = ranks 11-25).")
@click.option("--job-id", "job_ids", multiple=True,
              help="Review specific jobs by id. Pass multiple times or comma-separate. Overrides --top/--offset.")
def tailor_review(top: int, offset: int, job_ids: tuple[str, ...]) -> None:
    from .tailor import review_runner
    if job_ids:
        # Allow comma-separated values too: --job-id "abc,def" or --job-id abc --job-id def
        flat: list[str] = []
        for item in job_ids:
            flat.extend(p.strip() for p in item.split(",") if p.strip())
        review_runner.review_ids(flat)
    else:
        review_runner.review_top(top_n=top, offset=offset)


# ----- tracker ---------------------------------------------------------------
@cli.group()
def tracker() -> None:
    """Application tracker (SQLite)."""


@tracker.command("list")
@click.option("--status", default=None)
@click.option("--limit", default=50, show_default=True)
def tracker_list(status: str | None, limit: int) -> None:
    from .tracker import db
    rows = db.list_apps(status=status, limit=limit)
    if not rows:
        console.print("[yellow]Tracker is empty.[/]")
        return
    table = Table(show_lines=False)
    for col in ("grade", "score", "company", "title", "status", "job_id"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r.get("grade", "")),
            str(r.get("score", "")),
            str(r.get("company", ""))[:32],
            str(r.get("title", ""))[:40],
            str(r.get("status", "")),
            str(r.get("job_id", "")),
        )
    console.print(table)


@tracker.command("reconcile")
@click.option("--dry-run", is_flag=True,
              help="Show what would change without modifying the tracker.")
@click.option("--no-export", is_flag=True, help="Skip the Excel sidecar.")
def tracker_reconcile(dry_run: bool, no_export: bool) -> None:
    """Re-key tracker rows to current scored ids by (company, title), merging
    duplicate URLs from prior ingest runs and marking expired postings."""
    from .tracker import reconcile as rec
    report = rec.reconcile(dry_run=dry_run)
    rec.print_report(report, dry_run=dry_run)
    if not dry_run and not no_export:
        from .export import excel
        excel.export_quietly()


@tracker.command("set")
@click.argument("job_id")
@click.argument("status")
@click.option("--notes", default="")
@click.option("--no-export", is_flag=True, help="Skip the Excel sidecar.")
def tracker_set(job_id: str, status: str, notes: str, no_export: bool) -> None:
    from .tracker import db
    if db.set_status(job_id, status, notes):
        console.print(f"[green]{job_id} -> {status}[/]")
        if not no_export:
            from .export import excel
            excel.export_quietly()
    else:
        console.print(f"[red]No such job_id {job_id}[/]")


# ----- dashboard -------------------------------------------------------------
@cli.command("dashboard")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=8000, show_default=True)
@click.option("--reload", is_flag=True, help="Auto-reload on code change (dev).")
def dashboard_cmd(host: str, port: int, reload: bool) -> None:
    """Launch the local web dashboard at http://HOST:PORT.

    Reads jobs_scored.parquet + tracker.sqlite live on every request — no
    Excel re-export needed. One-click status updates persist to SQLite.
    """
    try:
        import uvicorn
    except ImportError as e:
        raise click.ClickException(
            "fastapi/uvicorn not installed. Run: pip install -e \".[dashboard]\""
        ) from e
    console.print(f"[cyan]Dashboard at http://{host}:{port}  (Ctrl-C to stop)[/]")
    uvicorn.run(
        "jobsearch.dashboard.app:app",
        host=host, port=port, reload=reload,
        log_level="warning",
    )


# ----- pipeline (one-shot) ---------------------------------------------------
@cli.group()
def pipeline() -> None:
    """End-to-end pipeline orchestration."""


@pipeline.command("run")
@click.option("--config", "config_path", default="config/queries.yaml", show_default=True,
              help="Query config used for ingest.")
@click.option("--top", type=int, default=10, show_default=True,
              help="Top-N jobs to tailor + review.")
@click.option("--skip-sponsors", is_flag=True,
              help="Skip the gov.uk sponsor register refresh (use cached CSV).")
@click.option("--skip-tailor", is_flag=True,
              help="Skip resume tailoring (and review).")
@click.option("--skip-review", is_flag=True,
              help="Skip the JD-aware reviewer pass.")
def pipeline_run(config_path: str, top: int, skip_sponsors: bool,
                 skip_tailor: bool, skip_review: bool) -> None:
    from .pipeline import runner
    runner.run(
        config_path=config_path,
        top=top,
        skip_sponsors=skip_sponsors,
        skip_tailor=skip_tailor,
        skip_review=skip_review,
    )


# ----- answer ----------------------------------------------------------------
@cli.command("answer")
@click.option("--job-id", required=True, help="Tracked job id (run `tracker list` to find).")
@click.option("--question", "-q", required=True,
              help='The application question. Quote it: --question "Why this role?"')
@click.option("--tone", default="professional", show_default=True,
              type=click.Choice(["concise", "professional", "warm", "formal"]),
              help="Tone preset for the answer.")
@click.option("--max-words", type=int, default=None,
              help="Hard length cap (e.g. 150 for a cover-letter slot).")
@click.option("--no-append", is_flag=True,
              help="Do not append to the .answers.md sidecar; just print.")
def answer_cmd(job_id: str, question: str, tone: str, max_words: int | None,
               no_append: bool) -> None:
    """Generate one tailored answer for an application question, grounded in the JD + your tailored resume."""
    from .answer import answer as answer_mod
    answer_mod.show(job_id, question, tone=tone, max_words=max_words, append=not no_append)


# ----- export ----------------------------------------------------------------
@cli.group()
def export() -> None:
    """Export pipeline state."""


@export.command("xlsx")
@click.option("--out", "out_path", default=None,
              help="Output path. Defaults to <OUTPUT_DIR>/jobs.xlsx.")
def export_xlsx(out_path: str | None) -> None:
    from .export import excel
    from pathlib import Path as _P
    excel.export(_P(out_path) if out_path else None)


# ----- apply -----------------------------------------------------------------
@cli.group()
def apply() -> None:
    """Browser-use pre-fill (human submits)."""


@apply.command("run")
@click.option("--job-id", required=True)
@click.option("--mode", type=click.Choice(["manual", "browser-use"]), default="manual",
              show_default=True,
              help="manual: open URL in your default browser, you submit. browser-use: LLM agent pre-fills (often blocked by SSO/captchas).")
def apply_run(job_id: str, mode: str) -> None:
    from .apply import prefiller
    if mode == "browser-use":
        asyncio.run(prefiller.prefill_with_browser_use(job_id))
    else:
        prefiller.manual(job_id)


if __name__ == "__main__":
    cli()

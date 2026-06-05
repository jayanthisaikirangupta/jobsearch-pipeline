"""End-to-end pipeline orchestrator.

Calls every step in order in a single Python process. Each step's existing
runner is reused — this module only sequences them and surfaces a clean
summary at the end.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class StepResult:
    name: str
    status: str  # "ok", "skipped", "error"
    elapsed_s: float
    note: str = ""


def _step(name: str, fn, results: list[StepResult]) -> bool:
    """Run a single step, capture timing + outcome. Returns True on success."""
    console.rule(f"[bold cyan]{name}")
    t0 = time.monotonic()
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        console.print(f"[red]{name} failed after {elapsed:.1f}s: {e}[/]")
        results.append(StepResult(name, "error", elapsed, str(e)))
        return False
    elapsed = time.monotonic() - t0
    console.print(f"[green]{name} ok ({elapsed:.1f}s)[/]")
    results.append(StepResult(name, "ok", elapsed))
    return True


def _skip(name: str, reason: str, results: list[StepResult]) -> None:
    console.rule(f"[bold yellow]{name} (skipped)")
    console.print(f"[dim]{reason}[/]")
    results.append(StepResult(name, "skipped", 0.0, reason))


def run(
    *,
    config_path: str = "config/queries.yaml",
    top: int = 10,
    skip_sponsors: bool = False,
    skip_tailor: bool = False,
    skip_review: bool = False,
) -> list[StepResult]:
    """Run the full daily pipeline. Returns per-step results; early-exits on
    any hard failure that would make later steps impossible."""
    results: list[StepResult] = []

    # ---- 1. sponsors fetch ----
    if skip_sponsors:
        _skip("sponsors fetch", "skip-sponsors flag set", results)
    else:
        from ..sponsors import register
        if not _step("sponsors fetch", lambda: register.fetch(force=False), results):
            console.print("[yellow]Sponsor register fetch failed — filter step will fall back to cached CSV if present.[/]")

    # ---- 2. ingest ----
    from ..ingest import runner as ingest_runner
    if not _step("ingest", lambda: ingest_runner.run(config_path), results):
        # Hard failure: filter has nothing to act on
        _print_summary(results)
        return results

    # ---- 3. filter ----
    from ..sponsors import filter as sf
    if not _step("filter", lambda: sf.filter_jobs(), results):
        _print_summary(results)
        return results

    # ---- 4. score ----
    from ..score import scorer
    if not _step("score", lambda: scorer.score_jobs(), results):
        _print_summary(results)
        return results

    # ---- 5. tailor ----
    if skip_tailor:
        _skip("tailor", "skip-tailor flag set", results)
    else:
        from ..tailor import runner as tailor_runner
        _step(f"tailor (top {top})", lambda: tailor_runner.run(top_n=top), results)

    # ---- 6. review ----
    if skip_review or skip_tailor:
        _skip("review", "skip-review or skip-tailor flag set", results)
    else:
        from ..tailor import review_runner
        _step(f"review (top {top})", lambda: review_runner.review_top(top_n=top), results)

    # ---- 7. excel sidecar ----
    from ..export import excel
    _step("export xlsx", lambda: excel.export_quietly(), results)

    _print_summary(results)
    return results


def _print_summary(results: list[StepResult]) -> None:
    table = Table(title="Pipeline summary", show_lines=False)
    table.add_column("Step")
    table.add_column("Status")
    table.add_column("Elapsed")
    table.add_column("Note")
    total = 0.0
    for r in results:
        color = {"ok": "green", "skipped": "yellow", "error": "red"}[r.status]
        table.add_row(r.name, f"[{color}]{r.status}[/]", f"{r.elapsed_s:.1f}s", r.note[:60])
        total += r.elapsed_s
    table.caption = f"Total: {total:.1f}s"
    console.print()
    console.print(table)

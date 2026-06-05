"""Reconcile tracker rows that have drifted out of sync with the scored parquet.

Why drift happens:
  * Indeed/LinkedIn rotate URLs when a job is reposted -> new scrape id.
  * Dedup picks a different representative URL each ingest run.
  * Postings expire upstream and disappear from the scored parquet.

Reconciliation strategy per orphan tracker row (orphan = id is in tracker but
not in jobs_scored.parquet):

  1. Match by (company, title) against the current scored parquet.
  2. If a canonical scored row exists:
       - Merge the orphan's status/notes/resume_path onto the canonical id.
       - Pick the most decisive status (applied > tailored > discovered).
       - Delete the orphan row.
  3. If no canonical match exists (posting genuinely expired upstream):
       - Mark the orphan status as 'expired'. Keep the row for history.

This is idempotent: running it twice is a no-op the second time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd
from rich.console import Console
from rich.table import Table

from ..config import get_settings
from . import db

console = Console()


@dataclass
class ReconcileReport:
    merged: list[tuple[str, str, str]] = field(default_factory=list)  # (orphan_id, canonical_id, company)
    expired: list[tuple[str, str]] = field(default_factory=list)      # (orphan_id, company)
    kept: int = 0


def _load_scored() -> pd.DataFrame:
    settings = get_settings()
    src = settings.data_dir / "jobs_scored.parquet"
    if not src.exists():
        raise FileNotFoundError(f"Run score first: {src} missing")
    return pd.read_parquet(src)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _pick_winner(rows: Iterable[dict]) -> dict:
    """Pick the most decisive tracker row from a set covering the same canonical job."""
    best = None
    for r in rows:
        rank = db.STATUS_RANK.get(r.get("status", "discovered"), 0)
        has_resume = bool(r.get("resume_path"))
        # tiebreak: rank desc, has_resume desc, updated_at desc
        key = (rank, int(has_resume), r.get("updated_at") or "")
        if best is None or key > best[0]:
            best = (key, r)
    return best[1] if best else {}


def reconcile(dry_run: bool = False) -> ReconcileReport:
    """Walk every tracker row, fix the orphans. Returns a report."""
    scored = _load_scored()
    scored_ids = set(scored["id"])

    # Build a (norm_company, norm_title) -> canonical_id index from the parquet
    canon_index: dict[tuple[str, str], str] = {}
    for _, r in scored.iterrows():
        key = (_norm(r.get("company")), _norm(r.get("title")))
        # First match wins (parquet is sorted by score DESC so this is the best canonical)
        canon_index.setdefault(key, str(r["id"]))

    tracked = db.list_apps(limit=10_000)
    report = ReconcileReport()

    # Group orphans + any tracker rows that share a canonical id, so we can merge
    by_canon: dict[str, list[dict]] = {}
    standalone_orphans: list[dict] = []
    for app in tracked:
        jid = app["job_id"]
        if jid in scored_ids:
            # Tracker id matches a current scored row directly — bucket under its own id
            by_canon.setdefault(jid, []).append(app)
            continue
        # Orphan: try to find a canonical row by company+title
        key = (_norm(app.get("company")), _norm(app.get("title")))
        canon = canon_index.get(key)
        if canon:
            by_canon.setdefault(canon, []).append(app)
        else:
            standalone_orphans.append(app)

    # === Merge groups that share a canonical id ===
    for canon_id, group in by_canon.items():
        if len(group) == 1 and group[0]["job_id"] == canon_id:
            report.kept += 1
            continue  # nothing to merge
        winner = _pick_winner(group)
        if dry_run:
            for r in group:
                if r["job_id"] != canon_id:
                    report.merged.append((r["job_id"], canon_id, r.get("company", "")))
            continue
        # Upsert the winner's data onto canon_id
        db.upsert_application(
            job_id=canon_id,
            title=winner.get("title", ""),
            company=winner.get("company", ""),
            url=winner.get("url", ""),
            grade=winner.get("grade", ""),
            score=int(winner.get("score") or 0),
            resume_path=winner.get("resume_path", ""),
            status=winner.get("status", "discovered"),
            notes=(winner.get("notes") or "").strip(),
        )
        # Delete every non-canonical orphan in the group
        for r in group:
            if r["job_id"] != canon_id:
                db.delete(r["job_id"])
                report.merged.append((r["job_id"], canon_id, r.get("company", "")))

    # === Mark truly expired orphans ===
    for app in standalone_orphans:
        if app.get("status") == "expired":
            report.kept += 1
            continue
        if not dry_run:
            db.set_status(app["job_id"], "expired",
                          notes=f"posting no longer in scored parquet ({app.get('status', '')})")
        report.expired.append((app["job_id"], app.get("company", "")))

    return report


def print_report(report: ReconcileReport, dry_run: bool) -> None:
    title = "Reconcile (DRY RUN)" if dry_run else "Reconcile"
    console.print(f"[bold cyan]{title}[/]")

    if report.merged:
        t = Table(title=f"Merged orphans onto canonical ids ({len(report.merged)})")
        t.add_column("Orphan id"); t.add_column("Canonical id"); t.add_column("Company")
        for orphan, canon, company in report.merged:
            t.add_row(orphan, canon, company[:40])
        console.print(t)

    if report.expired:
        t = Table(title=f"Marked expired ({len(report.expired)})")
        t.add_column("Tracker id"); t.add_column("Company")
        for jid, company in report.expired:
            t.add_row(jid, company[:40])
        console.print(t)

    console.print(f"[dim]Untouched canonical rows: {report.kept}[/]")
    if dry_run:
        console.print("[yellow]Dry run - nothing was modified. Re-run without --dry-run to apply.[/]")

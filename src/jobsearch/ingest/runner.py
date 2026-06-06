"""Run a query config across all configured sources and persist a single parquet."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from rich.console import Console

from ..config import get_settings
from .base import Query
from .sources import get_source

console = Console()


def _load_queries(path: str | Path) -> tuple[dict, list[dict]]:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return cfg.get("defaults", {}), cfg.get("queries", [])


def run(config_path: str | Path) -> Path:
    settings = get_settings()
    defaults, queries = _load_queries(config_path)

    frames: list[pd.DataFrame] = []
    for q in queries:
        sources = q.get("sources", ["indeed"])
        query = Query(
            label=q["label"],
            search_term=q["search_term"],
            location=q["location"],
            country_indeed=defaults.get("country_indeed", "UK"),
            hours_old=defaults.get("hours_old", 168),
            results_wanted=defaults.get("results_wanted", 50),
            description_format=defaults.get("description_format", "markdown"),
            location_overrides=q.get("location_overrides", {}) or {},
        )
        for src_key in sources:
            src = get_source(src_key)
            try:
                df = src.fetch(query)
            except Exception as e:  # noqa: BLE001
                console.print(f"[yellow]Source {src_key} failed for {query.label}: {e}[/]")
                continue
            df["query_label"] = query.label
            console.print(f"  {src_key:9s} {query.label:25s} -> {len(df)} rows")
            frames.append(df)

    if not frames:
        console.print("[red]No rows fetched. Check network / source availability.[/]")
        out = settings.data_dir / "jobs_raw.parquet"
        pd.DataFrame().to_parquet(out)
        return out

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.drop_duplicates(subset=["id"], keep="first")

    # Schema normalisation across sources. JobSpy sources return Timestamp
    # for posted_at; ATS sources return ISO-string. Coerce to a single
    # string representation so parquet write doesn't choke on mixed types.
    all_df["posted_at"] = all_df["posted_at"].astype("string")

    # Numeric salary fields likewise: JobSpy returns float, Adzuna returns
    # int, ATS leaves NA. Coerce min/max to float64 with NaN.
    for col in ("min_amount", "max_amount"):
        all_df[col] = pd.to_numeric(all_df[col], errors="coerce")

    # Semantic dedup: same role posted via different URLs / sources collapses
    # to one row. Adds dup_count + dup_sources columns. See ingest/dedup.py.
    from . import dedup
    before = len(all_df)
    all_df = dedup.deduplicate(all_df)
    after = len(all_df)
    if after < before:
        console.print(f"  dedup: {before} -> {after} rows ({before - after} duplicates collapsed)")

    out = settings.data_dir / "jobs_raw.parquet"
    all_df.to_parquet(out, index=False)
    console.print(f"[green]Wrote {len(all_df)} unique rows -> {out}[/]")
    return out

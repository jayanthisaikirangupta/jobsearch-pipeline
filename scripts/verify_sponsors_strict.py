"""One-off: re-verify each active job's company against the live sponsor register
using an EXACT-legal-entity rule (no fuzzy match). Companies that don't match are
candidates to be marked withdrawn (no sponsor licence).

Outputs three buckets to stdout:
  CONFIRMED — exact normalised match in the register
  AMBIGUOUS — no exact match but a strong substring/token-overlap candidate; needs manual/CH check
  UNVERIFIED — no plausible match; safe to withdraw

Run from repo root: python scripts/verify_sponsors_strict.py
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd

ACTIVE = ("discovered", "scored", "tailored", "applied", "interview")
ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "data" / "tracker.sqlite"
REGISTER = ROOT / "data" / "sponsor_register.csv"

SUFFIX = re.compile(
    r"\b(ltd|limited|llp|plc|inc|incorporated|corp|corporation|"
    r"uk|holdings?|group|company|co|the|and|&|of)\b\.?",
    re.IGNORECASE,
)
PUNCT = re.compile(r"[^a-z0-9 ]")


def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = SUFFIX.sub(" ", s)
    s = PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set[str]:
    return {t for t in norm(s).split() if len(t) > 1}


def main() -> None:
    df = pd.read_csv(REGISTER, dtype=str, encoding="utf-8", on_bad_lines="skip")
    org_col = next(c for c in df.columns if c.strip().lower() == "organisation name")
    # De-dup: the register lists the same legal entity once per route, so we'd
    # otherwise count one entity multiple times in the token-overlap heuristic.
    register_names = sorted(set(df[org_col].dropna().astype(str).tolist()))
    register_norm: dict[str, list[str]] = defaultdict(list)
    for n in register_names:
        register_norm[norm(n)].append(n)

    register_token_index: dict[str, set[str]] = defaultdict(set)
    for n in register_names:
        for t in tokens(n):
            register_token_index[t].add(n)

    con = sqlite3.connect(TRACKER)
    con.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(ACTIVE))
    rows = list(
        con.execute(
            f"SELECT DISTINCT company FROM applications WHERE status IN ({placeholders}) AND company IS NOT NULL",
            ACTIVE,
        )
    )
    companies = sorted({r["company"] for r in rows if r["company"]})

    confirmed: list[tuple[str, str]] = []
    ambiguous: list[tuple[str, list[str]]] = []
    unverified: list[str] = []

    for c in companies:
        cn = norm(c)
        if not cn:
            unverified.append(c)
            continue
        if cn in register_norm:
            confirmed.append((c, register_norm[cn][0]))
            continue
        # Exact normalised lookup failed; collect register entries whose token
        # set is a SUPERSET of the company's tokens (every company token appears).
        ctoks = tokens(c)
        if not ctoks:
            unverified.append(c)
            continue
        candidate_sets: list[set[str]] = [register_token_index.get(t, set()) for t in ctoks]
        if not all(candidate_sets):
            unverified.append(c)
            continue
        full_token_matches = sorted(set.intersection(*candidate_sets))
        if full_token_matches:
            ambiguous.append((c, full_token_matches[:5]))
        else:
            unverified.append(c)

    print(f"\n=== CONFIRMED ({len(confirmed)}) — exact normalised match ===")
    for c, m in confirmed:
        print(f"  {c}  ->  {m}")

    print(f"\n=== AMBIGUOUS ({len(ambiguous)}) — register entries contain all company tokens ===")
    for c, cands in ambiguous:
        print(f"  {c}")
        for cand in cands:
            print(f"      ?  {cand}")

    print(f"\n=== UNVERIFIED ({len(unverified)}) — no plausible register entry ===")
    for c in unverified:
        print(f"  {c}")


if __name__ == "__main__":
    main()

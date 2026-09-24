"""Final sponsor verification.

For each active tracker row (status in discovered/scored/tailored/applied/interview):
  1. Normalise company name and try exact match against the dedup-ed register.
  2. Try a curated brand -> register-name override (verified by hand from probes
     against the 2026-06-11 register). This handles brand-vs-legal-name cases
     like "Apple" -> "Apple Europe Limited".
  3. Otherwise mark as UNVERIFIED.

Default is dry-run: prints buckets and per-row impact.
Pass --apply to mutate the tracker (status -> 'withdrawn', notes append the reason).
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "data" / "tracker.sqlite"
REGISTER = ROOT / "data" / "sponsor_register.csv"

ACTIVE = ("discovered", "scored", "tailored", "applied", "interview")

# Curated mapping: messy job-board company string -> exact register entry that
# represents the same UK legal entity. Each pair was confirmed by manual probe
# against data/sponsor_register.csv on 2026-06-11. If the user disagrees with a
# mapping, edit this dict and re-run.
BRAND_OVERRIDES: dict[str, str] = {
    "American Express": "American Express Services Europe Limited",
    "Apple": "Apple Europe Limited",
    "AXIOM": "Axiom Global Limited",
    "Barclays": "Barclays Bank PLC",
    "CRU": "CRU International Ltd",
    "DataArt": "DataArt Technologies UK Ltd",
    "DoiT": "DOIT International UK&I Ltd",
    "Engelhart": "Engelhart CTP UK Ltd",
    "Heidi": "Heidi Health Ltd",
    "Intercom": "Intercom Software UK Limited",
    "Ipsos": "Ipsos Mori UK Limited",
    "JD.com": "JD.COM International UK Ltd",
    "JPMorganChase": "JPMorgan Chase Bank, National Association",
    "Leidos": "Leidos Innovations UK Ltd",
    "Manufacturing Technology Centre": "The Manufacturing Technology Centre Services Ltd",
    "McKinsey & Company": "McKinsey & Company Inc. United Kingdom",
    "Metrea Management LLC": "METREA MANAGEMENT LIMITED",
    "Monzo": "Monzo Bank Ltd",
    "Team17 Digital": "Team 17 Digital Limited",
    "Tesco": "Tesco Stores Limited",
    "Turner & Townsend Pty Limited": "Turner & Townsend Ltd",
    "WPP": "WPP 2005 Limited",
}

# Known NOT on register (verified by exhaustive probe). Mapped to None so we
# document the verdict rather than letting a future maintainer assume "unchecked".
KNOWN_UNSPONSORED: dict[str, str] = {
    "Skin + Me": "no SKIN + ME LTD entry; brand is not on the register",
    "G-Research": "no G-Research / Research entity matching the brand on the register",
    "Marstons Plc": "Marston's PLC not on the register (only unrelated 'Marston' entries)",
    "Wise Australia Investments": "AU entity; UK register shows only Wise Payments Limited (different)",
    "Opus 2 International": "Opus 2 not on the register",
    "Registrar Corp": "US entity; no UK entry on register",
    "Beatport": "not on register",
    "Clio": "not on register",
    "Nebius": "not on register",
    "Ookla": "not on register",
    "Scale Factory": "not on register",
    "clickhouse": "ClickHouse not on register",
    "Data Idols": "not on register",
    "Amus Technologies": "not on register",
    "Skm Group": "ambiguous SKM entries; none match the recruitment-tech 'SKM Group' brand",
    "Architect": "ambiguous; '@ Architect UK Ltd' is unrelated joinery firm",
    "Ember": "ambiguous; no Ember health/AI entity matches",
    "Singer Instrument Co Ltd": "matches Singer Instrument Company Limited (CONFIRMED, not unsponsored)",
}
# Singer Instrument was misclassified above; remove from KNOWN_UNSPONSORED.
KNOWN_UNSPONSORED.pop("Singer Instrument Co Ltd", None)

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


def load_register() -> dict[str, str]:
    df = pd.read_csv(REGISTER, dtype=str, encoding="utf-8", on_bad_lines="skip")
    org_col = next(c for c in df.columns if c.strip().lower() == "organisation name")
    register_names = sorted(set(df[org_col].dropna().astype(str).str.strip().tolist()))
    register_norm: dict[str, str] = {}
    for n in register_names:
        register_norm.setdefault(norm(n), n)
    return register_norm


def verify(company: str, register_norm: dict[str, str]) -> tuple[str, str]:
    """Return (verdict, detail). verdict in {'confirmed','unverified'}."""
    if company in KNOWN_UNSPONSORED:
        return "unverified", KNOWN_UNSPONSORED[company]
    if company in BRAND_OVERRIDES:
        return "confirmed", f"override -> {BRAND_OVERRIDES[company]}"
    cn = norm(company)
    if not cn:
        return "unverified", "empty company name"
    if cn in register_norm:
        return "confirmed", f"exact -> {register_norm[cn]}"
    return "unverified", "no exact normalised match and no override"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Mutate tracker (default: dry-run)")
    args = ap.parse_args()

    register_norm = load_register()
    con = sqlite3.connect(TRACKER)
    con.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(ACTIVE))
    rows = list(
        con.execute(
            f"SELECT job_id, title, company, status, notes FROM applications "
            f"WHERE status IN ({placeholders})",
            ACTIVE,
        )
    )

    by_company: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_company[r["company"] or ""].append(r)

    confirmed_companies: list[tuple[str, str]] = []
    unverified_rows: list[tuple[sqlite3.Row, str]] = []
    for company, group in sorted(by_company.items(), key=lambda kv: kv[0].lower()):
        verdict, detail = verify(company, register_norm)
        if verdict == "confirmed":
            confirmed_companies.append((company, detail))
        else:
            for row in group:
                unverified_rows.append((row, detail))

    print(f"\n=== CONFIRMED companies ({len(confirmed_companies)}) ===")
    for c, d in confirmed_companies:
        print(f"  {c}  ({d})")

    print(
        f"\n=== UNVERIFIED rows to mark withdrawn "
        f"({len(unverified_rows)} rows across {len({r['company'] for r,_ in unverified_rows})} companies) ==="
    )
    for r, d in unverified_rows:
        print(
            f"  [{r['status']}] {r['company']:30s} | {r['title'][:55]:55s} | {r['job_id']}  "
            f"({d})"
        )

    if not args.apply:
        print("\n(Dry run. Re-run with --apply to mutate the tracker.)")
        return

    now = pd.Timestamp.now().isoformat(timespec="seconds")
    cur = con.cursor()
    for r, d in unverified_rows:
        new_notes = f"sponsor-recheck 2026-06-11: not on register ({d})"
        cur.execute(
            "UPDATE applications SET status='withdrawn', notes=?, updated_at=? WHERE job_id=?",
            (new_notes, now, r["job_id"]),
        )
    con.commit()
    print(f"\nApplied: {len(unverified_rows)} rows updated to status='withdrawn'.")


if __name__ == "__main__":
    main()

"""SQLite tracker.

Single table 'applications' keyed by job_id. Status transitions:
discovered -> scored -> tailored -> applied -> interview -> offer | rejected.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    title TEXT,
    company TEXT,
    url TEXT,
    grade TEXT,
    score INTEGER,
    resume_path TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_grade ON applications(grade);
"""

# Columns added after v0.1. Idempotent — _conn() runs ALTER TABLE for any
# missing column on every connection. Cheap (PRAGMA + at most one ALTER per
# missing column at startup) and avoids needing a migration tool.
_LATER_COLUMNS = [
    ("reviewer_score", "INTEGER"),
    ("reviewer_grade", "TEXT"),
    ("reviewer_verdict", "TEXT"),
    ("reviewer_at", "TEXT"),
    # Free-text instructions the reviewer produced for the next tailor run.
    # Populated when the critique says the resume needs concrete edits;
    # consumed by /retailor as extra_context for the tailor LLM.
    ("retailor_instructions", "TEXT"),
]

VALID_STATUSES = {
    "discovered",
    "scored",
    "tailored",
    "applied",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "expired",  # job posting removed upstream before we could engage
}


# Status decisiveness used by reconcile() to pick a winner when merging
# duplicate tracker rows. Higher = more decisive / further along the funnel.
STATUS_RANK = {
    "discovered": 0,
    "scored": 1,
    "tailored": 2,
    "applied": 3,
    "interview": 4,
    "offer": 5,
    "rejected": 3,    # explicit terminal — same rank as applied
    "withdrawn": 3,
    "expired": 0,     # don't let an expired marker overwrite real progress
}


def delete(job_id: str) -> bool:
    """Remove a tracker row entirely. Used by reconcile() to drop merged orphans."""
    with _conn() as c:
        cur = c.execute("DELETE FROM applications WHERE job_id=?", (job_id,))
        return cur.rowcount > 0


def _db_path() -> Path:
    return get_settings().data_dir / "tracker.sqlite"


def _ensure_later_columns(c: sqlite3.Connection) -> None:
    """Add columns introduced after the original schema. Idempotent."""
    existing = {row[1] for row in c.execute("PRAGMA table_info(applications)")}
    for col, col_type in _LATER_COLUMNS:
        if col not in existing:
            c.execute(f"ALTER TABLE applications ADD COLUMN {col} {col_type}")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        _ensure_later_columns(c)
        yield c
        c.commit()
    finally:
        c.close()


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def upsert_application(
    job_id: str,
    title: str,
    company: str,
    url: str,
    grade: str,
    score: int,
    resume_path: str = "",
    status: str = "discovered",
    notes: str = "",
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status}; must be one of {sorted(VALID_STATUSES)}")
    now = _now()
    with _conn() as c:
        existing = c.execute("SELECT created_at FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        if existing:
            c.execute(
                """UPDATE applications SET
                    title=?, company=?, url=?, grade=?, score=?, resume_path=?,
                    status=?, notes=COALESCE(NULLIF(?, ''), notes), updated_at=?
                   WHERE job_id=?""",
                (title, company, url, grade, score, resume_path, status, notes, now, job_id),
            )
        else:
            c.execute(
                """INSERT INTO applications
                   (job_id, title, company, url, grade, score, resume_path,
                    status, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, title, company, url, grade, score, resume_path, status, notes, now, now),
            )


def set_review(job_id: str, *, score: int | None, grade: str | None,
               verdict: str | None,
               retailor_instructions: str | None = None) -> bool:
    """Persist reviewer output onto the tracker row. Used by review_runner.

    retailor_instructions: optional free-text guidance produced by the
    reviewer when it thinks the resume should be re-tailored. Read back by
    /retailor as extra_context for the next tailor run.
    """
    with _conn() as c:
        cur = c.execute(
            """UPDATE applications SET
                reviewer_score=?, reviewer_grade=?, reviewer_verdict=?,
                reviewer_at=?, retailor_instructions=?, updated_at=?
               WHERE job_id=?""",
            (score, grade, verdict, _now(),
             retailor_instructions, _now(), job_id),
        )
        return cur.rowcount > 0


def set_status(job_id: str, status: str, notes: str = "") -> bool:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status}")
    with _conn() as c:
        cur = c.execute(
            "UPDATE applications SET status=?, notes=COALESCE(NULLIF(?, ''), notes), updated_at=? WHERE job_id=?",
            (status, notes, _now(), job_id),
        )
        return cur.rowcount > 0


def get(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_apps(status: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM applications"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY score DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]

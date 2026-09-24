"""In-memory background task registry for the dashboard.

Why in-memory: the dashboard is a single-user local app. Tasks are short
(15-60s), don't need to survive a server restart, and there's no concurrent
write contention worth worrying about. A dict + RLock is sufficient and adds
zero deps.

Lifecycle:
  start(kind, job_id, fn, *args, **kwargs) -> task_id
        ↓ thread spawned, status='running'
  thread runs fn(*args, **kwargs)
        ↓ on success: status='done', result=<return value>
        ↓ on error:   status='error', error=<message>
  get(task_id) -> dict | None              (polled by HTMX)
  reap_finished(after_seconds=300) -> int  (housekeeping, optional)

Two task kinds: 'tailor' and 'review'. Both eventually mutate tracker.sqlite,
so the dashboard can re-render the affected row when the task completes.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Task:
    id: str
    kind: str           # "tailor" | "review" | "bulk-tailor" | "bulk-review" | ...
    job_id: str         # single id, or comma-joined list for bulk
    status: str = "running"  # running | done | error
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    error: str = ""
    result: Any = None
    # Bulk-task progress. None means "not a bulk task" — banner falls back
    # to the single-job message.
    progress: int | None = None
    total: int | None = None
    progress_label: str = ""  # e.g. current company being processed
    errors: list[str] = field(default_factory=list)


_LOCK = threading.RLock()
_TASKS: dict[str, Task] = {}


def start(kind: str, job_id: str, fn: Callable, *args, **kwargs) -> str:
    """Spawn a worker thread for fn(*args, **kwargs) and return its task_id."""
    task_id = uuid.uuid4().hex[:12]
    task = Task(id=task_id, kind=kind, job_id=job_id)
    with _LOCK:
        _TASKS[task_id] = task

    def _runner() -> None:
        try:
            result = fn(*args, **kwargs)
            with _LOCK:
                task.status = "done"
                task.result = result
                task.finished_at = time.monotonic()
        except Exception as e:  # noqa: BLE001
            with _LOCK:
                task.status = "error"
                task.error = f"{type(e).__name__}: {e}"
                task.finished_at = time.monotonic()
            # Stash a one-line trace tail so failures aren't black boxes
            tb = traceback.format_exc().splitlines()
            if tb:
                task.error += f"  ({tb[-1]})"

    t = threading.Thread(target=_runner, daemon=True, name=f"jobsearch-{kind}-{task_id}")
    t.start()
    return task_id


def start_bulk(kind: str, job_ids: list[str], fn: Callable,
               label_fn: Callable[[str], str] | None = None) -> str:
    """Spawn a worker thread that calls fn(job_id) for each id in sequence,
    updating progress as it goes. Returns the task_id.

    fn(job_id) may return anything; exceptions are caught per-row and appended
    to task.errors so a single bad row doesn't abort the batch.
    label_fn(job_id) -> str provides a human-readable label for the current
    row (e.g. company name) to show in the polling banner.
    """
    task_id = uuid.uuid4().hex[:12]
    task = Task(
        id=task_id, kind=kind, job_id=",".join(job_ids),
        progress=0, total=len(job_ids),
    )
    with _LOCK:
        _TASKS[task_id] = task

    def _runner() -> None:
        results: list[Any] = []
        for i, jid in enumerate(job_ids):
            with _LOCK:
                task.progress = i
                task.progress_label = label_fn(jid) if label_fn else jid
            try:
                results.append(fn(jid))
            except Exception as e:  # noqa: BLE001
                msg = f"{jid}: {type(e).__name__}: {e}"
                with _LOCK:
                    task.errors.append(msg)
        with _LOCK:
            task.progress = len(job_ids)
            task.progress_label = ""
            task.status = "done"
            task.result = results
            task.finished_at = time.monotonic()

    t = threading.Thread(target=_runner, daemon=True, name=f"jobsearch-{kind}-{task_id}")
    t.start()
    return task_id


def get(task_id: str) -> Task | None:
    with _LOCK:
        return _TASKS.get(task_id)


def has_active_for(job_id: str, kind: str | None = None) -> bool:
    """True if a running task exists for this job_id (and optionally kind).
    Used to disable the button while one is in flight."""
    return active_for(job_id, kind) is not None


def active_for(job_id: str, kind: str | None = None) -> Task | None:
    """Return the running task for this job_id (and optionally kind), if any."""
    with _LOCK:
        for t in _TASKS.values():
            if t.status != "running":
                continue
            if t.job_id != job_id:
                continue
            if kind and t.kind != kind:
                continue
            return t
    return None


def reap_finished(after_seconds: float = 300) -> int:
    """Drop tasks that finished more than N seconds ago. Optional housekeeping;
    not strictly necessary since the registry stays small in practice."""
    cutoff = time.monotonic() - after_seconds
    dropped = 0
    with _LOCK:
        for tid in list(_TASKS):
            t = _TASKS[tid]
            if t.finished_at and t.finished_at < cutoff:
                del _TASKS[tid]
                dropped += 1
    return dropped

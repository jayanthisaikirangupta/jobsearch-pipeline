"""FastAPI + HTMX dashboard.

Routes:
  GET  /                     — full page (split: action queue + tracker)
  GET  /action-queue         — htmx partial: action queue rows
  GET  /tracker              — htmx partial: tracker rows
  POST /tracker/{id}/status  — update status, return refreshed row
  POST /tracker/{id}/notes   — update notes, return refreshed row
  GET  /open/{id}            — open URL in default browser, return empty
  GET  /open-resume/{id}     — open the tailored .docx in Word

The dashboard never goes stale: every render queries SQLite + parquet fresh.
"""
from __future__ import annotations

import platform
import subprocess
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ..tracker import db
from . import data, tasks

# Minimum Claude-reviewer score a tailored CV needs before the dashboard
# allows marking the job 'applied'. Override per-request with force=true.
APPLY_MIN_REVIEWER_SCORE = 80


_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

app = FastAPI(title="Jobsearch Dashboard")


def _open_in_browser_or_app(target: str) -> None:
    """Open a URL or local file path with the OS default app."""
    try:
        if target.startswith("http"):
            webbrowser.open(target, new=2)
            return
        if platform.system() == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
            return
        if platform.system() == "Darwin":
            subprocess.Popen(["open", target])
            return
        subprocess.Popen(["xdg-open", target])
    except Exception:
        pass


# --- routes -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request,
          grade: str = "", location: str = "", status: str = "") -> HTMLResponse:
    queue_rows = data.action_queue(grade_filter=grade or None,
                                   location_filter=location or None)
    tracker_rows = data.tracker_view(status_filter=status or None)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": data.stats(),
            "rows": queue_rows,
            "tracker_rows": tracker_rows,
            "STATUS_ACTIONS": data.STATUS_ACTIONS,
            "current_grade": grade,
            "current_location": location,
            "current_status": status,
        },
    )


@app.get("/action-queue", response_class=HTMLResponse)
def action_queue_partial(request: Request,
                         grade: str = "", location: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        "_action_queue.html",
        {
            "request": request,
            "rows": data.action_queue(grade_filter=grade or None,
                                      location_filter=location or None),
            "STATUS_ACTIONS": data.STATUS_ACTIONS,
        },
    )


@app.get("/tracker", response_class=HTMLResponse)
def tracker_partial(request: Request, status: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        "_tracker.html",
        {
            "request": request,
            "tracker_rows": data.tracker_view(status_filter=status or None),
            "STATUS_ACTIONS": data.STATUS_ACTIONS,
        },
    )


# UI-friendly aliases for status names. The dashboard offers labels users
# expect ("skipped"); the DB stores the canonical status name. Map at the
# route boundary so the rest of the pipeline keeps speaking SQL.
_STATUS_ALIASES = {
    "skipped": "withdrawn",
}


def _ensure_tracker_row(job_id: str) -> dict | None:
    """Return the tracker row for job_id, creating it from jobs_scored.parquet
    if it doesn't exist yet. Returns None if the job isn't in scored either."""
    rec = db.get(job_id)
    if rec:
        return rec
    # Brand-new queue row — never tailored, never tracked. Look up the
    # scored parquet so we can create a meaningful tracker row.
    import pandas as pd
    from ..config import get_settings
    settings = get_settings()
    src = settings.data_dir / "jobs_scored.parquet"
    if not src.exists():
        return None
    df = pd.read_parquet(src)
    match = df[df["id"] == job_id]
    if match.empty:
        return None
    r = match.iloc[0]
    db.upsert_application(
        job_id=job_id,
        title=str(r.get("title", "") or ""),
        company=str(r.get("company", "") or ""),
        url=str(r.get("url", "") or ""),
        grade=str(r.get("grade", "") or ""),
        score=int(r.get("score_total", 0) or 0),
        resume_path="",
        status="discovered",
    )
    return db.get(job_id)


@app.post("/tracker/{job_id}/status", response_class=HTMLResponse)
def update_status(request: Request, job_id: str,
                  new_status: str = Form(...),
                  force: bool = Form(False)) -> HTMLResponse:
    canonical = _STATUS_ALIASES.get(new_status, new_status)
    if canonical not in db.VALID_STATUSES:
        raise HTTPException(400, f"Invalid status {new_status!r}")
    rec = _ensure_tracker_row(job_id)
    if not rec:
        raise HTTPException(404, f"Job {job_id} not in scored data — re-ingest?")
    # Reviewer gate: don't let a weak or unreviewed CV be marked 'applied'.
    # A tailored CV must score >= APPLY_MIN_REVIEWER_SCORE from the Claude
    # reviewer before applying — submitting C-grade resumes is how 284
    # applications produced zero interviews. Pass force=true to override
    # deliberately (e.g. applied with a manually written CV).
    if canonical == "applied" and not force:
        current = db.get(job_id) or {}
        rscore = current.get("reviewer_score")
        if rscore is None:
            raise HTTPException(
                409,
                "Blocked: this CV hasn't been reviewed yet. Run Review first "
                "(or resubmit with force=true to override).",
            )
        if int(rscore) < APPLY_MIN_REVIEWER_SCORE:
            raise HTTPException(
                409,
                f"Blocked: reviewer scored this CV {rscore}/100, below the "
                f"apply threshold of {APPLY_MIN_REVIEWER_SCORE}. Retailor it "
                f"(or resubmit with force=true to override).",
            )
    db.set_status(job_id, canonical, notes="updated via dashboard")
    # Re-render BOTH panels so the row moves between queue/tracker correctly.
    # HTMX swaps both targets via hx-swap-oob in the response.
    return templates.TemplateResponse(
        "_after_status_change.html",
        {
            "request": request,
            "rows": data.action_queue(),
            "tracker_rows": data.tracker_view(),
            "STATUS_ACTIONS": data.STATUS_ACTIONS,
            "stats": data.stats(),
        },
    )


@app.post("/tracker/{job_id}/notes", response_class=HTMLResponse)
def update_notes(request: Request, job_id: str,
                 notes: str = Form(...)) -> HTMLResponse:
    rec = db.get(job_id)
    if not rec:
        raise HTTPException(404, f"Job {job_id} not in tracker")
    db.set_status(job_id, rec["status"], notes=notes)
    return HTMLResponse(f'<span class="muted">Saved</span>')


@app.get("/open/{job_id}", response_class=Response)
def open_url(job_id: str) -> Response:
    rec = db.get(job_id)
    if rec and rec.get("url"):
        _open_in_browser_or_app(rec["url"])
    return Response(status_code=204)


@app.get("/open-resume/{job_id}", response_class=Response)
def open_resume(job_id: str) -> Response:
    rec = db.get(job_id)
    if rec and rec.get("resume_path"):
        _open_in_browser_or_app(rec["resume_path"])
    return Response(status_code=204)


@app.get("/open-cover-letter/{job_id}", response_class=Response)
def open_cover_letter(job_id: str) -> Response:
    """Open the generated cover letter .docx if one exists on disk."""
    from ..config import get_settings
    rec = db.get(job_id)
    company = (rec or {}).get("company", "") if rec else ""
    if not company:
        # Fall back to scored parquet
        import pandas as pd
        scored_p = get_settings().data_dir / "jobs_scored.parquet"
        if scored_p.exists():
            df = pd.read_parquet(scored_p)
            match = df[df["id"] == job_id]
            if not match.empty:
                company = str(match.iloc[0].get("company", ""))
    if not company:
        return Response(status_code=404)
    safe = "".join(c if c.isalnum() else "_" for c in company)[:40]
    path = get_settings().output_dir / "CV" / f"{job_id}_{safe}_CoverLetter.docx"
    if path.exists():
        _open_in_browser_or_app(str(path))
    return Response(status_code=204)


# --- Tailor / Review (background tasks) -----------------------------------

def _tailor_job(job_id: str, force: bool) -> str:
    """Worker function — runs in a thread."""
    from ..tailor import runner as tailor_runner
    out = tailor_runner.run_for_id(job_id, force=force)
    return str(out) if out else ""


def _review_job(job_id: str) -> dict:
    """Worker function — runs in a thread."""
    from ..tailor import review_runner
    results = review_runner.review_ids([job_id])
    if not results:
        raise RuntimeError("Reviewer returned no results — was the job tailored?")
    return results[0]


@app.post("/tailor/{job_id}", response_class=HTMLResponse)
def tailor_start(request: Request, job_id: str, force: bool = False) -> HTMLResponse:
    """Start a tailor job in the background. Returns a placeholder banner
    that polls /tasks/{id} every 1.5s until the task completes."""
    existing = tasks.active_for(job_id, kind="tailor")
    if existing:
        return _pending_response(request, existing.id, "tailor", job_id)
    task_id = tasks.start("tailor", job_id, _tailor_job, job_id, force)
    return _pending_response(request, task_id, "tailor", job_id)


@app.post("/review/{job_id}", response_class=HTMLResponse)
def review_start(request: Request, job_id: str) -> HTMLResponse:
    existing = tasks.active_for(job_id, kind="review")
    if existing:
        return _pending_response(request, existing.id, "review", job_id)
    task_id = tasks.start("review", job_id, _review_job, job_id)
    return _pending_response(request, task_id, "review", job_id)


def _retailor_job(job_id: str) -> dict:
    """Re-tailor a resume using the reviewer's stored instructions, then
    re-review the result. Runs in a background thread.

    Pulls retailor_instructions off the tracker row and feeds them to the
    tailor LLM as extra_context. force=True so the existing resume on disk
    is overwritten in place.
    """
    from ..tailor import runner as tailor_runner
    from ..tailor import review_runner

    rec = db.get(job_id)
    if not rec:
        raise RuntimeError(f"Job {job_id} not in tracker — tailor + review it first.")
    instructions = (rec.get("retailor_instructions") or "").strip()
    if not instructions:
        raise RuntimeError(
            "No retailor instructions on file. Run review first, or the "
            "reviewer concluded no changes are needed."
        )
    out = tailor_runner.run_for_id(job_id, force=True, extra_context=instructions)
    if not out:
        raise RuntimeError("Retailor produced no output.")
    results = review_runner.review_ids([job_id])
    return {"resume": str(out), "review": results[0] if results else None}


@app.post("/retailor/{job_id}", response_class=HTMLResponse)
def retailor_start(request: Request, job_id: str) -> HTMLResponse:
    """Re-tailor a resume using the reviewer's stored revision guidance."""
    existing = tasks.active_for(job_id, kind="retailor")
    if existing:
        return _pending_response(request, existing.id, "retailor", job_id)
    task_id = tasks.start("retailor", job_id, _retailor_job, job_id)
    return _pending_response(request, task_id, "retailor", job_id)


def _cover_letter_job(job_id: str, force: bool) -> str:
    """Worker function — runs in a thread."""
    from .. import cover_letter as cl_mod
    out = cl_mod.generate_for_id(job_id, force=force)
    return str(out) if out else ""


@app.post("/cover-letter/{job_id}", response_class=HTMLResponse)
def cover_letter_start(request: Request, job_id: str,
                       force: bool = False) -> HTMLResponse:
    """Generate a personalised cover letter using the tailored resume + JD.
    Saves to output/CV/{job_id}_{Company}_CoverLetter.docx."""
    existing = tasks.active_for(job_id, kind="cover-letter")
    if existing:
        return _pending_response(request, existing.id, "cover-letter", job_id)
    task_id = tasks.start("cover-letter", job_id, _cover_letter_job, job_id, force)
    return _pending_response(request, task_id, "cover-letter", job_id)


# --- Bulk actions ---------------------------------------------------------

def _parse_job_ids(raw: str) -> list[str]:
    """Form posts the checkbox values as a comma-separated string. Split,
    strip, dedupe (preserve order)."""
    seen: set[str] = set()
    out: list[str] = []
    for piece in (raw or "").split(","):
        jid = piece.strip()
        if jid and jid not in seen:
            seen.add(jid)
            out.append(jid)
    return out


def _label_for(job_id: str) -> str:
    rec = db.get(job_id)
    if rec and rec.get("company"):
        return rec["company"]
    return job_id


@app.post("/bulk/tailor", response_class=HTMLResponse)
def bulk_tailor(request: Request,
                job_ids: str = Form(...),
                force: bool = Form(False)) -> HTMLResponse:
    ids = _parse_job_ids(job_ids)
    if not ids:
        raise HTTPException(400, "No jobs selected")
    task_id = tasks.start_bulk(
        "bulk-tailor", ids,
        lambda jid: _tailor_job(jid, force),
        label_fn=_label_for,
    )
    return _pending_response(request, task_id, "bulk-tailor", f"{len(ids)} jobs")


@app.post("/bulk/review", response_class=HTMLResponse)
def bulk_review(request: Request, job_ids: str = Form(...)) -> HTMLResponse:
    ids = _parse_job_ids(job_ids)
    if not ids:
        raise HTTPException(400, "No jobs selected")
    task_id = tasks.start_bulk(
        "bulk-review", ids,
        _review_job,
        label_fn=_label_for,
    )
    return _pending_response(request, task_id, "bulk-review", f"{len(ids)} jobs")


@app.post("/bulk/skip", response_class=HTMLResponse)
def bulk_skip(request: Request, job_ids: str = Form(...)) -> HTMLResponse:
    """Skip is fast (just status updates) — do it synchronously and return
    refreshed panels straight away, no polling banner needed."""
    ids = _parse_job_ids(job_ids)
    if not ids:
        raise HTTPException(400, "No jobs selected")
    for jid in ids:
        if not _ensure_tracker_row(jid):
            continue
        db.set_status(jid, "withdrawn", notes="bulk-skipped via dashboard")
    # Return _task_done shape so the submitBulk() target (#task-status) gets
    # cleared and #queue + #tracker re-render via OOB swaps.
    return templates.TemplateResponse(
        "_task_done.html",
        {
            "request": request,
            "rows": data.action_queue(),
            "tracker_rows": data.tracker_view(),
            "STATUS_ACTIONS": data.STATUS_ACTIONS,
        },
    )


# --- Add by URL -----------------------------------------------------------

def _add_url_job(url: str, manual_overrides: dict | None) -> dict:
    """Worker function — runs in a thread."""
    from ..pipeline import single_url
    result = single_url.add(
        url,
        tailor=True,
        review=True,
        manual_overrides=manual_overrides,
    )
    # Return a small JSON-ish dict; the dashboard only needs the job_id to
    # know which row to highlight.
    return {"job_id": result.job_id, "notes": result.notes}


@app.post("/add-url", response_class=HTMLResponse)
def add_url_start(request: Request, url: str = Form(...)) -> HTMLResponse:
    """Auto-extract + score + tailor + review for a single URL.
    Falls back to a manual entry form if extraction fails."""
    from ..ingest import url as url_extract
    url = url.strip()
    if not url:
        raise HTTPException(400, "URL is required")
    # Pre-flight extract so failures hit the user immediately (no spinner
    # for 60s only to fail). The driver will re-extract — that's fine, it's
    # a single HTTP call.
    try:
        url_extract.extract(url)
    except url_extract.URLExtractionError as e:
        return templates.TemplateResponse(
            "_add_url_manual.html",
            {"request": request, "url": url, "error": str(e)},
        )
    task_id = tasks.start("add-url", url, _add_url_job, url, None)
    return _pending_response(request, task_id, "add-url", url)


@app.post("/add-url/manual", response_class=HTMLResponse)
def add_url_manual(request: Request,
                   url: str = Form(...),
                   title: str = Form(...),
                   company: str = Form(...),
                   location: str = Form(""),
                   description: str = Form(...)) -> HTMLResponse:
    """Manual entry path when auto-extract failed."""
    if not (title.strip() and company.strip() and description.strip()):
        raise HTTPException(400, "title, company, and description are required")
    overrides = {
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip(),
        "description": description.strip(),
    }
    task_id = tasks.start("add-url", url, _add_url_job, url, overrides)
    return _pending_response(request, task_id, "add-url", url)


# --- Ask (answer generator) -----------------------------------------------

def _answer_job(job_id: str, question: str, tone: str,
                max_words: int | None) -> str:
    """Worker function — runs in a thread."""
    from ..answer import answer as answer_mod
    return answer_mod.answer(job_id, question, tone=tone,
                             max_words=max_words, append=True)


@app.get("/ask/{job_id}", response_class=HTMLResponse)
def ask_modal(request: Request, job_id: str) -> HTMLResponse:
    """Open the Ask modal pre-filled with the job's company + title."""
    rec = db.get(job_id)
    company, title = "", ""
    if rec:
        company, title = rec.get("company", ""), rec.get("title", "")
    else:
        # Job in the queue but not tracked yet — pull from scored parquet
        import pandas as pd
        from ..config import get_settings
        scored_p = get_settings().data_dir / "jobs_scored.parquet"
        if scored_p.exists():
            df = pd.read_parquet(scored_p)
            match = df[df["id"] == job_id]
            if not match.empty:
                r = match.iloc[0]
                company, title = str(r.get("company", "")), str(r.get("title", ""))
    return templates.TemplateResponse(
        "_ask_modal.html",
        {
            "request": request,
            "job_id": job_id,
            "company": company,
            "title": title,
        },
    )


@app.post("/ask/{job_id}", response_class=HTMLResponse)
def ask_start(request: Request, job_id: str,
              question: str = Form(...),
              tone: str = Form("professional"),
              max_words: str = Form("")) -> HTMLResponse:
    """Kick off an answer generation in the background. Returns a polling
    placeholder; once done, the modal shows the rendered answer text."""
    if not question.strip():
        raise HTTPException(400, "Question is required")
    rec = db.get(job_id)
    # answer.answer needs the job in the tracker so it can find resume_path.
    # If it isn't there yet, create a stub so the answer module finds it.
    if not rec:
        _ensure_tracker_row(job_id)
    mw: int | None = None
    if max_words.strip():
        try:
            mw = int(max_words)
            if mw <= 0:
                mw = None
        except ValueError:
            mw = None
    task_id = tasks.start(
        "answer", job_id, _answer_job, job_id, question, tone, mw,
    )
    return templates.TemplateResponse(
        "_ask_pending.html",
        {
            "request": request,
            "task_id": task_id,
            "job_id": job_id,
            "question": question,
        },
    )


@app.get("/ask-result/{task_id}", response_class=HTMLResponse)
def ask_poll(request: Request, task_id: str) -> HTMLResponse:
    """Poll an answer task. While running: same pending placeholder.
    On done: renders the answer text with a copy button. On error: shows
    the error message inline so the user can adjust the question + retry."""
    t = tasks.get(task_id)
    if not t:
        return HTMLResponse('<div class="muted">Task expired. Close and try again.</div>')
    if t.status == "running":
        return templates.TemplateResponse(
            "_ask_pending.html",
            {
                "request": request,
                "task_id": t.id,
                "job_id": t.job_id,
                "question": "",  # already shown by the original render
            },
        )
    if t.status == "error":
        return templates.TemplateResponse(
            "_ask_error.html",
            {"request": request, "error": t.error},
        )
    return templates.TemplateResponse(
        "_ask_result.html",
        {"request": request, "answer": t.result or ""},
    )


def _pending_response(request: Request, task_id: str, kind: str,
                      job_id: str) -> HTMLResponse:
    """Render the placeholder row that polls until the task finishes."""
    t = tasks.get(task_id)
    return templates.TemplateResponse(
        "_task_pending.html",
        {
            "request": request,
            "task_id": task_id,
            "kind": kind,
            "job_id": job_id,
            "progress": (t.progress if t else None),
            "total": (t.total if t else None),
            "progress_label": (t.progress_label if t else ""),
            "error_count": (len(t.errors) if t else 0),
        },
    )


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_poll(request: Request, task_id: str) -> HTMLResponse:
    """Poll a task. The polling banner self-targets (hx-target=this), so:
      running → return _task_pending (banner re-renders in place)
      done    → return _task_done (banner cleared, queue+tracker OOB-refresh)
      error   → return _task_error (red banner with retry, in place)
      missing → treat as done (panels refresh, banner clears).
    """
    t = tasks.get(task_id)
    if not t or t.status == "done":
        return templates.TemplateResponse(
            "_task_done.html",
            {
                "request": request,
                "rows": data.action_queue(),
                "tracker_rows": data.tracker_view(),
                "STATUS_ACTIONS": data.STATUS_ACTIONS,
            },
        )
    if t.status == "running":
        return templates.TemplateResponse(
            "_task_pending.html",
            {
                "request": request,
                "task_id": t.id,
                "kind": t.kind,
                "job_id": t.job_id,
                "progress": t.progress,
                "total": t.total,
                "progress_label": t.progress_label,
                "error_count": len(t.errors),
            },
        )
    # status == "error"
    return templates.TemplateResponse(
        "_task_error.html",
        {
            "request": request,
            "task_id": t.id,
            "kind": t.kind,
            "job_id": t.job_id,
            "error": t.error,
        },
    )

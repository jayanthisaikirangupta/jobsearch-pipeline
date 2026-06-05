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
from . import data


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


@app.post("/tracker/{job_id}/status", response_class=HTMLResponse)
def update_status(request: Request, job_id: str,
                  new_status: str = Form(...)) -> HTMLResponse:
    if new_status not in db.VALID_STATUSES:
        raise HTTPException(400, f"Invalid status {new_status!r}")
    rec = db.get(job_id)
    if not rec:
        raise HTTPException(404, f"Job {job_id} not in tracker")
    db.set_status(job_id, new_status, notes="updated via dashboard")
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

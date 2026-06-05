"""Apply helpers — manual-first, browser-use opt-in.

Two modes:

* ``manual`` (default) — opens the apply URL in your real default browser
  (already logged in to LinkedIn / Workday / Google / etc), prints a checklist
  with the tailored resume path + key candidate fields, then prompts you for
  the outcome. Your answer drives the tracker status — never an agent return.

* ``browser-use`` — runs the LLM-driven browser agent. We do NOT auto-mark
  applied. After the agent finishes (success OR auth wall OR captcha), you
  confirm the actual outcome and the tracker is updated to match. This fixes
  the previous bug where every agent return marked the job ``applied``.
"""
from __future__ import annotations

import platform
import subprocess
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ..config import get_profile, get_settings
from ..tracker import db

console = Console()


# ---------------------------------------------------------------------------
# Shared helpers


def _candidate_fields() -> dict[str, str]:
    p = get_profile().candidate
    return {
        "Full name": p.full_name,
        "Email": p.email,
        "Phone": p.phone,
        "Location": p.location,
        "LinkedIn": getattr(p, "linkedin_url", "") or p.linkedin,
        "GitHub": getattr(p, "github_url", "") or p.github,
        "Visa status": p.visa_status,
        "Notice period": f"{p.notice_period_weeks} weeks",
    }


def _candidate_block() -> str:
    return "\n".join(f"  {k}: {v}" for k, v in _candidate_fields().items() if v)


def _open_in_default_browser(url: str) -> None:
    """Open ``url`` in the user's default browser, where they're already
    signed in. Falls back to webbrowser module if platform-specific call fails."""
    try:
        if platform.system() == "Windows":
            # `start` keeps the parent shell free and respects user defaults
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
            return
        if platform.system() == "Darwin":
            subprocess.Popen(["open", url])
            return
        subprocess.Popen(["xdg-open", url])
    except Exception:
        webbrowser.open(url, new=2)


def _open_resume(path: Path) -> None:
    if not path.exists():
        return
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
            return
        if platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def _prompt_outcome(default: str = "applied") -> tuple[str, str]:
    """Prompt the user for the real outcome of the application attempt.

    Returns: (status, notes).
    """
    console.print()
    console.print("[bold]How did it go?[/]")
    console.print("  [green]a[/] = applied (submitted successfully)")
    console.print("  [yellow]s[/] = skipped (not a fit / pulled the post / etc)")
    console.print("  [red]b[/] = blocked (login wall / captcha / form broken)")
    console.print("  [dim]l[/] = leave as-is (no status change)")
    choice = Prompt.ask(
        "Choice",
        choices=["a", "s", "b", "l"],
        default="a" if default == "applied" else "l",
    )
    if choice == "l":
        return "", ""
    if choice == "a":
        notes = Prompt.ask("Optional notes (recruiter name, ref number, etc.)", default="")
        return "applied", notes or "manually submitted"
    if choice == "s":
        notes = Prompt.ask("Reason", default="not a fit")
        return "withdrawn", notes
    if choice == "b":
        notes = Prompt.ask("What blocked you", default="login wall / captcha")
        return "discovered", f"BLOCKED: {notes}"  # back to discovered for retry
    return "", ""


# ---------------------------------------------------------------------------
# Manual mode (default)


def manual(job_id: str) -> None:
    record = db.get(job_id)
    if not record:
        raise KeyError(f"No tracked job with id {job_id}")
    if not record.get("url"):
        raise ValueError(f"Job {job_id} has no apply URL")

    resume_path = Path(record.get("resume_path") or "")

    body_lines = [
        f"[bold cyan]{record['company']}[/]  ·  {record['title']}",
        f"[dim]{record['url']}[/]",
        "",
        "[bold]Candidate details (copy/paste):[/]",
        _candidate_block(),
        "",
        f"[bold]Tailored resume:[/] {resume_path if resume_path.exists() else '(none on file)'}",
    ]
    review_md = resume_path.with_suffix(".review.md") if resume_path.exists() else None
    if review_md and review_md.exists():
        body_lines.append(f"[bold]Reviewer notes:[/] {review_md}")
    body_lines.extend([
        "",
        "[bold]Checklist before you click submit:[/]",
        "  1. Confirm the role title and seniority match what was scored.",
        "  2. Sponsorship question — answer YES (Skilled Worker visa needed before 2026-08-31).",
        "  3. Cover letter / 'why this role' field — write 3-4 sentences citing specifics.",
        "  4. Upload the tailored resume listed above.",
        "  5. Re-read the answers — don't auto-submit.",
    ])

    console.print(Panel("\n".join(body_lines), title=f"Apply manually — {job_id}", expand=False))

    _open_in_default_browser(record["url"])
    if resume_path.exists():
        _open_resume(resume_path)
        if review_md and review_md.exists():
            console.print(f"[dim]Tip: cat {review_md} for the reviewer's revision priorities[/]")

    status, notes = _prompt_outcome()
    if not status:
        console.print("[dim]No status change.[/]")
        return
    db.set_status(job_id, status, notes=notes)
    console.print(f"[green]{job_id} -> {status}[/]")


# ---------------------------------------------------------------------------
# Browser-use mode (opt-in, also no auto-applied)


PREFILL_TASK = """\
You are filling a job application form on behalf of the candidate.

Candidate details (DO NOT EDIT):
{candidate_block}

Resume to attach if asked: {resume_path}

Steps:
1. Navigate to the apply URL the user provides.
2. If a 'Sign in' / 'Continue with Google' wall appears, STOP and tell the user
   you cannot proceed. DO NOT attempt to log in.
3. Fill any visible fields using the candidate details above.
4. If a CV upload is requested, attach the resume file path above.
5. STOP at the final review/preview step. DO NOT click 'Submit Application'.
6. Tell the user: 'Pre-fill complete; review and submit manually.'

If anything blocks you (captcha, MFA, missing field, error message), STOP and
report what you saw. Do NOT pretend to have completed the application.
"""


async def prefill_with_browser_use(job_id: str) -> None:
    """Browser-use driven pre-fill. Falls back to manual confirmation
    afterward — never auto-marks applied."""
    record = db.get(job_id)
    if not record:
        raise KeyError(f"No tracked job with id {job_id}")
    if not record.get("url"):
        raise ValueError(f"Job {job_id} has no apply URL")

    settings = get_settings()

    # Lazy imports - browser-use is an optional dependency
    from browser_use import Agent
    from browser_use.llm import ChatAnthropicBedrock

    task = PREFILL_TASK.format(
        candidate_block=_candidate_block(),
        resume_path=record.get("resume_path", "<no tailored resume on file>"),
    )
    task += f"\n\nApply URL: {record['url']}"

    llm = ChatAnthropicBedrock(model=settings.tailor_model, aws_region=settings.aws_region)
    agent = Agent(task=task, llm=llm)
    console.print(f"[cyan]Launching browser-use for {record['company']} - {record['title']}[/]")

    try:
        await agent.run()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]browser-use raised: {e}[/]")
        console.print("[yellow]Confirm what actually happened so the tracker stays accurate.[/]")

    # CRITICAL: agent.run() returning does not mean submission succeeded.
    # Always ask the human for the real outcome. (Was the previous bug.)
    status, notes = _prompt_outcome(default="")
    if not status:
        console.print("[dim]No status change.[/]")
        return
    db.set_status(job_id, status, notes=f"browser-use: {notes}".strip(": "))
    console.print(f"[green]{job_id} -> {status}[/]")


# Back-compat: cli still imports `prefill`. Keep the same name as the manual flow.
def prefill(job_id: str) -> None:
    manual(job_id)

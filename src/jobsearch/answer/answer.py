"""Generate one tailored application answer per call.

Per call: load the job's JD from the scored parquet + the tailored resume text
from the tracker. Cache them as the prefix; ask Claude (Bedrock) the user's
question with optional tone/length controls. Print the answer and append a
timestamped Q+A entry to ``output/answers/<job_id>_<company>.answers.md``.

Why per-call instead of a fixed bundle: every application form asks slightly
different questions ("Why us in 200 chars", "Tell us about a hard problem",
"Salary expectations", "Notice period", "What sponsorship do you need"). A
bundle ages quickly. Per-call costs a single Bedrock turn and the prompt
prefix caches across the same job.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import docx2txt
import pandas as pd
from anthropic import AnthropicBedrock
from rich.console import Console
from rich.panel import Panel

from ..config import get_profile, get_settings
from ..tracker import db

console = Console()


SYSTEM_PROMPT = """You are writing as the candidate themselves — first-person, in plain human voice. You are NOT a recruiter, an assistant, or an AI helping the candidate. You ARE the candidate. The reader must believe a real person typed this in 2 minutes between meetings, not that an LLM polished it.

Sound human. Avoid these AI tells:
- No em-dashes (—). Use commas, full stops, or "and"/"but". This is the single biggest giveaway.
- No "rhetorical mirror" moves like "X is exactly how I think about Y", "Y is exactly the kind of work I want to do", "that's the work I want to be part of", "this is precisely the role I've been looking for".
- No corporate filler: "passionate", "excited about", "thrilled to", "leverage", "robust", "innovative", "cutting-edge", "synergy", "drive value", "deliver impact", "pragmatic", "first-principles", "world-class", "best-in-class", "stakeholder", "alignment", "ecosystem".
- No "I'd love to..." / "I'm keen to..." / "I would be delighted to..." soft-opens. Just say what you'd do or what attracts you.
- No quoting the JD's marketing copy back at them ("your mission of getting the right drug to the right patient", "your evaluation-before-hype philosophy"). They wrote it; reading it back sounds like a chatbot.
- No tricolons (rhythmic three-item lists for effect, e.g. "evaluation, observability, audit-readiness"). Two items or four-plus is fine.
- No sentence starting with "And honestly," / "Look," / "To be clear,".
- No headings, bullet points, or markdown unless the question explicitly asks for them.

Sound LIKE the candidate:
- Short sentences are good. Mix short with longer ones; don't write paragraphs of 20-word explanatory sentences.
- Contractions are fine ("I've", "don't", "it's"). They make text read human.
- Reference SPECIFIC things you did from your resume, with concrete nouns: "the OCR pipeline at K+N", "the n8n agentic workflow", "the BSON DECIMAL128 fix" — not "production-grade GenAI work" or "regulated-domain expertise".
- Plain words: "shipped" not "delivered", "built" not "architected", "fixed" not "remediated", "I want to" not "I aspire to", "good fit" not "strong alignment".
- It's OK — even good — to be slightly informal where the form allows. Real applications don't read like press releases.

Hard rules (do not violate):
- Ground every claim in the candidate's resume. Do NOT invent experience, metrics, or skills the resume doesn't support. If you don't see it on the resume, don't write it.
- The candidate is a UK Graduate-visa holder needing Skilled Worker sponsorship before 2026-08-31. If the question touches sponsorship, visa, or right-to-work, be direct: they hold a UK Graduate visa valid until 2026-08-31 and need Skilled Worker sponsorship via in-country switch.
- Match the requested length budget exactly. If a 150-word cap is requested, stop at 150 words even mid-thought rather than spilling over.
- First-person ("I", "my"). Active verbs. No third-person ("the candidate has...").
- Plain ASCII. No emoji.
- Return ONLY the answer text. No preamble, no caveats, no "Here is the answer:" wrapper.

Pre-flight check before you reply: if your draft contains any em-dash, "exactly how I think about", "I'd love to", "passionate", or quotes the JD back at the reader, rewrite it. The reader has read 200 LLM-generated cover messages this month; yours has to read like the candidate wrote it on their phone.
"""


def _resume_text(resume_path: str | None) -> str:
    if not resume_path:
        return ""
    p = Path(resume_path)
    if not p.exists():
        return ""
    try:
        return docx2txt.process(str(p)) or ""
    except Exception:
        return ""


def _candidate_brief() -> str:
    p = get_profile().candidate
    parts = [f"Name: {p.full_name}"]
    if p.location:
        parts.append(f"Location: {p.location}")
    if p.visa_status:
        parts.append(f"Visa: {p.visa_status}")
    if p.notice_period_weeks:
        parts.append(f"Notice period: {p.notice_period_weeks} weeks")
    return "\n".join(parts)


def _load_job(job_id: str) -> tuple[dict, str]:
    """Return (tracker_record, jd_text). Raises if either is missing."""
    record = db.get(job_id)
    if not record:
        raise KeyError(f"No tracked job with id {job_id}")

    settings = get_settings()
    scored_path = settings.data_dir / "jobs_scored.parquet"
    if not scored_path.exists():
        raise FileNotFoundError(f"jobs_scored.parquet missing — run `score run` first")

    scored = pd.read_parquet(scored_path)
    match = scored[scored["id"] == job_id]
    if match.empty:
        raise KeyError(f"Job {job_id} not in scored parquet — was it filtered out?")
    jd_text = str(match.iloc[0].get("description", "") or "")
    return record, jd_text


def answer(job_id: str, question: str, *, tone: str = "professional",
           max_words: int | None = None, append: bool = True) -> str:
    """Generate one answer. Returns the answer text and (by default) appends
    a timestamped entry to the job's .answers.md sidecar."""
    settings = get_settings()
    record, jd_text = _load_job(job_id)

    resume_text = _resume_text(record.get("resume_path"))
    company = record.get("company", "")
    role = record.get("title", "")

    constraints = [f"Tone: {tone}"]
    if max_words:
        constraints.append(f"Length budget: <= {max_words} words. End at the cap, do not exceed.")

    client = AnthropicBedrock(aws_region=settings.aws_region)
    response = client.messages.create(
        model=settings.tailor_model,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"<candidate>\n{_candidate_brief()}\n</candidate>\n\n"
                            f"<role>\nCompany: {company}\nTitle: {role}\n</role>\n\n"
                            f"<job_description>\n{jd_text}\n</job_description>\n\n"
                            f"<tailored_resume>\n{resume_text}\n</tailored_resume>"
                        ),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"<question>\n{question}\n</question>\n\n"
                            f"<constraints>\n" + "\n".join(constraints) + "\n</constraints>\n\n"
                            "Write the answer now. No preamble."
                        ),
                    },
                ],
            }
        ],
    )

    text = "".join(b.text for b in response.content if b.type == "text").strip()

    if append:
        _append_to_sidecar(job_id, company, question, text, tone=tone, max_words=max_words)
    return text


def _append_to_sidecar(job_id: str, company: str, question: str, answer_text: str,
                       *, tone: str, max_words: int | None) -> Path:
    settings = get_settings()
    safe = "".join(c if c.isalnum() else "_" for c in (company or "co"))[:40] or "co"
    out = settings.output_dir / "answers" / f"{job_id}_{safe}.answers.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    new_file = not out.exists()
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    constraints = f"tone={tone}"
    if max_words:
        constraints += f", max_words={max_words}"

    with out.open("a", encoding="utf-8") as f:
        if new_file:
            f.write(f"# Application answers — {company} ({job_id})\n\n")
        f.write(f"## {ts} — {question}\n\n_{constraints}_\n\n{answer_text}\n\n---\n\n")
    return out


def show(job_id: str, question: str, *, tone: str = "professional",
         max_words: int | None = None, append: bool = True) -> None:
    """CLI-friendly wrapper that prints the answer in a Rich panel."""
    text = answer(job_id, question, tone=tone, max_words=max_words, append=append)
    console.print(
        Panel(
            text,
            title=f"{question[:80]}",
            subtitle=f"job {job_id}",
            expand=False,
        )
    )
    if append:
        settings = get_settings()
        record = db.get(job_id) or {}
        safe = "".join(c if c.isalnum() else "_" for c in (record.get("company") or "co"))[:40] or "co"
        out = settings.output_dir / "answers" / f"{job_id}_{safe}.answers.md"
        console.print(f"[dim]Appended to {out}[/]")

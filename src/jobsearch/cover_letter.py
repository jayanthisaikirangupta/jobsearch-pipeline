"""Generate a personalised cover letter from a tailored resume + JD.

Reads:
  - the tailored .docx (full text) from output/resumes/
  - the JD + role + company from jobs_scored.parquet

Sends both to Claude on Bedrock, parses 4-5 body paragraphs out of the
JSON response, then renders to .docx in output/CV/ matching the
typography of the existing Elliptic cover letter:

  - Cambria, body 10pt, line-spacing 1.15
  - 0.5"/0.4" margins
  - Centered name (Cambria 14, NAVY), tagline (9.5, BLUE), contact (9.5, GRAY)
  - Date + salutation + justified body paragraphs
  - "Kind regards," + name in NAVY
  - Italic gray P.S. acknowledging AI assistance

Output: output/CV/{job_id}_{Company}_CoverLetter.docx
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import docx2txt
import pandas as pd
from anthropic import AnthropicBedrock
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from .config import get_profile, get_settings
from .tailor.writer import (
    BLUE,
    GRAY,
    NAVY,
    _add_hyperlink,
    _run,
    _spacing,
    _strip_ai_tells,
)
from .tracker import db


FONT = "Cambria"
NAME_PT = 14
TAGLINE_PT = 9.5
CONTACT_PT = 9.5
BODY_PT = 10


SYSTEM_PROMPT = """You are writing a cover letter for Sai Kiran Gupta Jayanthi, a UK-based AI/full-stack engineer applying for a specific role.

Voice rules — these are non-negotiable:
- First person, conversational, plain English. Read it aloud — it should sound like Sai talking, not a marketing brochure.
- NEVER use em-dashes (—) or en-dashes (–). Use commas, colons, "and", or two short sentences. This is the single biggest AI tell.
- No "leveraged", "synergies", "passionate about", "excited to", "thrilled to", "in today's fast-paced world", "I am writing to express", or any cover-letter cliche. If a sentence could appear in any cover letter, rewrite it.
- Concrete numbers and specific outcomes beat adjectives. "132 redundant network requests reduced to 9" beats "improved performance significantly".
- Don't oversell. If there's a gap, name it briefly and say how he'd close it. Honesty reads stronger than bluster.
- No headers, no markdown, no bullet points. Plain paragraphs.

Structure — exactly 4 paragraphs (NOT more, NOT fewer):
  Para 1: What he does day-to-day at Kuehne+Nagel (current role). Pick the 2-3 things from his experience MOST relevant to this JD's stack/domain. Include one specific quantified outcome.
  Para 2: One additional point of overlap with the JD: a side project, an additional skill from a previous role, or a specific tool the JD names. Keep it concrete.
  Para 3: Why THIS company / domain. Anchor in something genuine — regulated-data parallels, problem-domain interest, the product itself. Avoid generic praise of the company.
  Para 4: One honest acknowledgement of where he'd be growing into the role + a brief sign-off line. (E.g. "I haven't used X in production but I have Y, and I'd pick it up the same way I picked up the rest of my stack.")

Then a single closing line: "Thank you for considering my application. I would welcome the chance to talk."

Hard rules:
- Use ONLY facts present in the source resume or the experience inventory below. Do NOT invent metrics, employers, dates, or skills.
- The visa line is NOT in the cover letter. It belongs on the application form, not here.
- 320-420 words total across the 4 paragraphs + closing line. Tight is better than long.

Return STRICT JSON only:
{
  "tagline": "<JD-matched 1-line role identity, mirrors the resume's headline e.g. 'Full Stack Engineer | React, .NET Core & Azure'>",
  "salutation": "Dear <X>,",   // "Dear Hiring Team," is fine if no name available
  "paragraphs": ["<para 1>", "<para 2>", "<para 3>", "<para 4>"],
  "closing": "Thank you for considering my application. I would welcome the chance to talk."
}
"""


_POSTSCRIPT = (
    "P.S. I used AI to help format and polish this letter. The work, "
    "opinions, and story are mine; I would rather say so plainly than "
    "pretend otherwise."
)


def _extract_resume_text(resume_path: Path) -> str:
    if not resume_path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_path}")
    return docx2txt.process(str(resume_path)) or ""


def _lookup_jd(job_id: str) -> tuple[str, str, str]:
    """Returns (title, company, jd_text). Tries jobs_scored.parquet first;
    falls back to tracker metadata + a fresh URL re-extract if the row has
    aged out of the parquet (common when a job was added via /add-url and
    a later batch ingest replaced the parquet)."""
    settings = get_settings()
    src = settings.data_dir / "jobs_scored.parquet"
    if src.exists():
        df = pd.read_parquet(src)
        match = df[df["id"] == job_id]
        if not match.empty:
            r = match.iloc[0]
            return (
                str(r.get("title", "") or ""),
                str(r.get("company", "") or ""),
                str(r.get("description", "") or ""),
            )

    rec = db.get(job_id) or {}
    title = str(rec.get("title", "") or "")
    company = str(rec.get("company", "") or "")
    url = str(rec.get("url", "") or "")
    if not url:
        raise KeyError(
            f"job_id {job_id} not in scored parquet and no URL in tracker; "
            f"can't recover JD text."
        )
    try:
        from .ingest import url as url_extract
        row = url_extract.extract(url)
        return (
            title or str(row.get("title", "") or ""),
            company or str(row.get("company", "") or ""),
            str(row.get("description", "") or ""),
        )
    except Exception as e:
        raise RuntimeError(
            f"JD recovery failed for {job_id}: {e}. "
            f"Re-run ingest or paste the JD via /add-url manual entry."
        ) from e


def _generate_letter(resume_text: str, title: str, company: str, jd: str) -> dict[str, Any]:
    settings = get_settings()
    client = AnthropicBedrock(aws_region=settings.aws_region)

    user_content = [
        {
            "type": "text",
            "text": f"<source_resume>\n{resume_text}\n</source_resume>",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                f"Write a cover letter for this role. Mirror the JD's vocabulary "
                f"where it truthfully applies. Lean on quantified outcomes from "
                f"the resume.\n\n"
                f"<role>\nCompany: {company}\nTitle: {title}\n</role>\n\n"
                f"<job_description>\n{jd}\n</job_description>\n\n"
                f"Return JSON only."
            ),
        },
    ]

    response = client.messages.create(
        model=settings.tailor_model,
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _safe_filename(s: str, fallback: str = "co") -> str:
    safe = "".join(c if c.isalnum() else "_" for c in (s or fallback))[:40]
    return safe or fallback


def _contact_line(p, candidate) -> None:
    first = True

    def sep() -> None:
        nonlocal first
        if not first:
            _run(p, "  |  ", font=FONT, size=CONTACT_PT, color=GRAY)
        first = False

    if candidate.location:
        sep(); _run(p, candidate.location, font=FONT, size=CONTACT_PT, color=GRAY)
    if candidate.phone:
        sep(); _run(p, candidate.phone, font=FONT, size=CONTACT_PT, color=GRAY)
    if candidate.email:
        sep(); _add_hyperlink(p, f"mailto:{candidate.email}", candidate.email,
                              font=FONT, size=CONTACT_PT)
    if getattr(candidate, "linkedin_url", ""):
        sep(); _add_hyperlink(p, candidate.linkedin_url,
                              candidate.linkedin or "LinkedIn",
                              font=FONT, size=CONTACT_PT)
    if getattr(candidate, "github_url", ""):
        sep(); _add_hyperlink(p, candidate.github_url,
                              candidate.github or "GitHub",
                              font=FONT, size=CONTACT_PT)


def _render_letter(letter: dict[str, Any], candidate, out_path: Path) -> Path:
    doc = Document()
    section = doc.sections[0]
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5)
    section.top_margin = Inches(0.4)
    section.bottom_margin = Inches(0.4)

    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(BODY_PT)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.15

    # Header — name
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=1, line=1.0)
    _run(p, candidate.full_name, font=FONT, bold=True, size=NAME_PT, color=NAVY)

    # Tagline
    tagline = letter.get("tagline") or getattr(candidate, "tagline", "")
    if tagline:
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, before=0, after=1, line=1.0)
        _run(p, tagline, font=FONT, bold=True, size=TAGLINE_PT, color=BLUE)

    # Contact
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=10, line=1.0)
    _contact_line(p, candidate)

    # Date
    today = datetime.now().strftime("%d %B %Y")
    p = doc.add_paragraph()
    _spacing(p, before=0, after=8, line=1.15)
    _run(p, today, font=FONT, size=BODY_PT)

    # Salutation
    p = doc.add_paragraph()
    _spacing(p, before=0, after=8, line=1.15)
    _run(p, letter.get("salutation", "Dear Hiring Team,"),
         font=FONT, size=BODY_PT)

    # Body paragraphs
    for para in letter.get("paragraphs", []):
        if not para:
            continue
        p = doc.add_paragraph()
        _spacing(p, before=0, after=8, line=1.15)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _run(p, para, font=FONT, size=BODY_PT)

    # Closing line
    closing = letter.get(
        "closing",
        "Thank you for considering my application. I would welcome the chance to talk.",
    )
    if closing:
        p = doc.add_paragraph()
        _spacing(p, before=0, after=10, line=1.15)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _run(p, closing, font=FONT, size=BODY_PT)

    # Sign-off
    p = doc.add_paragraph()
    _spacing(p, before=0, after=2, line=1.15)
    _run(p, "Kind regards,", font=FONT, size=BODY_PT)

    p = doc.add_paragraph()
    _spacing(p, before=0, after=10, line=1.15)
    _run(p, candidate.full_name, font=FONT, bold=True, size=BODY_PT, color=NAVY)

    # P.S.
    p = doc.add_paragraph()
    _spacing(p, before=0, after=0, line=1.15)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _run(p, _POSTSCRIPT, font=FONT, italic=True, size=BODY_PT - 0.5, color=GRAY)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def generate_for_id(job_id: str, *, force: bool = False) -> Path:
    """Generate a cover letter for an already-tailored job. Returns the .docx path.

    Requires that the job has been tailored (resume_path on the tracker row).
    Output: settings.output_dir / "CV" / "{job_id}_{Company}_CoverLetter.docx".
    Idempotent unless force=True.
    """
    settings = get_settings()
    profile = get_profile()

    rec = db.get(job_id)
    if not rec or not rec.get("resume_path"):
        raise RuntimeError(
            f"Job {job_id} has no tailored resume yet. Run Tailor first."
        )
    resume_path = Path(rec["resume_path"])
    resume_text = _extract_resume_text(resume_path)

    title, company, jd = _lookup_jd(job_id)
    if not jd:
        raise RuntimeError(f"No job description found for {job_id}.")

    safe_company = _safe_filename(company)
    out_dir = settings.output_dir / "CV"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{job_id}_{safe_company}_CoverLetter.docx"

    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        return out_path

    letter = _generate_letter(resume_text, title, company, jd)
    return _render_letter(letter, profile.candidate, out_path)

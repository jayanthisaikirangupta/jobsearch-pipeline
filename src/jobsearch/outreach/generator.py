"""Generate direct-outreach messages for a job: the highest-conversion
channel available to a sponsorship-constrained candidate.

For each target job this produces one markdown file containing:

  1. WHO TO FIND       — LinkedIn search strings for the right humans
  2. CONNECTION NOTE   — <= 290 chars (LinkedIn's connection-request limit)
  3. LINKEDIN MESSAGE  — 4-6 sentences, sent after they accept / via InMail
  4. EMAIL             — subject + ~120-word body for a guessed/known address

Strategy baked into the prompts (agreed 2026-07): state the visa position
plainly and up front — Graduate visa until 31 Aug 2026, salary meets the
new-entrant threshold, needs Skilled Worker sponsorship — because vagueness
is what kills sponsored applications, not the requirement itself. Lead with
the one concrete thing Sai built that matches THIS job description.

Voice: plain, short, honest, concrete (Sai's voice rules, embedded below).

Reads:  jobs_scored.parquet (title, company, description)
        + the tailored resume .docx when one exists (better grounding)
Writes: output/outreach/{job_id}_{Company}_outreach.md

Usage:
    python -m jobsearch.cli outreach run --job-id <id>
    python -m jobsearch.cli outreach run --top 5        # best A/B not yet applied
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from anthropic import AnthropicBedrock
from rich.console import Console

from ..config import get_profile, get_settings
from ..tracker import db

console = Console()


SYSTEM_PROMPT = """You write outreach messages for Sai Kiran Gupta Jayanthi, a UK-based engineer contacting a hiring manager or recruiter about one specific job opening. Return STRICT JSON only.

VOICE — non-negotiable. The reader must believe Sai typed this himself in one quick pass:
- Plain, short, honest, concrete. "I built X" not "I architected a solution leveraging X".
- Lead with the most relevant fact. No windup, no "I hope this message finds you well", no "I am writing to express my interest".
- NEVER use em-dashes (—) or en-dashes (–). Commas, colons, "and", or two short sentences.
- No promotional words: robust, seamless, cutting-edge, passionate, excited, thrilled, leverage, unlock, empower, elevate, comprehensive.
- No rule-of-three lists ("fast, scalable, and reliable"). No "It's not just X, it's Y".
- Numbers and named mechanisms carry the weight. Adjectives do not.
- Confident, not boastful. Report the win, move on.
- A plain close beats a slogan: "Happy to send my CV over." / "Worth a quick call?"

VISA POSITION — include it plainly, once, in the LinkedIn message and the email (NOT in the connection note, no room):
State in one matter-of-fact sentence: he is on a UK Graduate visa and would need Skilled Worker sponsorship via the new entrant route, which the role's salary supports. Do not apologise for it, do not bury it, do not over-explain. One sentence. Example register: "One thing to flag early: I'm on a Graduate visa and would need Skilled Worker sponsorship, which this role's salary band supports under the new entrant route."

CONTENT RULES:
- You do NOT know the recipient's name. Never invent one. Open every message with the literal placeholder "Hi {first name}," exactly like that, so Sai swaps in the real name after finding the person.
- Pick the ONE project or outcome from Sai's background that best matches this specific JD, and lead with it. Do not list everything.
- Use ONLY facts from the background section below. Never invent metrics, tools, employers, or experience.
- Honest positioning: Java/Quarkus/Spring Boot is his primary stack; Python/TypeScript secondary. Production GenAI work is real (OCR+LLM pipeline, agentic Mantis pipeline, MCP integrations). AWS/graph databases/PySpark/Snowflake are conceptual or adjacent, never claim them as production experience. He "worked on the Lloyds Banking Group account at TCS", he was not a banker.
- Mention the specific role title so the reader knows exactly which opening this is about.
- The connection note must be <= 290 characters INCLUDING spaces. Count carefully.
- The LinkedIn message is 4-6 sentences. The email body is 100-140 words, 2-3 short paragraphs.
- who_to_find: 3-4 LinkedIn search strings for the right people at THIS company (e.g. "engineering manager {company}", "talent acquisition {company}", team-specific if the JD names a team), each with a 5-10 word reason.

Return STRICT JSON:
{
  "who_to_find": [
    {"search": "<LinkedIn search string>", "why": "<short reason>"}
  ],
  "connection_note": "<= 290 chars",
  "linkedin_message": "<4-6 sentences>",
  "email_subject": "<short, specific, no clickbait>",
  "email_body": "<100-140 words, 2-3 short paragraphs, ends with a plain close and 'Sai'>"
}
"""


BACKGROUND = """=== SAI'S BACKGROUND (only source of truth — do not add to it) ===
Current: Kuehne+Nagel UK (Milton Keynes, Jan 2025-present), Financial IT Development, KNTEA travel & expense platform. Stack: Java 17, Quarkus, Spring Boot, Angular 19/PrimeNG, MongoDB, Python.
Production GenAI work at K+N:
- Async OCR + LLM document-extraction pipeline for expense/receipt processing: schema validation, retries, idempotency, observability.
- Agentic ticket-assist pipeline for the Mantis bug tracker: multi-step reasoning, tool use, branching, retries, persistence.
- MCP server integrations (Mantis, IDE, MongoDB) so Claude assistants reason over live ticket/code/DB context on a locked-down enterprise network.
- n8n workflow automation.
Engineering wins:
- Root-caused and fixed a financial precision bug at the data-model level (Decimal128; silent rounding across thousands of records).
- Lazy-loading fix taking one hot path from 132 network calls to 9; ~30% transaction-latency reduction.
- Caching layer cutting repeat LLM/API calls.
Before: ~4.5 years at TCS on the Lloyds Banking Group account (Java backend, regulated banking environment). MSc Cloud Computing, University of Leicester.
Visa: UK Graduate visa to 31 Aug 2026; needs Skilled Worker sponsorship; salary meeting the new entrant threshold makes this straightforward for a licensed sponsor.
Location: Milton Keynes, happy to relocate anywhere in the UK.
"""


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (s or ""))[:40]


def _resume_text(job_id: str) -> str:
    rec = db.get(job_id) or {}
    path = rec.get("resume_path") or ""
    if path and Path(path).exists() and path.endswith(".docx"):
        try:
            import docx2txt
            return docx2txt.process(path) or ""
        except Exception:
            return ""
    return ""


def generate_for_job(job_id: str) -> Path:
    """Generate the outreach pack for one job_id. Returns the output path."""
    settings = get_settings()
    scored = pd.read_parquet(settings.data_dir / "jobs_scored.parquet")
    match = scored[scored["id"].astype(str) == str(job_id)]
    if match.empty:
        raise KeyError(f"job_id {job_id!r} not in jobs_scored.parquet")
    row = match.iloc[0]

    title = str(row.get("title") or "")
    company = str(row.get("company") or "")
    jd = str(row.get("description") or "")[:8000]

    resume = _resume_text(job_id)
    resume_block = (
        f"\n\n=== TAILORED CV ALREADY SENT/PREPARED FOR THIS ROLE ===\n{resume[:4000]}"
        if resume else ""
    )

    client = AnthropicBedrock(aws_region=settings.aws_region)
    response = client.messages.create(
        model=settings.tailor_model,
        max_tokens=1500,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"{BACKGROUND}{resume_block}\n\n"
                f"<role>\nCompany: {company}\nTitle: {title}\n</role>\n\n"
                f"<job_description>\n{jd}\n</job_description>\n\n"
                f"Write the outreach pack. JSON only."
            ),
        }],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    payload: dict[str, Any] = json.loads(text)

    note = payload.get("connection_note", "")
    if len(note) > 300:
        console.print(f"  [yellow]connection note {len(note)} chars — trimming to 290[/]")
        payload["connection_note"] = note[:287].rsplit(" ", 1)[0] + "..."

    out_dir = settings.output_dir / "outreach"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{job_id}_{_safe(company)}_outreach.md"

    finders = "\n".join(
        f"- **{f.get('search','')}** — {f.get('why','')}"
        for f in payload.get("who_to_find", [])
    )
    md = (
        f"# Outreach — {title} @ {company}\n\n"
        f"Job ID: `{job_id}`\n\n"
        f"## 1. Who to find on LinkedIn\n\n{finders}\n\n"
        f"## 2. Connection note (<= 300 chars, goes with the request)\n\n"
        f"> {payload.get('connection_note','')}\n\n"
        f"## 3. LinkedIn message (after accept / InMail)\n\n"
        f"{payload.get('linkedin_message','')}\n\n"
        f"## 4. Email\n\n"
        f"**Subject:** {payload.get('email_subject','')}\n\n"
        f"{payload.get('email_body','')}\n"
    )
    out.write_text(md, encoding="utf-8")

    db.upsert_application(
        job_id=job_id, company=company, title=title,
        url=str(row.get("url") or ""), grade=str(row.get("grade") or ""),
        score=int(row.get("score_total") or 0),
    )
    return out


def generate_top(n: int = 5) -> list[Path]:
    """Generate outreach packs for the top-n A/B jobs not yet applied to."""
    settings = get_settings()
    scored = pd.read_parquet(settings.data_dir / "jobs_scored.parquet")
    ab = scored[scored["grade"].isin(["A", "B"])].sort_values(
        "score_total", ascending=False
    )
    done_statuses = {"applied", "interview", "offer", "rejected", "withdrawn", "expired"}
    tracked = {a["job_id"]: a.get("status", "") for a in db.list_apps(limit=10_000)}

    outputs: list[Path] = []
    for _, row in ab.iterrows():
        if len(outputs) >= n:
            break
        jid = str(row["id"])
        if tracked.get(jid, "") in done_statuses:
            continue
        console.print(f"  outreach: {row['title']} @ {row['company']}")
        try:
            outputs.append(generate_for_job(jid))
        except Exception as e:  # keep the batch going
            console.print(f"  [red]failed for {jid}: {e}[/]")
    return outputs

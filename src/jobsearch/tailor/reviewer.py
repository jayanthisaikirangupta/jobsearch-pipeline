"""JD-aware reviewer for a tailored resume.

Pipeline:
  1. Read the rendered .docx and extract its plain text.
  2. Deterministic JD-keyword coverage check — top JD nouns vs resume text.
  3. Bedrock Claude critique with a strict JSON schema:
       overall_grade, score (0-100), missing_jd_keywords, generic_bullets,
       weak_summary_alignment, revision_priorities.
  4. Write a markdown review next to the resume + return the parsed dict.

Why not just trust Claude with everything? Because deterministic keyword coverage
is cheap, reliable, and gives the LLM a grounded starting point for its critique.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import docx2txt
from anthropic import AnthropicBedrock

from ..config import get_settings


# Common English stop words + ATS noise. Kept short on purpose — deterministic
# keyword overlap is a coarse first signal, not the final judgement.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "with", "by", "as", "is", "are", "was", "were", "be", "been", "being", "this",
    "that", "these", "those", "it", "its", "we", "you", "your", "our", "their",
    "they", "them", "i", "me", "my", "from", "into", "about", "across", "after",
    "before", "between", "during", "over", "under", "up", "down", "out", "than",
    "then", "so", "if", "while", "any", "all", "each", "every", "some", "no",
    "not", "do", "does", "did", "have", "has", "had", "will", "would", "should",
    "could", "may", "might", "can", "must", "shall", "will", "more", "most",
    "less", "few", "many", "much", "very", "such", "also", "well", "us", "use",
    "used", "using", "etc", "eg", "ie", "incl", "including", "include", "able",
    "ability", "experience", "experienced", "experiences", "year", "years", "role",
    "roles", "responsibility", "responsibilities", "team", "teams", "work",
    "working", "works", "job", "jobs", "candidate", "candidates", "applicant",
    "company", "companies", "client", "clients", "stakeholder", "stakeholders",
    "ensure", "ensures", "ensuring", "deliver", "delivers", "delivering",
    "develop", "develops", "developing", "build", "builds", "building", "create",
    "creates", "creating", "manage", "manages", "managing", "lead", "leads",
    "leading", "support", "supports", "supporting", "provide", "provides",
    "providing", "looking", "seeking", "join", "joining", "based", "across",
    "within", "without", "well", "good", "great", "strong", "excellent",
    "knowledge", "skills", "ability", "passion", "passionate", "self", "starter",
    "minimum", "preferred", "required", "must", "should", "ideally", "what",
    "who", "when", "where", "why", "how", "one", "two", "three", "four", "five",
    "via", "per", "non", "yet", "now", "current", "currently", "etc",
}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-./]{1,}")


# ---------- deterministic JD coverage --------------------------------------


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "")]


def jd_keyword_coverage(jd_text: str, resume_text: str, top_n: int = 30) -> dict[str, Any]:
    """Top-N JD content words and whether each appears in the resume.

    Returns: {present: [...], missing: [...], coverage_pct: float}
    """
    jd_tokens = [t for t in _tokens(jd_text) if t not in STOPWORDS and len(t) > 2]
    resume_tokens = set(_tokens(resume_text))

    counts = Counter(jd_tokens)
    top = [w for w, _ in counts.most_common(top_n)]

    present = [w for w in top if w in resume_tokens]
    missing = [w for w in top if w not in resume_tokens]
    pct = (len(present) / len(top) * 100) if top else 0.0
    return {"present": present, "missing": missing, "coverage_pct": round(pct, 1)}


# ---------- LLM critique ----------------------------------------------------


REVIEWER_SYSTEM = """You are a senior recruiter and ATS expert reviewing a tailored CV against a specific job description.

Your job: judge how well this CV will perform for THIS role and produce concrete, actionable revision guidance. The candidate is a UK Skilled Worker visa applicant — sponsor-licensed roles only — so flag anything that hurts shortlistability.

Review dimensions (in order of importance):
1. JD alignment — does the profile and top bullets directly speak to this role's must-haves?
2. Keyword coverage — are JD's terminology and tools surfaced naturally where the candidate truly has them?
3. Generic bullets — bullets that could appear on any CV add no signal; flag the worst offenders.
4. Quantified impact — are numbers / scale / outcomes present? Recruiters scan for these.
5. Weak summary alignment — does the profile read like it was written for THIS role?
6. ATS hygiene — typos, awkward phrasing, ASCII issues, formatting smells.

You must return STRICT JSON only — no prose, no markdown fences:

{
  "overall_grade": "A | B | C | D | F",
  "score": 0,
  "verdict": "<one short sentence — would a recruiter shortlist this CV?>",
  "strengths": ["<2-4 specific things this CV does well for this JD>"],
  "missing_jd_keywords": ["<JD terms the CV should surface but doesn't, that the candidate truly has>"],
  "generic_bullets": ["<verbatim bullets that read generic and need rewriting>"],
  "weak_alignment": ["<specific lines / sections that don't speak to the JD>"],
  "revision_priorities": [
    {"priority": 1, "issue": "<what to fix>", "suggestion": "<how to fix it>"},
    {"priority": 2, "issue": "...", "suggestion": "..."}
  ],
  "needs_retailor": true,
  "retailor_instructions": "<see RETAILOR INSTRUCTIONS section below>"
}

Score band guidance: A = 85+ (strong shortlist), B = 70-84 (likely shortlist), C = 55-69 (borderline), D = 40-54 (rewrite required), F < 40 (do not submit).
Be specific and tough. Vague feedback is worthless. Quote the CV verbatim where relevant.

RETAILOR INSTRUCTIONS — the most important new field:

The dashboard exposes a "Retailor" button that feeds your retailor_instructions text BACK to the tailor LLM along with the original resume + JD. Write that text as if you were briefing the next tailor pass directly.

Set "needs_retailor": true whenever the CV would meaningfully improve from a re-tailor pass (any C/D/F grade, any B grade with concrete revision priorities, or any A grade where adding 1-2 missing JD keywords would push it higher). Set it to false ONLY when the CV is already an A and there is literally nothing to add.

When needs_retailor is true, "retailor_instructions" must be a self-contained instruction block, written in plain English, that tells the next tailor pass exactly what to change. Do NOT just restate the critique — convert it into actionable edits. Structure it as numbered points:

1. HEADLINE: <if the headline should change, give the new one verbatim; otherwise omit>
2. PROFILE: <which sentences to rewrite; what JD terms / seniority / domain to surface>
3. SKILLS: <which categories to reorder; which items to add or move to the front; which rows to drop>
4. EXPERIENCE BULLETS: <which specific bullets to rewrite, quoting the original, with the JD term or metric to surface; which bullets to drop entirely>
5. PROJECTS: <which projects to drop/replace; which inventory projects to surface instead>
6. KEYWORDS TO SURFACE: <a flat list of JD terms the resume must mention naturally (only those the candidate genuinely has from the inventory)>
7. ANYTHING ELSE: <one-line warnings about ATS hygiene, em-dash slips, generic phrasing>

Keep retailor_instructions <= 1500 characters. If needs_retailor is false, set retailor_instructions to an empty string.
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _salvage_json(client: AnthropicBedrock, model: str, broken: str) -> dict[str, Any]:
    """One-shot retry that asks Claude to fix malformed JSON."""
    salvage = client.messages.create(
        model=model,
        max_tokens=4096,
        system="You repair malformed JSON. Reply with ONLY the valid JSON object — no prose, no fences.",
        messages=[
            {
                "role": "user",
                "content": (
                    "The JSON below is invalid (truncated or broken). "
                    "Return a syntactically valid JSON object with the same fields, "
                    "preserving as much content as possible and reasonably completing "
                    "any cut-off strings. Reply with JSON only.\n\n"
                    f"<broken_json>\n{broken}\n</broken_json>"
                ),
            }
        ],
    )
    text = "".join(b.text for b in salvage.content if b.type == "text")
    return json.loads(_strip_fences(text))


def llm_critique(resume_text: str, jd_text: str, role_title: str, company: str,
                 coverage: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    client = AnthropicBedrock(aws_region=settings.aws_region)

    response = client.messages.create(
        model=settings.tailor_model,
        max_tokens=4096,  # 2048 truncated mid-JSON around char 5000 — bumped
        system=[
            {
                "type": "text",
                "text": REVIEWER_SYSTEM,
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
                            f"<role>\nCompany: {company}\nTitle: {role_title}\n</role>\n\n"
                            f"<job_description>\n{jd_text}\n</job_description>"
                        ),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"<rendered_cv>\n{resume_text}\n</rendered_cv>\n\n"
                            f"<deterministic_signals>\n"
                            f"JD-keyword coverage: {coverage['coverage_pct']}%\n"
                            f"Present: {', '.join(coverage['present'][:15])}\n"
                            f"Missing: {', '.join(coverage['missing'][:15])}\n"
                            f"</deterministic_signals>\n\n"
                            f"Return JSON only. Keep the response compact — strengths/generic_bullets/weak_alignment <=4 items each, revision_priorities <=5."
                        ),
                    },
                ],
            }
        ],
    )

    text = _strip_fences("".join(b.text for b in response.content if b.type == "text"))
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Most likely cause: stop_reason == "max_tokens" cut us mid-string.
        # Try one salvage pass that asks Claude to fix the JSON itself.
        if response.stop_reason == "max_tokens":
            note = "(truncated by max_tokens; salvaging)"
        else:
            note = f"(parse error: {e}; salvaging)"
        try:
            return _salvage_json(client, settings.tailor_model, text)
        except json.JSONDecodeError as e2:
            raise ValueError(
                f"Reviewer JSON unparseable {note} and salvage failed: {e2}. "
                f"Truncated head: {text[:200]!r}"
            ) from e2


# ---------- public API ------------------------------------------------------


def extract_resume_text(docx_path: Path) -> str:
    """Plain text from a tailored .docx for the reviewer to read."""
    return docx2txt.process(str(docx_path)) or ""


def review_resume(resume_docx: Path, jd_text: str, role_title: str, company: str) -> dict[str, Any]:
    """Score a tailored resume against the JD it was tailored for. Writes
    a markdown review to <resume_docx>.review.md and returns the full result."""
    resume_text = extract_resume_text(resume_docx)
    coverage = jd_keyword_coverage(jd_text, resume_text)
    critique = llm_critique(resume_text, jd_text, role_title, company, coverage)

    result = {
        "resume": str(resume_docx),
        "company": company,
        "role": role_title,
        "coverage": coverage,
        "critique": critique,
    }

    md_path = resume_docx.with_suffix(".review.md")
    md_path.write_text(_format_markdown(result), encoding="utf-8")
    return result


def _format_markdown(result: dict[str, Any]) -> str:
    c = result["critique"]
    cov = result["coverage"]
    lines = [
        f"# CV Review — {result['company']}: {result['role']}",
        "",
        f"**Overall:** {c.get('overall_grade', '?')} · score {c.get('score', '?')}/100",
        f"**Verdict:** {c.get('verdict', '')}",
        f"**JD-keyword coverage (deterministic):** {cov['coverage_pct']}%",
        "",
        "## Strengths",
        *[f"- {s}" for s in c.get("strengths", [])],
        "",
        "## Missing JD keywords (that you actually have)",
        *[f"- `{k}`" for k in c.get("missing_jd_keywords", [])],
        "",
        "## Generic bullets to rewrite",
        *[f"- {b}" for b in c.get("generic_bullets", [])],
        "",
        "## Weak alignment",
        *[f"- {w}" for w in c.get("weak_alignment", [])],
        "",
        "## Revision priorities",
    ]
    for item in c.get("revision_priorities", []):
        lines.append(f"**{item.get('priority', '?')}. {item.get('issue', '')}**")
        lines.append(f"- {item.get('suggestion', '')}")
        lines.append("")
    if c.get("needs_retailor"):
        lines.append("## Retailor instructions (feed back to tailor LLM)")
        lines.append("")
        lines.append(c.get("retailor_instructions", "").strip() or "_(empty)_")
        lines.append("")
    lines.append("---")
    lines.append(f"*Coverage detail — present: {', '.join(cov['present']) or '(none)'}*")
    lines.append(f"*Coverage detail — missing: {', '.join(cov['missing']) or '(none)'}*")
    return "\n".join(lines)

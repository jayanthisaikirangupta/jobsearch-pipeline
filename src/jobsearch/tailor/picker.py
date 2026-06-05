"""Pick the closest resume variant for a JD by keyword overlap.

Indexes every .docx under settings.resumes_dir, extracts plain text via docx2txt,
and ranks variants against the JD using rapidfuzz token-set ratio.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import docx2txt
from rapidfuzz import fuzz

from ..config import get_settings


@dataclass
class ResumeVariant:
    name: str
    path: Path
    text: str


@lru_cache(maxsize=1)
def index_variants() -> list[ResumeVariant]:
    settings = get_settings()
    if not settings.resumes_dir.exists():
        return []
    variants: list[ResumeVariant] = []
    for p in settings.resumes_dir.glob("*.docx"):
        if p.name.startswith("~$"):
            continue  # Word lock files
        try:
            text = docx2txt.process(str(p)) or ""
        except Exception:
            text = ""
        variants.append(ResumeVariant(name=p.stem, path=p, text=text))
    return variants


def pick(job_title: str, job_description: str) -> ResumeVariant | None:
    """Return the variant whose text best matches the JD."""
    variants = index_variants()
    if not variants:
        return None
    jd = f"{job_title}\n{job_description}".lower()
    scored = [
        (fuzz.token_set_ratio(jd, v.text.lower()) + fuzz.partial_ratio(job_title.lower(), v.name.lower()), v)
        for v in variants
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]

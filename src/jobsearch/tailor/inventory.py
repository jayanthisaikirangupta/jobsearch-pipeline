"""Candidate experience inventory — every fact across every resume variant.

The picker chooses ONE variant per JD. That variant won't necessarily mention
every skill / project / accomplishment the candidate actually has — Sai's RAG
work might live in the AI Engineer variant while the Envision JD picks the
Envision_v2 variant. Without inventory, Claude can't surface RAG even though
it's real and documented.

This module concatenates ALL .docx variants in RESUMES_DIR into a single
"experience inventory" text block. The tailor passes it to Claude as a
cached prefix and tells the model: you may pull a small number of JD-relevant
items from the inventory into the tailored CV, as long as they're truly
present in the inventory (i.e. the candidate has actually done that work).

This is grounded augmentation, not fabrication. Anti-fabrication is enforced
by the rule "every added item MUST be traceable to a specific section of
this inventory" plus the inventory itself being the only source of truth.
"""
from __future__ import annotations

from functools import lru_cache

import docx2txt

from ..config import get_settings


@lru_cache(maxsize=1)
def build_inventory() -> str:
    """Return a single text blob with every .docx variant labeled by name.

    Cached at process level — re-run a fresh Python process to pick up new
    variants on disk. Cheap to compute (10ms per variant).
    """
    settings = get_settings()
    resumes_dir = settings.resumes_dir
    if not resumes_dir.exists():
        return ""

    sections: list[str] = []
    for p in sorted(resumes_dir.glob("*.docx")):
        if p.name.startswith("~$"):
            continue  # Word lock file
        try:
            text = docx2txt.process(str(p)) or ""
        except Exception:
            text = ""
        if not text.strip():
            continue
        sections.append(f"=== VARIANT: {p.stem} ===\n{text.strip()}")

    return "\n\n".join(sections)

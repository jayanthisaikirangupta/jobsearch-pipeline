"""Shared helpers for hosted-ATS sources (Ashby / Workable / SmartRecruiters).

Greenhouse and Lever predate this module and carry private copies of the
same logic; new ATS sources should import from here instead.
"""
from __future__ import annotations

import hashlib
import html as _html
import re

import yaml

from ...config import _PROJECT_ROOT

TOKENS_PATH = _PROJECT_ROOT / "config" / "sponsor_tokens.yaml"
DISCOVERED_PATH = _PROJECT_ROOT / "config" / "sponsor_tokens.discovered.yaml"
TIMEOUT = 15.0
USER_AGENT = "jobsearch-pipeline/0.1"


def load_tokens(key: str) -> list[str]:
    """Read the token list for one ATS, merging BOTH token files:

      config/sponsor_tokens.yaml            — hand-curated, never auto-edited
      config/sponsor_tokens.discovered.yaml — owned by discover_ats_tokens.py,
                                              safe to regenerate wholesale

    Tokens are NOT lower-cased here — SmartRecruiters identifiers are
    case-sensitive ("Experian" works, "experian" 404s). De-dupes
    case-insensitively, preserving first-seen casing (curated file wins).
    """
    seen, out = set(), []
    for path in (TOKENS_PATH, DISCOVERED_PATH):
        if not path.exists():
            continue
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for t in cfg.get(key) or []:
            t = str(t).strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


def row_id(source: str, token: str, internal_id, title: str) -> str:
    base = f"{source}|{token}|{internal_id or ''}|{title}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    decoded = _html.unescape(str(text))
    return re.sub(r"<[^>]+>", " ", decoded)


def matches_search(title: str, content: str, search_term: str) -> bool:
    """OR'd-phrase substring match, mirroring queries.yaml conventions."""
    if not search_term:
        return True
    needles = [s.strip().lower() for s in search_term.split(" OR ") if s.strip()]
    haystack = (title + " " + content).lower()
    return any(n in haystack for n in needles) if needles else True


_UK_HINTS = (
    "united kingdom", "uk", " gb", "england", "scotland", "wales",
    "northern ireland", "london", "manchester", "edinburgh", "cambridge",
    "bristol", "leeds", "glasgow", "milton keynes", "belfast", "cardiff",
    "newcastle", "nottingham", "southampton", "coventry", "aberdeen",
    "newport", "exeter", "ipswich", "northampton",
)


def matches_location(loc: str, target: str) -> bool:
    """UK-generic targets match any UK keyword; city targets need all tokens."""
    if not target:
        return True
    target_lower = target.lower()
    loc_lower = (loc or "").lower()

    if "united kingdom" in target_lower or target_lower.strip() in ("uk", "gb"):
        return any(kw in loc_lower for kw in _UK_HINTS)

    target_words = {w.strip(",.").lower()
                    for w in re.split(r"[\s,/]+", target)
                    if len(w) > 2 and w.lower() not in {"united", "kingdom", "uk", "gb"}}
    if not target_words:
        return target_lower in loc_lower
    return all(w in loc_lower for w in target_words)

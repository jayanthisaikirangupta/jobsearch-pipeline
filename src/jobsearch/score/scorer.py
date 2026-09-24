"""A-F fit score.

Five dimensions, each 0-20, summed to 0-100, then a small +/- tier
adjustment for seniority match:

  1. salary           — does the posted salary clear the visa floor?
  2. soc_eligibility  — title heuristically maps to a Table 1 SOC?
  3. skills_overlap   — JD keyword overlap with profile must/nice skills.
  4. location         — target locations + remote.
  5. sponsor_signal   — fuzzy-match score from the sponsor filter.
  +/- tier_match      — bonus if title is mid-level, penalty if it's junior
                        (overqualified flag) or staff/principal/director/manager
                        (under-qualified flag). Clamped to ±10.

Total -> grade:
  >= 85 A | >= 70 B | >= 55 C | >= 40 D | else F
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rich.console import Console

from ..config import get_profile, get_settings

console = Console()


SOC_TITLE_HINTS: dict[int, list[str]] = {
    2133: ["data engineer", "data architect", "solutions architect", "systems designer", "platform engineer"],
    2134: ["software engineer", "software developer", "backend", "full stack", "ai engineer", "ml engineer", "genai", "llm engineer"],
    2139: ["devops", "site reliability", "sre", "platform", "cloud engineer"],
}

GRADE_BANDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D")]


@dataclass
class ScoreBreakdown:
    salary: int
    soc_eligibility: int
    skills_overlap: int
    location: int
    sponsor_signal: int
    tier_match: int = 0

    @property
    def total(self) -> int:
        return (
            self.salary
            + self.soc_eligibility
            + self.skills_overlap
            + self.location
            + self.sponsor_signal
            + self.tier_match
        )

    @property
    def grade(self) -> str:
        # Floor at 0 in case tier_match is strongly negative on a low base
        score = max(0, self.total)
        for cutoff, g in GRADE_BANDS:
            if score >= cutoff:
                return g
        return "F"


def _annual_gbp(min_amt, max_amt, interval) -> float | None:
    """Best effort conversion to annual GBP."""
    amounts = [a for a in (min_amt, max_amt) if pd.notna(a)]
    if not amounts:
        return None
    midpoint = sum(float(a) for a in amounts) / len(amounts)
    interval = (interval or "").lower() if isinstance(interval, str) else ""
    if "year" in interval or "annual" in interval:
        return midpoint
    if "month" in interval:
        return midpoint * 12
    if "week" in interval:
        return midpoint * 52
    if "day" in interval or "daily" in interval:
        return midpoint * 220
    if "hour" in interval:
        return midpoint * 1800
    # Heuristic: amounts > 1000 are likely annual already
    return midpoint if midpoint > 5000 else None


def _score_salary(annual: float | None, floor: int, target: int) -> int:
    if annual is None:
        return 10  # unknown, neutral
    if annual < floor:
        return 0
    if annual >= target * 1.2:
        return 20
    # Linear ramp floor->target
    span = max(target - floor, 1)
    return int(min(20, 10 + 10 * (annual - floor) / span))


def _score_soc(title: str, target_socs: list[int]) -> int:
    title_l = (title or "").lower()
    for soc in target_socs:
        for hint in SOC_TITLE_HINTS.get(soc, []):
            if hint in title_l:
                return 20
    # Soft match
    for hints in SOC_TITLE_HINTS.values():
        for hint in hints:
            if hint in title_l:
                return 12
    return 4


# Lane detection: which of Sai's two role families does this title belong
# to? Lane "ai" = applied GenAI/LLM engineering; lane "software" =
# Java/Python full-stack SWE. Checked in order — "AI Engineer" hits the
# ai lane before the generic "engineer" hits software.
_LANE_TITLE_HINTS: list[tuple[str, list[str]]] = [
    ("ai", ["ai engineer", "genai", "generative ai", "llm", "agentic",
            "ai developer", "applied ai", "prompt engineer"]),
    ("software", ["software engineer", "software developer", "backend",
                  "back end", "full stack", "full-stack", "fullstack",
                  "java", "python developer", "python engineer", "frontend",
                  "front end", "react", "angular", "web developer",
                  "application developer", "platform engineer",
                  "cloud engineer", "devops", "site reliability",
                  "data engineer"]),
]


def _detect_lane(title: str) -> str | None:
    t = (title or "").lower()
    for lane, hints in _LANE_TITLE_HINTS:
        if any(h in t for h in hints):
            return lane
    return None


def _score_skills(description: str, must: list[str], nice: list[str],
                  title: str = "", lanes: dict[str, list[str]] | None = None) -> int:
    """Score 0-20 based on JD's overlap with confirmed must/nice skills.

    Rebalanced 2026: count distinct must-have hits and reward the absolute
    count (not ratio) since modern JDs typically list 8-12 keywords. Hitting
    5 must-haves out of 15 is genuinely strong, ratio-based scoring under-
    counts that. Caps at 20.
    """
    text = (description or "").lower()
    if not text:
        return 0
    # Lane-aware matching: when per-lane lists are configured and the title
    # maps to a lane, count must-hits against THAT lane only. A LangChain-
    # heavy JD no longer gets full skill marks as a "Java role" and vice
    # versa. Titles outside both lanes fall back to the union list.
    if lanes:
        lane = _detect_lane(title)
        if lane and lanes.get(lane):
            must = lanes[lane]
    # Use sub-string match for multi-word skills like "spring boot", "ci/cd"
    must_hits = sum(1 for k in must if k.lower() in text)
    nice_hits = sum(1 for k in nice if k.lower() in text)
    # Reward absolute count: 4+ must-hits = full 15, scales linearly below
    must_pts = min(15, (must_hits / 4) * 15)
    nice_pts = min(5, (nice_hits / 4) * 5)
    return int(must_pts + nice_pts)


# Tier signal keywords. Order matters: more specific patterns first.
_TIER_PATTERNS: list[tuple[int, list[str]]] = [
    # Out-of-lane role families: interview loops Sai would fail today
    # (stats/modelling, research ML, pure architecture). Hard drop — these
    # should never reach the Action Queue regardless of keyword overlap.
    (-20, ["data scientist", "research scientist", "applied scientist",
           "machine learning engineer", " ml engineer", "nlp engineer",
           "research engineer", "statistician", "solutions architect",
           "enterprise architect", "data architect"]),
    (-15, ["intern", "internship", "graduate", "junior", "entry level",
           "entry-level", "trainee", "apprentice"]),
    (-10, ["principal", "staff engineer", "staff software", "staff data",
           "staff machine", "staff ai", "staff cloud", "staff platform",
           "staff frontend", "staff backend", "staff site", "head of",
           "director", "vp",
           "engineering manager", "vice president"]),
    # 'Lead' is borderline — sometimes means tech lead (5+ yrs), sometimes
    # senior IC contributor. Small penalty.
    (-5, ["tech lead", "team lead", " lead "]),
    # 'Senior' in title but no obvious AI specialty cap is fine for Sai's
    # 5 yrs on Java/full-stack. No penalty.
    # Mid-level (no prefix) gets a small bonus to surface them more.
    (3, ["software engineer", "ai engineer", "data engineer",
         "full stack engineer", "full-stack engineer", "backend engineer",
         "frontend engineer", "cloud engineer", "devops engineer",
         "platform engineer"]),
]


def _score_tier(title: str) -> int:
    """Tier penalty/bonus based on title seniority. Returns int in roughly
    [-15, +3]. Applied AFTER the 5 main components, so a title that's a
    perfect match for Sai's tier (mid-level / senior-on-Java) lifts past
    the A boundary; a junior or staff title drops the row out of A/B."""
    if not title:
        return 0
    t = " " + title.lower() + " "
    for adjustment, patterns in _TIER_PATTERNS:
        for p in patterns:
            if p in t:
                return adjustment
    return 0


_UK_KEYWORDS = (
    "united kingdom", "uk", " gb", "england", "scotland", "wales",
    "northern ireland", "remote uk", "remote, uk", "remote-uk",
    "london", "manchester", "edinburgh", "glasgow", "birmingham",
    "cambridge", "bristol", "leeds", "liverpool", "sheffield",
    "newcastle", "cardiff", "belfast", "aberdeen", "milton keynes",
    "reading", "oxford", "nottingham", "brighton", "coventry", "york",
    "southampton", "portsmouth", "swansea", "dundee", "leicester",
    "exeter", "norwich", "bath", "ipswich",
)


def _score_location(loc: str, targets: list[str]) -> int:
    """Sai is willing to relocate anywhere in the UK, so any UK location
    earns full marks. Non-UK roles drop hard. Remote/hybrid is slightly
    preferred (less commute uncertainty) but UK on-site still hits 20."""
    if not loc:
        return 10  # missing — neutral, common on Indeed
    loc_l = loc.lower()
    is_uk = any(kw in loc_l for kw in _UK_KEYWORDS)
    if is_uk:
        return 20
    if "remote" in loc_l or "hybrid" in loc_l:
        # Could still be UK-based remote; give partial credit
        return 14
    return 4  # not UK, not remote — almost certainly mismatched


def _score_sponsor(score: float | int | None) -> int:
    if score is None or pd.isna(score):
        return 0
    s = float(score)
    if s >= 98:
        return 20
    if s >= 95:
        return 16
    if s >= 92:
        return 12
    if s >= 90:
        return 8
    return 0


# Data Engineer sub-filter: DE titles are fine when the JD is really a
# software role that touches data (Java/Python/Kafka/APIs), and a fail
# when it's a warehouse/platform role (Spark internals, Airflow, dbt,
# dimensional modelling) whose interview loop Sai would not pass today.
_DE_PLATFORM_STACK = ("airflow", "dbt", "databricks", "snowflake", "spark",
                      "redshift", "bigquery", "data warehouse", "dimensional model",
                      "data vault", "dagster", "fivetran")
_DE_CORE_STACK = ("java", "python", "kafka", "mongodb", "postgres", "api",
                  "microservice", "spring", "rest")


def _de_platform_penalty(title: str, description: str) -> int:
    """-15 when a Data Engineer JD leads with the platform stack rather
    than the software stack. 0 otherwise (including for non-DE titles)."""
    if "data engineer" not in (title or "").lower():
        return 0
    text = (description or "").lower()
    platform_hits = sum(1 for k in _DE_PLATFORM_STACK if k in text)
    core_hits = sum(1 for k in _DE_CORE_STACK if k in text)
    if platform_hits >= 2 and platform_hits > core_hits:
        return -15
    return 0


def score_row(row, profile) -> dict:
    """Score a single row (Mapping-like with .get) and return the column
    additions. Used by both the batch scorer below and the single-URL
    driver in pipeline/single_url.py — keep them sharing one impl."""
    annual = _annual_gbp(row.get("min_amount"), row.get("max_amount"), row.get("interval"))
    title = row.get("title", "")
    description = row.get("description", "")
    tier = _score_tier(title) + _de_platform_penalty(title, description)
    bd = ScoreBreakdown(
        salary=_score_salary(annual, profile.salary_floor_gbp, profile.salary_target_gbp),
        soc_eligibility=_score_soc(title, profile.target_socs),
        skills_overlap=_score_skills(
            description, profile.skills_must_have, profile.skills_nice_to_have,
            title=title, lanes=profile.skills_lanes,
        ),
        location=_score_location(row.get("location", ""), profile.target_locations),
        sponsor_signal=_score_sponsor(row.get("sponsor_score")),
        tier_match=tier,
    )
    return {
        "score_total": bd.total,
        "grade": bd.grade,
        "score_salary": bd.salary,
        "score_soc": bd.soc_eligibility,
        "score_skills": bd.skills_overlap,
        "score_location": bd.location,
        "score_sponsor_signal": bd.sponsor_signal,
        "score_tier_match": bd.tier_match,
        "annual_gbp": annual,
    }


def score_jobs() -> Path:
    settings = get_settings()
    profile = get_profile()
    src = settings.data_dir / "jobs_filtered.parquet"
    if not src.exists():
        raise FileNotFoundError(f"Run filter first: {src} missing")

    df = pd.read_parquet(src)
    if df.empty:
        out = settings.data_dir / "jobs_scored.parquet"
        df.to_parquet(out, index=False)
        return out

    rows = [score_row(r, profile) for _, r in df.iterrows()]
    scored = df.assign(**pd.DataFrame(rows)).sort_values("score_total", ascending=False)
    # Drop avoid-companies (TCS etc)
    if profile.avoid_companies:
        avoid_re = "|".join(re.escape(c.lower()) for c in profile.avoid_companies)
        keep = ~scored["company"].fillna("").str.lower().str.contains(avoid_re)
        scored = scored[keep]

    out = settings.data_dir / "jobs_scored.parquet"
    scored.to_parquet(out, index=False)

    grade_counts = scored["grade"].value_counts().to_dict()
    console.print(f"[green]Scored {len(scored)} jobs -> {out}[/]")
    console.print(f"  grades: {grade_counts}")
    return out

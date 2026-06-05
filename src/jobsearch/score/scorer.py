"""A-F fit score.

Five dimensions, each 0-20, summed to 0-100:
  1. salary           — does the posted salary clear the visa floor?
  2. soc_eligibility  — title heuristically maps to a Table 1 SOC?
  3. skills_overlap   — JD keyword overlap with profile must/nice skills.
  4. location         — target locations + remote.
  5. sponsor_signal   — fuzzy-match score from the sponsor filter.

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
    2433: ["data scientist", "applied scientist", "research scientist", "statistician"],
}

GRADE_BANDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D")]


@dataclass
class ScoreBreakdown:
    salary: int
    soc_eligibility: int
    skills_overlap: int
    location: int
    sponsor_signal: int

    @property
    def total(self) -> int:
        return (
            self.salary
            + self.soc_eligibility
            + self.skills_overlap
            + self.location
            + self.sponsor_signal
        )

    @property
    def grade(self) -> str:
        for cutoff, g in GRADE_BANDS:
            if self.total >= cutoff:
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


def _score_skills(description: str, must: list[str], nice: list[str]) -> int:
    text = (description or "").lower()
    if not text:
        return 0
    must_hits = sum(1 for k in must if re.search(rf"\b{re.escape(k.lower())}\b", text))
    nice_hits = sum(1 for k in nice if re.search(rf"\b{re.escape(k.lower())}\b", text))
    must_pts = min(15, (must_hits / max(len(must), 1)) * 15)
    nice_pts = min(5, (nice_hits / max(len(nice), 1)) * 5)
    return int(must_pts + nice_pts)


def _score_location(loc: str, targets: list[str]) -> int:
    if not loc:
        return 8
    loc_l = loc.lower()
    if "remote" in loc_l or "hybrid" in loc_l:
        return 18
    for t in targets:
        if t.lower() in loc_l:
            return 20
    if "united kingdom" in loc_l or "uk" in loc_l:
        return 12
    return 5


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

    rows: list[dict] = []
    for _, r in df.iterrows():
        annual = _annual_gbp(r.get("min_amount"), r.get("max_amount"), r.get("interval"))
        bd = ScoreBreakdown(
            salary=_score_salary(annual, profile.salary_floor_gbp, profile.salary_target_gbp),
            soc_eligibility=_score_soc(r.get("title", ""), profile.target_socs),
            skills_overlap=_score_skills(
                r.get("description", ""), profile.skills_must_have, profile.skills_nice_to_have
            ),
            location=_score_location(r.get("location", ""), profile.target_locations),
            sponsor_signal=_score_sponsor(r.get("sponsor_score")),
        )
        rows.append(
            {
                "score_total": bd.total,
                "grade": bd.grade,
                "score_salary": bd.salary,
                "score_soc": bd.soc_eligibility,
                "score_skills": bd.skills_overlap,
                "score_location": bd.location,
                "score_sponsor_signal": bd.sponsor_signal,
                "annual_gbp": annual,
            }
        )

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

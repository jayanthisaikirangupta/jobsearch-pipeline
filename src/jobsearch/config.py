"""Settings + profile loader."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    resumes_dir: Path = Path("./resumes")
    data_dir: Path = Path("./data")
    output_dir: Path = Path("./output")
    visa_salary_floor_gbp: int = 33_400
    target_soc_floor_gbp: int = 38_290
    jobspy_proxy: str = ""
    tailor_model: str = "anthropic.claude-sonnet-4-6"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.output_dir, self.output_dir / "resumes"):
            d.mkdir(parents=True, exist_ok=True)


class Candidate(BaseModel):
    full_name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    linkedin_url: str = ""
    github: str = ""
    github_url: str = ""
    visa_status: str = ""
    notice_period_weeks: int = 4
    tagline: str = ""


class Profile(BaseModel):
    candidate: Candidate
    skills_must_have: list[str] = Field(default_factory=list)
    skills_nice_to_have: list[str] = Field(default_factory=list)
    target_socs: list[int] = Field(default_factory=list)
    salary_floor_gbp: int = 33_400
    salary_target_gbp: int = 38_290
    target_locations: list[str] = Field(default_factory=list)
    avoid_companies: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


@lru_cache(maxsize=1)
def get_profile(path: str | Path = "config/profile.yaml") -> Profile:
    text = Path(path).read_text(encoding="utf-8")
    return Profile.model_validate(yaml.safe_load(text))

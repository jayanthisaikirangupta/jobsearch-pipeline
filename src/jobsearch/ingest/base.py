"""Source contract.

A Source pulls jobs for one (search_term, location) tuple and returns a
DataFrame with these required columns:

    id, source, title, company, location, description, url, posted_at,
    min_amount, max_amount, currency, interval

Adding a new board: drop a file under `sources/`, expose `class Source(BaseSource)`,
register the key in `sources/__init__.py:REGISTRY`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


REQUIRED_COLUMNS = [
    "id",
    "source",
    "title",
    "company",
    "location",
    "description",
    "url",
    "posted_at",
    "min_amount",
    "max_amount",
    "currency",
    "interval",
]


@dataclass
class Query:
    label: str
    search_term: str
    location: str
    country_indeed: str = "UK"
    hours_old: int = 168
    results_wanted: int = 50
    description_format: str = "markdown"
    # Search radius in miles for JobSpy sources (Indeed/LinkedIn/Glassdoor).
    # JobSpy's default is 50mi which leaks London results into a Milton Keynes
    # search. Tightening to 10mi keeps the city-specific net.
    distance: int = 10
    # JobSpy is_remote filter. None = no filter (return all), True = only
    # remote, False = exclude remote. Default None preserves prior behaviour.
    is_remote: bool | None = None
    # Optional per-source location override. Glassdoor's location-resolver
    # 400s on country-only strings ("United Kingdom"); use a city instead.
    location_overrides: dict[str, str] = field(default_factory=dict)

    def location_for(self, source_key: str) -> str:
        return self.location_overrides.get(source_key, self.location)


class BaseSource(ABC):
    key: str = ""

    @abstractmethod
    def fetch(self, query: Query) -> pd.DataFrame:
        """Return a normalized DataFrame for this query."""

    @staticmethod
    def normalize(df: pd.DataFrame, source_key: str) -> pd.DataFrame:
        """Ensure the DataFrame has the required columns + types."""
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        df["source"] = source_key
        return df[REQUIRED_COLUMNS].copy()

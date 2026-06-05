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

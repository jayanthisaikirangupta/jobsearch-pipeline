"""Source registry. Add new boards by importing + registering here."""
from __future__ import annotations

from ..base import BaseSource
from .adzuna import Source as AdzunaSource
from .ats_greenhouse import Source as GreenhouseSource
from .ats_lever import Source as LeverSource
from .glassdoor import Source as GlassdoorSource
from .indeed import Source as IndeedSource
from .linkedin import Source as LinkedinSource


REGISTRY: dict[str, type[BaseSource]] = {
    "indeed": IndeedSource,
    "glassdoor": GlassdoorSource,
    "linkedin": LinkedinSource,
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "adzuna": AdzunaSource,
}


def get_source(key: str) -> BaseSource:
    if key not in REGISTRY:
        raise KeyError(f"Unknown source {key!r}. Registered: {list(REGISTRY)}")
    return REGISTRY[key]()

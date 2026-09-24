"""Source registry. Add new boards by importing + registering here."""
from __future__ import annotations

from ..base import BaseSource
from .adzuna import Source as AdzunaSource
from .ats_ashby import Source as AshbySource
from .ats_greenhouse import Source as GreenhouseSource
from .ats_lever import Source as LeverSource
from .ats_smartrecruiters import Source as SmartRecruitersSource
from .ats_workable import Source as WorkableSource
from .councils import Source as CouncilsSource
from .glassdoor import Source as GlassdoorSource
from .indeed import Source as IndeedSource
from .linkedin import Source as LinkedinSource


REGISTRY: dict[str, type[BaseSource]] = {
    "indeed": IndeedSource,
    "glassdoor": GlassdoorSource,
    "linkedin": LinkedinSource,
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "workable": WorkableSource,
    "smartrecruiters": SmartRecruitersSource,
    "adzuna": AdzunaSource,
    "councils": CouncilsSource,
}


def get_source(key: str) -> BaseSource:
    if key not in REGISTRY:
        raise KeyError(f"Unknown source {key!r}. Registered: {list(REGISTRY)}")
    return REGISTRY[key]()

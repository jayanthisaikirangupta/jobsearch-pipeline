"""Source registry. Add new boards by importing + registering here."""
from __future__ import annotations

from ..base import BaseSource
from .indeed import Source as IndeedSource
from .glassdoor import Source as GlassdoorSource
from .linkedin import Source as LinkedinSource


REGISTRY: dict[str, type[BaseSource]] = {
    "indeed": IndeedSource,
    "glassdoor": GlassdoorSource,
    "linkedin": LinkedinSource,
}


def get_source(key: str) -> BaseSource:
    if key not in REGISTRY:
        raise KeyError(f"Unknown source {key!r}. Registered: {list(REGISTRY)}")
    return REGISTRY[key]()

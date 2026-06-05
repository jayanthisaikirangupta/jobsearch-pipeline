"""LinkedIn source. Memory flagged this as risky during a visa-critical period
without a proxy — set JOBSPY_PROXY in .env before enabling at scale."""
from __future__ import annotations

import pandas as pd

from ..base import BaseSource, Query
from ._jobspy import fetch_via_jobspy


class Source(BaseSource):
    key = "linkedin"

    def fetch(self, query: Query) -> pd.DataFrame:
        df = fetch_via_jobspy("linkedin", query)
        return self.normalize(df, self.key)

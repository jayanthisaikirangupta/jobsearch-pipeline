from __future__ import annotations

import pandas as pd

from ..base import BaseSource, Query
from ._jobspy import fetch_via_jobspy


class Source(BaseSource):
    key = "indeed"

    def fetch(self, query: Query) -> pd.DataFrame:
        df = fetch_via_jobspy("indeed", query)
        return self.normalize(df, self.key)

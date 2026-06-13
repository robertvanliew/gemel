"""Parquet-backed read-through cache wrapping any DataAdapter.

Bars are bulk columnar data: they live as one parquet file per ticker in
data/cache/, NOT in SQLite (which stores decisions and results only).
"""
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core.data.base import DataAdapter


class CachedAdapter(DataAdapter):
    def __init__(self, source: DataAdapter, cache_dir: str | Path = "data/cache", max_age_days: int = 1):
        self.source = source
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = max_age_days

    def _path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}.parquet"

    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        path = self._path(ticker)
        if path.exists():
            cached = pd.read_parquet(path)
            fresh_enough = cached.index[-1] >= pd.Timestamp(datetime.now().date()) - timedelta(days=self.max_age_days)
            if fresh_enough and len(cached) >= lookback_days:
                return cached.tail(lookback_days)
        bars = self.source.get_daily_bars(ticker, lookback_days=lookback_days)
        bars.to_parquet(path)
        return bars

    def get_quote(self, ticker: str) -> float:
        return self.source.get_quote(ticker)

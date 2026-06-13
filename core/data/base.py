"""DataAdapter: the only seam in the system that touches the network.

Everything downstream consumes the normalized DataFrame schema returned here:
columns [open, high, low, close, volume], tz-naive DatetimeIndex, float prices.
"""
from abc import ABC, abstractmethod

import pandas as pd


class DataAdapter(ABC):
    @abstractmethod
    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        """Daily OHLCV, normalized schema, oldest row first."""

    @abstractmethod
    def get_quote(self, ticker: str) -> float:
        """Most recent price the source can provide (delayed is acceptable)."""


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Map any source frame with OHLCV-ish columns onto the canonical schema."""
    out = df.rename(columns={c: c.lower() for c in df.columns})
    out = out[["open", "high", "low", "close", "volume"]].astype(
        {"open": float, "high": float, "low": float, "close": float}
    )
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out.index = idx.normalize()
    return out.sort_index()

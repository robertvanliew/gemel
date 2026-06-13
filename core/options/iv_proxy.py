"""Implied-volatility proxy for free-data mode (spec 'path b').

Tickers with a free CBOE volatility index use it directly (VIX family);
everything else falls back to annualized realized volatility. IV rank
locates today's IV within its trailing 52-week range (the scanner's
IVR >= 25 gate).
"""
import numpy as np
import pandas as pd

_VOL_INDEX = {"SPY": "^VIX", "QQQ": "^VXN", "IWM": "^RVX"}

TRADING_DAYS = 252


def vol_index_symbol(ticker: str) -> str | None:
    """The matching volatility-index symbol, or None -> use realized_vol."""
    return _VOL_INDEX.get(ticker.upper())


def realized_vol(closes: pd.Series, window: int | None = None) -> float:
    """Annualized std-dev of daily log returns (optionally over a tail window)."""
    closes = pd.Series(closes)
    if window is not None:
        closes = closes.tail(window + 1)
    log_returns = np.log(closes / closes.shift(1)).dropna()
    if log_returns.empty:
        return 0.0
    return float(log_returns.std(ddof=1) * np.sqrt(TRADING_DAYS))


def iv_rank(year_of_iv: pd.Series, current: float) -> float:
    """Where `current` sits in the past year's IV range, 0..100."""
    lo, hi = float(year_of_iv.min()), float(year_of_iv.max())
    if hi == lo:
        return 50.0
    return max(0.0, min(100.0, (current - lo) / (hi - lo) * 100.0))

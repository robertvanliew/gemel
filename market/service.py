"""Market breadth across the 11 S&P sector ETFs (the standard sector-breadth
basket). Honest, computable breadth — NOT full-market internals. Consumes a
DataAdapter; pure aggregation otherwise.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.data.base import DataAdapter

SECTOR_ETFS: list[str] = [
    "XLB", "XLC", "XLE", "XLF", "XLI",
    "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
]

_MIN_BARS = 50  # need at least 50 bars to compute SMA50; fewer → skip entirely


def _pct(count: int, total: int) -> float:
    """Return percentage rounded to 1 dp; 0.0 when total == 0."""
    if total == 0:
        return 0.0
    return round(count / total * 100, 1)


def compute_breadth(
    adapter: "DataAdapter",
    symbols: list[str] = SECTOR_ETFS,
    lookback_days: int = 260,
) -> dict:
    """Compute sector breadth for *symbols* using *adapter*.

    Returns a dict with keys: as_of, n, advancing, declining, new_high,
    new_low, above_sma50, above_sma200, bull_pct, bear_pct.
    """
    advancing = 0
    declining = 0
    new_high = 0
    new_low = 0
    above_sma50 = 0
    above_sma50_of = 0   # denominator: symbols where SMA50 is computable
    above_sma200 = 0
    above_sma200_of = 0  # denominator: symbols where SMA200 is computable
    n = 0
    as_of: str | None = None

    for sym in symbols:
        try:
            bars = adapter.get_daily_bars(sym, lookback_days=lookback_days)
            close = bars["close"]

            if len(close) < _MIN_BARS:
                continue  # too few bars — skip entirely

            last = close.iloc[-1]
            prev = close.iloc[-2]

            # Advance / decline
            if last > prev:
                advancing += 1
            else:
                declining += 1

            # 52-week new high / low
            window = close.tail(252)
            if last >= window.max():
                new_high += 1
            if last <= window.min():
                new_low += 1

            # SMA50 (need ≥50 rows)
            sma50_val = close.rolling(50).mean().iloc[-1]
            if not (isinstance(sma50_val, float) and math.isnan(sma50_val)):
                above_sma50_of += 1
                if last > sma50_val:
                    above_sma50 += 1

            # SMA200 (need ≥200 rows)
            sma200_val = close.rolling(200).mean().iloc[-1]
            if not (isinstance(sma200_val, float) and math.isnan(sma200_val)):
                above_sma200_of += 1
                if last > sma200_val:
                    above_sma200 += 1

            # Track as_of from the first successful symbol
            if n == 0:
                as_of = str(close.index[-1].date())

            n += 1

        except Exception:
            # Any error → skip this symbol
            continue

    # --- Aggregation ---
    adv_pct = _pct(advancing, n)
    dec_pct = _pct(declining, n)
    nh_pct = _pct(new_high, n)
    nl_pct = _pct(new_low, n)
    sma50_pct = _pct(above_sma50, above_sma50_of)
    sma200_pct = _pct(above_sma200, above_sma200_of)

    if n == 0:
        bull_pct = 0.0
        bear_pct = 0.0
    else:
        bull_pct = round((adv_pct + sma50_pct + sma200_pct) / 3, 1)
        bear_pct = round(100.0 - bull_pct, 1)

    return {
        "as_of": as_of,
        "n": n,
        "advancing":    {"count": advancing,   "pct": adv_pct},
        "declining":    {"count": declining,   "pct": dec_pct},
        "new_high":     {"count": new_high,    "pct": nh_pct},
        "new_low":      {"count": new_low,     "pct": nl_pct},
        "above_sma50":  {"count": above_sma50,  "pct": sma50_pct,  "of": above_sma50_of},
        "above_sma200": {"count": above_sma200, "pct": sma200_pct, "of": above_sma200_of},
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
    }

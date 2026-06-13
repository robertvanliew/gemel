"""Tests for market.service.compute_breadth — TDD-first.

Fake adapter is deterministic; zero network, zero trading/order imports.
"""
import math
import pandas as pd
import pytest

from core.data.base import DataAdapter
from market.service import SECTOR_ETFS, compute_breadth


# ---------------------------------------------------------------------------
# Fake adapter helpers
# ---------------------------------------------------------------------------

def _make_series(direction: str, n_bars: int = 260) -> pd.DataFrame:
    """Return an OHLCV DataFrame with a deterministic close series.

    direction='up'   -> strictly increasing 100..100+n-1 (last == max)
    direction='down' -> strictly decreasing 100+n-1..100 (last == min)
    direction='flat' -> constant 100 (last == prev, counts as declining)
    """
    idx = pd.bdate_range(end="2025-12-31", periods=n_bars)
    if direction == "up":
        close = [100.0 + i for i in range(n_bars)]
    elif direction == "down":
        close = [100.0 + (n_bars - 1 - i) for i in range(n_bars)]
    else:  # flat
        close = [100.0] * n_bars
    df = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1_000_000.0] * n_bars,
        },
        index=idx,
    )
    return df


class FakeAdapter(DataAdapter):
    """Maps symbol -> direction (or raises if direction=='error')."""

    def __init__(self, mapping: dict[str, str], short_symbols: list[str] | None = None):
        """
        mapping: {symbol: 'up'|'down'|'flat'|'error'}
        short_symbols: symbols to return only 20 bars for (simulating skipped)
        """
        self._mapping = mapping
        self._short = set(short_symbols or [])

    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        direction = self._mapping.get(ticker, "up")
        if direction == "error":
            raise RuntimeError(f"Simulated error for {ticker}")
        n = 20 if ticker in self._short else 260
        return _make_series(direction, n)

    def get_quote(self, ticker: str) -> float:
        return 100.0


def _all_up_adapter() -> FakeAdapter:
    return FakeAdapter({s: "up" for s in SECTOR_ETFS})


def _all_down_adapter() -> FakeAdapter:
    return FakeAdapter({s: "down" for s in SECTOR_ETFS})


# ---------------------------------------------------------------------------
# Test 1 — All-up basket
# ---------------------------------------------------------------------------

def test_all_up_basket():
    result = compute_breadth(_all_up_adapter(), symbols=SECTOR_ETFS)

    assert result["n"] == 11
    assert result["advancing"]["count"] == 11
    assert result["advancing"]["pct"] == 100.0
    assert result["declining"]["count"] == 0
    assert result["above_sma50"]["pct"] == 100.0
    assert result["above_sma50"]["of"] == 11
    assert result["above_sma200"]["pct"] == 100.0
    assert result["above_sma200"]["of"] == 11
    assert result["new_high"]["count"] == 11
    assert result["new_high"]["pct"] == 100.0
    assert result["new_low"]["count"] == 0
    assert result["bull_pct"] == 100.0
    assert result["bear_pct"] == 0.0
    assert result["as_of"] is not None


# ---------------------------------------------------------------------------
# Test 2 — All-down basket
# ---------------------------------------------------------------------------

def test_all_down_basket():
    result = compute_breadth(_all_down_adapter(), symbols=SECTOR_ETFS)

    assert result["n"] == 11
    assert result["advancing"]["count"] == 0
    assert result["advancing"]["pct"] == 0.0
    assert result["declining"]["count"] == 11
    assert result["above_sma50"]["pct"] == 0.0
    assert result["above_sma50"]["of"] == 11
    assert result["above_sma200"]["pct"] == 0.0
    assert result["above_sma200"]["of"] == 11
    assert result["new_low"]["count"] == 11
    assert result["new_low"]["pct"] == 100.0
    assert result["new_high"]["count"] == 0
    assert result["bull_pct"] == 0.0
    assert result["bear_pct"] == 100.0


# ---------------------------------------------------------------------------
# Test 3 — Mixed 6-up / 5-down
# ---------------------------------------------------------------------------

def test_mixed_basket():
    symbols = SECTOR_ETFS  # 11 total
    mapping = {s: "up" if i < 6 else "down" for i, s in enumerate(symbols)}
    adapter = FakeAdapter(mapping)
    result = compute_breadth(adapter, symbols=symbols)

    expected_adv_pct = round(6 / 11 * 100, 1)
    assert result["n"] == 11
    assert result["advancing"]["count"] == 6
    assert result["advancing"]["pct"] == expected_adv_pct
    assert result["declining"]["count"] == 5
    # bull + bear must be exactly 100.0
    assert result["bull_pct"] + result["bear_pct"] == 100.0


# ---------------------------------------------------------------------------
# Test 4 — Symbol with too-few bars is skipped
# ---------------------------------------------------------------------------

def test_short_symbol_is_skipped():
    """One symbol returns only 20 bars → skipped; n=10, not counted in SMA denominators."""
    short_sym = SECTOR_ETFS[0]  # e.g. "XLB"
    rest = SECTOR_ETFS[1:]
    mapping = {s: "up" for s in SECTOR_ETFS}
    adapter = FakeAdapter(mapping, short_symbols=[short_sym])

    result = compute_breadth(adapter, symbols=SECTOR_ETFS)

    assert result["n"] == 10
    # All evaluated symbols are up; SMA200 denominator must be 10 (short one excluded)
    assert result["above_sma200"]["of"] == 10
    assert result["above_sma50"]["of"] == 10


# ---------------------------------------------------------------------------
# Test 5 — n == 0 returns zeros and as_of None
# ---------------------------------------------------------------------------

def test_zero_symbols_evaluated():
    """All symbols raise → n=0, zeros everywhere, as_of None."""
    mapping = {s: "error" for s in SECTOR_ETFS}
    adapter = FakeAdapter(mapping)
    result = compute_breadth(adapter, symbols=SECTOR_ETFS)

    assert result["n"] == 0
    assert result["as_of"] is None
    assert result["advancing"]["count"] == 0
    assert result["advancing"]["pct"] == 0.0
    assert result["declining"]["count"] == 0
    assert result["above_sma50"]["count"] == 0
    assert result["above_sma50"]["pct"] == 0.0
    assert result["above_sma50"]["of"] == 0
    assert result["above_sma200"]["count"] == 0
    assert result["above_sma200"]["pct"] == 0.0
    assert result["above_sma200"]["of"] == 0
    assert result["new_high"]["count"] == 0
    assert result["new_low"]["count"] == 0
    assert result["bull_pct"] == 0.0
    assert result["bear_pct"] == 0.0


# ---------------------------------------------------------------------------
# Test 6 — pct values are valid floats; bull + bear == 100.0
# ---------------------------------------------------------------------------

def test_pct_ranges_and_bull_bear_sum_to_100():
    symbols = SECTOR_ETFS
    mapping = {s: "up" if i < 6 else "down" for i, s in enumerate(symbols)}
    adapter = FakeAdapter(mapping)
    result = compute_breadth(adapter, symbols=symbols)

    for key in ("advancing", "declining", "new_high", "new_low"):
        pct = result[key]["pct"]
        assert isinstance(pct, float), f"{key}.pct is not float"
        assert 0.0 <= pct <= 100.0, f"{key}.pct out of range: {pct}"

    for key in ("above_sma50", "above_sma200"):
        pct = result[key]["pct"]
        assert isinstance(pct, float), f"{key}.pct is not float"
        assert 0.0 <= pct <= 100.0, f"{key}.pct out of range: {pct}"

    assert isinstance(result["bull_pct"], float)
    assert isinstance(result["bear_pct"], float)
    assert result["bull_pct"] + result["bear_pct"] == 100.0

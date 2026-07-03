"""Tests for scanner.momentum — Momentum Leaders ranking + LEAP affordability."""

import datetime

import pandas as pd
import pytest

from core.data.base import DataAdapter
from scanner.momentum import (
    CHALLENGE_UNIVERSE,
    leap_estimate,
    momentum_leaders,
    roc,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _series(n: int, start_price: float, daily: float) -> pd.Series:
    idx = pd.bdate_range(start=datetime.date(2024, 1, 2), periods=n)
    return pd.Series([start_price * (1 + daily) ** i for i in range(n)],
                     index=idx, dtype=float)


def _ohlcv(closes: pd.Series) -> pd.DataFrame:
    c = closes.values
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99,
                         "close": c, "volume": [1e6] * len(c)}, index=closes.index)


class FakeAdapter(DataAdapter):
    """HOT: strong uptrend, full history. FLAT: no move. THIN: only 90 bars.
    BAD: raises (unfetchable)."""

    def __init__(self):
        self._data = {
            "HOT":  _ohlcv(_series(400, 100.0, 0.004)),   # big 1y momentum
            "FLAT": _ohlcv(_series(400, 100.0, 0.0)),     # 0% ROC
            "THIN": _ohlcv(_series(90, 50.0, 0.006)),     # < 252 bars
        }

    def get_daily_bars(self, ticker, lookback_days=365):
        if ticker not in self._data:
            raise ValueError(f"no data for {ticker}")
        return self._data[ticker]

    def get_quote(self, ticker):
        return float(self._data[ticker]["close"].iloc[-1])


@pytest.fixture
def report():
    return momentum_leaders(FakeAdapter(), ["FLAT", "HOT", "THIN", "BAD"],
                            account_size=35_000.0)


# ── roc ──────────────────────────────────────────────────────────────────────

def test_roc_basic():
    closes = _series(300, 100.0, 0.0)
    closes.iloc[-1] = 110.0
    assert roc(closes, 252) == pytest.approx(10.0)


def test_roc_insufficient_history_is_none():
    assert roc(_series(100, 100.0, 0.001), 252) is None


# ── leap_estimate ────────────────────────────────────────────────────────────

def test_leap_estimate_scales_with_spot():
    cheap = leap_estimate(50.0, 0.30)
    pricey = leap_estimate(500.0, 0.30)
    assert 0 < cheap < pricey
    assert pricey == pytest.approx(cheap * 10, rel=0.01)  # BS is linear in (s,k) scaling


def test_leap_estimate_degenerate_inputs():
    assert leap_estimate(0.0, 0.3) == 0.0
    assert leap_estimate(100.0, 0.0) == 0.0


# ── momentum_leaders ────────────────────────────────────────────────────────

def test_leaders_ranked_by_momentum(report):
    tickers = [r["ticker"] for r in report["leaders"]]
    # HOT (huge 252d ROC) must outrank FLAT (0%).
    assert tickers.index("HOT") < tickers.index("FLAT")
    ranks = [r["rank"] for r in report["leaders"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_unfetchable_ticker_skipped(report):
    assert all(r["ticker"] != "BAD" for r in report["leaders"])
    assert len(report["leaders"]) == 3


def test_thin_history_flagged(report):
    thin = next(r for r in report["leaders"] if r["ticker"] == "THIN")
    assert thin["thin_history"] is True
    assert thin["roc_252"] is None
    assert thin["roc_63"] is not None


def test_affordability_against_cap(report):
    assert report["cap_dollars"] == pytest.approx(700.0)
    for r in report["leaders"]:
        if r["leap_cost"] > 0:
            assert r["affordable"] == (r["leap_cost"] <= 700.0)


def test_flat_series_has_zero_roc(report):
    flat = next(r for r in report["leaders"] if r["ticker"] == "FLAT")
    assert flat["roc_252"] == pytest.approx(0.0)
    assert flat["roc_63"] == pytest.approx(0.0)


def test_default_universe_is_challenge_21():
    assert len(CHALLENGE_UNIVERSE) == 21
    assert "META" in CHALLENGE_UNIVERSE and "GLD" in CHALLENGE_UNIVERSE

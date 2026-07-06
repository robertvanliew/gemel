"""Tests for scanner.momentum — ROC ranking, model spread economics, flags."""

import datetime

import pandas as pd
import pytest

from core.data.base import DataAdapter
from scanner.momentum import (
    CHALLENGE_UNIVERSE,
    THEMES,
    model_spread,
    momentum_leaders,
    rank_row,
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
    MOON: ROC > 1000% (data-suspect). BAD: raises (unfetchable)."""

    def __init__(self):
        moon = _series(400, 10.0, 0.0)
        moon.iloc[-1] = 150.0  # +1400% on the year
        self._data = {
            "HOT":  _ohlcv(_series(400, 100.0, 0.004)),
            "FLAT": _ohlcv(_series(400, 100.0, 0.0)),
            "THIN": _ohlcv(_series(90, 50.0, 0.006)),
            "MOON": _ohlcv(moon),
        }

    def get_daily_bars(self, ticker, lookback_days=365):
        if ticker not in self._data:
            raise ValueError(f"no data for {ticker}")
        return self._data[ticker]

    def get_quote(self, ticker):
        return float(self._data[ticker]["close"].iloc[-1])


@pytest.fixture
def report():
    return momentum_leaders(FakeAdapter(), ["FLAT", "HOT", "THIN", "BAD", "MOON"],
                            account_size=4_000.0, cap_pct=0.15)


# ── roc ──────────────────────────────────────────────────────────────────────

def test_roc_basic():
    closes = _series(300, 100.0, 0.0)
    closes.iloc[-1] = 110.0
    assert roc(closes, 252) == pytest.approx(10.0)


def test_roc_insufficient_history_is_none():
    assert roc(_series(100, 100.0, 0.001), 252) is None


# ── model_spread ─────────────────────────────────────────────────────────────

def test_model_spread_economics():
    sp = model_spread(100.0, 0.30)
    assert sp["long_strike"] == pytest.approx(105.0)
    assert sp["short_strike"] == pytest.approx(120.0)
    assert sp["max_value"] == pytest.approx(1500.0)         # 15 wide x 100
    assert 0 < sp["debit"] < sp["max_value"]                # debit spread sanity
    assert sp["max_profit"] == pytest.approx(sp["max_value"] - sp["debit"])


def test_model_spread_degenerate_inputs():
    assert model_spread(0.0, 0.3)["debit"] == 0.0
    assert model_spread(100.0, 0.0)["debit"] == 0.0


# ── momentum_leaders ────────────────────────────────────────────────────────

def test_leaders_ranked_by_momentum(report):
    tickers = [r["ticker"] for r in report["leaders"]]
    assert tickers.index("HOT") < tickers.index("FLAT")
    ranks = [r["rank"] for r in report["leaders"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_unfetchable_ticker_skipped(report):
    assert all(r["ticker"] != "BAD" for r in report["leaders"])
    assert len(report["leaders"]) == 4


def test_thin_history_flagged_data_suspect(report):
    thin = next(r for r in report["leaders"] if r["ticker"] == "THIN")
    assert thin["thin_history"] is True
    assert thin["roc_252"] is None
    assert thin["data_suspect"] is True   # < 300 trading days


def test_extreme_roc_flagged_data_suspect(report):
    moon = next(r for r in report["leaders"] if r["ticker"] == "MOON")
    assert moon["roc_252"] > 1000
    assert moon["data_suspect"] is True
    hot = next(r for r in report["leaders"] if r["ticker"] == "HOT")
    assert hot["data_suspect"] is False


def test_cap_is_momentum_playbook_cap(report):
    # $4k account x 15% = $600 per position — NOT the credit playbook's 2%.
    assert report["cap_dollars"] == pytest.approx(600.0)
    for r in report["leaders"]:
        if r["spread"]["debit"] > 0:
            assert r["fits_cap"] == (r["spread"]["debit"] <= 600.0)


def test_rank_row_theme_tags():
    closes = _series(400, 100.0, 0.001)
    row = rank_row("META", closes, cap_dollars=600.0)
    assert row["theme"] == "software"
    row2 = rank_row("ZZZZ", closes, cap_dollars=600.0)
    assert row2["theme"] == "untagged"


def test_default_universe_is_challenge_21_and_all_themed():
    assert len(CHALLENGE_UNIVERSE) == 21
    assert all(t in THEMES for t in CHALLENGE_UNIVERSE)

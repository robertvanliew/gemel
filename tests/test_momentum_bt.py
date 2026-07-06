"""Smoke tests for the momentum debit-spread backtest (backtester/momentum_bt.py)."""

import datetime

import pandas as pd
import pytest

from core.data.base import DataAdapter
from backtester.momentum_bt import run_momentum_backtest


def _series(n: int, start_price: float, daily: float) -> pd.Series:
    """Trend + deterministic wiggle — realized vol must be nonzero or the
    engine (correctly) refuses to price a spread."""
    import math
    idx = pd.bdate_range(start=datetime.date(2022, 1, 3), periods=n)
    price, out = start_price, []
    for i in range(n):
        price *= 1 + daily + 0.008 * math.sin(i * 1.7)
        out.append(price)
    return pd.Series(out, index=idx, dtype=float)


def _ohlcv(closes: pd.Series) -> pd.DataFrame:
    c = closes.values
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99,
                         "close": c, "volume": [1e6] * len(c)}, index=closes.index)


class FakeAdapter(DataAdapter):
    """Three names: UP trends hard (profit exits should fire), SIDE drifts,
    DOWN declines (should rank last and mostly stay unheld)."""

    def __init__(self):
        n = 1100
        self._data = {
            "UP":   _ohlcv(_series(n, 40.0, 0.003)),
            "SIDE": _ohlcv(_series(n, 45.0, 0.0002)),
            "DOWN": _ohlcv(_series(n, 60.0, -0.001)),
        }

    def get_daily_bars(self, ticker, lookback_days=365):
        return self._data[ticker]

    def get_quote(self, ticker):
        return float(self._data[ticker]["close"].iloc[-1])


@pytest.fixture(scope="module")
def result():
    return run_momentum_backtest(FakeAdapter(), ["UP", "SIDE", "DOWN"],
                                 account_size=4_000.0, top_n=2, years=2)


def test_runs_and_shapes(result):
    assert len(result["equity_curve"]) > 400          # ~2y of daily marks
    assert result["stats"]["n_trades"] > 0
    assert result["params"]["cap_dollars"] == pytest.approx(600.0)


def test_equity_starts_at_account_size(result):
    first = result["equity_curve"][0]["equity"]
    # first mark is after any day-1 entries: cash + marks ≈ account minus entry slippage
    assert 3_500 <= first <= 4_050


def test_exits_follow_the_rules(result):
    allowed = {"profit_75pct", "signal_rerank", "dte_45", "end_of_test"}
    assert set(result["exits_by_reason"]) <= allowed
    assert all(t["reason"] in allowed for t in result["trades"])


def test_uptrend_gets_traded(result):
    assert any(t["ticker"] == "UP" for t in result["trades"])


def test_limitations_always_shipped(result):
    assert any("Hindsight bias" in s for s in result["limitations"])
    assert any("slippage" in s for s in result["limitations"])


def test_bad_universe_raises():
    class EmptyAdapter(DataAdapter):
        def get_daily_bars(self, ticker, lookback_days=365):
            raise ValueError("no data")

        def get_quote(self, ticker):
            raise ValueError("no data")

    with pytest.raises(ValueError):
        run_momentum_backtest(EmptyAdapter(), ["X"], years=2)

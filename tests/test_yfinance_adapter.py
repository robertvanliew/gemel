import pandas as pd
import pytest

import core.data.yfinance_adapter as yfa
from core.data.yfinance_adapter import YFinanceAdapter


class _FakeTicker:
    """Stands in for yfinance.Ticker — tests never touch the network."""

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period=None, interval=None, auto_adjust=True):
        idx = pd.date_range("2026-01-05", periods=3, freq="B", tz="America/New_York")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.5, 101.5, 102.5],
                "Volume": [1_000, 1_100, 1_200],
                "Dividends": [0.0, 0.0, 0.0],     # yfinance includes extras; adapter must drop them
                "Stock Splits": [0.0, 0.0, 0.0],
            },
            index=idx,
        )


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(yfa.yf, "Ticker", _FakeTicker)
    return YFinanceAdapter()


def test_get_daily_bars_normalized_schema(adapter):
    bars = adapter.get_daily_bars("SPY", lookback_days=120)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert bars.index.tz is None  # normalized to tz-naive dates
    assert bars["close"].iloc[-1] == pytest.approx(102.5)


def test_get_quote_is_last_close(adapter):
    assert adapter.get_quote("SPY") == pytest.approx(102.5)

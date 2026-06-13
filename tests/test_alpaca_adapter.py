import pandas as pd
import pytest

from core.data.alpaca_adapter import AlpacaAdapter


class _FakeBarsResponse:
    @property
    def df(self):
        idx = pd.MultiIndex.from_product(
            [["SPY"], pd.date_range("2026-01-05", periods=3, freq="B", tz="UTC")],
            names=["symbol", "timestamp"],
        )
        return pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1_000, 1_100, 1_200],
                "trade_count": [10, 11, 12],    # alpaca extras; adapter must drop
                "vwap": [100.4, 101.4, 102.4],
            },
            index=idx,
        )


class _FakeClient:
    def __init__(self, *a, **kw):
        pass

    def get_stock_bars(self, request):
        return _FakeBarsResponse()


@pytest.fixture
def adapter(monkeypatch):
    import core.data.alpaca_adapter as aa
    monkeypatch.setattr(aa, "StockHistoricalDataClient", _FakeClient)
    return AlpacaAdapter(api_key="test-key", secret_key="test-secret")


def test_missing_keys_raise():
    with pytest.raises(ValueError, match="ALPACA_API_KEY"):
        AlpacaAdapter(api_key="", secret_key="")


def test_get_daily_bars_normalized_schema(adapter):
    bars = adapter.get_daily_bars("SPY", lookback_days=3)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert bars.index.tz is None
    assert bars["close"].iloc[-1] == pytest.approx(102.5)


def test_get_quote_is_last_close(adapter):
    assert adapter.get_quote("SPY") == pytest.approx(102.5)

import pytest

from core.data.cache import CachedAdapter
from core.data.factory import make_adapter
from core.data.yfinance_adapter import YFinanceAdapter


def test_default_is_cached_yfinance(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    adapter = make_adapter(cache_dir=tmp_path)
    assert isinstance(adapter, CachedAdapter)
    assert isinstance(adapter.source, YFinanceAdapter)


def test_alpaca_selected_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_SOURCE", "alpaca")
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")

    import core.data.alpaca_adapter as aa

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

    monkeypatch.setattr(aa, "StockHistoricalDataClient", _FakeClient)
    adapter = make_adapter(cache_dir=tmp_path)
    assert isinstance(adapter, CachedAdapter)
    assert isinstance(adapter.source, aa.AlpacaAdapter)


def test_unknown_source_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_SOURCE", "robinhood")
    with pytest.raises(ValueError, match="DATA_SOURCE"):
        make_adapter(cache_dir=tmp_path)

import pandas as pd

from core.data.base import DataAdapter
from core.data.cache import CachedAdapter


class _CountingAdapter(DataAdapter):
    """Fake source that counts fetches so tests can prove cache hits."""

    def __init__(self):
        self.fetches = 0

    def get_daily_bars(self, ticker, lookback_days=120):
        self.fetches += 1
        idx = pd.date_range("2026-01-05", periods=lookback_days, freq="B")
        return pd.DataFrame(
            {
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.5, "volume": 1_000,
            },
            index=idx,
        )

    def get_quote(self, ticker):
        return 100.5


def test_second_read_hits_cache(tmp_path):
    src = _CountingAdapter()
    cached = CachedAdapter(src, cache_dir=tmp_path, max_age_days=999)
    a = cached.get_daily_bars("SPY", lookback_days=30)
    b = cached.get_daily_bars("SPY", lookback_days=30)
    assert src.fetches == 1
    # check_freq=False: parquet round-trips drop the index freq attribute
    pd.testing.assert_frame_equal(a, b, check_freq=False)
    assert (tmp_path / "SPY.parquet").exists()


def test_stale_cache_refetches(tmp_path):
    src = _CountingAdapter()
    cached = CachedAdapter(src, cache_dir=tmp_path, max_age_days=0)  # everything is stale
    cached.get_daily_bars("SPY", lookback_days=30)
    cached.get_daily_bars("SPY", lookback_days=30)
    assert src.fetches == 2


def test_quote_passes_through(tmp_path):
    src = _CountingAdapter()
    cached = CachedAdapter(src, cache_dir=tmp_path)
    assert cached.get_quote("SPY") == 100.5

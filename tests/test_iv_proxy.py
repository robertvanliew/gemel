import numpy as np
import pandas as pd
import pytest

from core.options.iv_proxy import iv_rank, realized_vol, vol_index_symbol


def test_vol_index_mapping():
    assert vol_index_symbol("SPY") == "^VIX"
    assert vol_index_symbol("QQQ") == "^VXN"
    assert vol_index_symbol("IWM") == "^RVX"
    assert vol_index_symbol("GLD") is None  # no index -> realized-vol fallback


def test_realized_vol_constant_series_is_zero():
    closes = pd.Series(np.full(60, 100.0))
    assert realized_vol(closes) == pytest.approx(0.0)


def test_realized_vol_is_annualized_std_of_log_returns():
    closes = pd.Series([100.0, 101.0, 100.0, 101.0] * 20)
    lr = np.log(closes / closes.shift(1)).dropna()
    expected = float(lr.std(ddof=1) * np.sqrt(252))
    assert realized_vol(closes) == pytest.approx(expected)


def test_iv_rank_endpoints_and_midpoint():
    year = pd.Series(np.linspace(10.0, 30.0, 252))  # 52wk range 10..30
    assert iv_rank(year, current=10.0) == pytest.approx(0.0)
    assert iv_rank(year, current=30.0) == pytest.approx(100.0)
    assert iv_rank(year, current=20.0) == pytest.approx(50.0)

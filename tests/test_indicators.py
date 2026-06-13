import pandas as pd
import pytest

from core.indicators import ema


def test_ema_hand_computed_span3():
    # span=3 -> k = 2/(3+1) = 0.5
    # e0=1; e1 = 2*0.5 + 1*0.5 = 1.5; e2 = 3*0.5 + 1.5*0.5 = 2.25
    s = pd.Series([1.0, 2.0, 3.0])
    out = ema(s, 3)
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] == pytest.approx(1.5)
    assert out.iloc[2] == pytest.approx(2.25)


def test_ema_returns_series_same_index():
    s = pd.Series([10.0, 11.0, 12.0], index=pd.date_range("2026-01-01", periods=3))
    out = ema(s, 2)
    assert (out.index == s.index).all()


from core.indicators import rsi


def test_rsi_all_gains_is_100():
    s = pd.Series([float(x) for x in range(1, 40)])
    assert rsi(s, 14).iloc[-1] == pytest.approx(100.0)


def test_rsi_hand_computed_period2():
    # closes [10,11,10,11] -> deltas [NaN,1,-1,1]
    # Wilder smoothing alpha=1/2, adjust=False (NaN-seeded, recursion starts at index 1):
    #   gains  [NaN,1,0,1] -> NaN, 1, .5, .75 ; losses [NaN,0,1,0] -> NaN, 0, .5, .25
    # RS = .75/.25 = 3 -> RSI = 100 - 100/(1+3) = 75
    s = pd.Series([10.0, 11.0, 10.0, 11.0])
    assert rsi(s, 2).iloc[-1] == pytest.approx(75.0)


def test_rsi_bounded_0_100():
    s = pd.Series([100.0, 99.0, 101.0, 98.0, 102.0, 97.0, 103.0, 100.0] * 5)
    out = rsi(s, 14).dropna()
    assert ((out >= 0) & (out <= 100)).all()


import numpy as np

from core.indicators import detect_support


def _bars_with_double_bottom() -> pd.DataFrame:
    # price drifts 110 -> dips to ~100 (bar 10) -> recovers -> dips to ~100.5 (bar 25) -> ends 107
    lows = np.array(
        [110, 108, 106, 104, 103, 102, 101.5, 101, 100.5, 100.2,
         100.0, 100.8, 102, 103.5, 105, 106, 105.5, 104, 103, 102,
         101.5, 101.2, 100.9, 100.7, 100.6, 100.5, 101.5, 103, 105, 107],
        dtype=float,
    )
    return pd.DataFrame({"low": lows, "close": lows + 0.5})


def test_detect_support_finds_double_bottom_level():
    bars = _bars_with_double_bottom()
    level = detect_support(bars, lookback=30)
    assert level is not None
    assert 99.5 <= level <= 101.0  # the ~100 cluster


def test_detect_support_none_when_no_swing_lows():
    # strictly rising lows -> a single swing low at best, below min_touches
    bars = pd.DataFrame({"low": np.linspace(100, 130, 30), "close": np.linspace(100.5, 130.5, 30)})
    assert detect_support(bars, lookback=30) is None


def test_detect_support_empty_bars_returns_none():
    bars = pd.DataFrame({"low": [], "close": []})
    assert detect_support(bars, lookback=30) is None


def test_rsi_all_losses_is_0():
    s = pd.Series([float(x) for x in range(39, 0, -1)])
    assert rsi(s, 14).iloc[-1] == pytest.approx(0.0)

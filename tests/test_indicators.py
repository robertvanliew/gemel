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
    # closes [10,11,10,11] -> deltas [1,-1,1]
    # Wilder smoothing alpha=1/2, adjust=False:
    #   gains  [1,0,1] -> 1, .5, .75 ; losses [0,1,0] -> 0, .5, .25
    # RS = .75/.25 = 3 -> RSI = 100 - 100/(1+3) = 75
    s = pd.Series([10.0, 11.0, 10.0, 11.0])
    assert rsi(s, 2).iloc[-1] == pytest.approx(75.0)


def test_rsi_bounded_0_100():
    s = pd.Series([100.0, 99.0, 101.0, 98.0, 102.0, 97.0, 103.0, 100.0] * 5)
    out = rsi(s, 14).dropna()
    assert ((out >= 0) & (out <= 100)).all()

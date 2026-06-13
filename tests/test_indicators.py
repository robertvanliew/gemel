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

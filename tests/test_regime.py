import numpy as np
import pandas as pd

from core.regime import Regime, classify_regime


def _closes(values) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_rising_market_is_trending_up():
    closes = _closes(np.linspace(100, 150, 120))
    assert classify_regime(closes) == Regime.TRENDING_UP


def test_falling_market_is_declining():
    closes = _closes(np.linspace(150, 100, 120))
    assert classify_regime(closes) == Regime.DECLINING


def test_flat_market_is_choppy():
    base = np.full(120, 100.0)
    base[::2] += 0.5  # tiny alternation around a flat line
    assert classify_regime(_closes(base)) == Regime.CHOPPY

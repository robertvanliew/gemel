"""Market-regime classification: SPY (or any benchmark) vs its 50-day EMA + slope.

Used by the scanner's master gate / playbook and the backtester's
regime-segmented reporting (the 'bull-market trap' check).
"""
from enum import Enum

import pandas as pd

from core.indicators import ema


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    CHOPPY = "choppy"
    DECLINING = "declining"


def classify_regime(closes: pd.Series, slope_bars: int = 10, slope_tol: float = 0.005) -> Regime:
    """Classify using the last close vs the 50-EMA and the EMA's recent slope.

    - above the 50-EMA with the EMA rising  > slope_tol over slope_bars -> TRENDING_UP
    - below the 50-EMA with the EMA falling < -slope_tol               -> DECLINING
    - everything else                                                   -> CHOPPY
    """
    e50 = ema(closes, 50)
    last_close = float(closes.iloc[-1])
    ema_now = float(e50.iloc[-1])
    ema_then = float(e50.iloc[-1 - slope_bars])
    slope = ema_now / ema_then - 1.0

    if last_close > ema_now and slope > slope_tol:
        return Regime.TRENDING_UP
    if last_close < ema_now and slope < -slope_tol:
        return Regime.DECLINING
    return Regime.CHOPPY

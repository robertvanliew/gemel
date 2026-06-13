"""Pure technical-indicator functions. No look-ahead: every value at index i
is computed from data up to and including i."""
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (adjust=False -> recursive, no look-ahead)."""
    return series.ewm(span=span, adjust=False).mean()

"""Pure technical-indicator functions. No look-ahead: every value at index i
is computed from data up to and including i."""
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (adjust=False -> recursive, no look-ahead)."""
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index with Wilder's smoothing (ewm alpha=1/period)."""
    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # where avg_loss == 0 (pure uptrend) RSI is 100 by definition
    out = out.where(avg_loss != 0, 100.0)
    out.iloc[0] = float("nan")  # no delta on the first bar
    return out

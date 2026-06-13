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


def detect_support(
    bars: pd.DataFrame,
    lookback: int = 60,
    wing: int = 2,
    cluster_tol: float = 0.015,
    min_touches: int = 2,
) -> float | None:
    """Find the strongest support level below the current close.

    Method: swing lows (a low strictly lower than `wing` bars on each side)
    within the last `lookback` bars are clustered when within `cluster_tol`
    (fractional) of the cluster's lowest level. The cluster with the most
    touches (ties -> the higher level) wins, if it has >= min_touches and sits
    below the last close. Returns the cluster's mean level, or None.
    Note: the last `wing` bars can never qualify as swing lows (no right-side
    confirmation yet).
    """
    window = bars.tail(lookback)
    if len(window) == 0:
        return None
    lows = window["low"].to_numpy()
    last_close = float(window["close"].iloc[-1])

    swings: list[float] = []
    for i in range(wing, len(lows) - wing):
        left = lows[i - wing : i]
        right = lows[i + 1 : i + 1 + wing]
        if (lows[i] < left).all() and (lows[i] < right).all():
            swings.append(float(lows[i]))
    if not swings:
        return None

    swings.sort()
    clusters: list[list[float]] = [[swings[0]]]
    for level in swings[1:]:
        if level <= clusters[-1][0] * (1.0 + cluster_tol):
            clusters[-1].append(level)
        else:
            clusters.append([level])

    candidates = [
        (len(c), sum(c) / len(c))
        for c in clusters
        if len(c) >= min_touches and (sum(c) / len(c)) < last_close
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))  # most touches, then highest level
    return candidates[-1][1]

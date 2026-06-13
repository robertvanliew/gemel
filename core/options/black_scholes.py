"""Black-Scholes pricing for European options.

One pricing path feeds the scanner's candidate math, the backtester's leg
valuation, and the dashboard's T+0 curves / P&L matrix — keep it pure.
"""
import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(s: float, k: float, t: float, sigma: float, r: float) -> float:
    """Black-Scholes d1 term: (ln(s/k) + (r + sigma^2/2) t) / (sigma sqrt(t))."""
    return (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def _validate(s: float, k: float, sigma: float) -> None:
    if s <= 0 or k <= 0:
        raise ValueError("spot and strike must be positive")
    if sigma <= 0:
        raise ValueError("sigma must be positive")


def bs_call(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return max(s - k, 0.0)
    _validate(s, k, sigma)
    d1 = _d1(s, k, t, sigma, r)
    d2 = d1 - sigma * math.sqrt(t)
    return s * _norm_cdf(d1) - k * math.exp(-r * t) * _norm_cdf(d2)


def bs_put(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return max(k - s, 0.0)
    _validate(s, k, sigma)
    d1 = _d1(s, k, t, sigma, r)
    d2 = d1 - sigma * math.sqrt(t)
    return k * math.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def call_delta(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return 1.0 if s > k else 0.0
    _validate(s, k, sigma)
    return _norm_cdf(_d1(s, k, t, sigma, r))


def put_delta(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return -1.0 if s < k else 0.0
    _validate(s, k, sigma)
    return _norm_cdf(_d1(s, k, t, sigma, r)) - 1.0

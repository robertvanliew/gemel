"""Pre-trade risk math: max loss, return on risk, break-even, and the 2%
per-trade max-loss cap. Pure functions — live delta/IV-rank are layered on
by the web endpoint, not here. Read-only; Gemel never places an order.
"""

from __future__ import annotations


def spread_metrics(
    short_strike: float,
    long_strike: float,
    credit: float,
    qty: int = 1,
) -> dict:
    """Return a dict of risk metrics for a vertical credit spread.

    Parameters
    ----------
    short_strike : float
        Strike price of the short leg (higher strike for a bull-put spread).
    long_strike : float
        Strike price of the long leg (lower strike for a bull-put spread).
    credit : float
        Net credit received per share (positive, must be < width).
    qty : int
        Number of contracts (each contract = 100 shares).

    Returns
    -------
    dict with keys: width, credit, max_profit, max_loss, break_even,
    return_on_risk.
    """
    width = abs(short_strike - long_strike)
    if credit <= 0 or credit >= width:
        raise ValueError("credit must be positive and below the spread width")

    risk_per_share = width - credit
    return {
        "width": float(width),
        "credit": round(credit, 2),
        "max_profit": round(credit * 100 * qty, 2),
        "max_loss": round(risk_per_share * 100 * qty, 2),
        "break_even": round(short_strike - credit, 2),
        "return_on_risk": round(credit / risk_per_share, 4),
    }


def csp_max_loss(strike: float, credit: float, qty: int = 1) -> float:
    """Maximum loss for a cash-secured put.

    Loss = (strike - credit) * 100 * qty  (stock goes to zero).
    """
    return round((strike - credit) * 100 * qty, 2)


def long_option_max_loss(debit: float, qty: int = 1) -> float:
    """Maximum loss for a long option (call or put).

    Loss = abs(debit) * 100 * qty.
    Accepts negative debit values and uses their magnitude.
    """
    return round(abs(debit) * 100 * qty, 2)


def max_loss_for(
    strategy: str,
    *,
    short_strike: float | None = None,
    long_strike: float | None = None,
    credit_debit: float = 0.0,
    qty: int = 1,
) -> float:
    """Dispatch max-loss calculation by strategy name.

    Supported strategies
    --------------------
    "bull_put_spread"   – requires short_strike and long_strike
    "cash_secured_put"  – requires short_strike
    "long_option"       – uses abs(credit_debit)

    Raises ValueError for unknown strategies or missing required strikes.
    """
    if strategy == "bull_put_spread":
        if short_strike is None:
            raise ValueError("bull_put_spread requires short_strike")
        if long_strike is None:
            raise ValueError("bull_put_spread requires long_strike")
        return spread_metrics(short_strike, long_strike, credit_debit, qty)["max_loss"]

    if strategy == "cash_secured_put":
        if short_strike is None:
            raise ValueError("cash_secured_put requires short_strike")
        return csp_max_loss(short_strike, credit_debit, qty)

    if strategy == "long_option":
        return long_option_max_loss(credit_debit, qty)

    raise ValueError(f"Unknown strategy: {strategy!r}")


def cap_pct(max_loss: float, account_size: float) -> float:
    """Return max_loss as a percentage of account_size, rounded to 2 dp.

    Raises ValueError if account_size <= 0.
    """
    if account_size <= 0:
        raise ValueError("account_size must be positive")
    return round(max_loss / account_size * 100, 2)


def within_cap(max_loss: float, account_size: float, pct: float = 0.02) -> bool:
    """Return True iff max_loss does not exceed pct of account_size."""
    return max_loss <= pct * account_size

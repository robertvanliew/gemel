"""Real option-chain quotes + the liquidity gate (spec §3), via yfinance.

Momentum in the stock ≠ liquid options — especially 6-12 months out, where a
wide market can eat 15-20% of a small spread round-trip. The gate (both
required, measured on the model spread's two legs):
  • net bid/ask width ≤ 10% of mid
  • open interest ≥ 100 contracts on EACH leg
Fail either → the name still ranks, flagged "illiquid — watchlist only."

Everything here degrades gracefully: no chain, no matching expiry, or a dead
quote returns {"ok": False, "reason": ...} — callers show the reason instead
of fabricating numbers. OI is previous-close data intraday; that's accepted.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

MAX_SPREAD_WIDTH_PCT = 10.0   # net bid/ask width vs mid
MIN_OPEN_INTEREST = 100       # each leg
DTE_MIN, DTE_MAX = 150, 365   # the 6-12 month expiry window (spec §2/§6)


def _dte(expiry: str, today: date) -> int:
    return (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days


def pick_expiry(expirations: list[str], today: date | None = None) -> str | None:
    """Nearest listed expiry inside the 6-12 month window (None if none).

    yfinance lists monthlies (and some weeklies) — nearest-in-window matches
    the spec's 'nearest monthly expiry in the 6-12 month window'.
    """
    today = today or date.today()
    in_window = [e for e in expirations if DTE_MIN <= _dte(e, today) <= DTE_MAX]
    return min(in_window, key=lambda e: _dte(e, today)) if in_window else None


def snap_strike(strikes: list[float], target: float) -> float | None:
    """Nearest listed strike to the model target."""
    return min(strikes, key=lambda k: abs(k - target)) if strikes else None


def _leg(calls, strike: float) -> dict[str, Any] | None:
    row = calls[calls["strike"] == strike]
    if row.empty:
        return None
    r = row.iloc[0]
    bid = float(r.get("bid") or 0.0)
    ask = float(r.get("ask") or 0.0)
    oi = int(r.get("openInterest") or 0)
    if ask <= 0:
        return None  # dead quote — can't price
    return {"strike": strike, "bid": bid, "ask": ask, "mid": (bid + ask) / 2, "oi": oi}


def spread_quote(ticker: str, long_target: float, short_target: float,
                 today: date | None = None) -> dict[str, Any]:
    """Price the model call debit spread on real strikes + run the liquidity gate.

    Returns ok=False with a reason when the chain can't support the trade —
    that IS the answer (illiquid / no listed expiry), not an error to hide.
    """
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        expiry = pick_expiry(list(tk.options or []), today)
        if not expiry:
            return {"ok": False, "reason": f"no listed expiry {DTE_MIN}-{DTE_MAX} DTE"}
        calls = tk.option_chain(expiry).calls
        strikes = [float(k) for k in calls["strike"].tolist()]
        k_long = snap_strike(strikes, long_target)
        k_short = snap_strike([k for k in strikes if k_long is not None and k > k_long],
                              short_target)
        if k_long is None or k_short is None:
            return {"ok": False, "reason": "no usable strikes near targets"}
        leg_l, leg_s = _leg(calls, k_long), _leg(calls, k_short)
        if not leg_l or not leg_s:
            return {"ok": False, "reason": "dead quote on a leg (no ask)"}
    except Exception as ex:
        return {"ok": False, "reason": f"chain unavailable ({type(ex).__name__})"}

    # Net debit: pay ask-buy/bid-sell at worst (entry side), receive bid-buy/
    # ask-sell at worst (exit side); mid is the reference for the width gate.
    debit_mid = leg_l["mid"] - leg_s["mid"]
    debit_ask = leg_l["ask"] - leg_s["bid"]   # pessimistic entry fill
    credit_bid = leg_l["bid"] - leg_s["ask"]  # pessimistic exit fill
    if debit_mid <= 0:
        return {"ok": False, "reason": "spread mid is non-positive (stale quotes)"}
    width_pct = (debit_ask - credit_bid) / debit_mid * 100.0
    min_oi = min(leg_l["oi"], leg_s["oi"])
    liquid = width_pct <= MAX_SPREAD_WIDTH_PCT and min_oi >= MIN_OPEN_INTEREST
    max_value = (k_short - k_long) * 100.0
    return {
        "ok": True,
        "expiry": expiry,
        "dte": _dte(expiry, today or date.today()),
        "long_strike": k_long, "short_strike": k_short,
        "debit_mid": round(debit_mid * 100, 0),      # $ per spread
        "debit_ask": round(debit_ask * 100, 0),      # $ entry fill (paper book uses this)
        "exit_bid": round(max(credit_bid, 0) * 100, 0),
        "max_value": round(max_value, 0),
        "max_profit_mid": round(max_value - debit_mid * 100, 0),
        "spread_width_pct": round(width_pct, 1),
        "min_oi": min_oi,
        "liquid": liquid,
        "liquidity_detail": (f"net width {width_pct:.0f}% of mid "
                             f"({'≤' if width_pct <= MAX_SPREAD_WIDTH_PCT else '>'}10%) · "
                             f"min leg OI {min_oi} "
                             f"({'≥' if min_oi >= MIN_OPEN_INTEREST else '<'}100)"),
    }


def mark_spread(ticker: str, long_strike: float, short_strike: float,
                expiry: str) -> dict[str, Any]:
    """Current value of an OPEN spread at bid-side mid-ish marks (exit side).

    Used by the paper book's live marks. Conservative: value = what closing
    now would actually fetch (sell long at bid, buy short back at ask).
    """
    try:
        import yfinance as yf
        calls = yf.Ticker(ticker).option_chain(expiry).calls
        leg_l, leg_s = _leg(calls, long_strike), _leg(calls, short_strike)
        if not leg_l or not leg_s:
            return {"ok": False, "reason": "leg quote unavailable"}
        value_bid = max(leg_l["bid"] - leg_s["ask"], 0.0)
        value_mid = max(leg_l["mid"] - leg_s["mid"], 0.0)
        return {"ok": True, "value_bid": round(value_bid * 100, 0),
                "value_mid": round(value_mid * 100, 0)}
    except Exception as ex:
        return {"ok": False, "reason": f"chain unavailable ({type(ex).__name__})"}

"""Real option-chain quotes + the liquidity gate (spec §3), via yfinance.

Momentum in the stock ≠ liquid options — especially 6-12 months out, where a
wide market can eat 15-20% of a small spread round-trip. The gate (both
required, measured on the chosen spread's two legs):
  • net bid/ask width ≤ 10% of mid
  • open interest ≥ 100 contracts on EACH leg
Fail either → the name still ranks, flagged "illiquid — watchlist only."

§8.1: the short leg is solved from the BUDGET on real strikes — the widest
spread whose ask-side debit fits ~$550 — not a fixed % of price.
§8.2: yfinance rate-limiting is handled here: ≥2.5s between chain fetches,
2 retries with exponential backoff, and a per-session cache so re-clicks
don't re-fetch. Failures stay fail-closed with the reason displayed.

OI is previous-close data intraday; that's accepted.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

MAX_SPREAD_WIDTH_PCT = 10.0   # net bid/ask width vs mid
MIN_OPEN_INTEREST = 100       # each leg
DTE_MIN, DTE_MAX = 150, 365   # the 6-12 month expiry window (spec §2/§6)
BUDGET = 550.0                # target ask-side debit (§8.1)

_THROTTLE_S = 2.5             # min gap between chain fetches (§8.2)
_CACHE_TTL_S = 600.0          # session cache: re-clicks don't re-fetch
_RETRIES = 2

_cache: dict[str, tuple[float, dict]] = {}
_last_fetch = 0.0


def _dte(expiry: str, today: date) -> int:
    return (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days


def pick_expiry(expirations: list[str], today: date | None = None) -> str | None:
    """Nearest listed expiry inside the 6-12 month window (None if none)."""
    today = today or date.today()
    in_window = [e for e in expirations if DTE_MIN <= _dte(e, today) <= DTE_MAX]
    return min(in_window, key=lambda e: _dte(e, today)) if in_window else None


def snap_strike(strikes: list[float], target: float) -> float | None:
    """Nearest listed strike to the model target."""
    return min(strikes, key=lambda k: abs(k - target)) if strikes else None


def budget_spread_from_legs(
    legs: list[dict[str, Any]],
    long_target: float,
    *,
    budget: float = BUDGET,
    cap: float | None = None,
) -> dict[str, Any]:
    """Pick the spread from real leg quotes (§8.1) — pure, unit-testable.

    `legs`: [{strike, bid, ask, oi, last?}, ...] for one expiry's calls, any
    order. Long leg = nearest strike to `long_target`; short leg = the HIGHEST
    strike whose ask-side net debit (long ask - short bid) still fits `budget`.
    Over cap only when even the narrowest width exceeds `cap`.

    After hours (Julie's session is Sunday) bid/ask come back 0 — legs fall
    back to the last trade, the quote is flagged `stale`, and the liquidity
    width check is skipped (OI, which is previous-close data anyway, still
    gates). Stale numbers are for planning; re-check at the open.
    """
    cap = cap if cap is not None else budget

    def eff(l, side):  # bid/ask, falling back to last trade when dark
        px = l[side]
        return px if px > 0 else (l.get("last") or 0.0)

    usable = sorted((l for l in legs if eff(l, "ask") > 0), key=lambda l: l["strike"])
    if len(usable) < 2:
        return {"ok": False, "reason": "not enough live strikes"}
    stale = any(l["ask"] <= 0 or l["bid"] <= 0 for l in usable)
    k_long = snap_strike([l["strike"] for l in usable], long_target)
    leg_l = next(l for l in usable if l["strike"] == k_long)
    above = [l for l in usable if l["strike"] > k_long]
    if not above:
        return {"ok": False, "reason": "no strikes above the long leg"}

    debit_ask = lambda s: eff(leg_l, "ask") - eff(s, "bid")   # pessimistic entry
    min_leg = above[0]
    if debit_ask(min_leg) * 100.0 > cap:
        return {"ok": False, "reason": "over cap — even the narrowest listed "
                f"width costs ${debit_ask(min_leg) * 100.0:,.0f} at the ask"}

    leg_s = min_leg
    for s in above[1:]:
        if debit_ask(s) * 100.0 > budget:
            break
        leg_s = s

    mid = lambda l: (eff(l, "bid") + eff(l, "ask")) / 2
    d_mid = mid(leg_l) - mid(leg_s)
    d_ask = debit_ask(leg_s)
    credit_bid = eff(leg_l, "bid") - eff(leg_s, "ask")        # pessimistic exit
    if d_mid <= 0:
        return {"ok": False, "reason": "spread mid is non-positive (stale quotes)"}
    min_oi = min(leg_l["oi"], leg_s["oi"])
    max_value = (leg_s["strike"] - leg_l["strike"]) * 100.0
    if stale:
        width_pct = None       # bid/ask dark — width unverifiable until the open
        liquid = min_oi >= MIN_OPEN_INTEREST
        detail = (f"market closed — priced at last trade; width check pending the open · "
                  f"min leg OI {min_oi} ({'≥' if liquid else '<'}100)")
    else:
        width_pct = round((d_ask - credit_bid) / d_mid * 100.0, 1)
        liquid = width_pct <= MAX_SPREAD_WIDTH_PCT and min_oi >= MIN_OPEN_INTEREST
        detail = (f"net width {width_pct:.0f}% of mid "
                  f"({'≤' if width_pct <= MAX_SPREAD_WIDTH_PCT else '>'}10%) · "
                  f"min leg OI {min_oi} "
                  f"({'≥' if min_oi >= MIN_OPEN_INTEREST else '<'}100)")
    return {
        "ok": True,
        "stale": stale,
        "long_strike": leg_l["strike"], "short_strike": leg_s["strike"],
        "width": round(leg_s["strike"] - leg_l["strike"], 2),
        "debit_mid": round(d_mid * 100, 0),
        "debit_ask": round(d_ask * 100, 0),
        "exit_bid": round(max(credit_bid, 0) * 100, 0),
        "max_value": round(max_value, 0),
        "max_profit_mid": round(max_value - d_mid * 100, 0),
        "spread_width_pct": width_pct,
        "min_oi": min_oi,
        "liquid": liquid,
        "liquidity_detail": detail,
    }


def _throttled_chain(ticker: str, today: date | None):
    """Fetch (expiry, calls-legs) with throttle + retry/backoff (§8.2)."""
    global _last_fetch
    import yfinance as yf
    last_err: Exception | None = None
    for attempt in range(_RETRIES + 1):
        wait = _THROTTLE_S - (time.monotonic() - _last_fetch)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_fetch = time.monotonic()
            tk = yf.Ticker(ticker)
            expiry = pick_expiry(list(tk.options or []), today)
            if not expiry:
                return None, None, f"no listed expiry {DTE_MIN}-{DTE_MAX} DTE"
            calls = tk.option_chain(expiry).calls
            legs = [{"strike": float(r["strike"]), "bid": float(r.get("bid") or 0.0),
                     "ask": float(r.get("ask") or 0.0), "oi": int(r.get("openInterest") or 0),
                     "last": float(r.get("lastPrice") or 0.0)}
                    for _, r in calls.iterrows()]
            return expiry, legs, None
        except Exception as ex:              # includes YFRateLimitError
            last_err = ex
            time.sleep(3 * (2 ** attempt))   # 3s, 6s, 12s backoff
    return None, None, f"chain unavailable after retries ({type(last_err).__name__})"


def spread_quote(ticker: str, long_target: float, short_target: float | None = None,
                 *, budget: float = BUDGET, cap: float | None = None,
                 today: date | None = None) -> dict[str, Any]:
    """Budget-solved spread on real strikes + the liquidity gate, cached per
    session. `short_target` is accepted for compatibility but the short leg is
    always solved from the budget (§8.1)."""
    key = f"{ticker}:{round(long_target, 1)}:{budget}:{cap}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return hit[1]
    expiry, legs, err = _throttled_chain(ticker, today)
    if err:
        out: dict[str, Any] = {"ok": False, "reason": err}
    else:
        out = budget_spread_from_legs(legs, long_target, budget=budget, cap=cap)
        if out.get("ok"):
            out["expiry"] = expiry
            out["dte"] = _dte(expiry, today or date.today())
    _cache[key] = (time.monotonic(), out)
    return out


def mark_spread(ticker: str, long_strike: float, short_strike: float,
                expiry: str) -> dict[str, Any]:
    """Current value of an OPEN spread at exit-side marks (sell long at bid,
    buy short back at ask) — what closing now would actually fetch. Cached
    briefly; throttled like every other chain call."""
    key = f"mark:{ticker}:{long_strike}:{short_strike}:{expiry}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < 120.0:   # marks stay fresher
        return hit[1]
    global _last_fetch
    try:
        import yfinance as yf
        wait = _THROTTLE_S - (time.monotonic() - _last_fetch)
        if wait > 0:
            time.sleep(wait)
        _last_fetch = time.monotonic()
        calls = yf.Ticker(ticker).option_chain(expiry).calls
        def leg(k):
            row = calls[calls["strike"] == k]
            if row.empty:
                return None
            r = row.iloc[0]
            return {"bid": float(r.get("bid") or 0.0), "ask": float(r.get("ask") or 0.0),
                    "last": float(r.get("lastPrice") or 0.0)}
        leg_l, leg_s = leg(long_strike), leg(short_strike)
        # After hours bid/ask are 0 — mark at the last trade instead (flagged stale).
        eff = lambda l, s: l[s] if l and l[s] > 0 else (l.get("last") if l else 0.0)
        if not leg_l or not leg_s or eff(leg_l, "ask") <= 0:
            out = {"ok": False, "reason": "leg quote unavailable"}
        else:
            stale = leg_l["bid"] <= 0 or leg_s["ask"] <= 0
            value_bid = max(eff(leg_l, "bid") - eff(leg_s, "ask"), 0.0)
            value_mid = max((eff(leg_l, "bid") + eff(leg_l, "ask")) / 2
                            - (eff(leg_s, "bid") + eff(leg_s, "ask")) / 2, 0.0)
            out = {"ok": True, "stale": stale,
                   "value_bid": round(value_bid * 100, 0),
                   "value_mid": round(value_mid * 100, 0)}
    except Exception as ex:
        out = {"ok": False, "reason": f"chain unavailable ({type(ex).__name__})"}
    _cache[key] = (time.monotonic(), out)
    return out

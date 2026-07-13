"""Option-spread quotes + the liquidity gate (spec §3), read from the
disk-backed chain store (§8.5 rework — scanner/chain_store.py).

Chains touch the network in exactly ONE place: the monthly refresh job in
chain_store. This module only READS saved files, so quoting a spread is
instant and can never be rate-limited. A missing chain returns "no saved
chain — run the monthly chain refresh first" — an actionable message, never
a verdict about the name (§8.7).

The liquidity gate (both required, measured on the chosen spread's two legs):
  • net bid/ask width ≤ 10% of mid
  • open interest ≥ 100 contracts on EACH leg
Fail either → the name still ranks, flagged "illiquid — watchlist only."

§8.1: the short leg is solved from the BUDGET on real strikes — the widest
spread whose ask-side debit fits ~$550 — not a fixed % of price.

OI is previous-close data intraday; that's accepted.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

MAX_SPREAD_WIDTH_PCT = 10.0   # net bid/ask width vs mid
MIN_OPEN_INTEREST = 100       # each leg
DTE_MIN, DTE_MAX = 150, 365   # the 6-12 month expiry window (spec §2/§6)
BUDGET = 550.0                # target ask-side debit (§8.1)


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
    short_ceiling: float | None = None,
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

    # §8.4: widen only while the debit fits AND the short strike stays under
    # the moneyness ceiling — no lottery structures on cheap stocks.
    leg_s = min_leg
    for s in above[1:]:
        if debit_ask(s) * 100.0 > budget:
            break
        if short_ceiling is not None and s["strike"] > short_ceiling:
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
    max_profit_mid = max_value - d_mid * 100
    return {
        "ok": True,
        "stale": stale,
        "long_strike": leg_l["strike"], "short_strike": leg_s["strike"],
        "width": round(leg_s["strike"] - leg_l["strike"], 2),
        # per-leg prices so any row is verifiable against a broker (§8.6)
        "long_ask": round(eff(leg_l, "ask"), 2),
        "short_bid": round(eff(leg_s, "bid"), 2),
        "debit_mid": round(d_mid * 100, 0),
        "debit_ask": round(d_ask * 100, 0),
        "exit_bid": round(max(credit_bid, 0) * 100, 0),
        "max_value": round(max_value, 0),
        "max_profit_mid": round(max_profit_mid, 0),
        # §8.4 sanity flag: payout > ~3× the debit means strikes drifted OTM
        "rr_outsized": bool(d_mid > 0 and max_profit_mid / (d_mid * 100) > 3.0),
        "spread_width_pct": width_pct,
        "min_oi": min_oi,
        "liquid": liquid,
        "liquidity_detail": detail,
    }


def _stored_legs(ticker: str, today: date | None):
    """(expiry, legs, err) from the SAVED chain — zero network (§8.5)."""
    from scanner import chain_store
    st = chain_store.StoredTicker(ticker)
    try:
        exps = st.options
    except ValueError as ex:
        return None, None, str(ex)
    expiry = pick_expiry(exps, today)
    if not expiry:
        return None, None, (f"no saved expiry {DTE_MIN}-{DTE_MAX} DTE — "
                            "run the chain refresh")
    calls = st.option_chain(expiry).calls
    legs = [{"strike": float(r["strike"]), "bid": float(r.get("bid") or 0.0),
             "ask": float(r.get("ask") or 0.0), "oi": int(r.get("openInterest") or 0),
             "last": float(r.get("lastPrice") or 0.0)}
            for _, r in calls.iterrows()]
    return expiry, legs, None


def spread_quote(ticker: str, long_target: float, short_target: float | None = None,
                 *, budget: float = BUDGET, cap: float | None = None,
                 spot: float | None = None, today: date | None = None) -> dict[str, Any]:
    """Budget-solved spread on real saved strikes + the liquidity gate.
    Reads the disk store only — instant, never rate-limited (§8.5).
    `short_target` is accepted for compatibility but the short leg is solved
    from the budget under the §8.4 moneyness ceiling (short ≤ ~20% above
    `spot` when given)."""
    expiry, legs, err = _stored_legs(ticker, today)
    if err:
        return {"ok": False, "reason": err}
    ceiling = spot * 1.20 if spot else None
    out = budget_spread_from_legs(legs, long_target, budget=budget, cap=cap,
                                  short_ceiling=ceiling)
    if out.get("ok"):
        out["expiry"] = expiry
        out["dte"] = _dte(expiry, today or date.today())
    return out


def mark_spread(ticker: str, long_strike: float, short_strike: float,
                expiry: str) -> dict[str, Any]:
    """Current value of an OPEN spread at exit-side marks (sell long at bid,
    buy short back at ask) — what closing now would actually fetch. Reads the
    saved chain: held expiries are always included in the refresh
    (must_include), and a mark is only as fresh as the last refresh — the UI
    labels it with the store's 'chains as of' stamp."""
    from scanner import chain_store
    try:
        st = chain_store.StoredTicker(ticker)
        calls = st.option_chain(expiry).calls
    except ValueError as ex:
        return {"ok": False, "reason": str(ex)}
    def leg(k):
        row = calls[calls["strike"] == k]
        if row.empty:
            return None
        r = row.iloc[0]
        return {"bid": float(r.get("bid") or 0.0), "ask": float(r.get("ask") or 0.0),
                "last": float(r.get("lastPrice") or 0.0)}
    leg_l, leg_s = leg(long_strike), leg(short_strike)
    # After-hours snapshots have bid/ask 0 — mark at the last trade (flagged stale).
    eff = lambda l, s: l[s] if l and l[s] > 0 else (l.get("last") if l else 0.0)
    if not leg_l or not leg_s or eff(leg_l, "ask") <= 0:
        return {"ok": False, "reason": "strikes not in the saved chain — re-run the refresh"}
    stale = leg_l["bid"] <= 0 or leg_s["ask"] <= 0
    value_bid = max(eff(leg_l, "bid") - eff(leg_s, "ask"), 0.0)
    value_mid = max((eff(leg_l, "bid") + eff(leg_l, "ask")) / 2
                    - (eff(leg_s, "bid") + eff(leg_s, "ask")) / 2, 0.0)
    return {"ok": True, "stale": stale,
            "value_bid": round(value_bid * 100, 0),
            "value_mid": round(value_mid * 100, 0)}

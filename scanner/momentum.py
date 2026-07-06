"""Momentum Leaders: rank a stock universe by trailing rate-of-change, with a
model CALL DEBIT SPREAD costed per name (the playbook's vehicle — defined risk,
sized for a small account — not naked LEAPs).

Borrowed from the public-portfolio-challenge playbook (rank by 252-day and
63-day ROC, buy the leaders) minus the parts that don't survive scrutiny:
rankings recompute on LIVE data instead of a hindsight-frozen list, every name
is costed against the momentum playbook's own per-position cap, and rows with
suspect data (ROC > 1,000%, thin listing history) are flagged for chart
verification rather than silently included.

Model spread (§8.1, corrected): buy ~5% OTM call, then solve the WIDTH from
the budget — the widest spread whose debit fits ~$550 — instead of a fixed
%-of-price width that scales with the stock and priced every big name out.
A name is "over cap" only when even the narrowest listed increment costs more
than the $600 cap: genuinely untradeable at this account size. Estimates are
Black-Scholes at mid — the liquidity gate (scanner/chains.py) prices the real
thing on real strikes.

Read-only — emits a report dict, never an order. A rank is not a recommendation.
"""
from __future__ import annotations

from typing import Any

from core.data.base import DataAdapter
from core.options.black_scholes import bs_call
from core.options.iv_proxy import realized_vol

# The episode-11 "frozen 21" from the challenge repo, kept as the default
# watchlist only — rankings always recompute on live data.
CHALLENGE_UNIVERSE: list[str] = [
    "ANET", "DUOL", "HOOD", "LLY", "GS", "META", "TSM",
    "AVGO", "XOM", "COP", "OSCR", "AMAT", "ADI", "DDOG",
    "OKTA", "NET", "APP", "GLD", "MU", "SNDK", "SPCX",
]

# Manual theme tags (spec v1) — enforce the max-2-per-theme rule. Unknown
# tickers (lookup box / custom lists) tag "untagged" and count as their own
# theme until edited.
THEMES: dict[str, str] = {
    "ANET": "AI hardware", "TSM": "AI hardware", "AVGO": "AI hardware",
    "AMAT": "AI hardware", "ADI": "AI hardware", "MU": "AI hardware",
    "SNDK": "AI hardware",
    "META": "software", "DDOG": "software", "OKTA": "software",
    "NET": "software", "APP": "software", "DUOL": "software",
    "HOOD": "financials", "GS": "financials",
    "LLY": "healthcare", "OSCR": "healthcare",
    "XOM": "energy", "COP": "energy",
    "GLD": "gold", "SPCX": "space",
}

_ROC_LONG = 252    # ~1 trading year — THE signal
_ROC_SHORT = 63    # ~1 quarter — leadership health check
_SPREAD_T = 0.75   # ~9 months, mid of the 6-12 month expiry window
LONG_OTM = 0.05    # buy ~5% OTM (the long leg anchor)
SHORT_OTM = 0.20   # legacy fixed-width (still used by the backtest module)
BUDGET = 550.0     # solve spread width from this target debit (§8.1)
RR_FLOOR = 1.5     # candidates gate: max profit ≥ 1.5× debit (pass/fail ONLY)
_MIN_HISTORY = 300      # fewer trading days -> "verify on chart" (IPO/spinoff/split)
_SUSPECT_ROC = 1000.0   # 1-yr ROC beyond this -> "verify on chart"


def roc(closes, periods: int) -> float | None:
    """Rate of change over the last `periods` bars, as a percent.

    None when there isn't enough history (thin listings — the challenge's own
    logs flag SNDK/OSCR/DUOL for exactly this).
    """
    if len(closes) <= periods:
        return None
    past = float(closes.iloc[-1 - periods])
    if past <= 0:
        return None
    return (float(closes.iloc[-1]) / past - 1.0) * 100.0


def strike_increment(spot: float) -> float:
    """Typical listed strike spacing 6-12 months out. A heuristic for the
    model estimate only — real chains (chains.py) use the actual strikes."""
    if spot < 50:
        return 2.5
    if spot < 200:
        return 5.0
    if spot < 500:
        return 10.0
    if spot < 1500:
        return 25.0
    return 50.0


def model_spread(spot: float, sigma: float, *, budget: float = BUDGET,
                 cap: float | None = None) -> dict[str, float | bool]:
    """Budget-solved model spread (§8.1 + §8.4): long leg ~5% OTM, width = the
    widest strike-increment multiple satisfying BOTH constraints —
      • BS debit fits `budget` (~$550), AND
      • short strike ≤ ~20% above spot (the moneyness ceiling — §8.4; without
        it cheap stocks got lottery structures like OSCR's 2×-spot short leg).

    `untradeable` is True only when even ONE increment of width costs more
    than `cap` — that name genuinely cannot be traded at this account size.
    `rr_outsized` flags max-profit > ~3× debit: an outsized payout means the
    strikes drifted too far OTM — verify before trusting. Strikes are
    estimates on heuristic increments; chains.py prices reality.
    """
    empty = {"long_strike": 0.0, "short_strike": 0.0, "width": 0.0, "debit": 0.0,
             "long_px": 0.0, "short_px": 0.0, "max_value": 0.0, "max_profit": 0.0,
             "untradeable": True, "rr_outsized": False}
    if spot <= 0 or sigma <= 0:
        return empty
    cap = cap if cap is not None else budget
    inc = strike_increment(spot)
    k_long = round(spot * (1 + LONG_OTM) / inc) * inc
    ceiling = spot * (1 + SHORT_OTM)          # §8.4 moneyness ceiling
    long_px = bs_call(spot, k_long, _SPREAD_T, sigma)

    def short_px_for(k_short: float) -> float:
        return bs_call(spot, k_short, _SPREAD_T, sigma)

    def debit_for(k_short: float) -> float:
        return (long_px - short_px_for(k_short)) * 100.0

    def result(k_short: float, untradeable: bool) -> dict[str, float | bool]:
        debit = debit_for(k_short)
        max_value = (k_short - k_long) * 100.0
        max_profit = max_value - debit
        return {
            "long_strike": round(k_long, 2),
            "short_strike": round(k_short, 2),
            "width": round(k_short - k_long, 2),
            "debit": round(debit, 0),
            "long_px": round(long_px, 2),
            "short_px": round(short_px_for(k_short), 2),
            "max_value": round(max_value, 0),
            "max_profit": round(max_profit, 0),
            "untradeable": untradeable,
            "rr_outsized": bool(debit > 0 and max_profit / debit > 3.0),
        }

    min_debit = debit_for(k_long + inc)
    if min_debit > cap:
        return result(k_long + inc, untradeable=True)

    # widen while BOTH constraints hold (debit grows with width)
    best = k_long + inc
    for n in range(2, 41):
        k = k_long + n * inc
        if k > ceiling or debit_for(k) > budget:
            break
        best = k
    return result(best, untradeable=False)


def rank_row(ticker: str, closes, *, cap_dollars: float) -> dict[str, Any] | None:
    """One table row: ROCs, model spread economics, flags. None if unusable."""
    if len(closes) < 2:
        return None
    spot = float(closes.iloc[-1])
    r252 = roc(closes, _ROC_LONG)
    r63 = roc(closes, _ROC_SHORT)
    sigma = realized_vol(closes, window=63)
    sp = model_spread(spot, sigma, budget=BUDGET, cap=cap_dollars)
    return {
        "ticker": ticker,
        "theme": THEMES.get(ticker, "untagged"),
        "spot": round(spot, 2),
        "roc_252": None if r252 is None else round(r252, 1),
        "roc_63": None if r63 is None else round(r63, 1),
        "thin_history": r252 is None,
        # §8.3: no 1-yr ROC = no signal — never a candidate, sinks in the sort.
        "no_signal": r252 is None,
        "data_suspect": (len(closes) < _MIN_HISTORY
                         or (r252 is not None and r252 > _SUSPECT_ROC)),
        "spread": sp,
        # §8.1: over cap only when even the minimum width doesn't fit —
        # genuinely untradeable at this account size.
        "fits_cap": not sp["untradeable"],
    }


def momentum_leaders(
    adapter: DataAdapter,
    universe: list[str] | None = None,
    *,
    account_size: float = 4_000.0,
    cap_pct: float = 0.15,
) -> dict[str, Any]:
    """Rank `universe` by momentum and cost the model spread per name.

    Sort key: 252-day ROC when available, else 63-day (thin history sinks to
    where its shorter record puts it, and is labelled as such).
    """
    universe = universe or CHALLENGE_UNIVERSE
    cap_dollars = account_size * cap_pct

    rows: list[dict[str, Any]] = []
    for ticker in universe:
        try:
            bars = adapter.get_daily_bars(ticker, lookback_days=420)
        except Exception:
            continue  # unfetchable name (delisted / rate-limited) — skip, don't fabricate
        row = rank_row(ticker, bars["close"], cap_dollars=cap_dollars)
        if row:
            rows.append(row)

    # §8.3: the signal is 1-yr ROC — rows without it sink to the BOTTOM
    # (3-mo ROC is a health check, not a substitute signal).
    rows.sort(key=lambda r: (r["roc_252"] is None,
                             -(r["roc_252"] if r["roc_252"] is not None else 0.0)))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    return {
        "account_size": account_size,
        "cap_pct": cap_pct,
        "cap_dollars": round(cap_dollars, 2),
        "leaders": rows,
    }

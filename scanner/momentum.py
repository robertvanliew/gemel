"""Momentum Leaders: rank a stock universe by trailing rate-of-change, with a
model CALL DEBIT SPREAD costed per name (the playbook's vehicle — defined risk,
sized for a small account — not naked LEAPs).

Borrowed from the public-portfolio-challenge playbook (rank by 252-day and
63-day ROC, buy the leaders) minus the parts that don't survive scrutiny:
rankings recompute on LIVE data instead of a hindsight-frozen list, every name
is costed against the momentum playbook's own per-position cap, and rows with
suspect data (ROC > 1,000%, thin listing history) are flagged for chart
verification rather than silently included.

Model spread: buy ~5% OTM call, sell ~20% OTM (a 15%-of-spot-wide spread),
~9 months out (mid of the 6-12 month window). Estimates are Black-Scholes at
mid — the liquidity gate (scanner/chains.py) prices the real thing.

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
LONG_OTM = 0.05    # buy ~5% OTM
SHORT_OTM = 0.20   # sell ~20% OTM
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


def model_spread(spot: float, sigma: float) -> dict[str, float]:
    """BS estimate of the model call debit spread on one contract, in dollars.

    Returns {long_strike, short_strike, debit, max_value, max_profit}. Strikes
    are the ideal targets — chains.py snaps them to real listed strikes.
    """
    if spot <= 0 or sigma <= 0:
        return {"long_strike": 0.0, "short_strike": 0.0, "debit": 0.0,
                "max_value": 0.0, "max_profit": 0.0}
    k_long = spot * (1 + LONG_OTM)
    k_short = spot * (1 + SHORT_OTM)
    debit = (bs_call(spot, k_long, _SPREAD_T, sigma)
             - bs_call(spot, k_short, _SPREAD_T, sigma)) * 100.0
    max_value = (k_short - k_long) * 100.0
    return {
        "long_strike": round(k_long, 2),
        "short_strike": round(k_short, 2),
        "debit": round(debit, 0),
        "max_value": round(max_value, 0),
        "max_profit": round(max_value - debit, 0),
    }


def rank_row(ticker: str, closes, *, cap_dollars: float) -> dict[str, Any] | None:
    """One table row: ROCs, model spread economics, flags. None if unusable."""
    if len(closes) < 2:
        return None
    spot = float(closes.iloc[-1])
    r252 = roc(closes, _ROC_LONG)
    r63 = roc(closes, _ROC_SHORT)
    sigma = realized_vol(closes, window=63)
    sp = model_spread(spot, sigma)
    return {
        "ticker": ticker,
        "theme": THEMES.get(ticker, "untagged"),
        "spot": round(spot, 2),
        "roc_252": None if r252 is None else round(r252, 1),
        "roc_63": None if r63 is None else round(r63, 1),
        "thin_history": r252 is None,
        "data_suspect": (len(closes) < _MIN_HISTORY
                         or (r252 is not None and r252 > _SUSPECT_ROC)),
        "spread": sp,
        # Spread max loss = the debit paid — judged against the MOMENTUM
        # playbook's per-position cap, not the credit playbook's 2%.
        "fits_cap": bool(0 < sp["debit"] <= cap_dollars),
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

    rows.sort(
        key=lambda r: r["roc_252"] if r["roc_252"] is not None
        else (r["roc_63"] if r["roc_63"] is not None else -1e9),
        reverse=True,
    )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    return {
        "account_size": account_size,
        "cap_pct": cap_pct,
        "cap_dollars": round(cap_dollars, 2),
        "leaders": rows,
    }

"""Momentum Leaders: rank a stock universe by trailing rate-of-change.

Borrowed from the public-portfolio-challenge playbook (rank leaders by 252-day
and 63-day ROC, buy LEAP calls on the strongest) — minus the parts that don't
survive scrutiny: the universe here re-ranks on LIVE data instead of a list
frozen in hindsight, and each name is checked against the account's 2% cap so
"leaders you can't actually afford" are visible instead of a trap.

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

_ROC_LONG = 252   # ~1 trading year
_ROC_SHORT = 63   # ~1 quarter
_LEAP_YEARS = 1.0  # ATM LEAP estimate horizon


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


def leap_estimate(spot: float, sigma: float) -> float:
    """Rough cost of one ATM ~1-year call contract (BS estimate, x100 shares).

    An estimate to gauge affordability, not a quote — real LEAP chains carry
    skew and spread this can't see.
    """
    if spot <= 0 or sigma <= 0:
        return 0.0
    return bs_call(spot, spot, _LEAP_YEARS, sigma) * 100.0


def momentum_leaders(
    adapter: DataAdapter,
    universe: list[str] | None = None,
    *,
    account_size: float = 35_000.0,
    cap_pct: float = 0.02,
) -> dict[str, Any]:
    """Rank `universe` by momentum and estimate LEAP affordability per name.

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
        closes = bars["close"]
        if len(closes) < 2:
            continue
        spot = float(closes.iloc[-1])
        r252 = roc(closes, _ROC_LONG)
        r63 = roc(closes, _ROC_SHORT)
        sigma = realized_vol(closes, window=63)
        leap = leap_estimate(spot, sigma)
        rows.append({
            "ticker": ticker,
            "spot": round(spot, 2),
            "roc_252": None if r252 is None else round(r252, 1),
            "roc_63": None if r63 is None else round(r63, 1),
            "thin_history": r252 is None,
            "leap_cost": round(leap, 0),
            # Long-call max loss is the full premium — judged against the same
            # 2% cap the flight check enforces.
            "affordable": bool(leap > 0 and leap <= cap_dollars),
        })

    rows.sort(
        key=lambda r: r["roc_252"] if r["roc_252"] is not None
        else (r["roc_63"] if r["roc_63"] is not None else -1e9),
        reverse=True,
    )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    return {
        "account_size": account_size,
        "cap_dollars": round(cap_dollars, 2),
        "leaders": rows,
    }

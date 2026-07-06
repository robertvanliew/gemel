"""Momentum call-debit-spread backtest (spec §6) — the playbook end-to-end:
monthly rank by 252-day ROC → hold the top N as ~9-month call debit spreads
(buy 5% OTM / sell 20% OTM) → profit exit at 75% of max value → signal exit
when a held name falls out of the ranking's top 10 → forced close under 45 DTE.

Pricing is Black-Scholes on daily closes with entry sigma held per position;
fills are modeled at mid ± SLIPPAGE_PCT each way (pay up on entry, give up on
exit) because historical option chains aren't available — the original
strategy's backtest used real bid/ask and it matters at these widths, so
treat absolute returns here with suspicion.

DISPLAYED LIMITATION (non-negotiable): any run on the default 21-name
watchlist inherits hindsight bias — the names were chosen knowing they
performed. Results are for tuning exits/sizing, never for projecting returns.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from backtester.engine import _stats
from core.data.base import DataAdapter
from core.options.black_scholes import bs_call
from core.options.iv_proxy import realized_vol
from momo.service import (
    CAP_PCT, DTE_WARN, MAX_POSITIONS, PROFIT_EXIT_PCT, SIGNAL_EXIT_RANK,
)
from scanner.momentum import CHALLENGE_UNIVERSE, LONG_OTM, SHORT_OTM

SLIPPAGE_PCT = 0.05      # each way, of spread value — stand-in for bid/ask
SPREAD_DAYS = 270        # ~9 months to expiry at entry
_ROC = 252


@dataclass
class _Position:
    ticker: str
    entry_date: datetime.date
    expiry: datetime.date
    k_long: float
    k_short: float
    sigma: float
    cost: float           # $ paid incl. slippage
    max_value: float


@dataclass
class _Closed:
    ticker: str
    entry_date: datetime.date
    exit_date: datetime.date
    exit_reason: str
    pnl: float
    # duck-typed extras for _stats
    in_sample: bool = True
    regime: str = ""


def _spread_value(spot: float, pos: _Position, on: datetime.date) -> float:
    t = max((pos.expiry - on).days, 0) / 365.0
    if t == 0:
        return (max(spot - pos.k_long, 0) - max(spot - pos.k_short, 0)) * 100.0
    return (bs_call(spot, pos.k_long, t, pos.sigma)
            - bs_call(spot, pos.k_short, t, pos.sigma)) * 100.0


def run_momentum_backtest(
    adapter: DataAdapter,
    universe: list[str] | None = None,
    *,
    account_size: float = 4_000.0,
    top_n: int = MAX_POSITIONS,
    years: int = 3,
    profit_exit_pct: float = PROFIT_EXIT_PCT,
    signal_exit_rank: int = SIGNAL_EXIT_RANK,
) -> dict[str, Any]:
    universe = universe or CHALLENGE_UNIVERSE
    cap = account_size * CAP_PCT

    # Aligned close matrix (outer join, ffill) — names listed mid-window join late.
    frames = {}
    for t in universe:
        try:
            frames[t] = adapter.get_daily_bars(t, lookback_days=years * 365 + 420)["close"]
        except Exception:
            continue
    if not frames:
        raise ValueError("no data for any universe name")
    closes = pd.DataFrame(frames).sort_index().ffill()
    sim_idx = closes.index[-(years * 252):]
    if len(sim_idx) < 60:
        raise ValueError("not enough history for the requested window")

    # first trading day of each month = re-rank day
    rerank_days = {d for i, d in enumerate(sim_idx)
                   if i == 0 or d.month != sim_idx[i - 1].month}

    cash = account_size
    open_pos: list[_Position] = []
    closed: list[_Closed] = []
    equity_dates: list[str] = []
    equity: list[float] = []
    traded_names: set[str] = set()

    def _close(pos: _Position, on: datetime.date, spot: float, reason: str) -> None:
        nonlocal cash
        value = _spread_value(spot, pos, on) * (1 - SLIPPAGE_PCT)
        cash += value
        closed.append(_Closed(pos.ticker, pos.entry_date, on, reason,
                              round(value - pos.cost, 2)))

    for ts in sim_idx:
        day = ts.date()
        row = closes.loc[ts]

        # ----- daily exit checks (profit / DTE) -----
        for pos in list(open_pos):
            spot = float(row.get(pos.ticker, float("nan")))
            if pd.isna(spot):
                continue
            value = _spread_value(spot, pos, day)
            if value >= pos.max_value * profit_exit_pct / 100.0:
                _close(pos, day, spot, "profit_75pct"); open_pos.remove(pos)
            elif (pos.expiry - day).days < DTE_WARN:
                _close(pos, day, spot, "dte_45"); open_pos.remove(pos)

        # ----- monthly re-rank: signal exits + entries -----
        if ts in rerank_days:
            hist = closes.loc[:ts]
            rocs: dict[str, float] = {}
            for t in closes.columns:
                s = hist[t].dropna()
                if len(s) > _ROC and float(s.iloc[-1 - _ROC]) > 0:
                    rocs[t] = float(s.iloc[-1]) / float(s.iloc[-1 - _ROC]) - 1.0
            ranking = sorted(rocs, key=rocs.get, reverse=True)
            rank_of = {t: i + 1 for i, t in enumerate(ranking)}

            for pos in list(open_pos):   # signal exit first — frees slots/cash
                if rank_of.get(pos.ticker, 999) > signal_exit_rank:
                    spot = float(row.get(pos.ticker, float("nan")))
                    if not pd.isna(spot):
                        _close(pos, day, spot, "signal_rerank"); open_pos.remove(pos)

            held = {p.ticker for p in open_pos}
            for t in ranking[:top_n]:
                if len(open_pos) >= top_n or t in held:
                    continue
                spot = float(row.get(t, float("nan")))
                s_hist = hist[t].dropna()
                if pd.isna(spot) or len(s_hist) < 64:
                    continue
                sigma = realized_vol(s_hist, window=63)
                if sigma <= 0:
                    continue
                k_long, k_short = spot * (1 + LONG_OTM), spot * (1 + SHORT_OTM)
                t_yrs = SPREAD_DAYS / 365.0
                debit = (bs_call(spot, k_long, t_yrs, sigma)
                         - bs_call(spot, k_short, t_yrs, sigma)) * 100.0
                cost = debit * (1 + SLIPPAGE_PCT)
                if cost <= 0 or cost > cap or cost > cash:
                    continue   # affordability is part of the strategy, not an error
                cash -= cost
                open_pos.append(_Position(t, day, day + datetime.timedelta(days=SPREAD_DAYS),
                                          k_long, k_short, sigma, round(cost, 2),
                                          (k_short - k_long) * 100.0))
                traded_names.add(t)

        # ----- mark equity -----
        marks = sum(_spread_value(float(row[p.ticker]), p, day)
                    for p in open_pos if not pd.isna(row.get(p.ticker, float("nan"))))
        equity_dates.append(day.isoformat())
        equity.append(round(cash + marks, 2))

    # close whatever's left at the final bar
    last_ts = sim_idx[-1]
    for pos in list(open_pos):
        spot = float(closes.loc[last_ts, pos.ticker])
        _close(pos, last_ts.date(), spot, "end_of_test")
    open_pos.clear()

    stats = _stats(closed)
    peak = pd.Series(equity).cummax()
    dd_pct = float(((pd.Series(equity) - peak) / peak).min() * 100) if equity else 0.0
    by_reason: dict[str, int] = {}
    for c in closed:
        by_reason[c.exit_reason] = by_reason.get(c.exit_reason, 0) + 1

    return {
        "params": {"universe_size": len(closes.columns), "top_n": top_n,
                   "account_size": account_size, "cap_dollars": round(cap, 2),
                   "years": years, "profit_exit_pct": profit_exit_pct,
                   "signal_exit_rank": signal_exit_rank,
                   "slippage_pct": SLIPPAGE_PCT * 100},
        "equity_curve": [{"date": d, "equity": e} for d, e in zip(equity_dates, equity)],
        "stats": {**stats, "final_equity": equity[-1] if equity else account_size,
                  "total_return_pct": round((equity[-1] / account_size - 1) * 100, 1) if equity else 0.0,
                  "max_drawdown_pct": round(dd_pct, 1),
                  "participation": f"{len(traded_names)}/{len(closes.columns)}"},
        "exits_by_reason": by_reason,
        "trades": [{"ticker": c.ticker, "entry": c.entry_date.isoformat(),
                    "exit": c.exit_date.isoformat(), "reason": c.exit_reason,
                    "pnl": c.pnl} for c in closed],
        "limitations": [
            "Hindsight bias: the default watchlist was assembled knowing these names performed. "
            "Use results to tune exits/sizing, never to project returns.",
            f"Fills are Black-Scholes mid ±{SLIPPAGE_PCT * 100:.0f}% slippage, entry sigma held per "
            "position — real 6-12 month chains are wider and skewed.",
        ],
    }

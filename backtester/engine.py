"""Options backtester engine.

Public API
----------
run_backtest(adapter, *, ticker, strategy, start, end, ...) -> dict
_stats(trades) -> dict   (exposed for unit-testing)

Supported strategies
--------------------
bull_put_spread   : short put + long put (short_k - width)
cash_secured_put  : short put only (long = None)
long_option       : raises ValueError (not implemented)

Walk-forward design
-------------------
* One position at a time; entries on the *close* of a flat day.
* Every decision on day i uses only data up to and including day i (no
  look-ahead).
* IV series: if vol_index_symbol(ticker) is not None, use vol-index close / 100
  aligned by date with forward-fill; else use rolling-20 realised vol of the
  ticker's own log returns.
* OOS split: the last oos_fraction of trading days is out-of-sample.
* Sensitivity: 2x3 grid over dte in [30, 45] and delta in [0.15, 0.20, 0.25].
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from core.options.black_scholes import bs_put, put_delta
from core.options.iv_proxy import vol_index_symbol, realized_vol
from core.regime import classify_regime

# ---------------------------------------------------------------------------
# Internal trade record
# ---------------------------------------------------------------------------

@dataclass
class _Trade:
    entry_date:  datetime.date
    exit_date:   datetime.date
    exit_reason: str
    pnl:         float
    regime:      str
    in_sample:   bool
    credit:      float   # per-share credit collected
    short_k:     float
    long_k:      Optional[float]


# ---------------------------------------------------------------------------
# Stats helper (exposed for unit-testing)
# ---------------------------------------------------------------------------

def _stats(trades: list) -> dict:
    """Compute performance statistics from a list of _Trade (or duck-typed) objects."""
    n = len(trades)
    if n == 0:
        return dict(n_trades=0, win_rate=0.0, avg_win=0.0, avg_loss=0.0,
                    profit_factor=0.0, max_drawdown=0.0)

    pnls = [t.pnl for t in trades]
    wins  = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / n * 100.0
    avg_win  = float(sum(wins)  / len(wins))  if wins   else 0.0
    avg_loss = float(sum(losses)/ len(losses)) if losses else 0.0

    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss == 0 and gross_win > 0:
        profit_factor = 999.0
    elif gross_loss == 0 and gross_win == 0:
        profit_factor = 0.0
    else:
        profit_factor = gross_win / gross_loss

    # max drawdown on cumulative pnl series
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd

    return dict(
        n_trades=n,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=float(profit_factor),
        max_drawdown=float(max_dd),
    )


def _pf_txt(pf: float) -> str:
    """Human profit-factor string; 999.0 is the 'no losing trades' sentinel."""
    return "∞" if pf >= 999.0 else f"{pf:.2f}"


def deploy_gate(
    is_stats: dict,
    oos_stats: dict,
    *,
    min_oos_pf: float = 1.3,
    max_degradation: float = 0.30,
    min_oos_trades: int = 20,
) -> dict:
    """A blunt GO / NO-GO verdict: would this playbook clear the bar to trade?

    Judged ONLY on the held-out out-of-sample slice, so it can't be curve-fit:
      1. enough out-of-sample trades to trust the number,
      2. out-of-sample profit factor clears the floor, and
      3. it didn't fall apart vs in-sample (degradation within tolerance).

    Read-only discipline — a pass means 'worth paper-trading', never advice to
    place an order.
    """
    oos_pf = oos_stats["profit_factor"]
    is_pf = is_stats["profit_factor"]
    oos_n = oos_stats["n_trades"]

    checks = [
        {
            "key": "sample",
            "label": f"Out-of-sample trades ≥ {min_oos_trades}",
            "value": str(oos_n),
            "passed": oos_n >= min_oos_trades,
        },
        {
            "key": "profit_factor",
            "label": f"Out-of-sample profit factor ≥ {min_oos_pf:.2f}",
            "value": _pf_txt(oos_pf),
            "passed": oos_pf >= min_oos_pf,
        },
    ]

    # Degradation: how much of the in-sample edge survived out of sample.
    if is_pf > 0 and is_pf < 999.0:
        ratio = oos_pf / is_pf
        drop = max(0.0, 1.0 - ratio)
        checks.append({
            "key": "degradation",
            "label": f"Degradation ≤ {int(max_degradation * 100)}% vs in-sample",
            "value": f"{drop * 100:.0f}% drop",
            "passed": ratio >= (1.0 - max_degradation),
        })
    else:
        # No usable in-sample profit factor to compare against — can't clear it.
        checks.append({
            "key": "degradation",
            "label": f"Degradation ≤ {int(max_degradation * 100)}% vs in-sample",
            "value": "n/a (no in-sample edge)",
            "passed": False,
        })

    cleared = all(c["passed"] for c in checks)
    if cleared:
        summary = ("CLEARED — the edge held up on data it never saw. "
                   "Paper-trade it first; a backtest is not a guarantee.")
    else:
        fails = ", ".join(c["label"].split(" ≥")[0].split(" ≤")[0].strip().lower()
                          for c in checks if not c["passed"])
        summary = f"NOT CLEARED — failed on: {fails}. Don't size into this yet."

    return {
        "cleared": cleared,
        "summary": summary,
        "checks": checks,
        "thresholds": {
            "min_oos_pf": min_oos_pf,
            "max_degradation": max_degradation,
            "min_oos_trades": min_oos_trades,
        },
    }


# ---------------------------------------------------------------------------
# IV series builder
# ---------------------------------------------------------------------------

def _build_iv_series(adapter, ticker: str, trading_idx: pd.DatetimeIndex) -> pd.Series:
    """Return a Series of sigma (fraction) aligned to trading_idx."""
    vol_sym = vol_index_symbol(ticker)
    if vol_sym is not None:
        vix_bars = adapter.get_daily_bars(vol_sym, lookback_days=4000)
        # sigma = VIX close / 100, aligned to ticker trading days
        vix_closes = vix_bars["close"]
        # reindex to trading_idx, forward-fill missing
        sigma_series = (vix_closes / 100.0).reindex(trading_idx, method="ffill")
        # any remaining NaN (leading gaps): back-fill then fallback 0.20
        sigma_series = sigma_series.bfill().fillna(0.20)
    else:
        ticker_bars = adapter.get_daily_bars(ticker, lookback_days=4000)
        closes = ticker_bars["close"]
        # rolling 20-day annualised realised vol
        log_ret = np.log(closes / closes.shift(1))
        rolling_vol = log_ret.rolling(20).std(ddof=1) * math.sqrt(252)
        sigma_series = rolling_vol.reindex(trading_idx, method="ffill").bfill().fillna(0.20)

    return sigma_series


# ---------------------------------------------------------------------------
# Strike finder
# ---------------------------------------------------------------------------

def _find_short_strike(spot: float, t: float, sigma: float,
                       target_delta: float) -> int:
    """Search integer strikes K < spot, return K closest to target_delta.

    target_delta is positive (e.g. 0.18); put_delta returns negative values,
    so we compare abs(put_delta(K)) to target_delta.
    Searches from floor(spot) down to floor(spot * 0.8).
    """
    best_k = int(math.floor(spot)) - 1
    best_diff = float("inf")
    low_bound = int(math.floor(spot * 0.8))
    for k in range(int(math.floor(spot)), low_bound, -1):
        if k <= 0:
            break
        delta = put_delta(spot, k, t, sigma)   # negative value in (-1, 0)
        diff = abs(abs(delta) - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_k = k
    return best_k


# ---------------------------------------------------------------------------
# Core walk-forward simulation (factored for sensitivity re-use)
# ---------------------------------------------------------------------------

def _simulate(
    trading_days: pd.DatetimeIndex,
    closes: pd.Series,
    sigma_series: pd.Series,
    oos_start: datetime.date,
    *,
    strategy: str,
    dte: int,
    width: float,
    target_delta: float,
    profit_target_pct: float,
    stop_mult: float,
    time_stop_dte: int,
    friction_per_contract: float,
) -> List[_Trade]:
    """Walk forward and return list of completed trades."""
    trades: List[_Trade] = []
    n = len(trading_days)
    i = 0  # current day index

    while i < n:
        day = trading_days[i].date()
        spot = float(closes.loc[trading_days[i]])
        sigma = float(sigma_series.loc[trading_days[i]])
        if sigma <= 0:
            sigma = 0.01  # floor

        T_entry = dte / 365.0

        # ── find strikes ──────────────────────────────────────────────────
        short_k = float(_find_short_strike(spot, T_entry, sigma, target_delta))
        if strategy == "bull_put_spread":
            long_k: Optional[float] = short_k - width
        elif strategy == "cash_secured_put":
            long_k = None
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # ── entry credit ─────────────────────────────────────────────────
        short_put_entry = bs_put(spot, short_k, T_entry, sigma)
        if long_k is not None:
            long_put_entry = bs_put(spot, long_k, T_entry, sigma)
            credit = short_put_entry - long_put_entry
        else:
            credit = short_put_entry

        if credit <= 0:
            i += 1
            continue

        # ── entry regime (no look-ahead: slice closes up to entry_date) ──
        # classify_regime needs at least 50+10=60 bars for its EMA+slope.
        # For early entries with fewer bars, default to "choppy".
        entry_closes = closes.loc[:trading_days[i]]
        if len(entry_closes) >= 61:
            regime = classify_regime(entry_closes).value
        else:
            regime = "choppy"

        in_sample = day < oos_start

        # ── hold loop ─────────────────────────────────────────────────────
        days_held = 0
        exit_reason = "expiry"
        exit_value = 0.0

        for j in range(i + 1, n):
            days_held = j - i
            hold_day = trading_days[j]
            spot_d = float(closes.loc[hold_day])
            sigma_d = float(sigma_series.loc[hold_day])
            if sigma_d <= 0:
                sigma_d = 0.01

            remaining_t = max((dte - days_held) / 365.0, 0.0)

            # current spread/put value
            short_put_now = bs_put(spot_d, short_k, remaining_t, sigma_d)
            if long_k is not None:
                long_put_now = bs_put(spot_d, long_k, remaining_t, sigma_d)
                V = short_put_now - long_put_now
            else:
                V = short_put_now

            # check exit conditions in priority order
            if V <= credit * (1.0 - profit_target_pct):
                exit_reason = "profit_target"
                exit_value = V
                i = j  # next entry starts the day after
                break
            elif V >= credit * stop_mult:
                exit_reason = "stop"
                exit_value = V
                i = j
                break
            elif days_held >= dte - time_stop_dte:
                exit_reason = "time_stop"
                exit_value = V
                i = j
                break
            elif days_held >= dte:
                # expiry: intrinsic value
                if long_k is not None:
                    intrinsic_short = max(short_k - spot_d, 0.0)
                    intrinsic_long  = max(long_k  - spot_d, 0.0)
                    exit_value = intrinsic_short - intrinsic_long
                else:
                    exit_value = max(short_k - spot_d, 0.0)
                exit_reason = "expiry"
                i = j
                break
        else:
            # reached end of data without exit — skip position (incomplete)
            i += 1
            continue

        pnl_per_share = credit - exit_value
        pnl = pnl_per_share * 100.0 * 1 - friction_per_contract

        trade = _Trade(
            entry_date=day,
            exit_date=trading_days[i].date(),
            exit_reason=exit_reason,
            pnl=pnl,
            regime=regime,
            in_sample=in_sample,
            credit=credit,
            short_k=short_k,
            long_k=long_k,
        )
        trades.append(trade)
        i += 1  # next entry on the day after exit

    return trades


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_backtest(
    adapter,
    *,
    ticker: str = "SPY",
    strategy: str = "bull_put_spread",
    start: datetime.date,
    end: datetime.date,
    dte: int = 38,
    width: float = 5.0,
    target_delta: float = 0.18,
    profit_target_pct: float = 0.50,
    stop_mult: float = 2.0,
    time_stop_dte: int = 21,
    friction_per_contract: float = 2.0,
    oos_fraction: float = 0.30,
) -> dict:
    """Run a walk-forward backtest and return a result dict.

    Raises ValueError for unimplemented strategies.
    """
    if strategy == "long_option":
        raise ValueError("long_option backtest is not implemented yet")
    if strategy not in ("bull_put_spread", "cash_secured_put"):
        raise ValueError(f"Unknown strategy: {strategy!r}")

    # ── load data ─────────────────────────────────────────────────────────
    all_bars = adapter.get_daily_bars(ticker, lookback_days=4000)
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end)
    bars = all_bars.loc[start_ts:end_ts]

    if bars.empty:
        raise ValueError(f"No bars for {ticker} in [{start}, {end}]")

    closes       = bars["close"]
    trading_days = bars.index  # DatetimeIndex of trading days in window

    # ── build IV series ───────────────────────────────────────────────────
    sigma_series = _build_iv_series(adapter, ticker, trading_days)

    # ── OOS split ─────────────────────────────────────────────────────────
    n_days = len(trading_days)
    oos_idx  = int(math.floor(n_days * (1.0 - oos_fraction)))
    oos_idx  = max(1, min(oos_idx, n_days - 1))
    oos_start_date = trading_days[oos_idx].date()

    # ── main simulation ───────────────────────────────────────────────────
    all_trades = _simulate(
        trading_days, closes, sigma_series, oos_start_date,
        strategy=strategy,
        dte=dte,
        width=width,
        target_delta=target_delta,
        profit_target_pct=profit_target_pct,
        stop_mult=stop_mult,
        time_stop_dte=time_stop_dte,
        friction_per_contract=friction_per_contract,
    )

    # ── stats ─────────────────────────────────────────────────────────────
    is_trades  = [t for t in all_trades if t.in_sample]
    oos_trades = [t for t in all_trades if not t.in_sample]
    is_stats   = _stats(is_trades)
    oos_stats  = _stats(oos_trades)

    # ── regime breakdown ──────────────────────────────────────────────────
    regime_map: dict[str, list] = {}
    for t in all_trades:
        regime_map.setdefault(t.regime, []).append(t)

    regime_list = []
    for reg, reg_trades in regime_map.items():
        rs = _stats(reg_trades)
        regime_list.append({
            "regime":        reg,
            "trades":        rs["n_trades"],
            "win_rate":      rs["win_rate"],
            "avg_pnl":       float(sum(t.pnl for t in reg_trades) / len(reg_trades)),
            "profit_factor": rs["profit_factor"],
        })

    # ── equity curve ──────────────────────────────────────────────────────
    cum = 0.0
    equity_curve = []
    for t in all_trades:
        cum += t.pnl
        equity_curve.append({"date": t.exit_date.isoformat(), "equity": cum})

    # ── sensitivity grid ─────────────────────────────────────────────────
    sens_dte    = [30, 45]
    sens_delta  = [0.15, 0.20, 0.25]
    sens_pf: list[list[float]] = []

    for s_dte in sens_dte:
        row = []
        for s_delta in sens_delta:
            sens_trades = _simulate(
                trading_days, closes, sigma_series, oos_start_date,
                strategy=strategy,
                dte=s_dte,
                width=width,
                target_delta=s_delta,
                profit_target_pct=profit_target_pct,
                stop_mult=stop_mult,
                time_stop_dte=time_stop_dte,
                friction_per_contract=friction_per_contract,
            )
            row.append(float(_stats(sens_trades)["profit_factor"]))
        sens_pf.append(row)

    return {
        "ticker":   ticker,
        "strategy": strategy,
        "params": {
            "dte":               dte,
            "width":             width,
            "target_delta":      target_delta,
            "profit_target_pct": profit_target_pct,
            "stop_mult":         stop_mult,
            "time_stop_dte":     time_stop_dte,
        },
        "oos_start":      oos_start_date.isoformat(),
        "stats":          _stats(all_trades),
        "in_sample":      is_stats,
        "out_of_sample":  oos_stats,
        "deploy_gate":    deploy_gate(is_stats, oos_stats),
        "regime":         regime_list,
        "equity_curve":   equity_curve,
        "sensitivity": {
            "dte":   sens_dte,
            "delta": sens_delta,
            "pf":    sens_pf,
        },
    }

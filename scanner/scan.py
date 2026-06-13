"""Weekly ETF scanner: orchestrates the core engine into a screen + ranked
candidates. Read-only — emits a report dict, never an order.

Screen per ticker (mirrors the playbook):
  above_20ema, above_50ema : last close > EMA(20|50)
  rsi_ok                   : 40 <= RSI(14) <= 70
  ivr_ok                   : IV rank >= 25
  support_ok               : detect_support found a level below close
  event_ok                 : no FOMC/earnings in [today, today+dte] (ETFs: earnings None)
A ticker QUALIFIES when all six pass. Master gate: SPY close > SPY 50-EMA.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from core.calendar import has_event_risk
from core.data.base import DataAdapter
from core.indicators import detect_support, ema, rsi
from core.options.black_scholes import bs_put, put_delta
from core.options.iv_proxy import iv_rank, realized_vol, vol_index_symbol
from core.regime import classify_regime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNIVERSE: list[str] = ["SPY", "QQQ", "IWM", "GLD", "XLK", "XLV"]

RSI_LOW: float = 40.0
RSI_HIGH: float = 70.0
IVR_MIN: float = 25.0

_DEFAULT_DTE: int = 38
_DEFAULT_WIDTH: float = 5.0
_DEFAULT_TARGET_DELTA: float = 0.18


# ---------------------------------------------------------------------------
# Volatility / IVR helpers
# ---------------------------------------------------------------------------

def _vol_and_ivr(
    adapter: DataAdapter,
    ticker: str,
    etf_bars: pd.DataFrame,
) -> tuple[float, float]:
    """Return (sigma_fraction, ivr_0_to_100) for the given ticker.

    For tickers with a mapped vol-index (SPY/QQQ/IWM) fetch that index's
    daily closes; current vol in *points* (e.g. 18.0) becomes sigma/100.
    For others (GLD/XLK/XLV) build a rolling realized-vol series over the
    ETF's own price history and derive both sigma and IVR from it.
    """
    vi = vol_index_symbol(ticker)
    if vi is not None:
        # -- vol-index branch --
        vi_bars = adapter.get_daily_bars(vi, lookback_days=300)
        vi_close = vi_bars["close"]
        current_pts = float(vi_close.iloc[-1])          # e.g. 18.5 (points)
        year_series = vi_close.tail(252)                 # trailing ~252 sessions
        ivr = iv_rank(year_series, current_pts)
        sigma = current_pts / 100.0
    else:
        # -- realized-vol branch --
        closes = etf_bars["close"]
        # Rolling annualized std-dev of log returns, window=20
        log_ret = np.log(closes / closes.shift(1))
        rolling_std = log_ret.rolling(window=20).std(ddof=1) * math.sqrt(252)
        rolling_pts = rolling_std * 100.0               # convert to points for ranking
        rolling_pts_clean = rolling_pts.dropna()
        year_pts = rolling_pts_clean.tail(252)
        sigma = float(rolling_std.iloc[-1]) if not rolling_std.iloc[-1:].isna().all() else 0.20
        current_pts = sigma * 100.0
        ivr = iv_rank(year_pts, current_pts) if not year_pts.empty else 50.0

    return sigma, ivr


# ---------------------------------------------------------------------------
# Candidate strike selection
# ---------------------------------------------------------------------------

def _find_candidate(
    spot: float,
    t: float,
    sigma: float,
    ivr: float,
    width: float = _DEFAULT_WIDTH,
    target_delta: float = _DEFAULT_TARGET_DELTA,
    dte: int = _DEFAULT_DTE,
) -> dict[str, Any]:
    """Search integer strikes below spot for the one closest to target_delta.

    Scans floor(spot) downward to floor(spot*0.80), exclusive of spot itself.
    Returns the candidate spread dict.
    """
    floor_spot = math.floor(spot)
    low_bound = math.floor(spot * 0.80)

    best_k: int | None = None
    best_diff = float("inf")

    for k in range(floor_spot, low_bound - 1, -1):
        if k >= spot:
            continue  # must be strictly below spot (OTM put)
        try:
            delta = put_delta(spot, float(k), t, sigma)
        except (ValueError, ZeroDivisionError):
            continue
        diff = abs(delta - (-target_delta))
        if diff < best_diff:
            best_diff = diff
            best_k = k

    if best_k is None:
        # Fallback: just below spot
        best_k = floor_spot if floor_spot < spot else floor_spot - 1

    short_strike = float(best_k)
    long_strike = short_strike - width

    credit = round(bs_put(spot, short_strike, t, sigma) - bs_put(spot, long_strike, t, sigma), 2)
    max_loss = round((width - credit) * 100.0, 2)
    break_even = round(short_strike - credit, 2)
    profit_target = round(credit * 0.5, 2)
    stop = round(credit * 2.0, 2)

    try:
        short_delta_val = round(put_delta(spot, short_strike, t, sigma), 3)
    except (ValueError, ZeroDivisionError):
        short_delta_val = 0.0

    return {
        "short_strike": short_strike,
        "long_strike": long_strike,
        "width": width,
        "credit": credit,
        "max_loss": max_loss,
        "break_even": break_even,
        "profit_target": profit_target,
        "stop": stop,
        "dte": dte,
        "short_delta": short_delta_val,
        "ivr": round(ivr, 1),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def screen_ticker(
    adapter: DataAdapter,
    ticker: str,
    today: date,
    dte: int = _DEFAULT_DTE,
    width: float = _DEFAULT_WIDTH,
    target_delta: float = _DEFAULT_TARGET_DELTA,
) -> dict[str, Any]:
    """Screen a single ticker through six criteria and, when it qualifies,
    construct a bull-put-spread candidate.

    Returns
    -------
    {
        "ticker":    str,
        "spot":      float,
        "rsi":       float,        # last RSI(14) value
        "ivr":       float,        # IV rank 0..100
        "support":   float | None, # detected support level
        "passes":    {above_20ema, above_50ema, rsi_ok, ivr_ok, support_ok, event_ok},
        "qualifies": bool,
        "candidate": dict | None,  # spread candidate if qualifies
    }
    """
    bars = adapter.get_daily_bars(ticker, lookback_days=300)
    closes = bars["close"]
    spot = float(closes.iloc[-1])

    # -- EMA criteria --
    try:
        e20 = ema(closes, 20)
        e50 = ema(closes, 50)
        above_20ema = bool(spot > float(e20.iloc[-1]))
        above_50ema = bool(spot > float(e50.iloc[-1]))
    except Exception:
        above_20ema = False
        above_50ema = False

    # -- RSI --
    try:
        rsi_series = rsi(closes, period=14)
        rsi_val = float(rsi_series.iloc[-1])
        if math.isnan(rsi_val):
            rsi_val = 50.0
        rsi_ok = bool(RSI_LOW <= rsi_val <= RSI_HIGH)
    except Exception:
        rsi_val = 50.0
        rsi_ok = False

    # -- Volatility / IVR --
    try:
        sigma, ivr_val = _vol_and_ivr(adapter, ticker, bars)
        ivr_ok = bool(ivr_val >= IVR_MIN)
    except Exception:
        sigma = 0.20
        ivr_val = 50.0
        ivr_ok = False

    # -- Support --
    try:
        support_level = detect_support(bars, lookback=60)
        support_ok = bool(support_level is not None and support_level < spot)
    except Exception:
        support_level = None
        support_ok = False

    # -- Event risk --
    try:
        expiry = today + timedelta(days=dte)
        event_risk = has_event_risk(today, expiry, None)
        event_ok = not event_risk
    except Exception:
        event_ok = False

    passes = {
        "above_20ema": above_20ema,
        "above_50ema": above_50ema,
        "rsi_ok": rsi_ok,
        "ivr_ok": ivr_ok,
        "support_ok": support_ok,
        "event_ok": event_ok,
    }
    qualifies = all(passes.values())

    # -- Candidate --
    candidate: dict[str, Any] | None = None
    if qualifies:
        t = dte / 365.0
        candidate = _find_candidate(spot, t, sigma, ivr_val, width, target_delta, dte)

    return {
        "ticker": ticker,
        "spot": spot,
        "rsi": rsi_val,
        "ivr": ivr_val,
        "support": support_level,
        "passes": passes,
        "qualifies": qualifies,
        "candidate": candidate,
    }


def run_scan(
    adapter: DataAdapter,
    today: date | None = None,
    universe: list[str] = UNIVERSE,
    dte: int = _DEFAULT_DTE,
) -> dict[str, Any]:
    """Run the full weekly scan across `universe`.

    Returns
    -------
    {
        "ran_at":           str (ISO date),
        "master_gate_pass": bool,
        "regime":           str ("trending_up" | "choppy" | "declining"),
        "playbook":         str,
        "results":          list[dict],   # screen_ticker dicts + "rank" key
    }

    Each result dict is the output of `screen_ticker` plus:
        "rank": int | None   — 1-based rank among qualifiers by credit/width desc;
                               None for non-qualifiers.
    """
    if today is None:
        today = date.today()

    # Master gate: SPY last close vs SPY 50-EMA
    spy_bars = adapter.get_daily_bars("SPY", lookback_days=300)
    spy_close = spy_bars["close"]
    spy_last = float(spy_close.iloc[-1])
    spy_e50 = ema(spy_close, 50)
    master_gate_pass = bool(spy_last > float(spy_e50.iloc[-1]))

    regime = classify_regime(spy_close).value

    playbook = (
        "bull put credit spreads"
        if master_gate_pass
        else "stand aside (bear call paper-only)"
    )

    # Screen all tickers
    results: list[dict[str, Any]] = []
    for ticker in universe:
        res = screen_ticker(adapter, ticker, today=today, dte=dte)
        res["rank"] = None  # default; set below for qualifiers
        results.append(res)

    # Rank qualifiers by credit-to-width ratio descending (highest credit/width first)
    qualifiers = [r for r in results if r["qualifies"]]
    qualifiers.sort(
        key=lambda r: (r["candidate"]["credit"] / r["candidate"]["width"]),
        reverse=True,
    )
    for i, r in enumerate(qualifiers, start=1):
        r["rank"] = i

    return {
        "ran_at": today.isoformat(),
        "master_gate_pass": master_gate_pass,
        "regime": regime,
        "playbook": playbook,
        "results": results,
    }

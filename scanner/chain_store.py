"""Disk-backed option-chain store (§8.5 rework).

The design rule: option chains touch the network in EXACTLY one place — the
deliberate monthly refresh job in this module. It fetches the top-ranked
names + every held ticker, one request every 5-10 seconds (jittered), retries
with exponential backoff (20s → 40s → 80s) instead of skipping, and writes
one JSON file per ticker to DATA_DIR/chains/ atomically (tmp + rename).

Everything else — candidates, paper-entry prefill, position marks — reads the
saved copy through `StoredTicker`, a drop-in for yf.Ticker with the same
`.options` / `.option_chain(expiry)` surface. Reads do zero network I/O and
can never be rate-limited. Per §8.7: a missing chain is "no saved chain — run
the monthly chain refresh first", never a verdict about the name.

Saved per ticker: third-Friday monthlies in the 150-400 DTE window (up to
CHAIN_MAX_EXPIRIES — covers the model's "nearest monthly in 6-12 months" pick
with slack on both sides) plus any `must_include` expiries (held positions'
exact expiries, so marks keep working as a position decays toward the 45-DTE
warning). Calls only, seven columns.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

DTE_MIN, DTE_MAX = 150, 400
_COLS = ["strike", "bid", "ask", "lastPrice", "openInterest", "volume",
         "impliedVolatility"]


def _delay_min() -> float: return float(os.getenv("CHAIN_FETCH_DELAY_MIN", "5"))
def _delay_max() -> float: return float(os.getenv("CHAIN_FETCH_DELAY_MAX", "10"))
def _retries() -> int: return int(os.getenv("CHAIN_FETCH_RETRIES", "3"))
def _backoff() -> float: return float(os.getenv("CHAIN_FETCH_BACKOFF", "20"))
def _max_expiries() -> int: return int(os.getenv("CHAIN_MAX_EXPIRIES", "5"))


def store_dir() -> Path:
    root = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent))
    d = root / "chains"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# expiry selection
# ---------------------------------------------------------------------------

def third_friday(year: int, month: int) -> date:
    first_wd = date(year, month, 1).weekday()          # Mon=0 … Fri=4
    first_friday = 1 + (4 - first_wd) % 7
    return date(year, month, first_friday + 14)


def monthly_expiries_in_window(expirations: list[str],
                               today: date | None = None,
                               max_n: int | None = None) -> list[str]:
    """Third-Friday monthlies inside the 150-400 DTE window, nearest first."""
    today = today or date.today()
    out = []
    for e in expirations:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d != third_friday(d.year, d.month):
            continue
        if DTE_MIN <= (d - today).days <= DTE_MAX:
            out.append(e)
    out.sort(key=lambda e: e)
    return out[: (max_n if max_n is not None else _max_expiries())]


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------

def _path(ticker: str) -> Path:
    return store_dir() / f"{ticker.upper()}.json"


def save_ticker_data(ticker: str, data: dict[str, Any]) -> None:
    """Atomic write — a crashed job never leaves a torn file."""
    p = _path(ticker)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(p)


def load(ticker: str) -> dict[str, Any] | None:
    p = _path(ticker)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def has(ticker: str) -> bool:
    return load(ticker) is not None


def expiries(ticker: str) -> list[str]:
    d = load(ticker)
    return sorted((d or {}).get("expiries", {}).keys())


def calls(ticker: str, expiry: str) -> pd.DataFrame | None:
    d = load(ticker)
    rows = (d or {}).get("expiries", {}).get(expiry)
    if rows is None:
        return None
    return pd.DataFrame(rows, columns=_COLS)


def summary() -> dict[str, Any]:
    """What's on disk: per-ticker fetched_at + oldest/newest — the UI prints
    'chains as of …' from this so stale data is labeled stale."""
    tickers: dict[str, str] = {}
    for p in store_dir().glob("*.json"):
        if p.name == "manifest.json":
            continue
        try:
            tickers[p.stem] = json.loads(p.read_text(encoding="utf-8"))["fetched_at"]
        except Exception:
            continue
    stamps = sorted(tickers.values())
    return {"count": len(tickers), "tickers": tickers,
            "oldest": stamps[0] if stamps else None,
            "newest": stamps[-1] if stamps else None}


class StoredTicker:
    """Drop-in for yf.Ticker backed by the saved files — same `.options` /
    `.option_chain(expiry)` surface, zero network."""

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self._data = load(self.symbol)

    @property
    def options(self) -> list[str]:
        if self._data is None:
            raise ValueError(f"no saved chain for {self.symbol} — run the "
                             "monthly chain refresh first")
        return sorted(self._data.get("expiries", {}).keys())

    def option_chain(self, expiry: str) -> SimpleNamespace:
        if self._data is None:
            raise ValueError(f"no saved chain for {self.symbol} — run the "
                             "monthly chain refresh first")
        rows = self._data.get("expiries", {}).get(expiry)
        if rows is None:
            raise ValueError(f"expiry {expiry} not in the saved chain for "
                             f"{self.symbol} — re-run the chain refresh")
        return SimpleNamespace(calls=pd.DataFrame(rows, columns=_COLS),
                               puts=pd.DataFrame(columns=_COLS))


# ---------------------------------------------------------------------------
# the ONE fetch site — a deliberate, poll-able background job
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_job: dict[str, Any] = {"state": "idle", "done": 0, "total": 0, "current": None,
                        "results": {}, "started_at": None, "finished_at": None}


def job_status() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_job))   # cheap deep copy


def _sleep_jitter() -> None:
    time.sleep(random.uniform(_delay_min(), max(_delay_min(), _delay_max())))


def _with_retries(fn):
    """Retry with exponential backoff INSTEAD of skipping — this is a monthly
    job; taking minutes is fine, a rate-limit skip is not."""
    last: Exception | None = None
    for attempt in range(_retries() + 1):
        try:
            return fn()
        except Exception as ex:
            last = ex
            if attempt < _retries():
                time.sleep(_backoff() * (2 ** attempt))   # 20s, 40s, 80s
    raise last  # type: ignore[misc]


def _f(v) -> float:
    """float(v) with NaN/None/garbage -> 0.0 (yfinance loves NaN cells,
    and NaN is truthy so `v or 0` does NOT catch it)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if f != f else f


def _i(v) -> int:
    return int(_f(v))


def _fetch_ticker(ticker: str, extra_expiries: list[str]) -> dict[str, Any]:
    import yfinance as yf
    tk = yf.Ticker(ticker)
    _sleep_jitter()
    all_exps = _with_retries(lambda: list(tk.options or []))
    wanted = monthly_expiries_in_window(all_exps)
    for e in extra_expiries:                    # held expiries always saved
        if e in all_exps and e not in wanted:
            wanted.append(e)
    if not wanted:
        raise ValueError(f"no listed expiry {DTE_MIN}-{DTE_MAX} DTE")
    spot = None
    try:
        spot = float(tk.fast_info["lastPrice"])   # best-effort
    except Exception:
        pass
    exp_data: dict[str, list] = {}
    for e in wanted:
        _sleep_jitter()
        chain = _with_retries(lambda e=e: tk.option_chain(e))
        df = chain.calls
        rows = []
        for _, r in df.iterrows():
            rows.append([_f(r.get("strike")), _f(r.get("bid")),
                         _f(r.get("ask")), _f(r.get("lastPrice")),
                         _i(r.get("openInterest")), _i(r.get("volume")),
                         _f(r.get("impliedVolatility"))])
        exp_data[e] = rows
    data = {"ticker": ticker, "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "spot": spot, "expiries": exp_data}
    save_ticker_data(ticker, data)
    return {"ok": True, "expiries": len(exp_data)}


def _run_job(tickers: list[str], must_include: dict[str, list[str]]) -> None:
    global _job
    for t in tickers:
        with _lock:
            _job["current"] = t
        try:
            res = _fetch_ticker(t, must_include.get(t, []))
        except Exception as ex:
            res = {"ok": False, "reason": f"{type(ex).__name__}: {ex}"}
        with _lock:
            _job["results"][t] = res
            _job["done"] += 1
    try:  # manifest — cheap at-a-glance record of the run
        (store_dir() / "manifest.json").write_text(
            json.dumps({"finished_at": datetime.now().isoformat(timespec="seconds"),
                        "results": _job["results"]}), encoding="utf-8")
    except OSError:
        pass
    with _lock:
        _job["state"] = "done"
        _job["current"] = None
        _job["finished_at"] = datetime.now().isoformat(timespec="seconds")


def start_refresh(tickers: list[str],
                  must_include: dict[str, list[str]] | None = None) -> bool:
    """Kick off the background fetch. Returns False if one is already running."""
    global _job
    with _lock:
        if _job["state"] == "running":
            return False
        _job = {"state": "running", "done": 0, "total": len(tickers),
                "current": None, "results": {},
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None}
    threading.Thread(target=_run_job, args=(tickers, must_include or {}),
                     daemon=True).start()
    return True

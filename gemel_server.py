"""Gemel server — FastAPI app serving the local dashboard and the read-only API.

Read-only with respect to the brokerage: endpoints read market data, or
read/write the LOCAL journal database. Nothing here places an order.
Launch with run.bat (uvicorn gemel_server:app) -> localhost:8000.
"""
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from analytics.service import compute_analytics
from backtester.engine import run_backtest
from core.data.factory import make_adapter
from core.db import init_db, make_engine
from core.options.black_scholes import put_delta
from core.options.iv_proxy import iv_rank, vol_index_symbol
from flightcheck.service import cap_pct, max_loss_for, spread_metrics, within_cap
from journal import service as journal
from market.service import compute_breadth
from scanner.scan import run_scan

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard-mockup.html"

# Paper account size used for the 2% per-trade max-loss cap (override in .env).
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "35000"))
MAX_LOSS_CAP_PCT = 0.02

app = FastAPI(title="Gemel", docs_url=None, redoc_url=None)

# Journal DB (gemel.db), created on first launch. Locally it lives next to the
# code; in a hosted deploy set DATA_DIR to a mounted persistent volume (e.g.
# /data) so saved trades survive restarts and redeploys.
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT))
DATA_DIR.mkdir(parents=True, exist_ok=True)
_engine = make_engine(f"sqlite:///{(DATA_DIR / 'gemel.db').as_posix()}")
init_db(_engine)


def get_session():
    with Session(_engine) as session:
        yield session


# ---------- pages ----------
@app.get("/")
def dashboard() -> FileResponse:
    """Serve the single-file dashboard. Its JS fetches the /api/* endpoints;
    opened from file:// those fetches no-op and the sample data shows instead."""
    return FileResponse(DASHBOARD)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    """Lightweight liveness probe for the UI's LIVE bar: which data source is
    active and the latest SPY close it can see right now."""
    adapter = make_adapter()
    bars = adapter.get_daily_bars("SPY", lookback_days=5)
    return {
        "source": type(adapter.source).__name__.replace("Adapter", "").lower(),
        "asof": bars.index[-1].date().isoformat(),
        "spy_spot": round(float(bars["close"].iloc[-1]), 2),
    }


@app.get("/api/market")
def market() -> JSONResponse:
    """Sector breadth across the 11 S&P sector ETFs for the Today home —
    advancing/declining, new highs/lows, % above SMA50/200, bull/bear gauge."""
    return JSONResponse(compute_breadth(make_adapter()))


@app.get("/api/ohlc")
def ohlc(ticker: str = "SPY", days: int = 180) -> JSONResponse:
    """Real daily OHLCV for the Gemel-native charts (scanner candles + Today
    index sparklines). Read-only market data."""
    try:
        bars = make_adapter().get_daily_bars(ticker.upper(), lookback_days=days)
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(status_code=422, detail=str(ex))
    r2 = lambda s: [round(float(x), 2) for x in s]
    return JSONResponse({
        "ticker": ticker.upper(),
        "dates": [d.date().isoformat() for d in bars.index],
        "open": r2(bars["open"]), "high": r2(bars["high"]),
        "low": r2(bars["low"]), "close": r2(bars["close"]),
        "volume": [float(x) for x in bars["volume"]],
    })


# ---------- scanner ----------
@app.get("/api/scan")
def scan() -> JSONResponse:
    """Run the weekly ETF scan on live data and return the report."""
    adapter = make_adapter()
    return JSONResponse(run_scan(adapter, today=date.today()))


# ---------- backtester ----------
@app.get("/api/backtest")
def backtest(ticker: str = "SPY", strategy: str = "bull_put_spread",
             dte: int = 38, delta: float = 0.18,
             start: str | None = None, end: str | None = None) -> JSONResponse:
    """Run an options backtest on real history (BS + historical VIX IV proxy).

    Defaults to the last ~8 years through today; the sensitivity grid re-simulates
    across delta x DTE, so this is the slowest endpoint (several seconds)."""
    try:
        s = date.fromisoformat(start) if start else date(date.today().year - 8, 1, 1)
        e = date.fromisoformat(end) if end else date.today()
        result = run_backtest(adapter := make_adapter(), ticker=ticker, strategy=strategy,
                              start=s, end=e, dte=dte, target_delta=delta)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex))
    return JSONResponse(result)


# ---------- flight check ----------
@app.get("/api/flightcheck")
def flightcheck(ticker: str = "SPY", strategy: str = "bull_put_spread",
                short_strike: float | None = None, long_strike: float | None = None,
                credit: float = 0.0, qty: int = 1, dte: int = 38) -> JSONResponse:
    """Pre-trade flight check: max loss, return on risk, break-even, the 2% cap
    verdict, plus best-effort live short-leg delta + IV rank. Read-only."""
    out: dict = {"strategy": strategy, "account_size": ACCOUNT_SIZE,
                 "cap_dollars": round(ACCOUNT_SIZE * MAX_LOSS_CAP_PCT, 2)}
    try:
        ml = max_loss_for(strategy, short_strike=short_strike, long_strike=long_strike, credit_debit=credit, qty=qty)
        out["max_loss"] = ml
        out["cap_pct"] = cap_pct(ml, ACCOUNT_SIZE)
        out["within_cap"] = within_cap(ml, ACCOUNT_SIZE, MAX_LOSS_CAP_PCT)
    except ValueError as ex:
        out["error"] = str(ex)
    if strategy == "bull_put_spread" and short_strike and long_strike:
        try:
            m = spread_metrics(short_strike, long_strike, credit, qty)
            out.update({"return_on_risk": m["return_on_risk"], "break_even": m["break_even"],
                        "max_profit": m["max_profit"], "width": m["width"]})
        except ValueError:
            pass
    try:  # best-effort live enrichment
        adapter = make_adapter()
        idx = vol_index_symbol(ticker)
        if idx:
            vix = adapter.get_daily_bars(idx, lookback_days=300)["close"]
            sigma = float(vix.iloc[-1]) / 100.0
            out["ivr"] = round(iv_rank(vix.tail(252), float(vix.iloc[-1])), 0)
        else:
            import numpy as np
            closes = adapter.get_daily_bars(ticker, lookback_days=300)["close"]
            roll = (np.log(closes / closes.shift(1)).rolling(20).std() * (252 ** 0.5) * 100).dropna()
            sigma = float(roll.iloc[-1]) / 100.0
            out["ivr"] = round(iv_rank(roll.tail(252), float(roll.iloc[-1])), 0)
        out["spot"] = round(float(adapter.get_quote(ticker)), 2)
        if short_strike:
            out["short_delta"] = round(put_delta(out["spot"], short_strike, max(dte, 1) / 365, sigma), 3)
    except Exception:
        pass
    return JSONResponse(out)


# ---------- journal ----------
class OpenTradeBody(BaseModel):
    ticker: str
    strategy: str
    credit_debit: float
    reason_for_entry: str
    profit_target: str
    stop: str
    time_stop: str
    is_paper: bool = True
    qty: int = 1
    short_strike: float | None = None
    long_strike: float | None = None
    delta_at_entry: float | None = None
    dte_at_entry: int | None = None


class CloseTradeBody(BaseModel):
    exit_price: float
    exit_reason: str
    pnl: float


class RuleItem(BaseModel):
    rule_key: str
    rule_label: str
    followed: bool


def _trade_dict(t) -> dict:
    return {
        "id": t.id, "ticker": t.ticker, "strategy": t.strategy,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "is_paper": t.is_paper, "qty": t.qty,
        "short_strike": t.short_strike, "long_strike": t.long_strike,
        "credit_debit": t.credit_debit, "delta_at_entry": t.delta_at_entry,
        "dte_at_entry": t.dte_at_entry, "reason_for_entry": t.reason_for_entry,
        "profit_target": t.profit_target, "stop": t.stop, "time_stop": t.time_stop,
        "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "pnl": t.pnl, "status": t.status,
    }


def _with_grade(session, t) -> dict:
    adh = journal.adherence_pct(session, t.id)
    return {**_trade_dict(t), "adherence": adh, "grade": journal.process_grade(adh)}


@app.get("/api/journal/trades")
def list_trades(session: Session = Depends(get_session)) -> dict:
    open_ = [_with_grade(session, t) for t in journal.list_open(session)]
    closed = [_with_grade(session, t) for t in journal.list_closed(session)]
    camps = [
        {"campaign": {"id": c["campaign"].id, "ticker": c["campaign"].ticker,
                       "strategy": c["campaign"].strategy, "status": c["campaign"].status},
         "legs": [_trade_dict(t) for t in c["legs"]], "net_pnl": c["net_pnl"]}
        for c in journal.list_campaigns(session)
    ]
    return {"open": open_, "closed": closed, "campaigns": camps}


@app.post("/api/journal/open")
def open_trade(body: OpenTradeBody, session: Session = Depends(get_session)) -> dict:
    # Server-side 2% max-loss cap (README guardrail) — enforced in addition to the UI.
    try:
        ml = max_loss_for(body.strategy, short_strike=body.short_strike,
                          long_strike=body.long_strike, credit_debit=body.credit_debit, qty=body.qty)
    except ValueError:
        ml = None  # incomplete strikes -> can't compute; let the exit-plan rule gate it
    if ml is not None and not within_cap(ml, ACCOUNT_SIZE, MAX_LOSS_CAP_PCT):
        raise HTTPException(
            status_code=422,
            detail=f"Max loss ${ml:,.0f} is {cap_pct(ml, ACCOUNT_SIZE):.1f}% of the account — over the "
                   f"{int(MAX_LOSS_CAP_PCT * 100)}% cap (${ACCOUNT_SIZE * MAX_LOSS_CAP_PCT:,.0f}). "
                   f"Size down or use a defined-risk spread.")
    try:
        t = journal.open_trade(session, opened_at=datetime.now(), **body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _trade_dict(t)


@app.post("/api/journal/{trade_id}/close")
def close_trade(trade_id: int, body: CloseTradeBody, session: Session = Depends(get_session)) -> dict:
    try:
        t = journal.close_trade(session, trade_id, closed_at=datetime.now(), **body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _trade_dict(t)


@app.post("/api/journal/{trade_id}/rules")
def set_rules(trade_id: int, rules: list[RuleItem], session: Session = Depends(get_session)) -> dict:
    journal.set_rules(session, trade_id, [r.model_dump() for r in rules])
    return {"trade_id": trade_id, "adherence": journal.adherence_pct(session, trade_id)}


# ---------- analytics ----------
@app.get("/api/analytics")
def analytics(last_n: int | None = None, session: Session = Depends(get_session)) -> JSONResponse:
    return JSONResponse(compute_analytics(session, last_n=last_n))

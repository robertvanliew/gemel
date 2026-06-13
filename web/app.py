"""FastAPI app — serves the local dashboard and the live data API.

Read-only with respect to the brokerage: endpoints read market data, or
read/write the LOCAL journal database. Nothing here places an order.
Launch with run.bat (uvicorn) -> localhost:8000.
"""
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
from journal import service as journal
from scanner.scan import run_scan

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard-mockup.html"

app = FastAPI(title="Trading Tools", docs_url=None, redoc_url=None)

# Local journal DB (data/trading.sqlite). Created on first launch.
(ROOT / "data").mkdir(exist_ok=True)
_engine = make_engine(f"sqlite:///{(ROOT / 'data' / 'trading.sqlite').as_posix()}")
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
    s = date.fromisoformat(start) if start else date(date.today().year - 8, 1, 1)
    e = date.fromisoformat(end) if end else date.today()
    adapter = make_adapter()
    try:
        result = run_backtest(adapter, ticker=ticker, strategy=strategy,
                              start=s, end=e, dte=dte, target_delta=delta)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex))
    return JSONResponse(result)


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


@app.get("/api/journal/trades")
def list_trades(session: Session = Depends(get_session)) -> dict:
    open_ = [{**_trade_dict(t), "adherence": journal.adherence_pct(session, t.id)} for t in journal.list_open(session)]
    closed = [{**_trade_dict(t), "adherence": journal.adherence_pct(session, t.id)} for t in journal.list_closed(session)]
    camps = [
        {"campaign": {"id": c["campaign"].id, "ticker": c["campaign"].ticker,
                       "strategy": c["campaign"].strategy, "status": c["campaign"].status},
         "legs": [_trade_dict(t) for t in c["legs"]], "net_pnl": c["net_pnl"]}
        for c in journal.list_campaigns(session)
    ]
    return {"open": open_, "closed": closed, "campaigns": camps}


@app.post("/api/journal/open")
def open_trade(body: OpenTradeBody, session: Session = Depends(get_session)) -> dict:
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

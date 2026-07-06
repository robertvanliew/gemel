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
from backtester.momentum_bt import run_momentum_backtest
from market.service import compute_breadth
from momo import book as momo_book
from momo import service as momo_rules
from scanner.chains import mark_spread, spread_quote
from scanner.momentum import momentum_leaders, rank_row
from scanner.scan import run_scan

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard-mockup.html"

# Per-playbook risk caps (spec §0 — never one global number):
#   Credit spreads: 2% of ACCOUNT_SIZE per trade (the original guardrail).
#   Momentum debit spreads: 15% of MOMENTUM_ACCOUNT_SIZE per position, plus a
#   90% total-deployment cap, ≥$400 cash free, ≤7 positions, ≤2 per theme.
#   Standing decision recorded in the spec: the momentum book runs ~12% per
#   position or it does not run — there is no config that satisfies both a 2%
#   cap and a $450-550 spread on a $4k account.
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "35000"))
MAX_LOSS_CAP_PCT = 0.02
MOMENTUM_ACCOUNT_SIZE = float(os.getenv("MOMENTUM_ACCOUNT_SIZE", "4000"))

app = FastAPI(title="Gemel", docs_url=None, redoc_url=None)

# Journal storage. Two modes:
#   • DATABASE_URL set  -> hosted Postgres (e.g. Neon free tier). Lets the web
#     server stay stateless, so it can run on a free/ephemeral host.
#   • otherwise         -> local SQLite at DATA_DIR (a mounted volume in a
#     container, or next to the code locally). This is the default.
def _resolve_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        # SQLAlchemy needs the psycopg3 driver named explicitly; Neon/Heroku
        # hand out bare postgres:// or postgresql:// URLs.
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    data_dir = Path(os.getenv("DATA_DIR", ROOT))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'gemel.db').as_posix()}"


_engine = make_engine(_resolve_db_url())
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


@app.get("/api/backtest/momentum")
def backtest_momentum(years: int = 3, top_n: int | None = None,
                      profit_exit: float | None = None) -> JSONResponse:
    """Momentum debit-spread strategy end-to-end on the watchlist (spec §6).
    For tuning exits/sizing — the hindsight-bias limitation ships in the payload."""
    try:
        result = run_momentum_backtest(
            make_adapter(),
            account_size=MOMENTUM_ACCOUNT_SIZE,
            years=max(1, min(years, 8)),
            top_n=top_n or momo_rules.MAX_POSITIONS,
            profit_exit_pct=profit_exit or momo_rules.PROFIT_EXIT_PCT)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex))
    return JSONResponse(result)


def _playbook_config() -> dict:
    """The momentum playbook's active rules — displayed on its page so the
    cap in force is never ambiguous (spec §0)."""
    return {
        "account_size": MOMENTUM_ACCOUNT_SIZE,
        "cap_pct": momo_rules.CAP_PCT,
        "cap_dollars": round(MOMENTUM_ACCOUNT_SIZE * momo_rules.CAP_PCT, 2),
        "deploy_cap_pct": momo_rules.DEPLOY_CAP_PCT,
        "min_cash": momo_rules.MIN_CASH,
        "max_positions": momo_rules.MAX_POSITIONS,
        "max_per_theme": momo_rules.MAX_PER_THEME,
        "profit_exit_pct": momo_rules.PROFIT_EXIT_PCT,
        "signal_exit_rank": momo_rules.SIGNAL_EXIT_RANK,
        "dte_warn": momo_rules.DTE_WARN,
    }


@app.get("/api/momentum")
def momentum(tickers: str | None = None) -> JSONResponse:
    """Momentum Leaders: rank a universe by 252d/63d rate-of-change on live
    data, each name costed as the model call debit spread against the momentum
    playbook's per-position cap. Read-only — a rank is not a recommendation."""
    universe = None
    if tickers:
        universe = [t.strip().upper() for t in tickers.split(",") if t.strip()][:40]
    report = momentum_leaders(make_adapter(), universe,
                              account_size=MOMENTUM_ACCOUNT_SIZE,
                              cap_pct=momo_rules.CAP_PCT)
    report["playbook"] = _playbook_config()
    return JSONResponse(report)


@app.get("/api/momentum/lookup")
def momentum_lookup(ticker: str) -> JSONResponse:
    """Ticker lookup: compute one symbol's ROCs + model spread so the UI can
    show where it WOULD rank against the current watchlist, without adding it."""
    t = ticker.strip().upper()
    try:
        bars = make_adapter().get_daily_bars(t, lookback_days=420)
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(status_code=422, detail=f"{t}: {ex}")
    row = rank_row(t, bars["close"],
                   cap_dollars=MOMENTUM_ACCOUNT_SIZE * momo_rules.CAP_PCT)
    if row is None:
        raise HTTPException(status_code=422, detail=f"{t}: not enough history")
    return JSONResponse(row)


@app.get("/api/momentum/candidates")
def momentum_candidates(session: Session = Depends(get_session)) -> JSONResponse:
    """This month's qualifying candidates (spec §2): rank on live data, then
    gate — data-suspect flagged, fits the playbook cap, real-chain liquidity
    pass, ≤2 per theme counting current holdings — down to ≤7, with proposed
    strikes and est. debit. Suggested for review, not execution. Slow (~10-30s):
    fetches real option chains for the names that survive the cheap gates."""
    report = momentum_leaders(make_adapter(),
                              account_size=MOMENTUM_ACCOUNT_SIZE,
                              cap_pct=momo_rules.CAP_PCT)
    held = momo_book.list_open(session)
    theme_counts: dict[str, int] = {}
    for p in held:
        theme_counts[p.theme] = theme_counts.get(p.theme, 0) + 1
    held_tickers = {p.ticker for p in held}

    candidates, skipped = [], []
    for r in report["leaders"]:
        if len(candidates) >= momo_rules.MAX_POSITIONS:
            break
        if r["ticker"] in held_tickers:
            continue
        if not r["fits_cap"]:
            continue
        if theme_counts.get(r["theme"], 0) >= momo_rules.MAX_PER_THEME:
            skipped.append({"ticker": r["ticker"], "why": f"theme “{r['theme']}” already at max"})
            continue
        q = spread_quote(r["ticker"], r["spread"]["long_strike"], r["spread"]["short_strike"])
        if not q.get("ok"):
            skipped.append({"ticker": r["ticker"], "why": q.get("reason", "chain unavailable")})
            continue
        if not q["liquid"]:
            skipped.append({"ticker": r["ticker"], "why": f"illiquid — {q['liquidity_detail']}"})
            continue
        if q["debit_ask"] > MOMENTUM_ACCOUNT_SIZE * momo_rules.CAP_PCT:
            skipped.append({"ticker": r["ticker"], "why": "real debit over cap at the ask"})
            continue
        theme_counts[r["theme"]] = theme_counts.get(r["theme"], 0) + 1
        candidates.append({**{k: r[k] for k in ("rank", "ticker", "theme", "spot",
                                                "roc_252", "roc_63", "data_suspect")},
                           "quote": q})
    return JSONResponse({"candidates": candidates, "skipped": skipped,
                         "playbook": _playbook_config()})


# ---------- momentum paper book ----------
class MomoOpenBody(BaseModel):
    ticker: str
    theme: str
    long_strike: float
    short_strike: float
    expiry: str           # ISO date
    entry_debit: float    # total $, ask-side fill
    qty: int = 1


class MomoCloseBody(BaseModel):
    exit_value: float     # total $, bid-side fill
    exit_rule: str        # profit | signal | dte | discretionary
    rule_triggered: bool = False


def _momo_pos_dict(p) -> dict:
    return {"id": p.id, "ticker": p.ticker, "theme": p.theme,
            "long_strike": p.long_strike, "short_strike": p.short_strike,
            "expiry": p.expiry.isoformat(), "qty": p.qty,
            "entry_debit": p.entry_debit, "max_value": p.max_value,
            "opened_at": p.opened_at.isoformat(),
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "exit_value": p.exit_value, "realized_pnl": p.realized_pnl,
            "exit_rule": p.exit_rule, "rule_triggered": p.rule_triggered,
            "status": p.status}


@app.get("/api/momo/book")
def momo_book_view(ranks: str | None = None,
                   session: Session = Depends(get_session)) -> JSONResponse:
    """Open paper positions with live marks, exit-rule state, theme exposure,
    and the scorecard. `ranks` = comma list of tickers in current rank order
    (from the last Rank now) so the signal-exit rule can be evaluated."""
    rank_of: dict[str, int] = {}
    if ranks:
        for i, t in enumerate([x.strip().upper() for x in ranks.split(",") if x.strip()], 1):
            rank_of[t] = i
    today = date.today()
    open_rows = []
    for p in momo_book.list_open(session):
        mark = mark_spread(p.ticker, p.long_strike, p.short_strike, p.expiry.isoformat())
        value = mark["value_bid"] if mark.get("ok") else None
        alerts = momo_rules.exit_alerts(
            current_value=value if value is not None else 0.0,
            max_value=p.max_value,
            dte=(p.expiry - today).days,
            # No ranking supplied -> rank 0 (in top N) so we don't cry signal-exit
            # blind; the flag is then nulled below as "unknown until Rank now".
            rank=rank_of.get(p.ticker) if rank_of else 0,
        )
        if not rank_of:
            alerts["signal_exit"] = None
        open_rows.append({**_momo_pos_dict(p),
                          "dte": (p.expiry - today).days,
                          "mark_ok": bool(mark.get("ok")),
                          "mark_reason": mark.get("reason"),
                          "current_value": value,
                          "unrealized_pnl": None if value is None else round(value - p.entry_debit, 2),
                          "alerts": alerts})
    closed = momo_book.list_closed(session)
    open_dicts = [{"entry_debit": p.entry_debit, "theme": p.theme}
                  for p in momo_book.list_open(session)]
    deployed = round(sum(d["entry_debit"] for d in open_dicts), 2)
    return JSONResponse({
        "open": open_rows,
        "closed": [_momo_pos_dict(p) for p in closed],
        "themes": momo_rules.theme_exposure(open_dicts),
        "deployed": deployed,
        "cash_free": round(MOMENTUM_ACCOUNT_SIZE - deployed, 2),
        "scorecard": momo_rules.scorecard(
            [{"realized_pnl": p.realized_pnl or 0.0, "rule_triggered": p.rule_triggered}
             for p in closed]),
        "playbook": _playbook_config(),
    })


@app.post("/api/momo/open")
def momo_open(body: MomoOpenBody, session: Session = Depends(get_session)) -> dict:
    """Open a paper spread — every playbook rule enforced server-side."""
    open_dicts = [{"entry_debit": p.entry_debit, "theme": p.theme}
                  for p in momo_book.list_open(session)]
    violations = momo_rules.entry_violations(
        debit=body.entry_debit, theme=body.theme,
        account_size=MOMENTUM_ACCOUNT_SIZE, open_positions=open_dicts)
    if violations:
        raise HTTPException(status_code=422, detail=" ".join(violations))
    try:
        expiry = date.fromisoformat(body.expiry)
    except ValueError:
        raise HTTPException(status_code=422, detail="expiry must be YYYY-MM-DD")
    if body.short_strike <= body.long_strike:
        raise HTTPException(status_code=422, detail="short strike must be above long strike")
    pos = momo_book.open_position(
        session, ticker=body.ticker.upper(), theme=body.theme,
        long_strike=body.long_strike, short_strike=body.short_strike,
        expiry=expiry, entry_debit=body.entry_debit, qty=body.qty)
    return _momo_pos_dict(pos)


@app.post("/api/momo/{position_id}/close")
def momo_close(position_id: int, body: MomoCloseBody,
               session: Session = Depends(get_session)) -> dict:
    try:
        pos = momo_book.close_position(session, position_id,
                                       exit_value=body.exit_value,
                                       exit_rule=body.exit_rule,
                                       rule_triggered=body.rule_triggered)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return _momo_pos_dict(pos)


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

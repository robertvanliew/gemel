# Trading Tools — Design Spec
**Date:** 2026-06-12 · **Status:** Approved direction, consolidated from iterative design sessions
**Visual reference:** `dashboard-mockup.html` (the real app's UI is built to match it)

## 1. Goal

A local, single-user suite of three composable tools that make a disciplined options-learning
plan sharper: a **Journal & Analytics** layer, a **Backtester**, and a weekly **Scanner** — served
through one local web dashboard. The tools inform and validate decisions; they never make them.

## 2. Hard guardrails (non-negotiable)

- **No brokerage write access. No order placement. Ever.** No trading-scoped SDK call anywhere.
  Alpaca credentials are used exclusively for market-data reads.
- **Auto-execution is out of scope** (deferred "Phase 3", unlocked only by: positive expectancy in
  backtest incl. out-of-sample + 4 weeks profitable paper trading + high rule adherence).
- The backtest engine structurally prevents **look-ahead bias**: decisions at bar *i* read bars `0..i` only.
- **Anti-overfitting**: every backtest auto-reserves an out-of-sample tail; report shows IS vs OOS side by side.
- Secrets live in `.env` (gitignored); the repo never contains keys.

## 3. Architecture

- **Language:** Python 3.14 (venv at `.venv`, already provisioned: yfinance 1.4.1, alpaca-py 0.43.4, python-dotenv).
- **Web:** FastAPI + Jinja2 templates + HTMX (no JS build step) + Plotly 2.35.2 via CDN.
- **Storage:** SQLite via SQLModel, single file `data/trading.sqlite`. Parquet price cache in `data/cache/`.
- **Layout:**
```
core/
  data/base.py            # DataAdapter interface: get_daily_bars, get_quote, get_chain, get_vol_index
  data/yfinance_adapter.py # default adapter, zero-config
  data/alpaca_adapter.py   # keyed adapter (.env), IEX feed
  data/cache.py            # parquet OHLCV cache
  indicators.py            # ema, rsi, detect_support (swing-low clustering), adx
  options/black_scholes.py # price + greeks (put/call), T+0 valuation
  options/iv_proxy.py      # VIX→SPY, VXN→QQQ, RVX→IWM, realized-vol fallback; IV rank
  regime.py                # trending-up / choppy / declining classifier (SPY vs 50-EMA + slope)
  calendar.py              # earnings + FOMC event-risk lookups
  db.py                    # SQLModel schema + session
journal/                   # trade logging, CSV import mapping, analytics calcs
backtester/                # engine, strategy interface, 3 strategies, reports
scanner/                   # screen logic + run_scan.py standalone entrypoint
web/                       # FastAPI app, routes, templates (6 views), static
tests/                     # offline unit tests, fixtures; no network in tests
```
- **Adapter rule:** only `core/data/` touches the network. Everything downstream consumes DataFrames →
  all logic is testable offline; swapping/adding adapters is config (`DATA_SOURCE=yfinance|alpaca` in `.env`).

## 4. Database schema (SQLite)

- `campaigns(id, ticker, strategy, opened_at, closed_at, status)` — a chain of rolled positions judged as one idea.
- `trades(id, campaign_id FK, ticker, strategy, opened_at, closed_at, is_paper, qty,
  short_strike, long_strike, credit_debit, delta_at_entry, dte_at_entry,
  reason_for_entry, profit_target NOT NULL, stop NOT NULL, time_stop NOT NULL,
  exit_price, exit_reason, pnl, status)` — **exit plan enforced at schema level**.
- `trade_rules(id, trade_id FK, rule_key, rule_label, followed BOOL)` — per-trade checklist → adherence score.
- `backtest_runs(id, created_at, strategy, ticker, params_json, date_start, date_end, oos_start,
  stats_json, regime_stats_json, sensitivity_json)`
- `backtest_trades(id, run_id FK, ...same trade economics..., regime, in_sample BOOL)`
- `scan_reports(id, ran_at, master_gate_pass BOOL, regime, playbook, summary_md)`
- `scan_results(id, report_id FK, ticker, passes_json, ivr, rsi, metrics_json, qualifies BOOL,
  rank, candidate_json)`  — candidate_json holds strikes/credit/max-loss/break-even/target/stop.
- Price bars are **not** stored in SQLite — they live in the parquet cache (`data/cache/`), which is
  bulk columnar data and pandas-native. SQLite holds only decisions and results.

## 5. Tools

### 5.1 Journal & Analytics
- **Entry paths:** manual form (open → close lifecycle) **and** CSV import (Robinhood/generic column
  mapping with preview; reflective fields annotated manually afterward).
- **Rules checklist** per strategy (entry criteria + exit discipline); adherence % per trade and over time.
- **Campaigns:** a roll closes one trade row and opens another under the same `campaign_id`;
  analytics aggregate P&L per campaign so roll legs don't pollute stats.
- **Analytics:** rolling win rate (10/20/all), avg win vs loss, profit factor, equity curve,
  adherence-over-time, **Week-6 scaling gate** (green only if adherence ≥ 90% AND net P&L > 0).
- Paper and real trades logged identically (`is_paper` flag).

### 5.2 Backtester
- **Strategy interface:** small Python classes (entry rules, exit rules, position params).
  Ships with: Bull Put Credit Spread (1st), Cash-Secured Put (2nd), Directional Long Option (3rd).
- **Engine:** event-driven over daily bars; options legs priced via Black-Scholes + IV proxy;
  models frictions (bid-ask spread cost, slippage, assignment for short puts).
- **Report:** win rate, avg win/loss, profit factor, max drawdown; **regime segmentation**
  (trending-up/choppy/declining); **parameter sensitivity** (delta 0.15/0.20/0.25 × DTE 30/45);
  **in-sample vs out-of-sample** comparison with degradation flag.

### 5.3 Scanner
- **Standalone scheduled script** (`scanner/run_scan.py`) — Windows Task Scheduler, Sunday ~6 PM,
  "run ASAP after missed start" enabled. Also runnable from the dashboard ("Run now").
- **Universe:** SPY, QQQ, IWM, GLD, XLK, XLV (configurable list).
- **Master gate:** SPY vs 50-day EMA → regime playbook (bull puts active / bear calls paper-only /
  iron condors locked). The gate switches strategies; it doesn't just say no.
- **Per-ETF criteria:** > 20-EMA, > 50-EMA, RSI 40–70, **IVR ≥ 25**, clear support, no earnings/FOMC before expiry.
- **Ranking:** credit-to-spread ratio, support buffer, open interest. Top candidate gets suggested
  strikes, credit, max loss, break-even, profit target (50%), stop (2× credit), DTE, IVR.
- **Output:** report written to DB; dashboard renders it. Optional Claude natural-language weekly summary.
- **It emits a report, never an order.**

## 6. Dashboard (matches `dashboard-mockup.html`)

Six views: **Positions** (home: account risk cards, per-position payoff expiration+T+0 with IV/days
sliders, P&L matrix heatmap, exit-trigger status tags), **Journal**, **Analytics**, **Backtester**,
**Scanner** (candlestick regime chart with EMA 20/50 + volume, playbook, screen grid, top candidate),
**Learn** (pre-trade checklist, 90-day ramp, 73-term glossary with filter; jargon tooltips app-wide).

- **Theme system:** v4 token contract; exchange light default (navy rail, white surfaces) + dark toggle;
  charts read CSS variables at render (`cssv()`/`plotTheme()`), re-render on toggle via `Plotly.react`.
- **Chart rules:** payoff/matrix charts ship **fixed ranges + `fixedrange` + `uirevision`** (sliders are
  the interaction); only market charts (candles, equity) are explorable (range buttons, crosshair,
  drag-zoom/pan). Equity charts: no zero-fill; axis hugs data; right-side last-value tag.
- Positions T+0 curves and P&L matrix computed by the **backend** Black-Scholes (same `core/options`
  path as the backtester) — mockup's inline JS math is replaced by API responses.
- Local only: `uvicorn` on `localhost:8000`, no auth, launched via `run.bat`.

## 7. Data plan

- **yfinance (default):** daily OHLCV, option chains, VIX/VXN/RVX. Zero config. ✅ verified live 2026-06-12.
- **Alpaca (keyed upgrade):** real-time IEX quotes, stock bars, options data. Keys in `.env`. ✅ verified live 2026-06-12.
- **Polygon/ORATS (deferred):** real historical options data, only if a strategy proves out.
- Bars cached to parquet; cache-first reads with staleness window.

## 8. Testing

- Core unit-tested offline against fixtures: indicators (known EMA/RSI values), Black-Scholes
  (published reference prices), support detection, IV proxy/IVR, regime classifier.
- Engine: look-ahead regression test (peeking strategy must be structurally impossible);
  deterministic end-to-end run on fixture data with known stats.
- Journal analytics vs hand-computed examples; campaign aggregation cases.
- Adapters mocked; **no network calls in the test suite**. TDD throughout.

## 9. Build sequence

1. **Foundation:** repo scaffold, venv deps, `core/` (adapters+cache → indicators → BS+IV proxy → db schema), tests.
2. **Journal & Analytics** + its dashboard views (immediately useful for paper trading underway).
3. **Backtester** engine + 3 strategies + report views.
4. **Scanner** script + report view + Task Scheduler registration.
5. **Polish:** Positions live view, theme parity with mockup, `run.bat`, optional Claude summary layer.

## 10. Out of scope

Auto-execution / brokerage write access (Phase 3 gate); Polygon/ORATS integration; cloud deployment;
multi-user/auth; intraday trading features; mobile app.

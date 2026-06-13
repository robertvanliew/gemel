# GEMEL

**The coach, not the calculator.** A local-first, read-only options-spread discipline tool for newer traders. It screens trades by market regime, enforces a pre-trade flight check before anything reaches the journal, grades every trade on *process* rather than P&L, and visualizes risk with live payoff curves and a losing-streak simulator.

GEMEL does not connect to a broker and **never places, modifies, or cancels an order.** It tells you whether a trade clears your own rules and grades how you followed them. You place every trade yourself.

---

## ⚠️ Risk disclaimer

This software is for **educational and informational purposes only.** It is **not financial, investment, or trading advice**, and nothing it outputs is a recommendation to buy or sell any security.

Options trading involves substantial risk, including the **risk of losing more than your initial investment.** Spreads, cash-secured puts, and all strategies discussed here can result in total loss. Past performance and backtested results do not predict future results; backtests use historical and sometimes simulated data and will differ from live trading.

GEMEL is read-only by design. It makes no guarantees about data accuracy, calculations, or outcomes. You are solely responsible for your own trading decisions and for consulting a licensed financial professional. Use at your own risk.

---

## What it does

- **Today / Positions** — a daily check that opens with a plain verdict (often "nothing needs your attention"), live payoff diagrams (expiration vs T+0), profit-capture progress, and exit triggers checked against your written plan.
- **Pre-trade flight check** — type a spread and it computes max loss, return on risk, short-leg delta, IV rank, and break-even. Nothing reaches the journal until max loss clears the 2% account cap **and** the exit plan (profit target, stop, time stop) is written.
- **Scanner** — a market-regime gate (SPY vs its 50-day EMA) that switches the active playbook, plus a per-ETF screen including IV rank, an Opportunity Map shaded by setup score, and a native candlestick chart with EMA overlays, volume, indicators, and drawing tools.
- **Journal** — closed and open trades, rolls linked into campaigns so P&L is judged per idea, and a process grade (A–F) on every trade separate from its P&L.
- **Analytics** — win rate, profit factor, equity curve, rule-adherence over time, a Week-6 scaling gate (size up only when adherence ≥ 90% and P&L positive), and a Monte Carlo losing-streak simulator.
- **Backtester** — parameter sensitivity on the playbook.
- **Learn** — a categorized glossary; every dotted term in the app links back to it.

## Architecture

Three layers, separating probabilistic decisions from deterministic work (see `AGENTS.md`):

- **Frontend** — a single self-contained `dashboard-mockup.html` (no build step; Plotly via CDN). Runs as a static preview with sample data, or live when the backend is up.
- **Backend** — a FastAPI app (`gemel_server.py`) serving the dashboard and these read-only endpoints:
  `/api/status` · `/api/market` · `/api/ohlc` · `/api/scan` · `/api/flightcheck` · `/api/journal/trades` · `/api/journal/open` · `/api/analytics` · `/api/backtest`
- **Store** — local SQLite (`gemel.db`). Exit-plan fields are `NOT NULL`; the 2% cap is enforced server-side as well as in the UI.

Market data defaults to **yfinance** (no key). Alpaca is optional.

## Setup

```bash
# 1. clone and enter
git clone https://github.com/robertvanliew/gemel.git
cd gemel

# 2. create a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 3. install dependencies
pip install -r requirements.txt

# 4. configure secrets
cp .env.example .env        # then edit .env with your keys

# 5. run
uvicorn gemel_server:app --port 8000 --reload
# or double-click run.bat on Windows
```

Open <http://localhost:8000>. The live bar turns green once `/api/status` responds with real data.

To run as a static preview without the backend, just open `dashboard-mockup.html` in a browser — it falls back to sample data.

## Verifying the UI

```bash
node verify-screens.js   # screenshots every view to _screens/ for design review
```

## Project status

Personal project, in active development. Read-only by design and not affiliated with any broker. "GEMEL" and the pillar mark are in use as a working brand identity; trademark status is unsettled.

## License

See [LICENSE](./LICENSE).

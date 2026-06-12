# Smoke test: prove real market data flows before we build the app.
# Pulls live SPY daily bars via yfinance and runs the scanner's master-gate check.
# Run:  .venv\Scripts\python.exe check_data.py
import yfinance as yf

bars = yf.Ticker("SPY").history(period="6mo", interval="1d")
if bars.empty:
    raise SystemExit("No data returned — check internet connection.")

close = bars["Close"]
ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
spot = close.iloc[-1]
asof = bars.index[-1].date()

print(f"SPY as of {asof}")
print(f"  last close : ${spot:,.2f}")
print(f"  20-day EMA : ${ema20:,.2f}  ({'above' if spot > ema20 else 'below'})")
print(f"  50-day EMA : ${ema50:,.2f}  ({'above' if spot > ema50 else 'below'})")
print()
if spot > ema50:
    print("MASTER GATE: OPEN — SPY above its 50-day EMA. Playbook: bull put credit spreads.")
else:
    print("MASTER GATE: CLOSED — SPY below its 50-day EMA. No bull put entries this week.")

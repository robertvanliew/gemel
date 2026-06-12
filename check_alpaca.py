# Smoke test: verify the Alpaca Market Data connection using keys from .env
# Run:  .venv\Scripts\python.exe check_alpaca.py
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()
key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
if not key or not secret:
    raise SystemExit("Keys missing — paste ALPACA_API_KEY and ALPACA_SECRET_KEY into the .env file first.")

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

client = StockHistoricalDataClient(key, secret)
req = StockBarsRequest(
    symbol_or_symbols="SPY",
    timeframe=TimeFrame.Day,
    start=datetime.now() - timedelta(days=10),
)
bars = client.get_stock_bars(req).df

print("ALPACA CONNECTED — last 5 daily SPY bars:")
print(bars.tail(5)[["open", "high", "low", "close", "volume"]].round(2))

"""Keyed adapter for Alpaca Market Data (free tier = IEX feed).

MARKET DATA ONLY: this module imports the historical-data client exclusively.
No trading client, no order endpoints — that is a hard project guardrail.
"""
import os
from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from core.data.base import DataAdapter, normalize_bars


class AlpacaAdapter(DataAdapter):
    def __init__(self, api_key: str | None = None, secret_key: str | None = None):
        api_key = api_key if api_key is not None else os.getenv("ALPACA_API_KEY", "")
        secret_key = secret_key if secret_key is not None else os.getenv("ALPACA_SECRET_KEY", "")
        if not api_key or not secret_key:
            raise ValueError("ALPACA_API_KEY / ALPACA_SECRET_KEY missing — set them in .env")
        self.client = StockHistoricalDataClient(api_key, secret_key)

    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=lookback_days * 2),
        )
        raw = self.client.get_stock_bars(req).df
        if raw.empty:
            raise RuntimeError(f"alpaca returned no data for {ticker!r}")
        raw = raw.xs(ticker, level="symbol")
        return normalize_bars(raw).tail(lookback_days)

    def get_quote(self, ticker: str) -> float:
        return float(self.get_daily_bars(ticker, lookback_days=5)["close"].iloc[-1])

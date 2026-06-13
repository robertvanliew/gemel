"""Default zero-config adapter. Free, ~15-min-delayed quotes, daily bars,
volatility indices (^VIX family) — sufficient for the whole phase-1 system."""
import pandas as pd
import yfinance as yf

from core.data.base import DataAdapter, normalize_bars


class YFinanceAdapter(DataAdapter):
    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        # yfinance periods are coarse; round up to cover lookback_days calendar-wise
        days = max(lookback_days, 5)
        raw = yf.Ticker(ticker).history(period=f"{days * 2}d", interval="1d", auto_adjust=True)
        if raw.empty:
            raise RuntimeError(f"yfinance returned no data for {ticker!r}")
        return normalize_bars(raw).tail(lookback_days)

    def get_quote(self, ticker: str) -> float:
        return float(self.get_daily_bars(ticker, lookback_days=5)["close"].iloc[-1])

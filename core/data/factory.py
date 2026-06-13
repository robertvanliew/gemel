"""Build the configured adapter: DATA_SOURCE in .env -> yfinance (default) | alpaca.

Everything that needs market data calls make_adapter() and stays
source-agnostic. Always wrapped in the parquet cache.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from core.data.base import DataAdapter
from core.data.cache import CachedAdapter


def make_adapter(cache_dir: str | Path = "data/cache") -> CachedAdapter:
    load_dotenv()
    source_name = os.getenv("DATA_SOURCE", "yfinance").lower()
    source: DataAdapter
    if source_name == "yfinance":
        from core.data.yfinance_adapter import YFinanceAdapter
        source = YFinanceAdapter()
    elif source_name == "alpaca":
        from core.data.alpaca_adapter import AlpacaAdapter
        source = AlpacaAdapter()
    else:
        raise ValueError(f"DATA_SOURCE={source_name!r} is not supported (yfinance | alpaca)")
    return CachedAdapter(source, cache_dir=cache_dir)

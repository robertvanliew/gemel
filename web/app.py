"""FastAPI app — serves the local dashboard and the live data API.

Read-only by design: every endpoint reads market data or the local DB.
Nothing here places an order. Launch with run.bat (uvicorn) -> localhost:8000.
"""
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from core.data.factory import make_adapter
from scanner.scan import run_scan

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard-mockup.html"

app = FastAPI(title="Trading Tools", docs_url=None, redoc_url=None)


@app.get("/")
def dashboard() -> FileResponse:
    """Serve the single-file dashboard. Its JS progressively fetches the
    /api/* endpoints below; opened from file:// those fetches no-op and the
    sample data shows instead."""
    return FileResponse(DASHBOARD)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/scan")
def scan() -> JSONResponse:
    """Run the weekly ETF scan on live data and return the report.

    The adapter is built per request from .env (yfinance default / alpaca if
    DATA_SOURCE=alpaca); results are cached to parquet by the CachedAdapter,
    so repeat calls the same day are fast.
    """
    adapter = make_adapter()
    report = run_scan(adapter, today=date.today())
    return JSONResponse(report)

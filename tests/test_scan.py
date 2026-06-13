from datetime import date

import numpy as np
import pandas as pd

from core.data.base import DataAdapter
from scanner.scan import UNIVERSE, screen_ticker, run_scan


class _FakeAdapter(DataAdapter):
    """Synthetic, deterministic bars. Uptrending ETFs; flat ~18 vol indices."""

    def get_daily_bars(self, ticker, lookback_days=120):
        n = max(lookback_days, 300)
        idx = pd.date_range("2025-01-01", periods=n, freq="B")
        if ticker.startswith("^"):
            # volatility index: oscillates 12..28, current ~18 -> mid IV rank
            vals = 20.0 + 6.0 * np.sin(np.linspace(0, 9, n))
            return pd.DataFrame({"open": vals, "high": vals + 1, "low": vals - 1,
                                 "close": vals, "volume": 0.0}, index=idx)
        # ETF: steady uptrend 100 -> 160 with mild noise and a clear support shelf
        base = np.linspace(100, 160, n) + np.sin(np.linspace(0, 20, n)) * 1.5
        return pd.DataFrame({"open": base, "high": base + 1.0, "low": base - 1.0,
                             "close": base, "volume": 1_000_000.0}, index=idx)

    def get_quote(self, ticker):
        return float(self.get_daily_bars(ticker, 5)["close"].iloc[-1])


def test_universe_is_the_six_etfs():
    assert UNIVERSE == ["SPY", "QQQ", "IWM", "GLD", "XLK", "XLV"]


def test_screen_ticker_returns_expected_shape():
    res = screen_ticker(_FakeAdapter(), "SPY", today=date(2026, 6, 15), dte=38)
    # passes dict has all six criteria as booleans
    assert set(res["passes"]) == {"above_20ema", "above_50ema", "rsi_ok", "ivr_ok", "support_ok", "event_ok"}
    assert all(isinstance(v, bool) for v in res["passes"].values())
    assert isinstance(res["qualifies"], bool)
    assert 0.0 <= res["ivr"] <= 100.0
    assert 0.0 <= res["rsi"] <= 100.0


def test_uptrending_etf_passes_trend_and_has_candidate():
    res = screen_ticker(_FakeAdapter(), "SPY", today=date(2026, 6, 15), dte=38)
    assert res["passes"]["above_20ema"] is True
    assert res["passes"]["above_50ema"] is True
    # a qualifying ticker exposes a concrete spread candidate
    if res["qualifies"]:
        c = res["candidate"]
        assert c["short_strike"] > c["long_strike"]
        assert c["credit"] > 0
        assert c["max_loss"] > 0
        assert c["break_even"] == round(c["short_strike"] - c["credit"], 2)
        # short strike sits below spot (OTM put) and credit < width
        assert c["short_strike"] < res["spot"]
        assert c["credit"] < c["width"]


def test_event_risk_blocks_when_fomc_in_window():
    # expiry window spanning an FOMC date (2026-06-17) -> event_ok False
    res = screen_ticker(_FakeAdapter(), "SPY", today=date(2026, 6, 10), dte=10)
    assert res["passes"]["event_ok"] is False
    assert res["qualifies"] is False


def test_run_scan_structure_and_master_gate():
    report = run_scan(_FakeAdapter(), today=date(2026, 6, 15))
    assert set(report) >= {"ran_at", "master_gate_pass", "regime", "playbook", "results"}
    assert isinstance(report["master_gate_pass"], bool)
    assert len(report["results"]) == len(UNIVERSE)
    # uptrending synthetic SPY -> gate open, bull-put playbook
    assert report["master_gate_pass"] is True
    assert "bull put" in report["playbook"].lower()
    # results carry a rank ordering for qualifiers
    ranks = [r["rank"] for r in report["results"] if r["qualifies"]]
    assert ranks == sorted(ranks)

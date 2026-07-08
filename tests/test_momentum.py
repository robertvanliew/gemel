"""Tests for scanner.momentum — ROC ranking, model spread economics, flags."""

import datetime

import pandas as pd
import pytest

from core.data.base import DataAdapter
from scanner.momentum import (
    CHALLENGE_UNIVERSE,
    THEMES,
    model_spread,
    momentum_leaders,
    rank_row,
    regime_gate,
    roc,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _series(n: int, start_price: float, daily: float) -> pd.Series:
    idx = pd.bdate_range(start=datetime.date(2024, 1, 2), periods=n)
    return pd.Series([start_price * (1 + daily) ** i for i in range(n)],
                     index=idx, dtype=float)


def _ohlcv(closes: pd.Series) -> pd.DataFrame:
    c = closes.values
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99,
                         "close": c, "volume": [1e6] * len(c)}, index=closes.index)


class FakeAdapter(DataAdapter):
    """HOT: strong uptrend, full history. FLAT: no move. THIN: only 90 bars.
    MOON: ROC > 1000% (data-suspect). BAD: raises (unfetchable)."""

    def __init__(self):
        moon = _series(400, 10.0, 0.0)
        moon.iloc[-1] = 150.0  # +1400% on the year
        self._data = {
            "HOT":  _ohlcv(_series(400, 100.0, 0.004)),
            "FLAT": _ohlcv(_series(400, 100.0, 0.0)),
            "THIN": _ohlcv(_series(90, 50.0, 0.006)),
            "MOON": _ohlcv(moon),
        }

    def get_daily_bars(self, ticker, lookback_days=365):
        if ticker not in self._data:
            raise ValueError(f"no data for {ticker}")
        return self._data[ticker]

    def get_quote(self, ticker):
        return float(self._data[ticker]["close"].iloc[-1])


@pytest.fixture
def report():
    return momentum_leaders(FakeAdapter(), ["FLAT", "HOT", "THIN", "BAD", "MOON"],
                            account_size=4_000.0, cap_pct=0.15)


# ── roc ──────────────────────────────────────────────────────────────────────

def test_roc_basic():
    closes = _series(300, 100.0, 0.0)
    closes.iloc[-1] = 110.0
    assert roc(closes, 252) == pytest.approx(10.0)


def test_roc_insufficient_history_is_none():
    assert roc(_series(100, 100.0, 0.001), 252) is None


# ── model_spread (§8.1: budget-solved width) ────────────────────────────────

def test_model_spread_solves_width_from_budget():
    sp = model_spread(100.0, 0.30, budget=550.0, cap=600.0)
    assert sp["untradeable"] is False
    assert sp["long_strike"] == pytest.approx(105.0)        # 5% OTM on $5 increments
    assert 0 < sp["debit"] <= 550.0                         # fits the budget
    assert sp["width"] >= 5.0
    # widening one more increment would blow the budget — this IS the widest
    wider = model_spread(100.0, 0.30, budget=sp["debit"] - 1, cap=600.0)
    assert wider["width"] <= sp["width"]
    assert sp["max_profit"] == pytest.approx(sp["max_value"] - sp["debit"])


def test_model_spread_untradeable_when_min_width_over_cap():
    # High price + high vol: even one $50 increment costs > $600.
    sp = model_spread(1745.0, 0.80, budget=550.0, cap=600.0)
    assert sp["untradeable"] is True
    assert sp["debit"] > 600.0                              # shows WHY it fails


def test_model_spread_high_price_name_becomes_tradable_if_narrow_fits():
    # Same stock, tame vol: a narrow spread may fit — that's the §8.1 point.
    sp = model_spread(600.0, 0.18, budget=550.0, cap=600.0)
    if not sp["untradeable"]:
        assert sp["debit"] <= 600.0


def test_model_spread_degenerate_inputs():
    assert model_spread(0.0, 0.3)["untradeable"] is True
    assert model_spread(100.0, 0.0)["untradeable"] is True


def test_model_spread_moneyness_ceiling_on_cheap_stock():
    # §8.4: OSCR-style — $32 stock, huge budget headroom. Without the ceiling
    # the width ran to ~2× spot; with it the short leg stays ≤ ~20% above.
    sp = model_spread(32.0, 0.60, budget=550.0, cap=600.0)
    assert sp["untradeable"] is False
    assert sp["short_strike"] <= 32.0 * 1.20 + 2.5   # ceiling (+1 increment tolerance)
    assert sp["rr_outsized"] is False or sp["max_profit"] / sp["debit"] > 3.0


def test_model_spread_exposes_leg_prices_for_verification():
    # §8.6: rows must be verifiable against a broker — leg prices ship.
    sp = model_spread(100.0, 0.30, budget=550.0, cap=600.0)
    assert sp["long_px"] > sp["short_px"] > 0
    assert sp["debit"] == pytest.approx((sp["long_px"] - sp["short_px"]) * 100, abs=1.0)


# ── momentum_leaders ────────────────────────────────────────────────────────

def test_leaders_ranked_by_momentum(report):
    tickers = [r["ticker"] for r in report["leaders"]]
    assert tickers.index("HOT") < tickers.index("FLAT")
    ranks = [r["rank"] for r in report["leaders"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_no_signal_sinks_to_bottom(report):
    # §8.3: THIN has a 3-mo ROC but no 1-yr ROC — no signal, LAST regardless.
    assert report["leaders"][-1]["ticker"] == "THIN"
    assert report["leaders"][-1]["no_signal"] is True


def test_unfetchable_ticker_skipped(report):
    assert all(r["ticker"] != "BAD" for r in report["leaders"])
    assert len(report["leaders"]) == 4


def test_thin_history_flagged_data_suspect(report):
    thin = next(r for r in report["leaders"] if r["ticker"] == "THIN")
    assert thin["thin_history"] is True
    assert thin["roc_252"] is None
    assert thin["data_suspect"] is True   # < 300 trading days


def test_extreme_roc_flagged_data_suspect(report):
    moon = next(r for r in report["leaders"] if r["ticker"] == "MOON")
    assert moon["roc_252"] > 1000
    assert moon["data_suspect"] is True
    hot = next(r for r in report["leaders"] if r["ticker"] == "HOT")
    assert hot["data_suspect"] is False


def test_cap_is_momentum_playbook_cap(report):
    # $4k account x 15% = $600 per position — NOT the credit playbook's 2%.
    assert report["cap_dollars"] == pytest.approx(600.0)
    # §8.7: the model produces an ESTIMATE flag only — the authoritative
    # verdict comes from a real chain; without one the UI shows "no data".
    for r in report["leaders"]:
        assert r["fits_cap_est"] == (not r["spread"]["untradeable"])
        assert "fits_cap" not in r   # the old confident field is gone


# ── regime_gate (§9) ────────────────────────────────────────────────────────

def _spy(closes):
    idx = pd.bdate_range(start=datetime.date(2024, 1, 2), periods=len(closes))
    return pd.Series(closes, index=idx, dtype=float)


def test_gate_open_at_or_above_92pct_of_high():
    g = regime_gate(_spy([500.0] * 260 + [465.0]))   # 93% of the 500 high
    assert g["open"] is True
    assert g["pct_of_high"] == pytest.approx(93.0)


def test_gate_closed_below_92pct_of_high():
    g = regime_gate(_spy([500.0] * 260 + [455.0]))   # 91% of the 500 high
    assert g["open"] is False
    assert g["pct_below"] == pytest.approx(9.0)


def test_gate_uses_trailing_252d_high_only():
    # An older, higher high outside the window must not count.
    closes = [600.0] * 50 + [500.0] * 252 + [470.0]  # 600 is >252 bars back
    g = regime_gate(_spy(closes))
    assert g["yr_high"] == pytest.approx(500.0)
    assert g["open"] is True                          # 94% of 500


def test_gate_defaults_open_on_thin_history():
    g = regime_gate(_spy([500.0] * 5))
    assert g["open"] is True and "defaults open" in g.get("reason", "")


def test_rank_row_theme_tags():
    closes = _series(400, 100.0, 0.001)
    row = rank_row("META", closes, cap_dollars=600.0)
    assert row["theme"] == "software"
    row2 = rank_row("ZZZZ", closes, cap_dollars=600.0)
    assert row2["theme"] == "untagged"


def test_default_universe_is_challenge_21_and_all_themed():
    assert len(CHALLENGE_UNIVERSE) == 21
    assert all(t in THEMES for t in CHALLENGE_UNIVERSE)

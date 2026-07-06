"""Tests for the momentum playbook rules (momo/service.py) and the pure parts
of the option-chain module (scanner/chains.py)."""

import datetime

import pytest

from momo.service import (
    entry_violations,
    exit_alerts,
    scorecard,
    theme_exposure,
)
from scanner.chains import pick_expiry, snap_strike


TODAY = datetime.date(2026, 7, 1)
ACCT = 4_000.0


def _pos(debit: float, theme: str) -> dict:
    return {"entry_debit": debit, "theme": theme}


# ── entry_violations (spec §0/§4 caps) ──────────────────────────────────────

def test_normal_spread_passes():
    assert entry_violations(debit=520.0, theme="software",
                            account_size=ACCT, open_positions=[]) == []


def test_per_position_cap_15pct():
    v = entry_violations(debit=750.0, theme="software",
                         account_size=ACCT, open_positions=[])
    assert len(v) == 1 and "per-position cap" in v[0]


def test_book_full_at_7():
    positions = [_pos(400, f"t{i}") for i in range(7)]
    v = entry_violations(debit=100.0, theme="new",
                         account_size=ACCT, open_positions=positions)
    assert any("Book is full" in x for x in v)


def test_third_position_same_theme_blocked():
    positions = [_pos(400, "AI hardware"), _pos(400, "AI hardware")]
    v = entry_violations(debit=400.0, theme="AI hardware",
                         account_size=ACCT, open_positions=positions)
    assert any("per theme" in x for x in v)


def test_deployment_cap_and_min_cash():
    positions = [_pos(600, f"t{i}") for i in range(5)]   # $3,000 deployed
    v = entry_violations(debit=601.0, theme="new",
                         account_size=ACCT, open_positions=positions)
    assert any("deployment cap" in x for x in v)
    assert any("cash free" in x for x in v)


def test_nonpositive_debit_rejected():
    assert entry_violations(debit=0.0, theme="x", account_size=ACCT,
                            open_positions=[]) == ["Debit must be positive."]


# ── theme_exposure (spec §4 meter) ──────────────────────────────────────────

def test_theme_exposure_readout():
    positions = [_pos(500, "AI hardware"), _pos(480, "AI hardware"), _pos(520, "energy")]
    themes = theme_exposure(positions)
    ai = next(t for t in themes if t["theme"] == "AI hardware")
    assert ai["count"] == 2
    assert ai["dollars"] == pytest.approx(980.0)
    assert ai["pct_of_deployed"] == pytest.approx(980 / 1500 * 100, abs=0.1)


# ── exit_alerts (spec §4 rules) ─────────────────────────────────────────────

def test_profit_exit_at_75pct_of_max():
    a = exit_alerts(current_value=1125.0, max_value=1500.0, dte=200, rank=3)
    assert a["profit_exit"] is True and a["pct_of_max"] == pytest.approx(75.0)
    b = exit_alerts(current_value=1100.0, max_value=1500.0, dte=200, rank=3)
    assert b["profit_exit"] is False


def test_signal_exit_when_out_of_top10():
    assert exit_alerts(current_value=100, max_value=1500, dte=200, rank=11)["signal_exit"]
    assert not exit_alerts(current_value=100, max_value=1500, dte=200, rank=10)["signal_exit"]
    assert exit_alerts(current_value=100, max_value=1500, dte=200, rank=None)["signal_exit"]


def test_dte_warning_under_45():
    assert exit_alerts(current_value=0, max_value=1500, dte=44, rank=1)["dte_warning"]
    assert not exit_alerts(current_value=0, max_value=1500, dte=45, rank=1)["dte_warning"]


# ── scorecard (spec §4 — adherence first) ───────────────────────────────────

def test_scorecard_adherence_and_pnl():
    closed = [
        {"realized_pnl": 300.0, "rule_triggered": True},
        {"realized_pnl": -200.0, "rule_triggered": True},
        {"realized_pnl": 150.0, "rule_triggered": False},   # discretionary
    ]
    s = scorecard(closed)
    assert s["n_closed"] == 3
    assert s["total_pnl"] == pytest.approx(250.0)
    assert s["win_rate"] == pytest.approx(66.7, abs=0.1)
    assert s["avg_win"] == pytest.approx(225.0)
    assert s["avg_loss"] == pytest.approx(-200.0)
    assert s["adherence_pct"] == pytest.approx(66.7, abs=0.1)


def test_scorecard_empty():
    assert scorecard([])["adherence_pct"] is None


# ── chains: pure helpers (spec §3) ──────────────────────────────────────────

def test_pick_expiry_nearest_in_6_to_12mo_window():
    exps = ["2026-07-17", "2026-09-18", "2026-12-18", "2027-03-19", "2027-09-17"]
    # 2026-12-18 is 170 DTE from 2026-07-01 — first inside [150, 365].
    assert pick_expiry(exps, TODAY) == "2026-12-18"


def test_pick_expiry_none_when_no_window_match():
    assert pick_expiry(["2026-07-17", "2026-08-21"], TODAY) is None


def test_snap_strike():
    assert snap_strike([90, 95, 100, 105, 110], 103.9) == 105
    assert snap_strike([], 100.0) is None

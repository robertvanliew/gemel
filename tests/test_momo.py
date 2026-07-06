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
from scanner.chains import budget_spread_from_legs, pick_expiry, snap_strike


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


# ── chains: budget-solved spread from real legs (§8.1) ──────────────────────

def _legs():
    """Tight, liquid synthetic chain. debit_ask vs 105-long: 110→$230,
    115→$380, 120→$500, 125→$590."""
    return [
        {"strike": 105.0, "bid": 10.0, "ask": 10.2, "oi": 500},
        {"strike": 110.0, "bid": 7.9, "ask": 8.1, "oi": 400},
        {"strike": 115.0, "bid": 6.4, "ask": 6.6, "oi": 300},
        {"strike": 120.0, "bid": 5.2, "ask": 5.4, "oi": 250},
        {"strike": 125.0, "bid": 4.3, "ask": 4.5, "oi": 200},
    ]


def test_budget_picks_widest_affordable_width():
    q = budget_spread_from_legs(_legs(), 105.0, budget=550.0, cap=600.0)
    assert q["ok"] is True
    assert q["long_strike"] == 105.0
    assert q["short_strike"] == 120.0          # $500 fits; 125 would be $590 > $550
    assert q["debit_ask"] == pytest.approx(500.0)
    assert q["max_value"] == pytest.approx(1500.0)
    assert q["liquid"] is True


def test_budget_over_cap_when_even_min_width_too_dear():
    q = budget_spread_from_legs(_legs(), 105.0, budget=150.0, cap=200.0)
    assert q["ok"] is False and "over cap" in q["reason"]


def test_budget_rr_numbers_available_for_the_floor_gate():
    q = budget_spread_from_legs(_legs(), 105.0, budget=550.0, cap=600.0)
    # candidates gate checks max_profit_mid >= 1.5x debit_mid — fields must exist
    assert q["max_profit_mid"] / q["debit_mid"] > 1.5


def test_budget_dead_chain():
    assert budget_spread_from_legs([], 105.0)["ok"] is False
    one = [{"strike": 105.0, "bid": 10.0, "ask": 10.2, "oi": 500}]
    assert budget_spread_from_legs(one, 105.0)["ok"] is False


def test_budget_respects_moneyness_ceiling():
    # §8.4: with a ceiling at 118, the picker must stop at 115 even though the
    # 120 short still fits the budget.
    q = budget_spread_from_legs(_legs(), 105.0, budget=550.0, cap=600.0,
                                short_ceiling=118.0)
    assert q["ok"] is True
    assert q["short_strike"] == 115.0


def test_budget_quote_ships_leg_prices_and_payout_flag():
    q = budget_spread_from_legs(_legs(), 105.0, budget=550.0, cap=600.0)
    # §8.6: per-leg prices for broker verification
    assert q["long_ask"] == pytest.approx(10.2)
    assert q["short_bid"] == pytest.approx(5.2)
    # §8.4: payout flag present (this structure is ~2.1x — not outsized)
    assert q["rr_outsized"] is False


def test_budget_after_hours_falls_back_to_last_trade():
    """Market closed: bid/ask are 0 but lastPrice exists — Julie's Sunday
    session must still get planning numbers, flagged stale, OI-only liquidity."""
    legs = [
        {"strike": 105.0, "bid": 0.0, "ask": 0.0, "oi": 500, "last": 10.1},
        {"strike": 110.0, "bid": 0.0, "ask": 0.0, "oi": 400, "last": 8.0},
        {"strike": 120.0, "bid": 0.0, "ask": 0.0, "oi": 250, "last": 5.3},
    ]
    q = budget_spread_from_legs(legs, 105.0, budget=550.0, cap=600.0)
    assert q["ok"] is True and q["stale"] is True
    assert q["short_strike"] == 120.0            # (10.1-5.3)*100 = $480 fits
    assert q["debit_ask"] == pytest.approx(480.0)
    assert q["spread_width_pct"] is None          # width unverifiable after hours
    assert q["liquid"] is True                    # OI-only gate
    assert "market closed" in q["liquidity_detail"]
    # OI still gates when stale
    legs_thin = [dict(l, oi=5) for l in legs]
    assert budget_spread_from_legs(legs_thin, 105.0)["liquid"] is False

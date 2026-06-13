import pytest
from datetime import datetime, timezone
from sqlmodel import Session
from core.db import make_engine, init_db

@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        yield s

def _make_closed_trade(session, pnl, closed_at, ticker="SPY", opened_at=None):
    """Helper to create a closed trade directly."""
    from journal.service import open_trade, close_trade
    if opened_at is None:
        opened_at = closed_at
    t = open_trade(
        session,
        ticker=ticker,
        strategy="test",
        opened_at=opened_at,
        credit_debit=1.0,
        reason_for_entry="test",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    close_trade(session, t.id, exit_price=0.5, exit_reason="test", pnl=pnl, closed_at=closed_at)
    return t

# Test 1: Empty DB
def test_empty_db(session):
    from analytics.service import compute_analytics
    result = compute_analytics(session)
    assert result["n_trades"] == 0
    assert result["win_rate"] == 0
    assert result["profit_factor"] == 0
    assert result["scaling_gate"]["green"] is False
    assert result["equity_curve"] == []
    assert result["adherence_over_time"] == []
    assert result["avg_adherence"] == 0.0

# Test 2: Known set of wins and losses
def test_known_set(session):
    from analytics.service import compute_analytics
    base = datetime(2024, 1, 1)
    _make_closed_trade(session, 100.0,  datetime(2024, 1, 1))
    _make_closed_trade(session, 120.0,  datetime(2024, 1, 2))
    _make_closed_trade(session, 80.0,   datetime(2024, 1, 3))
    _make_closed_trade(session, -90.0,  datetime(2024, 1, 4))
    _make_closed_trade(session, -110.0, datetime(2024, 1, 5))

    result = compute_analytics(session)
    assert result["n_trades"] == 5
    assert result["win_rate"] == pytest.approx(60.0)
    assert result["avg_win"] == pytest.approx(100.0)
    assert result["avg_loss"] == pytest.approx(-100.0)
    assert result["profit_factor"] == pytest.approx(1.5)

# Test 3: max_drawdown
def test_max_drawdown(session):
    from analytics.service import compute_analytics
    _make_closed_trade(session, 100.0,  datetime(2024, 1, 1))
    _make_closed_trade(session, -150.0, datetime(2024, 1, 2))
    _make_closed_trade(session, 50.0,   datetime(2024, 1, 3))

    result = compute_analytics(session)
    # equity: [100, -50, 0]; peak: [100, 100, 100]; dd: [0, -150, -100]; min = -150
    assert result["max_drawdown"] == pytest.approx(-150.0)

# Test 4a: scaling_gate green=True (adherence >= 90 AND total pnl > 0)
def test_scaling_gate_green(session):
    from analytics.service import compute_analytics
    from journal.service import set_rules
    t1_id = _make_closed_trade(session, 100.0, datetime(2024, 1, 1)).id
    set_rules(session, t1_id, [
        {"rule_key": "r1", "rule_label": "Rule 1", "followed": True},
        {"rule_key": "r2", "rule_label": "Rule 2", "followed": True},
    ])
    result = compute_analytics(session)
    assert result["scaling_gate"]["green"] is True
    assert "green" in result["scaling_gate"]["reason"].lower() or result["scaling_gate"]["green"]

# Test 4b: scaling_gate green=False when pnl negative despite high adherence
def test_scaling_gate_green_false_negative_pnl(session):
    from analytics.service import compute_analytics
    from journal.service import set_rules
    t1_id = _make_closed_trade(session, -100.0, datetime(2024, 1, 1)).id
    set_rules(session, t1_id, [
        {"rule_key": "r1", "rule_label": "Rule 1", "followed": True},
        {"rule_key": "r2", "rule_label": "Rule 2", "followed": True},
    ])
    result = compute_analytics(session)
    assert result["scaling_gate"]["green"] is False

# Test 4c: scaling_gate green=False when pnl positive but adherence < 90
def test_scaling_gate_green_false_low_adherence(session):
    from analytics.service import compute_analytics
    from journal.service import set_rules
    t1_id = _make_closed_trade(session, 100.0, datetime(2024, 1, 1)).id
    # 4 of 5 = 80% adherence
    set_rules(session, t1_id, [
        {"rule_key": "r1", "rule_label": "Rule 1", "followed": True},
        {"rule_key": "r2", "rule_label": "Rule 2", "followed": True},
        {"rule_key": "r3", "rule_label": "Rule 3", "followed": True},
        {"rule_key": "r4", "rule_label": "Rule 4", "followed": True},
        {"rule_key": "r5", "rule_label": "Rule 5", "followed": False},
    ])
    result = compute_analytics(session)
    assert result["avg_adherence"] == pytest.approx(80.0)
    assert result["scaling_gate"]["green"] is False

# Test 5: last_n limits to most recent n closed trades
def test_last_n(session):
    from analytics.service import compute_analytics
    _make_closed_trade(session, 200.0, datetime(2024, 1, 1))
    _make_closed_trade(session, 100.0, datetime(2024, 1, 2))
    _make_closed_trade(session, -50.0, datetime(2024, 1, 3))

    result = compute_analytics(session, last_n=2)
    assert result["n_trades"] == 2
    # Most recent 2: +100 and -50
    assert result["win_rate"] == pytest.approx(50.0)

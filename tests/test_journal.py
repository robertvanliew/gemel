import pytest
from datetime import datetime, timezone
from sqlmodel import Session, select
from core.db import make_engine, init_db, Campaign, Trade

@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        yield s

# Test 1: open_trade happy path
def test_open_trade_happy_path(session):
    from journal.service import open_trade
    t = open_trade(
        session,
        ticker="SPY",
        strategy="put_spread",
        opened_at=datetime(2024, 1, 10, 10, 0, tzinfo=timezone.utc),
        credit_debit=1.50,
        reason_for_entry="High IV",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    assert t.id is not None
    assert t.status == "open"
    assert t.ticker == "SPY"
    assert t.credit_debit == 1.50

# Test 2: open_trade with empty profit_target raises ValueError
def test_open_trade_missing_exit_plan_raises(session):
    from journal.service import open_trade
    with pytest.raises(ValueError, match="exit plan"):
        open_trade(
            session,
            ticker="SPY",
            strategy="put_spread",
            opened_at=datetime(2024, 1, 10, 10, 0),
            credit_debit=1.50,
            reason_for_entry="High IV",
            profit_target="",
            stop="2x",
            time_stop="21 DTE",
        )

# Test 3: open_trade with None stop raises ValueError
def test_open_trade_none_stop_raises(session):
    from journal.service import open_trade
    with pytest.raises(ValueError, match="exit plan"):
        open_trade(
            session,
            ticker="SPY",
            strategy="put_spread",
            opened_at=datetime(2024, 1, 10, 10, 0),
            credit_debit=1.50,
            reason_for_entry="High IV",
            profit_target="50%",
            stop=None,
            time_stop="21 DTE",
        )

# Test 4: close_trade
def test_close_trade(session):
    from journal.service import open_trade, close_trade
    t = open_trade(
        session,
        ticker="AAPL",
        strategy="covered_call",
        opened_at=datetime(2024, 1, 10),
        credit_debit=2.00,
        reason_for_entry="Neutral",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    closed = close_trade(
        session,
        t.id,
        exit_price=0.50,
        exit_reason="Profit target hit",
        pnl=150.0,
        closed_at=datetime(2024, 2, 1),
    )
    assert closed.status == "closed"
    assert closed.pnl == 150.0
    assert closed.exit_price == 0.50
    assert closed.exit_reason == "Profit target hit"
    assert closed.closed_at == datetime(2024, 2, 1)

# Test 5: close_trade missing id raises ValueError
def test_close_trade_missing_id_raises(session):
    from journal.service import close_trade
    with pytest.raises(ValueError):
        close_trade(
            session,
            9999,
            exit_price=1.0,
            exit_reason="x",
            pnl=0.0,
            closed_at=datetime(2024, 2, 1),
        )

# Test 6: set_rules replaces (not duplicates), adherence_pct
def test_set_rules_replaces_and_adherence(session):
    from journal.service import open_trade, set_rules, adherence_pct
    t = open_trade(
        session,
        ticker="SPY",
        strategy="iron_condor",
        opened_at=datetime(2024, 1, 10),
        credit_debit=1.00,
        reason_for_entry="Range",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    # First call
    set_rules(session, t.id, [
        {"rule_key": "r1", "rule_label": "Rule 1", "followed": True},
        {"rule_key": "r2", "rule_label": "Rule 2", "followed": False},
    ])
    # Second call replaces
    rules = set_rules(session, t.id, [
        {"rule_key": "r1", "rule_label": "Rule 1", "followed": True},
        {"rule_key": "r2", "rule_label": "Rule 2", "followed": True},
        {"rule_key": "r3", "rule_label": "Rule 3", "followed": True},
        {"rule_key": "r4", "rule_label": "Rule 4", "followed": False},
    ])
    assert len(rules) == 4  # not 6
    pct = adherence_pct(session, t.id)
    assert pct == 75.0  # 3 of 4

# Test 7: adherence_pct returns None when no rules
def test_adherence_pct_no_rules_returns_none(session):
    from journal.service import open_trade, adherence_pct
    t = open_trade(
        session,
        ticker="SPY",
        strategy="put_spread",
        opened_at=datetime(2024, 1, 10),
        credit_debit=1.00,
        reason_for_entry="High IV",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    assert adherence_pct(session, t.id) is None

# Test 8: list_open / list_closed partition + ordering
def test_list_open_closed_partition(session):
    from journal.service import open_trade, close_trade, list_open, list_closed
    t1 = open_trade(
        session,
        ticker="SPY",
        strategy="A",
        opened_at=datetime(2024, 1, 1),
        credit_debit=1.00,
        reason_for_entry="x",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    t2 = open_trade(
        session,
        ticker="QQQ",
        strategy="B",
        opened_at=datetime(2024, 1, 5),
        credit_debit=2.00,
        reason_for_entry="y",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
    )
    close_trade(session, t1.id, exit_price=0.5, exit_reason="TP", pnl=50.0, closed_at=datetime(2024, 2, 1))

    open_trades = list_open(session)
    closed_trades = list_closed(session)

    open_ids = [t.id for t in open_trades]
    closed_ids = [t.id for t in closed_trades]
    assert t2.id in open_ids
    assert t1.id not in open_ids
    assert t1.id in closed_ids
    assert t2.id not in closed_ids

# Test 9: list_campaigns sums net_pnl
def test_list_campaigns_net_pnl(session):
    from journal.service import open_trade, close_trade, list_campaigns
    camp = Campaign(
        ticker="SPY",
        strategy="IC",
        opened_at=datetime(2024, 1, 1),
        status="open",
    )
    session.add(camp)
    session.commit()
    session.refresh(camp)

    leg1 = open_trade(
        session,
        ticker="SPY",
        strategy="IC",
        opened_at=datetime(2024, 1, 1),
        credit_debit=1.00,
        reason_for_entry="x",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
        campaign_id=camp.id,
    )
    leg2 = open_trade(
        session,
        ticker="SPY",
        strategy="IC",
        opened_at=datetime(2024, 1, 2),
        credit_debit=2.00,
        reason_for_entry="y",
        profit_target="50%",
        stop="2x",
        time_stop="21 DTE",
        campaign_id=camp.id,
    )
    close_trade(session, leg1.id, exit_price=0.5, exit_reason="TP", pnl=-54.0, closed_at=datetime(2024, 2, 1))
    close_trade(session, leg2.id, exit_price=0.5, exit_reason="TP", pnl=118.0, closed_at=datetime(2024, 2, 2))

    campaigns = list_campaigns(session)
    assert len(campaigns) == 1
    camp_dict = campaigns[0]
    assert camp_dict["net_pnl"] == pytest.approx(64.0)
    assert len(camp_dict["legs"]) == 2

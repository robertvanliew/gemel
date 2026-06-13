from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core.db import Campaign, Trade, TradeRule, make_engine, init_db


@pytest.fixture
def session():
    engine = make_engine("sqlite://")  # in-memory
    init_db(engine)
    with Session(engine) as s:
        yield s


def _valid_trade(**overrides):
    base = dict(
        ticker="SPY",
        strategy="bull_put_spread",
        opened_at=datetime(2026, 6, 1, 10, 0),
        is_paper=True,
        qty=1,
        short_strike=575.0,
        long_strike=570.0,
        credit_debit=1.42,
        delta_at_entry=0.18,
        dte_at_entry=38,
        reason_for_entry="above 20/50 EMA, RSI 58",
        profit_target="buy back at 50% (0.71)",
        stop="2x credit (2.84)",
        time_stop="close or roll at 21 DTE",
        status="open",
    )
    base.update(overrides)
    return Trade(**base)


def test_round_trip_trade_with_rules(session):
    trade = _valid_trade()
    session.add(trade)
    session.commit()
    session.add(TradeRule(trade_id=trade.id, rule_key="above_emas", rule_label="Above 20/50 EMA", followed=True))
    session.commit()

    loaded = session.exec(select(Trade)).one()
    assert loaded.short_strike == 575.0
    rules = session.exec(select(TradeRule)).all()
    assert len(rules) == 1 and rules[0].followed is True


def test_exit_plan_is_required_at_schema_level(session):
    # profit_target / stop / time_stop are NOT NULL: the journal's
    # "won't save without an exit plan" rule is enforced by the schema.
    session.add(_valid_trade(profit_target=None))
    with pytest.raises(IntegrityError):
        session.commit()


def test_campaign_links_rolled_trades(session):
    camp = Campaign(ticker="QQQ", strategy="bull_put_spread", opened_at=datetime(2026, 4, 14), status="closed")
    session.add(camp)
    session.commit()
    session.add(_valid_trade(ticker="QQQ", campaign_id=camp.id, status="closed", pnl=-54.0))
    session.add(_valid_trade(ticker="QQQ", campaign_id=camp.id, status="closed", pnl=118.0))
    session.commit()

    legs = session.exec(select(Trade).where(Trade.campaign_id == camp.id)).all()
    assert sum(t.pnl for t in legs) == pytest.approx(64.0)

from datetime import datetime
from sqlmodel import Session, select
from core.db import Trade, TradeRule, Campaign


def open_trade(
    session: Session,
    *,
    ticker: str,
    strategy: str,
    opened_at: datetime,
    credit_debit: float,
    reason_for_entry: str,
    profit_target: str,
    stop: str,
    time_stop: str,
    is_paper: bool = True,
    qty: int = 1,
    short_strike: float | None = None,
    long_strike: float | None = None,
    delta_at_entry: float | None = None,
    dte_at_entry: int | None = None,
    campaign_id: int | None = None,
) -> Trade:
    if not profit_target or not stop or not time_stop:
        raise ValueError("exit plan required: profit_target, stop, time_stop")
    trade = Trade(
        ticker=ticker,
        strategy=strategy,
        opened_at=opened_at,
        credit_debit=credit_debit,
        reason_for_entry=reason_for_entry,
        profit_target=profit_target,
        stop=stop,
        time_stop=time_stop,
        is_paper=is_paper,
        qty=qty,
        short_strike=short_strike,
        long_strike=long_strike,
        delta_at_entry=delta_at_entry,
        dte_at_entry=dte_at_entry,
        campaign_id=campaign_id,
        status="open",
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return trade


def close_trade(
    session: Session,
    trade_id: int,
    *,
    exit_price: float,
    exit_reason: str,
    pnl: float,
    closed_at: datetime,
) -> Trade:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise ValueError(f"Trade {trade_id} not found")
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason
    trade.pnl = pnl
    trade.closed_at = closed_at
    trade.status = "closed"
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return trade


def set_rules(session: Session, trade_id: int, rules: list[dict]) -> list[TradeRule]:
    # Delete existing rules for this trade
    existing = session.exec(select(TradeRule).where(TradeRule.trade_id == trade_id)).all()
    for rule in existing:
        session.delete(rule)
    session.commit()
    # Insert new rules
    new_rules = []
    for r in rules:
        rule = TradeRule(
            trade_id=trade_id,
            rule_key=r["rule_key"],
            rule_label=r["rule_label"],
            followed=r["followed"],
        )
        session.add(rule)
        new_rules.append(rule)
    session.commit()
    for rule in new_rules:
        session.refresh(rule)
    return new_rules


def adherence_pct(session: Session, trade_id: int) -> float | None:
    rules = session.exec(select(TradeRule).where(TradeRule.trade_id == trade_id)).all()
    if not rules:
        return None
    followed = sum(1 for r in rules if r.followed)
    return (followed / len(rules)) * 100.0


def list_open(session: Session) -> list[Trade]:
    return session.exec(
        select(Trade).where(Trade.status == "open").order_by(Trade.opened_at.desc())
    ).all()


def list_closed(session: Session) -> list[Trade]:
    return session.exec(
        select(Trade).where(Trade.status == "closed").order_by(Trade.closed_at.desc())
    ).all()


def list_campaigns(session: Session) -> list[dict]:
    campaigns = session.exec(select(Campaign)).all()
    result = []
    for camp in campaigns:
        legs = session.exec(select(Trade).where(Trade.campaign_id == camp.id)).all()
        net_pnl = sum(leg.pnl or 0.0 for leg in legs)
        result.append({"campaign": camp, "legs": list(legs), "net_pnl": net_pnl})
    return result

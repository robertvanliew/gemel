"""Momentum paper book — DB operations. Rules live in momo/service.py; this
layer records what happened and mirrors every open/close into the journal so
the momentum book shows up in adherence review like everything else.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Session, select

from core.db import MomoPosition
from journal import service as journal
from momo.service import PROFIT_EXIT_PCT, SIGNAL_EXIT_RANK, DTE_WARN


def list_open(session: Session) -> list[MomoPosition]:
    return session.exec(select(MomoPosition)
                        .where(MomoPosition.status == "open")
                        .order_by(MomoPosition.opened_at.desc())).all()


def list_closed(session: Session) -> list[MomoPosition]:
    return session.exec(select(MomoPosition)
                        .where(MomoPosition.status == "closed")
                        .order_by(MomoPosition.closed_at.desc())).all()


def open_position(
    session: Session,
    *,
    ticker: str,
    theme: str,
    long_strike: float,
    short_strike: float,
    expiry: date,
    entry_debit: float,   # total $, ask-side
    qty: int = 1,
) -> MomoPosition:
    """Record the paper fill + auto-journal it with the playbook's standing
    exit plan (spec §4: journal entry on every paper open with rule state)."""
    now = datetime.now()
    max_value = (short_strike - long_strike) * 100.0 * qty
    t = journal.open_trade(
        session,
        ticker=ticker,
        strategy="call_debit_spread",
        opened_at=now,
        credit_debit=-round(entry_debit / (100.0 * qty), 2),  # per-share, debit = negative
        reason_for_entry=f"Momentum playbook: monthly re-rank leader ({theme})",
        profit_target=f"close at ≥{PROFIT_EXIT_PCT:.0f}% of max value (${max_value * PROFIT_EXIT_PCT / 100:,.0f})",
        stop=f"signal exit — falls out of top {SIGNAL_EXIT_RANK} at the monthly re-rank",
        time_stop=f"close before {DTE_WARN} DTE — pin risk",
        is_paper=True,
        qty=qty,
        short_strike=short_strike,
        long_strike=long_strike,
        dte_at_entry=(expiry - now.date()).days,
    )
    pos = MomoPosition(
        ticker=ticker, theme=theme,
        long_strike=long_strike, short_strike=short_strike,
        expiry=expiry, qty=qty,
        entry_debit=round(entry_debit, 2), max_value=round(max_value, 2),
        opened_at=now, journal_trade_id=t.id,
    )
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return pos


def close_position(
    session: Session,
    position_id: int,
    *,
    exit_value: float,    # total $, bid-side
    exit_rule: str,       # profit | signal | dte | discretionary
    rule_triggered: bool,
) -> MomoPosition:
    pos = session.get(MomoPosition, position_id)
    if pos is None or pos.status != "open":
        raise ValueError(f"Open momentum position {position_id} not found")
    now = datetime.now()
    pos.closed_at = now
    pos.exit_value = round(exit_value, 2)
    pos.realized_pnl = round(exit_value - pos.entry_debit, 2)
    pos.exit_rule = exit_rule
    pos.rule_triggered = rule_triggered
    pos.status = "closed"
    session.add(pos)
    if pos.journal_trade_id:
        journal.close_trade(
            session, pos.journal_trade_id,
            exit_price=round(exit_value / (100.0 * pos.qty), 2),
            exit_reason=f"{exit_rule} exit ({'rule-triggered' if rule_triggered else 'discretionary'})",
            pnl=pos.realized_pnl,
            closed_at=now,
        )
    session.commit()
    session.refresh(pos)
    return pos

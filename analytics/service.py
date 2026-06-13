from sqlmodel import Session, select
from core.db import Trade, TradeRule
from journal.service import adherence_pct


def compute_analytics(session: Session, last_n: int | None = None) -> dict:
    # Get all closed trades with pnl, ordered by closed_at ascending
    trades = session.exec(
        select(Trade)
        .where(Trade.status == "closed")
        .where(Trade.pnl != None)
        .order_by(Trade.closed_at.asc())
    ).all()

    if last_n is not None:
        trades = trades[-last_n:]

    n_trades = len(trades)

    if n_trades == 0:
        return {
            "n_trades": 0,
            "win_rate": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0,
            "max_drawdown": 0.0,
            "equity_curve": [],
            "adherence_over_time": [],
            "avg_adherence": 0.0,
            "scaling_gate": {
                "green": False,
                "reason": "No closed trades to evaluate.",
            },
        }

    winners = [t.pnl for t in trades if t.pnl > 0]
    losers = [t.pnl for t in trades if t.pnl < 0]

    win_rate = (len(winners) / n_trades) * 100.0
    avg_win = sum(winners) / len(winners) if winners else 0.0
    avg_loss = sum(losers) / len(losers) if losers else 0.0

    gross_win = sum(winners)
    gross_loss = abs(sum(losers))
    if gross_loss == 0:
        profit_factor = 999.0 if gross_win > 0 else 0.0
    else:
        profit_factor = gross_win / gross_loss

    # Equity curve
    equity_curve = []
    cumulative = 0.0
    for t in trades:
        cumulative += t.pnl
        equity_curve.append({
            "date": t.closed_at.date().isoformat(),
            "equity": cumulative,
        })

    # Max drawdown
    peak = float("-inf")
    min_drawdown = 0.0
    running = 0.0
    for t in trades:
        running += t.pnl
        if running > peak:
            peak = running
        dd = running - peak
        if dd < min_drawdown:
            min_drawdown = dd
    max_drawdown = min_drawdown

    # Adherence over time
    adherence_over_time = []
    for t in trades:
        pct = adherence_pct(session, t.id)
        if pct is not None:
            adherence_over_time.append({
                "date": t.closed_at.date().isoformat(),
                "adherence": pct,
            })

    avg_adherence = (
        sum(a["adherence"] for a in adherence_over_time) / len(adherence_over_time)
        if adherence_over_time
        else 0.0
    )

    total_pnl = sum(t.pnl for t in trades)
    green = avg_adherence >= 90.0 and total_pnl > 0
    if green:
        reason = f"Scaling gate is GREEN: avg adherence {avg_adherence:.1f}% >= 90% and total PnL ${total_pnl:.2f} > 0."
    else:
        reasons = []
        if avg_adherence < 90.0:
            reasons.append(f"avg adherence {avg_adherence:.1f}% < 90%")
        if total_pnl <= 0:
            reasons.append(f"total PnL ${total_pnl:.2f} <= 0")
        reason = "Scaling gate is RED: " + "; ".join(reasons) + "."

    return {
        "n_trades": n_trades,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "equity_curve": equity_curve,
        "adherence_over_time": adherence_over_time,
        "avg_adherence": avg_adherence,
        "scaling_gate": {
            "green": green,
            "reason": reason,
        },
    }

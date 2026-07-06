"""Momentum playbook paper book — pure rules, no I/O.

The playbook's standing decisions (spec §0, signed off before anything runs):
  • per-position cap 15% of the momentum account — above the ~12.5-14% a
    normal $500-570 spread needs on $4k, tight enough that a $750+ spread
    forces a smaller book
  • total deployment ≤ 90% of account, and ≥ $400 cash always free
  • ≤ 7 simultaneous positions, ≤ 2 per theme
  • position count follows qualifying opportunities, never the reverse —
    cash is a position
  • exits: spread ≥ 75% of max value (profit) · falls out of the ranking's
    top N at the monthly re-rank (signal) · warn under 45 DTE (pin risk)

Adherence — did exits match a triggered rule? — is the readiness metric for
going live, not P&L.
"""
from __future__ import annotations

from typing import Any

# Playbook constants (spec §0/§4). Account size comes from the caller (env).
CAP_PCT = 0.15
DEPLOY_CAP_PCT = 0.90
MIN_CASH = 400.0
MAX_POSITIONS = 7
MAX_PER_THEME = 2
PROFIT_EXIT_PCT = 75.0     # % of max value
SIGNAL_EXIT_RANK = 10      # held name below this rank at re-rank -> signal exit
DTE_WARN = 45


def entry_violations(
    *,
    debit: float,
    theme: str,
    account_size: float,
    open_positions: list[dict[str, Any]],
) -> list[str]:
    """Every rule the proposed entry would break (empty list = clear to open).

    `open_positions` rows need {"entry_debit": $, "theme": str}.
    """
    v: list[str] = []
    cap = account_size * CAP_PCT
    if debit <= 0:
        v.append("Debit must be positive.")
        return v
    if debit > cap:
        v.append(f"${debit:,.0f} is {debit / account_size * 100:.1f}% of the account — "
                 f"over the momentum playbook's {CAP_PCT * 100:.0f}% per-position cap "
                 f"(${cap:,.0f}). A pricier spread means a smaller book, not a bigger cap.")
    if len(open_positions) >= MAX_POSITIONS:
        v.append(f"Book is full ({MAX_POSITIONS} positions). Cash is a position — "
                 "close something on a rule before opening more.")
    deployed = sum(p["entry_debit"] for p in open_positions)
    if deployed + debit > account_size * DEPLOY_CAP_PCT:
        v.append(f"Would deploy ${deployed + debit:,.0f} of ${account_size:,.0f} — over the "
                 f"{DEPLOY_CAP_PCT * 100:.0f}% total deployment cap.")
    if account_size - (deployed + debit) < MIN_CASH:
        v.append(f"Would leave under ${MIN_CASH:,.0f} cash free.")
    same_theme = sum(1 for p in open_positions if p["theme"] == theme)
    if same_theme >= MAX_PER_THEME:
        v.append(f"Already {same_theme} open in “{theme}” — max {MAX_PER_THEME} per theme.")
    return v


def theme_exposure(open_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live concentration readout: per theme — count, dollars, % of deployed."""
    deployed = sum(p["entry_debit"] for p in open_positions) or 1.0
    themes: dict[str, dict[str, Any]] = {}
    for p in open_positions:
        t = themes.setdefault(p["theme"], {"theme": p["theme"], "count": 0, "dollars": 0.0})
        t["count"] += 1
        t["dollars"] += p["entry_debit"]
    out = sorted(themes.values(), key=lambda t: -t["dollars"])
    for t in out:
        t["pct_of_deployed"] = round(t["dollars"] / deployed * 100, 1)
        t["dollars"] = round(t["dollars"], 2)
    return out


def exit_alerts(
    *,
    current_value: float,
    max_value: float,
    dte: int,
    rank: int | None,
) -> dict[str, Any]:
    """Rule state for one open position. `rank` is the name's rank in the
    latest re-rank (None = ranking not run / name absent -> treated as fallen out)."""
    pct_of_max = 0.0 if max_value <= 0 else current_value / max_value * 100.0
    profit = pct_of_max >= PROFIT_EXIT_PCT
    signal = rank is None or rank > SIGNAL_EXIT_RANK
    return {
        "pct_of_max": round(pct_of_max, 1),
        "profit_exit": profit,
        "signal_exit": signal,
        "dte_warning": dte < DTE_WARN,
        "any_rule": profit or signal or dte < DTE_WARN,
    }


def scorecard(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Running results + the metric that decides live-readiness: adherence %.

    `closed` rows need {"realized_pnl": $, "rule_triggered": bool|None}.
    """
    n = len(closed)
    if n == 0:
        return {"n_closed": 0, "total_pnl": 0.0, "win_rate": None,
                "avg_win": None, "avg_loss": None, "adherence_pct": None}
    wins = [p["realized_pnl"] for p in closed if p["realized_pnl"] > 0]
    losses = [p["realized_pnl"] for p in closed if p["realized_pnl"] <= 0]
    ruled = sum(1 for p in closed if p.get("rule_triggered"))
    return {
        "n_closed": n,
        "total_pnl": round(sum(p["realized_pnl"] for p in closed), 2),
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "adherence_pct": round(ruled / n * 100, 1),
    }

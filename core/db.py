"""SQLite schema via SQLModel. Holds decisions and results only — price bars
live in the parquet cache. The exit-plan fields on Trade are NOT NULL by
design: 'the plan is written when you're calm' is enforced by the schema.
"""
from datetime import datetime

from sqlmodel import Field, SQLModel, create_engine


class Campaign(SQLModel, table=True):
    """A chain of rolled positions judged as one trade idea."""
    id: int | None = Field(default=None, primary_key=True)
    ticker: str
    strategy: str
    opened_at: datetime
    closed_at: datetime | None = None
    status: str = "open"  # open | closed


class Trade(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id")
    ticker: str
    strategy: str  # bull_put_spread | cash_secured_put | long_option
    opened_at: datetime
    closed_at: datetime | None = None
    is_paper: bool = True
    qty: int = 1
    short_strike: float | None = None
    long_strike: float | None = None   # None for single-leg strategies
    credit_debit: float                # +credit collected / -debit paid, per share
    delta_at_entry: float | None = None
    dte_at_entry: int | None = None
    reason_for_entry: str
    # exit plan — required, not optional (journal hard rule)
    profit_target: str = Field(nullable=False)
    stop: str = Field(nullable=False)
    time_stop: str = Field(nullable=False)
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl: float | None = None           # realized, dollars, set at close
    status: str = "open"               # open | closed


class TradeRule(SQLModel, table=True):
    """One checklist row per rule per trade -> adherence scoring."""
    id: int | None = Field(default=None, primary_key=True)
    trade_id: int = Field(foreign_key="trade.id")
    rule_key: str
    rule_label: str
    followed: bool


class BacktestRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)
    strategy: str
    ticker: str
    params_json: str          # JSON: delta band, DTE, frictions...
    date_start: datetime
    date_end: datetime
    oos_start: datetime       # in-sample/out-of-sample boundary
    stats_json: str           # JSON: win rate, PF, drawdown... (IS and OOS)
    regime_stats_json: str    # JSON: per-regime breakdown
    sensitivity_json: str     # JSON: delta x DTE grid


class BacktestTrade(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="backtestrun.id")
    opened_at: datetime
    closed_at: datetime
    short_strike: float | None = None
    long_strike: float | None = None
    credit_debit: float
    exit_reason: str
    pnl: float
    regime: str               # trending_up | choppy | declining
    in_sample: bool


class ScanReport(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ran_at: datetime = Field(default_factory=datetime.now)
    master_gate_pass: bool
    regime: str
    playbook: str
    summary_md: str = ""


class ScanResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="scanreport.id")
    ticker: str
    passes_json: str          # JSON: {criterion: bool}
    rsi: float | None = None
    ivr: float | None = None
    metrics_json: str = "{}"
    qualifies: bool = False
    rank: int | None = None
    candidate_json: str | None = None  # strikes/credit/max-loss/BE/target/stop for the top pick


def make_engine(url: str = "sqlite:///data/trading.sqlite"):
    return create_engine(url, connect_args={"check_same_thread": False})


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)

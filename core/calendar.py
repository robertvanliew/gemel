"""Event-risk filter: scheduled events that can gap price through both strikes.

FOMC meeting dates are a static list (8/year, published years ahead by the Fed)
— update annually. Earnings dates come from the data adapter at scan time and
are passed in; ETFs in the core universe have no earnings, but XLK/XLV-style
sector screens treat top-holding earnings clusters as the earnings_date.
"""
from datetime import date

# Second day of each two-day FOMC meeting (the announcement day), 2026.
# Source: federalreserve.gov FOMC calendar. Update each December.
FOMC_DATES: list[date] = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]


def has_event_risk(start: date, expiry: date, earnings_date: date | None) -> bool:
    """True if an FOMC meeting or the given earnings date falls in [start, expiry]."""
    if any(start <= d <= expiry for d in FOMC_DATES):
        return True
    if earnings_date is not None and start <= earnings_date <= expiry:
        return True
    return False

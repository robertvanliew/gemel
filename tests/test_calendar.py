from datetime import date

from core.calendar import FOMC_DATES, has_event_risk


def test_fomc_dates_present_for_2026():
    assert any(d.year == 2026 for d in FOMC_DATES)


def test_fomc_inside_window_is_event_risk():
    fomc = sorted(d for d in FOMC_DATES if d.year == 2026)[0]
    assert has_event_risk(start=fomc, expiry=fomc, earnings_date=None) is True


def test_no_events_means_no_risk():
    assert has_event_risk(start=date(2026, 1, 2), expiry=date(2026, 1, 3), earnings_date=None) is False


def test_earnings_inside_window_is_event_risk():
    assert (
        has_event_risk(start=date(2026, 7, 1), expiry=date(2026, 8, 15), earnings_date=date(2026, 7, 30))
        is True
    )


def test_earnings_after_expiry_is_fine():
    assert (
        has_event_risk(start=date(2026, 7, 1), expiry=date(2026, 7, 10), earnings_date=date(2026, 7, 30))
        is False
    )

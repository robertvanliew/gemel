"""Tests for the disk-backed chain store (§8.5 rework) and chains.py reading
from it — no network anywhere in here."""

import datetime

import pytest

from scanner import chain_store
from scanner.chains import mark_spread, spread_quote


TODAY = datetime.date(2026, 7, 13)


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp dir so every test gets an empty store."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


def _save(ticker="TEST", expiry=None, rows=None):
    expiry = expiry or (datetime.date.today() + datetime.timedelta(days=200)).isoformat()
    # columns: strike, bid, ask, lastPrice, openInterest, volume, impliedVolatility
    rows = rows if rows is not None else [
        [105.0, 10.0, 10.2, 10.1, 500, 60, 0.35],
        [110.0, 7.9, 8.1, 8.0, 400, 50, 0.34],
        [115.0, 6.4, 6.6, 6.5, 300, 40, 0.33],
        [120.0, 5.2, 5.4, 5.3, 250, 30, 0.33],
    ]
    chain_store.save_ticker_data(ticker, {
        "ticker": ticker, "fetched_at": "2026-07-13T10:00:00",
        "spot": 100.0, "expiries": {expiry: rows},
    })
    return expiry


# ── expiry selection ────────────────────────────────────────────────────────

def test_third_friday():
    assert chain_store.third_friday(2026, 12) == datetime.date(2026, 12, 18)
    assert chain_store.third_friday(2027, 1) == datetime.date(2027, 1, 15)


def test_monthly_expiries_in_window_filters_weeklies_and_window():
    exps = ["2026-08-21", "2026-12-11", "2026-12-18", "2027-01-15",
            "2027-03-19", "2027-06-18", "2027-09-17", "2028-01-21"]
    got = chain_store.monthly_expiries_in_window(exps, TODAY)
    # 2026-08-21 is 39 DTE (too near); 2026-12-11 is a weekly (not 3rd Friday);
    # 2027-09-17 is 431 DTE (past 400); 2028 far out.
    assert got == ["2026-12-18", "2027-01-15", "2027-03-19", "2027-06-18"]


def test_monthly_expiries_capped():
    exps = [f"2027-0{m}-15" for m in range(1, 7)]  # not all 3rd Fridays, fine
    got = chain_store.monthly_expiries_in_window(
        ["2026-12-18", "2027-01-15", "2027-03-19", "2027-06-18"], TODAY, max_n=2)
    assert len(got) == 2 and got[0] == "2026-12-18"


# ── save / load / StoredTicker ──────────────────────────────────────────────

def test_roundtrip_and_summary():
    exp = _save("AAA")
    assert chain_store.has("AAA") is True
    assert chain_store.expiries("AAA") == [exp]
    df = chain_store.calls("AAA", exp)
    assert list(df["strike"]) == [105.0, 110.0, 115.0, 120.0]
    s = chain_store.summary()
    assert s["count"] == 1 and s["newest"] == "2026-07-13T10:00:00"


def test_stored_ticker_surface():
    exp = _save("BBB")
    st = chain_store.StoredTicker("bbb")     # case-insensitive
    assert st.options == [exp]
    chain = st.option_chain(exp)
    assert float(chain.calls.iloc[0]["ask"]) == pytest.approx(10.2)
    assert chain.puts.empty


def test_stored_ticker_missing_errors_are_actionable():
    with pytest.raises(ValueError, match="run the monthly chain refresh"):
        chain_store.StoredTicker("NOPE").options
    exp = _save("CCC")
    with pytest.raises(ValueError, match="re-run the chain refresh"):
        chain_store.StoredTicker("CCC").option_chain("1999-01-15")


# ── chains.py reads the store (no network) ─────────────────────────────────

def test_spread_quote_from_saved_chain():
    exp = _save("DDD")
    q = spread_quote("DDD", 105.0, budget=550.0, cap=600.0, spot=100.0)
    assert q["ok"] is True
    assert q["expiry"] == exp
    assert q["long_strike"] == 105.0 and q["short_strike"] == 120.0
    assert q["liquid"] is True


def test_spread_quote_missing_chain_is_actionable_not_a_verdict():
    q = spread_quote("GHOST", 105.0)
    assert q["ok"] is False
    assert "run the monthly chain refresh" in q["reason"]


def test_mark_spread_from_saved_chain():
    exp = _save("EEE")
    m = mark_spread("EEE", 105.0, 120.0, exp)
    assert m["ok"] is True
    # sell long at bid (10.0), buy short back at ask (5.4) -> $460
    assert m["value_bid"] == pytest.approx(460.0)


def test_mark_spread_missing_expiry():
    _save("FFF")
    m = mark_spread("FFF", 105.0, 120.0, "1999-01-15")
    assert m["ok"] is False and "re-run the chain refresh" in m["reason"]

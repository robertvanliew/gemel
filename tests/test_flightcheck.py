"""Tests for flightcheck.service — pre-trade risk math.

All expected values are hand-computed so the test suite acts as a
specification rather than a mirror of the implementation.
"""

import pytest

from flightcheck.service import (
    cap_pct,
    csp_max_loss,
    long_option_max_loss,
    max_loss_for,
    spread_metrics,
    within_cap,
)

# ---------------------------------------------------------------------------
# spread_metrics — basic single contract
# ---------------------------------------------------------------------------

class TestSpreadMetricsBasic:
    def test_width(self):
        result = spread_metrics(575, 570, 1.42)
        assert result["width"] == 5.0

    def test_max_loss_single(self):
        result = spread_metrics(575, 570, 1.42)
        # (5.0 - 1.42) * 100 * 1 = 3.58 * 100 = 358.0
        assert result["max_loss"] == 358.0

    def test_max_profit_single(self):
        result = spread_metrics(575, 570, 1.42)
        # 1.42 * 100 * 1 = 142.0
        assert result["max_profit"] == 142.0

    def test_break_even(self):
        result = spread_metrics(575, 570, 1.42)
        # 575 - 1.42 = 573.58
        assert result["break_even"] == 573.58

    def test_return_on_risk(self):
        result = spread_metrics(575, 570, 1.42)
        # round(1.42 / 3.58, 4) = 0.3966
        assert result["return_on_risk"] == round(1.42 / 3.58, 4)
        assert result["return_on_risk"] == 0.3966

    def test_credit_stored_rounded(self):
        result = spread_metrics(575, 570, 1.42)
        assert result["credit"] == 1.42

    def test_return_shape(self):
        result = spread_metrics(575, 570, 1.42)
        expected_keys = {"width", "credit", "max_profit", "max_loss", "break_even", "return_on_risk"}
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# spread_metrics — qty scaling
# ---------------------------------------------------------------------------

class TestSpreadMetricsQty:
    def test_max_loss_qty3(self):
        result = spread_metrics(575, 570, 1.42, qty=3)
        # 3.58 * 100 * 3 = 1074.0
        assert result["max_loss"] == 1074.0

    def test_max_profit_qty3(self):
        result = spread_metrics(575, 570, 1.42, qty=3)
        # 1.42 * 100 * 3 = 426.0
        assert result["max_profit"] == 426.0


# ---------------------------------------------------------------------------
# spread_metrics — validation errors
# ---------------------------------------------------------------------------

class TestSpreadMetricsValidation:
    def test_credit_exceeds_width_raises(self):
        # credit=6 on width=5 → invalid
        with pytest.raises(ValueError):
            spread_metrics(575, 570, 6.0)

    def test_credit_equals_width_raises(self):
        # credit==width is also degenerate (zero max-loss)
        with pytest.raises(ValueError):
            spread_metrics(575, 570, 5.0)

    def test_credit_zero_raises(self):
        with pytest.raises(ValueError):
            spread_metrics(575, 570, 0.0)

    def test_credit_negative_raises(self):
        with pytest.raises(ValueError):
            spread_metrics(575, 570, -1.0)


# ---------------------------------------------------------------------------
# csp_max_loss
# ---------------------------------------------------------------------------

class TestCspMaxLoss:
    def test_single_contract(self):
        # (220 - 2.10) * 100 * 1 = 217.90 * 100 = 21790.0
        assert csp_max_loss(220, 2.10) == 21790.0

    def test_qty2(self):
        # 21790.0 * 2 = 43580.0
        assert csp_max_loss(220, 2.10, qty=2) == 43580.0


# ---------------------------------------------------------------------------
# long_option_max_loss
# ---------------------------------------------------------------------------

class TestLongOptionMaxLoss:
    def test_negative_debit_uses_magnitude(self):
        # abs(-3.50) * 100 = 350.0
        assert long_option_max_loss(-3.50) == 350.0

    def test_positive_debit(self):
        assert long_option_max_loss(3.5) == 350.0

    def test_qty_scales(self):
        assert long_option_max_loss(3.5, qty=2) == 700.0


# ---------------------------------------------------------------------------
# max_loss_for dispatch
# ---------------------------------------------------------------------------

class TestMaxLossFor:
    def test_bull_put_spread(self):
        result = max_loss_for(
            "bull_put_spread",
            short_strike=575,
            long_strike=570,
            credit_debit=1.42,
        )
        assert result == 358.0

    def test_bull_put_spread_missing_long_strike_raises(self):
        with pytest.raises(ValueError):
            max_loss_for("bull_put_spread", short_strike=575, credit_debit=1.42)

    def test_bull_put_spread_missing_short_strike_raises(self):
        with pytest.raises(ValueError):
            max_loss_for("bull_put_spread", long_strike=570, credit_debit=1.42)

    def test_cash_secured_put(self):
        result = max_loss_for(
            "cash_secured_put",
            short_strike=220,
            credit_debit=2.10,
        )
        assert result == 21790.0

    def test_cash_secured_put_missing_strike_raises(self):
        with pytest.raises(ValueError):
            max_loss_for("cash_secured_put", credit_debit=2.10)

    def test_long_option(self):
        result = max_loss_for("long_option", credit_debit=3.5)
        assert result == 350.0

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError):
            max_loss_for("iron_condor", short_strike=575, long_strike=570, credit_debit=1.42)


# ---------------------------------------------------------------------------
# cap_pct and within_cap
# ---------------------------------------------------------------------------

class TestCapPct:
    def test_basic(self):
        # round(358/35000*100, 2)
        assert cap_pct(358, 35000) == round(358 / 35000 * 100, 2)

    def test_known_value(self):
        # 358/35000*100 = 1.022857... → rounds to 1.02
        assert cap_pct(358, 35000) == 1.02

    def test_zero_account_raises(self):
        with pytest.raises(ValueError):
            cap_pct(358, 0)

    def test_negative_account_raises(self):
        with pytest.raises(ValueError):
            cap_pct(358, -1000)


class TestWithinCap:
    def test_below_cap_is_true(self):
        # 2% of 35000 = 700; 358 <= 700 → True
        assert within_cap(358, 35000) is True

    def test_within_cap_is_true(self):
        # 690 <= 700 → True
        assert within_cap(690, 35000) is True

    def test_exactly_at_cap_is_true(self):
        # 700 <= 700 → True
        assert within_cap(700, 35000) is True

    def test_above_cap_returns_false(self):
        # 701 > 700 → False
        assert within_cap(701, 35000) is False

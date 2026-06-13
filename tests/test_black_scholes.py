import pytest

from core.options.black_scholes import bs_call, bs_put, put_delta


# Classic textbook reference values: S=100, K=100, T=1y, r=5%, sigma=20%
S, K, T, R, SIG = 100.0, 100.0, 1.0, 0.05, 0.20


def test_bs_call_reference_value():
    assert bs_call(S, K, T, SIG, R) == pytest.approx(10.4506, abs=1e-3)


def test_bs_put_reference_value():
    assert bs_put(S, K, T, SIG, R) == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    import math
    call, put = bs_call(S, K, T, SIG, R), bs_put(S, K, T, SIG, R)
    assert call - put == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)


def test_put_delta_reference_value():
    # d1 = 0.35 -> N(d1) = 0.63683 -> put delta = N(d1) - 1 = -0.36317
    assert put_delta(S, K, T, SIG, R) == pytest.approx(-0.36317, abs=1e-4)


def test_expiry_is_intrinsic():
    assert bs_put(90.0, 100.0, 0.0, SIG, R) == pytest.approx(10.0)
    assert bs_call(110.0, 100.0, 0.0, SIG, R) == pytest.approx(10.0)

"""Sanity checks. Run with:  pytest"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from fisd.curve import bootstrap, interpolate_par
from fisd.data import parse_treasury_csv, SAMPLE_FILE
from fisd.pricing import bachelier, bond_price, bond_dv01
from fisd.products import callable_vs_bullet, range_accrual, fixed_to_floating

PAR = interpolate_par([1, 2, 3, 5, 7, 10], [0.037, 0.035, 0.0345, 0.0352, 0.0365, 0.038])
CURVE = bootstrap(PAR)


def test_par_swaps_reprice_to_zero():
    for n in range(1, 11):
        assert PAR[n - 1] * CURVE.annuity_at(n) + CURVE.df_at(n) == pytest.approx(1.0)
        assert CURVE.swap_rate(0, n) == pytest.approx(PAR[n - 1])


def test_forwards_rebuild_discount_factors():
    assert np.prod(1 / (1 + CURVE.fwd)) == pytest.approx(CURVE.df_at(10))


def test_put_call_parity():
    f, k, a = 0.036, 0.034, 2.7
    payer = bachelier(f, k, 95, 2, a, "payer")
    receiver = bachelier(f, k, 95, 2, a, "receiver")
    assert payer - receiver == pytest.approx(a * (f - k))


def test_bond_at_par_and_dv01_positive():
    assert bond_price(0.04, 0.04, 10) == pytest.approx(100.0)
    assert 0.07 < bond_dv01(0.04, 0.04, 10) < 0.09


def test_callable_coupon_solves_the_equation():
    r = callable_vs_bullet(CURVE, 5, 2, 0.01, 95)
    extra_coupon_pv = (r["callable_coupon"] - r["bullet_coupon"]) * CURVE.annuity_at(5)
    assert extra_coupon_pv == pytest.approx(r["option_value"], abs=1e-10)
    assert r["pickup_bp"] > 0


def test_callable_pickup_rises_with_vol():
    low = callable_vs_bullet(CURVE, 5, 2, 0.01, 60)["pickup_bp"]
    high = callable_vs_bullet(CURVE, 5, 2, 0.01, 130)["pickup_bp"]
    assert high > low


def test_range_accrual_limits():
    wide = range_accrual(CURVE, 5, -1.0, 1.0, 100, 0.005, 0.005)   # always in range
    assert wide["coupon"] == pytest.approx(wide["plain_coupon"])
    narrow = range_accrual(CURVE, 5, 0.03, 0.04, 100, 0.005, 0.005)
    assert narrow["coupon"] > narrow["plain_coupon"]
    more_vol = range_accrual(CURVE, 5, 0.03, 0.04, 150, 0.005, 0.005)
    assert more_vol["coupon"] > narrow["coupon"]                   # investor is short vol


def test_fixed_to_floating_spread():
    r = fixed_to_floating(CURVE, 5, 0.05)
    assert r["spread_over_sofr"] == pytest.approx(0.05 - PAR[4])


def test_treasury_parser_on_sample_file():
    table = parse_treasury_csv(SAMPLE_FILE.read_text())
    assert list(table.columns) == [1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
    assert table.index.is_monotonic_increasing
    assert table.iloc[-1][10.0] == pytest.approx(0.0395)

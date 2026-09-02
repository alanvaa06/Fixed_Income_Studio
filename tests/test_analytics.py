"""Bond and curve analytics."""

import numpy as np
import pandas as pd
import pytest

from nelson_siegel import TreasuryNelsonSiegelModel
from nelson_siegel.analytics import (
    Bond,
    bond_report,
    carry_roll_down,
    curve_changes,
    curve_spreads,
    duration_convexity,
    forward_rate,
    forward_rate_table,
    key_rate_durations,
    pca_yield_changes,
    price_from_curve,
    price_from_yield,
    rich_cheap,
    yield_to_maturity,
    z_spread,
)
from nelson_siegel.data import DataManager
from nelson_siegel.short_rate import VasicekModel

MATS = np.array([0.25, 1, 2, 5, 10, 30])
YLDS = np.array([0.0495, 0.0465, 0.043, 0.0395, 0.0405, 0.0435])


@pytest.fixture(scope="module")
def curve():
    return TreasuryNelsonSiegelModel().fit(MATS, YLDS)


def test_bond_cash_flows_and_validation():
    times, amounts = Bond(2.0, 0.05, 2).cash_flows()
    assert np.allclose(times, [0.5, 1.0, 1.5, 2.0])
    assert np.allclose(amounts, [2.5, 2.5, 2.5, 102.5])
    times, amounts = Bond(1.25, 0.04, 2).cash_flows()  # fractional first period
    assert np.allclose(times, [0.25, 0.75, 1.25]) and amounts[-1] == 102.0
    times, amounts = Bond(3.0).cash_flows()
    assert len(times) == 6 and amounts[:-1].sum() == 0 and amounts[-1] == 100
    for bad in (dict(maturity=0), dict(maturity=1, frequency=0), dict(maturity=1, coupon=-0.1)):
        with pytest.raises(ValueError):
            Bond(**bad)


def test_price_yield_round_trip_and_par_bond():
    bond = Bond(10, 0.045, 2)
    assert np.isclose(price_from_yield(bond, 0.045), 100.0)  # coupon == yield prices at par
    price = price_from_yield(bond, 0.05)
    assert price < 100 and np.isclose(yield_to_maturity(bond, price), 0.05)
    with pytest.raises(ValueError):
        yield_to_maturity(bond, -1)


def test_duration_convexity_against_finite_differences():
    bond = Bond(10, 0.04, 2)
    y = 0.045
    risk = duration_convexity(bond, y)
    h = 1e-5
    p_up, p_dn, p0 = price_from_yield(bond, y + h), price_from_yield(bond, y - h), price_from_yield(bond, y)
    num_dur = -(p_up - p_dn) / (2 * h) / p0
    num_conv = (p_up - 2 * p0 + p_dn) / h**2 / p0
    assert np.isclose(risk["modified_duration"], num_dur, rtol=1e-5)
    assert np.isclose(risk["convexity"], num_conv, rtol=1e-3)
    assert np.isclose(risk["macaulay_duration"], risk["modified_duration"] * (1 + y / 2))
    assert np.isclose(risk["dv01"], risk["modified_duration"] * p0 * 1e-4)
    zero = duration_convexity(Bond(7.0), 0.04)
    assert np.isclose(zero["macaulay_duration"], 7.0)


def test_curve_pricing_zspread_and_key_rates(curve):
    bond = Bond(10, 0.04)
    model_price = price_from_curve(bond, curve)
    assert 90 < model_price < 110
    assert abs(z_spread(bond, model_price, curve)) < 1e-9
    cheaper = model_price * 0.99
    assert z_spread(bond, cheaper, curve) > 0
    krd = key_rate_durations(bond, curve)
    assert (krd >= -1e-9).all()
    # A 10-year bullet loads mostly on the 10-year key rate and not on 30y.
    assert krd.idxmax() == 10.0 and krd[30.0] < 1e-6
    # The tent bumps sum to a parallel shift, so KRDs sum to the zero-curve duration.
    h = 1e-5
    parallel = -(price_from_curve(bond, lambda t: curve.predict(t) + h) - price_from_curve(bond, lambda t: curve.predict(t) - h)) / (2 * h) / model_price
    assert np.isclose(krd.sum(), parallel, rtol=1e-4)
    report = bond_report(bond, curve, price=cheaper)
    assert report["market_price"] == cheaper and report["ytm"] > report["model_ytm"]
    assert set(report) >= {"z_spread", "modified_duration", "convexity", "dv01", "key_rate_durations", "cash_flows"}
    # Works with a short-rate curve too (duck typing on predict()).
    vas = VasicekModel().set_params(0.04, 0.3, 0.045, 0.01)
    assert 80 < price_from_curve(Bond(5, 0.03), vas) < 100


def test_carry_roll_down_and_forwards(curve):
    table = carry_roll_down(curve, maturities=(1, 2, 5, 10, 30), horizon=1.0)
    assert list(table.index) == [2.0, 5.0, 10.0, 30.0]  # 1y dropped: not beyond the horizon
    assert np.allclose(table["total_bps"], table["carry_bps"] + table["roll_down_bps"])
    y1 = curve.predict([1.0])[0]
    assert np.allclose(table["carry_bps"], (table["yield"] - y1) / 1e-4)
    # The 1y forward into the 9y matches the forward table.
    fwd = forward_rate(curve, 1.0, 10.0)
    assert np.isclose(table.loc[10.0, "forward_yield"], fwd)
    ft = forward_rate_table(curve, pairs=((1, 9), (5, 5)))
    assert list(ft.index) == ["1y9y", "5y5y"] and np.isclose(ft.loc["1y9y", "forward"], fwd)
    assert np.isclose(forward_rate(curve, 0.0, 5.0), curve.predict([5.0])[0])
    with pytest.raises(ValueError):
        forward_rate(curve, 5.0, 2.0)
    with pytest.raises(ValueError):
        carry_roll_down(curve, maturities=(1, 2), horizon=3.0)
    with pytest.raises(ValueError):
        carry_roll_down(curve, horizon=0)


def test_curve_spreads_from_model_and_panel(curve):
    s = curve_spreads(curve)
    y = lambda m: curve.predict([m])[0]  # noqa: E731
    assert np.isclose(s["2s10s"], (y(10) - y(2)) / 1e-4)
    assert np.isclose(s["2s5s10s"], (2 * y(5) - y(2) - y(10)) / 1e-4)
    panel = DataManager(public_sources=False).get_treasury_data("2025-01-01", "2025-03-01")
    ts = curve_spreads(panel)
    assert list(ts.columns) == list(s.index) and len(ts) == len(panel)
    assert np.allclose(ts["5s30s"], (panel[30.0] - panel[5.0]) / 1e-4)
    custom = curve_spreads(curve, {"1s2s": ((2.0, 1.0), (1.0, -1.0))})
    assert list(custom.index) == ["1s2s"]


def test_rich_cheap_ranking(curve):
    table = rich_cheap(curve, MATS, YLDS)
    assert table.index.name == "maturity" and table["rank"].iloc[0] == 1
    assert (table["residual_bps"].diff().dropna() <= 0).all()  # sorted cheapest first
    assert set(table["verdict"]) <= {"cheap", "rich"}
    assert np.isclose(table["z"].std(ddof=1), 1.0)
    single = rich_cheap(curve, [5.0], [0.04])
    assert np.isnan(single["z"].iloc[0])


def test_pca_and_curve_changes():
    panel = DataManager(public_sources=False).get_treasury_data("2023-01-01", "2026-01-01")
    pca = pca_yield_changes(panel)
    assert len(pca["explained_variance"]) == 3 and pca["explained_variance"][0] > 0.5
    load = pca["loadings"]
    assert list(load.columns) == ["Level", "Slope", "Curvature"] and (load["Level"] > 0).all()
    assert load["Slope"].iloc[-1] > load["Slope"].iloc[0]
    assert pca["scores"].shape == (len(panel) - 1, 3) and pca["on_changes"]
    levels = pca_yield_changes(panel, n_components=2, diff=False)
    assert levels["scores"].shape[1] == 2 and not levels["on_changes"]
    with pytest.raises(ValueError):
        pca_yield_changes(panel.iloc[:3])

    moves = curve_changes(panel)
    assert moves.index.name == "maturity" and "chg_252_bps" in moves.columns
    assert np.isclose(moves.loc[10.0, "chg_1_bps"], (panel[10.0].iloc[-1] - panel[10.0].iloc[-2]) / 1e-4)
    assert moves.attrs["as_of"] == panel.index[-1]
    assert np.isnan(curve_changes(panel.iloc[-3:])["chg_252_bps"]).all()
    with pytest.raises(ValueError):
        curve_changes(panel.iloc[:0])

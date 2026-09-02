"""Short-rate models: closed forms, calibration, estimation and simulation."""

import numpy as np
import pandas as pd
import pytest

from nelson_siegel.model import CurveModel
from nelson_siegel.short_rate import (
    SHORT_RATE_REGISTRY,
    CIRModel,
    VasicekModel,
    estimate_short_rate,
    get_short_rate_model_class,
)

MATS = np.array([0.25, 1.0, 2.0, 5.0, 10.0, 30.0])
CASES = [
    (VasicekModel, (0.045, 0.3, 0.05, 0.012)),
    (CIRModel, (0.045, 0.3, 0.05, 0.06)),
]


@pytest.mark.parametrize("cls,params", CASES)
def test_models_satisfy_curve_model_protocol(cls, params):
    model = cls().set_params(*params)
    assert isinstance(model, CurveModel)
    desc = cls.describe()
    assert desc["family"] == "short-rate" and desc["supports_history"] is False
    assert [f["key"] for f in desc["factors"]] == ["r0", "kappa", "theta", "sigma"]
    assert set(model.get_factors()) == {"ShortRate", "MeanReversion", "LongRunMean", "Volatility"}


@pytest.mark.parametrize("cls,params", CASES)
def test_closed_forms_are_internally_consistent(cls, params):
    model = cls().set_params(*params)
    y = model.predict(MATS)
    P = model.discount_factor(MATS)
    assert np.allclose(P, np.exp(-MATS * y))
    # Yield converges to the short rate at the origin.
    assert np.isclose(model.predict([1e-8])[0], params[0], atol=1e-6)
    # The closed-form forward equals -d ln P / dt.
    h = 1e-5
    numeric = -(np.log(model.discount_factor(MATS + h)) - np.log(model.discount_factor(MATS - h))) / (2 * h)
    assert np.allclose(numeric, model.forward_rate(MATS), atol=1e-6)
    # Mean reversion: long yields sit between r0 and theta plus/minus convexity.
    assert y[0] < y[-1]  # upward sloping since theta > r0
    assert np.isclose(model.half_life(), np.log(2) / params[1])


@pytest.mark.parametrize("cls,params", CASES)
def test_expected_path_and_expectations_yield(cls, params):
    model = cls().set_params(*params)
    r0, kappa, theta, _ = params
    t = np.array([0.0, 1.0, 5.0, 50.0])
    path = model.expected_path(t)
    assert np.isclose(path[0], r0) and np.isclose(path[-1], theta, atol=1e-6)
    eh = model.expectations_yield(t)
    assert np.isclose(eh[0], r0)
    # Average of expected rates is between the current rate and the mean.
    assert min(r0, theta) <= eh[1] <= max(r0, theta)
    # Numerically integrate E[r] to check the average.
    grid = np.linspace(0, 5, 20001)
    integral = np.trapezoid(model.expected_path(grid), grid) / 5.0
    assert np.isclose(integral, eh[2], atol=1e-6)


@pytest.mark.parametrize("cls,params", CASES)
def test_calibration_recovers_parameters(cls, params):
    truth = cls().set_params(*params)
    y = truth.predict(MATS)
    fitted = cls().fit(MATS, y)
    for name, value in zip(cls.param_names, params):
        assert np.isclose(fitted.parameters[name], value, rtol=2e-2, atol=1e-4), name
    stats = fitted.fit_stats()
    assert stats["rmse"] < 1e-6 and stats["r_squared"] > 0.999 and stats["n_obs"] == len(MATS)
    assert stats["decay_at_bound"] is False
    # Holding sigma fixed is supported and exact.
    fixed = cls().fit(MATS, y, sigma=params[3])
    assert np.isclose(fixed.parameters["sigma"], params[3])
    assert "fixed_sigma" in fixed.fit_stats()["method"]
    assert fixed.classify_bonds(MATS, y + np.array([1, -1, 1, -1, 1, -1]) * 1e-4) == [
        "expensive", "cheap", "expensive", "cheap", "expensive", "cheap"
    ]


def test_calibration_handles_noisy_market_like_curve():
    mats = np.array([1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
    yields = np.array([4.35, 4.30, 4.20, 4.05, 3.90, 3.88, 3.95, 4.05, 4.20, 4.70, 4.85]) / 100
    for cls in (VasicekModel, CIRModel):
        model = cls().fit(mats, yields)
        assert model.fit_stats()["rmse"] < 0.004  # inverted-then-rising curve: one factor is rough
        assert np.isfinite(model.forward_rate(mats)).all()
        assert 0 < model.parameters["kappa"] < 3


def test_calibration_validation():
    with pytest.raises(ValueError):
        VasicekModel().fit([1, 2, 3], [0.04, 0.04, 0.04])
    with pytest.raises(ValueError):
        CIRModel().fit(MATS, np.array([-0.01, 0.01, 0.02, 0.03, 0.03, 0.03]))
    with pytest.raises(ValueError):
        VasicekModel().predict(MATS)
    with pytest.raises(ValueError):
        VasicekModel().set_params(0.03, -0.1, 0.04, 0.01)
    with pytest.raises(ValueError):
        VasicekModel().fit(MATS, y := VasicekModel().set_params(*CASES[0][1]).predict(MATS), sigma=-1)
    assert repr(VasicekModel()).endswith("fitted=False)")


@pytest.mark.parametrize("cls,params", CASES)
def test_simulation_shapes_and_moments(cls, params):
    model = cls().set_params(*params)
    paths = model.simulate(horizon_years=2, n_paths=500, steps_per_year=52, seed=3)
    assert paths.shape == (105, 500)
    assert np.allclose(paths.iloc[0], params[0])
    assert paths.index.name == "years" and np.isclose(paths.index[-1], 2.0)
    mean_end = paths.iloc[-1].mean()
    assert np.isclose(mean_end, model.expected_path([2.0])[0], atol=0.004)
    if cls is CIRModel:
        assert (paths >= -1e-12).all().all()
        assert model.feller_condition() is True
    # Deterministic under the same seed.
    again = model.simulate(horizon_years=2, n_paths=500, steps_per_year=52, seed=3)
    assert paths.equals(again)


def _simulated_history(cls, params, years=40, seed=1):
    model = cls().set_params(*params)
    sim = model.simulate(horizon_years=years, n_paths=1, steps_per_year=52, seed=seed).iloc[:, 0]
    sim.index = pd.date_range("1980-01-01", periods=len(sim), freq="W")
    return sim


@pytest.mark.parametrize("cls,params", CASES)
@pytest.mark.parametrize("method", ["ols", "mle"])
def test_time_series_estimation_recovers_dynamics(cls, params, method):
    history = _simulated_history(cls, params)
    est = estimate_short_rate(history, cls.model_id, method)
    r0, kappa, theta, sigma = params
    assert est.model == cls.model_id and est.method == method
    assert np.isclose(est.dt, 7 / 365.25, rtol=0.05)
    assert est.n_obs == len(history)
    assert abs(est.kappa - kappa) < 0.15  # finite-sample bias in mean reversion is well known
    assert np.isclose(est.theta, theta, atol=0.006)
    assert np.isclose(est.sigma, sigma, rtol=0.1)
    assert est.stationary and est.half_life_years is not None
    assert np.isfinite(est.log_likelihood) and np.isfinite(est.aic)
    assert np.isclose(est.r0, history.iloc[-1])
    if cls is CIRModel:
        assert est.feller is True
    else:
        assert est.feller is None and 0 < est.ar_coefficient < 1
    curve = est.as_model()
    assert isinstance(curve, cls) and curve.fitted
    assert set(est.as_dict()) >= {"kappa", "theta", "sigma", "half_life_years"}


def test_estimation_validation_and_explicit_dt():
    rates = np.linspace(0.03, 0.05, 30)
    est = estimate_short_rate(rates, "vasicek", dt=1 / 12)
    assert est.dt == 1 / 12
    with pytest.raises(ValueError):
        estimate_short_rate(rates, "vasicek")  # no dt on a RangeIndex
    with pytest.raises(ValueError):
        estimate_short_rate(rates[:10], "vasicek", dt=1 / 12)
    with pytest.raises(ValueError):
        estimate_short_rate(rates, "hull-white", dt=1 / 12)
    with pytest.raises(ValueError):
        estimate_short_rate(rates, "vasicek", method="gmm", dt=1 / 12)
    with pytest.raises(ValueError):
        estimate_short_rate(np.linspace(-0.01, 0.02, 30), "cir", dt=1 / 12)


def test_unit_root_series_is_reported_non_stationary():
    rng = np.random.default_rng(0)
    walk = 0.03 + np.cumsum(rng.normal(0, 0.0005, 300))
    est = estimate_short_rate(walk, "vasicek", dt=1 / 52)
    assert est.ar_coefficient > 0.95
    assert est.sigma > 0


def test_registry_lookup():
    assert get_short_rate_model_class("CIR") is CIRModel
    assert get_short_rate_model_class("vasicek") is VasicekModel
    assert set(SHORT_RATE_REGISTRY) == {"vasicek", "cir"}
    with pytest.raises(ValueError):
        get_short_rate_model_class("ho-lee")

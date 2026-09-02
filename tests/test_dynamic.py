"""Tests for the Diebold-Li dynamic factor model."""

import numpy as np
import pandas as pd
import pytest

from nelson_siegel.analysis import YieldCurveAnalyzer
from nelson_siegel.dynamic import DynamicNelsonSiegel, backtest
from nelson_siegel.model import NelsonSiegelModel, SvenssonModel


def _simulate_factors(n=400, rho=(0.98, 0.95, 0.90), mu=(0.04, -0.015, 0.005), sigma=(3e-4, 4e-4, 8e-4),
                      tau=1.6, seed=0, freq="W-FRI"):
    rng = np.random.default_rng(seed)
    k = 3
    F = np.zeros((n, k))
    F[0] = mu
    for t in range(1, n):
        F[t] = np.array(mu) + np.array(rho) * (F[t - 1] - np.array(mu)) + rng.normal(0, sigma)
    idx = pd.date_range("2015-01-02", periods=n, freq=freq)
    df = pd.DataFrame(F, index=idx, columns=["Level", "Slope", "Curvature"])
    df["Tau"] = tau
    df["RMSE"] = 1e-4
    return df


def test_ar_recovers_persistence_and_mean():
    df = _simulate_factors(n=3000)
    dns = DynamicNelsonSiegel("ar").fit(df)
    rho = dns.persistence()
    assert abs(rho["Level"] - 0.98) < 0.02
    assert abs(rho["Slope"] - 0.95) < 0.03
    assert abs(rho["Curvature"] - 0.90) < 0.04
    mean = dns.unconditional_mean()
    assert np.allclose(mean, [0.04, -0.015, 0.005], atol=2e-3)
    assert dns.summary()["stationary"] is True
    assert dns.decays_ == (1.6,)


def test_var_nests_ar_in_sample():
    df = _simulate_factors(n=500)
    ar = DynamicNelsonSiegel("ar").fit(df)
    var = DynamicNelsonSiegel("var").fit(df)
    # VAR has more regressors so its in-sample residual variance cannot exceed AR's.
    assert (np.diag(var.resid_cov_) <= np.diag(ar.resid_cov_) * 1.02).all()
    assert var.coef_.shape == (3, 3)
    assert np.count_nonzero(ar.coef_ - np.diag(np.diag(ar.coef_))) == 0


def test_random_walk_forecast_is_flat_with_growing_bands():
    df = _simulate_factors(n=200)
    dns = DynamicNelsonSiegel("rw").fit(df)
    fc = dns.forecast_factors(8)
    assert np.allclose(fc[["Level", "Slope", "Curvature"]].to_numpy(), np.tile(dns.last_, (8, 1)))
    assert (np.diff(fc["Level_std"].to_numpy()) > 0).all()
    assert fc["Tau"].eq(1.6).all()
    assert dns.summary()["stationary"] is False


def test_forecast_index_uses_inferred_step():
    df = _simulate_factors(n=100, freq="W-FRI")
    fc = DynamicNelsonSiegel("ar").fit(df).forecast_factors(3)
    assert isinstance(fc.index, pd.DatetimeIndex)
    assert (fc.index - df.index[-1]).days.tolist() == [7, 14, 21]


def test_ar_forecast_converges_to_unconditional_mean():
    df = _simulate_factors(n=800)
    dns = DynamicNelsonSiegel("ar").fit(df)
    fc = dns.forecast_factors(2000)
    assert np.allclose(fc.iloc[-1][["Level", "Slope", "Curvature"]].to_numpy(), dns.unconditional_mean(), atol=1e-6)


def test_forecast_curve_matches_loadings():
    df = _simulate_factors(n=200)
    dns = DynamicNelsonSiegel("ar").fit(df)
    mats = [0.5, 2.0, 10.0, 30.0]
    curves = dns.forecast_curve(mats, 5)
    fc = dns.forecast_factors(5)
    expected = NelsonSiegelModel.basis(mats, 1.6) @ fc[["Level", "Slope", "Curvature"]].to_numpy().T
    assert np.allclose(curves.to_numpy(), expected.T)
    assert np.allclose(dns.current_curve(mats), NelsonSiegelModel.basis(mats, 1.6) @ dns.last_)


def test_half_life_and_summary_shape():
    df = _simulate_factors(n=600)
    summary = DynamicNelsonSiegel("ar").fit(df).summary()
    hl = summary["half_life_steps"]
    assert hl["Level"] > hl["Slope"] > hl["Curvature"] > 0
    assert set(summary) >= {"method", "n_obs", "step_days", "persistence", "residual_std", "unconditional_mean"}
    assert summary["step_days"] == 7.0


def test_input_validation():
    df = _simulate_factors(n=200)
    with pytest.raises(ValueError, match="method must be"):
        DynamicNelsonSiegel("arima")
    with pytest.raises(ValueError, match="at least 10"):
        DynamicNelsonSiegel("ar").fit(df.iloc[:5])
    with pytest.raises(ValueError, match="missing columns"):
        DynamicNelsonSiegel("ar").fit(df.drop(columns=["Curvature"]))
    with pytest.raises(ValueError, match="Pass decays"):
        DynamicNelsonSiegel("ar").fit(df.drop(columns=["Tau"]))
    with pytest.raises(ValueError, match="fitted before"):
        DynamicNelsonSiegel("ar").forecast_factors(3)
    with pytest.raises(ValueError, match="horizon"):
        DynamicNelsonSiegel("ar").fit(df).forecast_factors(0)


def test_nonstationary_dynamics_warn():
    n = 300
    idx = pd.date_range("2015-01-02", periods=n, freq="W-FRI")
    rng = np.random.default_rng(1)
    F = np.zeros((n, 3))
    F[0] = [0.03, -0.01, 0.005]
    for t in range(1, n):  # mildly explosive dynamics
        F[t] = 1.02 * F[t - 1] + rng.normal(0, 1e-4, 3)
    df = pd.DataFrame(F, index=idx, columns=["Level", "Slope", "Curvature"])
    df["Tau"] = 1.5
    with pytest.warns(RuntimeWarning, match="non-stationary"):
        dns = DynamicNelsonSiegel("ar").fit(df)
    assert dns.unconditional_mean() is None
    assert dns.half_life()["Level"] is None


def test_svensson_factor_history_is_supported():
    df = _simulate_factors(n=200)
    df["Curvature2"] = -0.5 * df["Curvature"]
    df["Tau2"] = 8.0
    dns = DynamicNelsonSiegel("ar", model_cls=SvenssonModel).fit(df)
    assert dns.factor_names_ == ["Level", "Slope", "Curvature", "Curvature2"]
    assert dns.decays_ == (1.6, 8.0)
    curves = dns.forecast_curve([1.0, 10.0], 2)
    assert curves.shape == (2, 2)


def test_backtest_ar_beats_random_walk_on_mean_reverting_factors():
    df = _simulate_factors(n=500, rho=(0.9, 0.8, 0.7))
    table = backtest(df, horizons=(1, 4), min_train=100, maturities=[1.0, 5.0, 10.0])
    assert set(table.index.get_level_values("method")) == {"rw", "ar", "var"}
    for h in (1, 4):
        assert table.loc[("ar", h), "Curvature_rmse"] < table.loc[("rw", h), "Curvature_rmse"]
        assert table.loc[("ar", h), "yield_rmse"] < table.loc[("rw", h), "yield_rmse"]
    assert (table["n_forecasts"] == 500 - 100 - 4 + 1).all()


def test_backtest_validation():
    df = _simulate_factors(n=60)
    with pytest.raises(ValueError, match="min_train"):
        backtest(df, horizons=(12,), min_train=52)


def test_analyzer_forecast_and_backtest_end_to_end():
    analyzer = YieldCurveAnalyzer()
    result = analyzer.forecast_factors("treasury", horizon=8, method="ar",
                                       start_date="2021-01-01", end_date="2025-12-31")
    assert len(result["forecast"]) == 8
    assert result["curves"].shape == (8, len(result["maturities"]))
    assert result["summary"]["method"] == "ar"
    assert len(result["current_curve"]) == len(result["maturities"])

    table = analyzer.backtest_factor_forecasts("treasury", horizons=(1, 4), start_date="2021-01-01",
                                               end_date="2025-12-31", min_train=60,
                                               factors=result["factors"])
    assert "yield_rmse" in table.columns and len(table) == 6

"""Term premium module: ACM affine model, EH decompositions and regressions."""

import warnings

import numpy as np
import pandas as pd
import pytest

from nelson_siegel import DynamicNelsonSiegel, YieldCurveAnalyzer
from nelson_siegel.data import DataManager
from nelson_siegel.short_rate import ShortRateEstimate, VasicekModel, estimate_short_rate
from nelson_siegel.term_premium import (
    ACMTermPremiumModel,
    campbell_shiller,
    dns_term_premium,
    fama_bliss,
    interpolate_maturities,
    ols_newey_west,
    short_rate_term_premium,
    to_monthly,
    zero_panel_from_factors,
)


def _affine_economy(seed=0, T=600, N=120):
    """Simulate a two-factor Gaussian affine economy with known prices of risk."""
    rng = np.random.default_rng(seed)
    K = 2
    mu = np.zeros(K)
    Phi = np.diag([0.985, 0.90])
    Sigma = np.diag([0.0004, 0.0003]) ** 2
    delta0, delta1 = 0.04 / 12, np.array([1.0, 0.5])
    lam0 = np.array([-0.00015, 0.00005])
    lam1 = np.array([[-0.01, 0.004], [0.003, -0.015]])
    sigma2 = 1e-8

    def rec(l0, l1):
        A = np.zeros(N + 1)
        B = np.zeros((N + 1, K))
        for n in range(1, N + 1):
            Bp = B[n - 1]
            A[n] = A[n - 1] + Bp @ (mu - l0) + 0.5 * (Bp @ Sigma @ Bp + sigma2) - delta0
            B[n] = Bp @ (Phi - l1) - delta1
        return A, B

    A, B = rec(lam0, lam1)
    Arn, Brn = rec(np.zeros(K), np.zeros((K, K)))
    X = np.zeros((T, K))
    x = np.zeros(K)
    for t in range(T):
        x = mu + Phi @ x + rng.multivariate_normal(np.zeros(K), Sigma)
        X[t] = x
    n = np.arange(1, N + 1)
    Y = -(A[1:][None, :] + X @ B[1:].T) / n[None, :] * 12
    Yrn = -(Arn[1:][None, :] + X @ Brn[1:].T) / n[None, :] * 12
    idx = pd.date_range("1975-01-31", periods=T, freq="ME")
    panel = pd.DataFrame(Y + rng.normal(0, 1e-5, Y.shape), index=idx, columns=n / 12)
    return panel, Y - Yrn


def test_acm_recovers_simulated_term_premium():
    panel, tp_true = _affine_economy()
    model = ACMTermPremiumModel(n_factors=2, max_maturity_months=120).fit(panel)
    for years, col in ((10.0, 119), (5.0, 59)):
        est = model.term_premium([years])[years].to_numpy()
        truth = tp_true[:, col]
        assert np.corrcoef(est, truth)[0, 1] > 0.95
        assert np.abs(est - truth).mean() < 0.25 * np.abs(truth).mean() + 1e-4
    assert model.fit_rmse() < 5e-5
    summary = model.summary()
    assert summary["n_factors"] == 2 and summary["explained_variance"][0] > 0.9
    assert summary["max_eigenvalue"] < 1.0
    assert len(summary["lambda0"]) == 2 and np.asarray(summary["lambda1"]).shape == (2, 2)


def test_acm_decomposition_is_additive():
    panel, _ = _affine_economy(seed=1, T=300)
    model = ACMTermPremiumModel(n_factors=2).fit(panel)
    d = model.decompose(10.0)
    assert list(d.columns) == ["observed", "fitted", "risk_neutral", "expected_short_rate", "term_premium", "convexity"]
    assert np.allclose(d["fitted"] - d["risk_neutral"], d["term_premium"])
    assert np.allclose(d["risk_neutral"] - d["expected_short_rate"], d["convexity"])
    assert np.abs(d["observed"] - d["fitted"]).max() < 1e-3
    # One-month yield equals the short rate up to the return-error convexity term.
    one_month = model.fitted_yields([1 / 12])[1 / 12]
    assert np.abs(one_month - panel[1 / 12].loc[one_month.index]).max() < 1e-3
    # Convexity is small at short maturities and negative-or-tiny at long ones.
    assert np.abs(model.decompose(1 / 12)["convexity"]).max() < 1e-3


def test_acm_validation():
    panel, _ = _affine_economy(T=100)
    with pytest.raises(ValueError):
        ACMTermPremiumModel(n_factors=0)
    with pytest.raises(ValueError):
        ACMTermPremiumModel(max_maturity_months=6)
    with pytest.raises(ValueError):
        ACMTermPremiumModel().fit(panel.iloc[:20])
    model = ACMTermPremiumModel(3, 60).fit(panel)
    with pytest.raises(ValueError):
        model.term_premium([10.0])
    with pytest.raises(ValueError):
        ACMTermPremiumModel().summary()


def test_acm_on_synthetic_gsw_panel_gives_sane_premia():
    dm = DataManager(public_sources=False)
    zeros = dm.get_zero_curve(np.arange(1, 121) / 12, "2000-01-01", "2026-06-30")
    monthly = to_monthly(zeros)
    assert 300 <= len(monthly) <= 320
    model = ACMTermPremiumModel(3).fit(monthly)
    tp = model.term_premium([2.0, 5.0, 10.0])
    assert tp.shape[1] == 3 and len(tp) == len(monthly)
    assert (tp.abs() < 0.05).all().all()  # premia within +/- 500 bp
    assert model.fit_rmse() < 2e-4


def test_helpers_interpolate_and_resample():
    idx = pd.date_range("2024-01-01", periods=70, freq="D")
    panel = pd.DataFrame({1.0: 0.04, 5.0: 0.045, 10.0: 0.05}, index=idx)
    grid = interpolate_maturities(panel, [1.0, 3.0, 7.5, 0.5, 20.0])
    assert np.isclose(grid[3.0].iloc[0], 0.0425)
    assert np.isclose(grid[7.5].iloc[0], 0.0475)
    assert np.isclose(grid[0.5].iloc[0], 0.04) and np.isclose(grid[20.0].iloc[0], 0.05)  # flat ends
    monthly = to_monthly(panel)
    assert len(monthly) == 3 and monthly.index[0] == pd.Timestamp("2024-01-31")
    with pytest.raises(ValueError):
        to_monthly(panel.reset_index(drop=True))
    panel.iloc[0, 1:] = np.nan
    assert np.isnan(interpolate_maturities(panel, [2.0]).iloc[0, 0])


def test_zero_panel_from_factors_matches_loadings():
    idx = pd.date_range("2024-01-31", periods=3, freq="ME")
    factors = pd.DataFrame({"Level": 0.04, "Slope": -0.01, "Curvature": 0.005, "Tau": 1.5, "RMSE": 0.0}, index=idx)
    panel = zero_panel_from_factors(factors, [0.25, 2, 10])
    from nelson_siegel.model import NelsonSiegelModel

    expected = NelsonSiegelModel.model_function(np.array([0.25, 2.0, 10.0]), 0.04, -0.01, 0.005, 1.5)
    assert np.allclose(panel.iloc[0].to_numpy(), expected)
    assert list(panel.columns) == [0.25, 2.0, 10.0]


def test_newey_west_regression_and_eh_tests():
    rng = np.random.default_rng(3)
    x = rng.normal(size=200)
    y = 0.5 + 2.0 * x + rng.normal(scale=0.1, size=200)
    res = ols_newey_west(x, y, lags=2)
    assert np.isclose(res.slope, 2.0, atol=0.05) and np.isclose(res.intercept, 0.5, atol=0.05)
    assert res.t_stat_vs_zero > 20 and res.t_stat_vs_one > 10 and res.r_squared > 0.99
    assert res.as_dict()["n_obs"] == 200 and res.lags == 2
    with pytest.raises(ValueError):
        ols_newey_west(x[:5], y[:5], 1)

    # Under a pure random-walk short rate the EH holds: Campbell-Shiller slope ~ 1.
    T = 480
    r = 0.03 + np.cumsum(rng.normal(0, 0.0008, T))
    idx = pd.date_range("1985-01-31", periods=T, freq="ME")
    panel = pd.DataFrame({m: r + rng.normal(0, 1e-5, T) for m in (1 / 12, 1.0, 4.0, 5.0, 9.0, 10.0)}, index=idx)
    cs = campbell_shiller(panel, 10.0, 1.0)
    assert abs(cs.slope - 1.0) < 3 * max(cs.slope_se, 0.05) + 0.5
    fb = fama_bliss(panel, 5.0, 1.0)
    assert np.isfinite(fb.slope) and fb.n_obs == T - 12
    with pytest.raises(ValueError):
        campbell_shiller(panel, 1.0, 1.0)
    with pytest.raises(ValueError):
        fama_bliss(panel, 1.0, 1.0)
    with pytest.raises(ValueError):
        campbell_shiller(panel, 10.0, 0.001, steps_per_year=12)


def test_dns_term_premium_uses_factor_dynamics():
    analyzer = YieldCurveAnalyzer()
    factors = analyzer.analyze_historical_factors("treasury", "2019-01-01", "2026-06-30")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dns = DynamicNelsonSiegel("ar").fit(factors)
    out = dns_term_premium(dns, factors, [2.0, 5.0, 10.0])
    assert set(out) == {"fitted", "expected_short_rate", "term_premium"}
    for frame in out.values():
        assert list(frame.columns) == [2.0, 5.0, 10.0] and len(frame) == len(factors)
    assert np.allclose(out["fitted"] - out["expected_short_rate"], out["term_premium"])
    # Expected-rate average over ~0 years equals today's short rate Level + Slope.
    tiny = dns_term_premium(dns, factors, [1 / 52])["expected_short_rate"].iloc[-1, 0]
    assert np.isclose(tiny, factors["Level"].iloc[-1] + factors["Slope"].iloc[-1], atol=1e-6)
    # Random walk: expected path is flat, so the EH yield is today's short rate.
    rw = DynamicNelsonSiegel("rw").fit(factors)
    flat = dns_term_premium(rw, factors, [5.0])["expected_short_rate"].iloc[:, 0]
    assert np.allclose(flat, factors["Level"] + factors["Slope"])
    with pytest.raises(ValueError):
        dns_term_premium(DynamicNelsonSiegel("ar"), factors, [5.0])


def test_short_rate_term_premium_table():
    history = VasicekModel().set_params(0.04, 0.4, 0.03, 0.01).simulate(30, 1, 52, seed=5).iloc[:, 0]
    history.index = pd.date_range("1990-01-01", periods=len(history), freq="W")
    est = estimate_short_rate(history, "vasicek")
    table = short_rate_term_premium(est, [1, 5, 10], [0.041, 0.043, 0.046])
    assert list(table.columns) == ["observed", "expected_short_rate", "term_premium"]
    assert np.allclose(table["observed"] - table["expected_short_rate"], table["term_premium"])
    assert table.index.name == "maturity"
    # Expected average converges toward theta with maturity.
    eh = table["expected_short_rate"].to_numpy()
    assert abs(eh[-1] - est.theta) < abs(eh[0] - est.theta)
    with pytest.raises(ValueError):
        short_rate_term_premium(est, [1, 5], [0.04])
    custom = short_rate_term_premium(est, [1.0], [0.04], r0=0.05)
    assert custom["expected_short_rate"].iloc[0] > table["expected_short_rate"].iloc[0]
    assert isinstance(est, ShortRateEstimate)

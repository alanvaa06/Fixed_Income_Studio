"""Focused tests for analysis-layer performance helpers."""

import time

import numpy as np
import pandas as pd

from nelson_siegel.analysis import YieldCurveAnalyzer
from nelson_siegel.model import NelsonSiegelModel


def test_resample_long_range_reduces_observation_count():
    """Long daily ranges are downsampled for interactive workloads."""
    analyzer = YieldCurveAnalyzer()
    dates = pd.date_range("2023-01-01", periods=800, freq="D")
    frame = pd.DataFrame(
        {
            1.0: [0.02] * len(dates),
            2.0: [0.025] * len(dates),
            5.0: [0.03] * len(dates),
            10.0: [0.035] * len(dates),
        },
        index=dates,
    )

    sampled = analyzer._resample_long_range(frame)

    assert len(sampled) < len(frame)
    assert sampled.index.is_monotonic_increasing


def _synthetic_yields_frame(n_dates: int, tau: float = 1.5, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    maturities = np.array([0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0])
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="W-FRI")
    level = 0.03 + 0.005 * np.sin(np.linspace(0, 6, n_dates))
    slope = -0.01 + 0.002 * np.cos(np.linspace(0, 5, n_dates))
    curve = 0.005 + 0.001 * rng.standard_normal(n_dates)
    rows = []
    for i in range(n_dates):
        y = NelsonSiegelModel.model_function(maturities, level[i], slope[i], curve[i], tau)
        rows.append(y)
    return pd.DataFrame(np.vstack(rows), index=dates, columns=maturities)


def test_batch_fit_factors_matches_per_row_reference():
    frame = _synthetic_yields_frame(50)
    tau = 1.5

    batch = YieldCurveAnalyzer._batch_fit_factors(frame, tau)

    expected = []
    for date, row in frame.iterrows():
        m = NelsonSiegelModel()
        m.fit_fixed_tau(frame.columns.values, row.values, tau=tau)
        expected.append((m.parameters["beta0"], m.parameters["beta1"], m.parameters["beta2"]))
    expected_arr = np.array(expected)

    assert np.allclose(batch[["Level", "Slope", "Curvature"]].to_numpy(), expected_arr, atol=1e-10)
    assert (batch["Tau"] == tau).all()


def test_batch_fit_factors_handles_mixed_nan_masks():
    frame = _synthetic_yields_frame(20)
    # Drop the 30y column from rows 0-4, the 0.5y column from rows 5-9, leave the rest.
    frame.iloc[0:5, -1] = np.nan
    frame.iloc[5:10, 0] = np.nan
    tau = 1.5

    batch = YieldCurveAnalyzer._batch_fit_factors(frame, tau)

    assert len(batch) == len(frame)
    for date, row in frame.iterrows():
        m = NelsonSiegelModel()
        m.fit_fixed_tau(frame.columns.values, row.values, tau=tau)
        assert np.isclose(batch.loc[date, "Level"], m.parameters["beta0"], atol=1e-10)
        assert np.isclose(batch.loc[date, "Slope"], m.parameters["beta1"], atol=1e-10)


def test_batch_fit_factors_skips_rows_with_too_few_points():
    frame = _synthetic_yields_frame(5)
    frame.iloc[0, :] = np.nan
    frame.iloc[1, 1:] = np.nan  # only one valid maturity

    batch = YieldCurveAnalyzer._batch_fit_factors(frame, tau=1.5, min_data_points=3)

    assert len(batch) == 3
    assert frame.index[0] not in batch.index
    assert frame.index[1] not in batch.index


def test_estimate_global_tau_returns_finite_value():
    analyzer = YieldCurveAnalyzer()
    tau = analyzer._estimate_global_tau("treasury")
    assert np.isfinite(tau)
    assert 0 < tau <= 10
    assert analyzer._global_tau["treasury"] == tau


def test_estimate_global_tau_reuses_supplied_data(monkeypatch):
    """Passing the already-downloaded frame must not trigger a second download."""
    analyzer = YieldCurveAnalyzer()
    frame = _synthetic_yields_frame(30, tau=1.5)
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("download should not happen")

    monkeypatch.setattr(analyzer.data_manager, "get_treasury_data", boom)
    tau = analyzer._estimate_global_tau("treasury", data=frame)
    assert calls["n"] == 0
    assert np.isclose(tau, 1.5, atol=0.02)


def test_panel_profile_tau_recovers_common_tau():
    """Pooled profile over many curves recovers the shared decay parameter."""
    frame = _synthetic_yields_frame(120, tau=2.3, seed=11)
    tau = YieldCurveAnalyzer._panel_profile_tau(frame, (0.05, 10.0))
    assert np.isclose(tau, 2.3, atol=0.01)


def test_panel_profile_tau_more_stable_than_single_curve():
    """Panel estimate should be closer to truth than a noisy single-date fit on average."""
    rng = np.random.default_rng(5)
    frame = _synthetic_yields_frame(80, tau=1.8, seed=2)
    noisy = frame + rng.normal(0, 3e-4, frame.shape)
    panel_tau = YieldCurveAnalyzer._panel_profile_tau(noisy, (0.05, 10.0))
    single_errors = []
    for _, row in noisy.iloc[::10].iterrows():
        m = NelsonSiegelModel().fit(noisy.columns.values, row.values)
        single_errors.append(abs(m.parameters["tau"] - 1.8))
    assert abs(panel_tau - 1.8) <= np.mean(single_errors) + 1e-9


def test_batch_fit_factors_reports_rmse():
    frame = _synthetic_yields_frame(10, tau=1.5)
    batch = YieldCurveAnalyzer._batch_fit_factors(frame, 1.5)
    assert "RMSE" in batch.columns
    assert (batch["RMSE"] < 1e-8).all()
    frame_noisy = frame + 1e-3
    frame_noisy.iloc[:, 0] += 5e-3
    batch_noisy = YieldCurveAnalyzer._batch_fit_factors(frame_noisy, 1.5)
    assert (batch_noisy["RMSE"] > 1e-4).all()


def test_analyze_single_curve_exposes_fit_stats_and_forward():
    analyzer = YieldCurveAnalyzer()
    result = analyzer.analyze_single_curve(
        "treasury",
        yields_data={0.5: 0.045, 1.0: 0.043, 2.0: 0.040, 5.0: 0.038, 10.0: 0.040, 30.0: 0.043},
    )
    assert result["fit_stats"]["method"] == "profile"
    assert len(result["smooth_forward"]) == len(result["smooth_maturities"])
    assert np.all(np.isfinite(result["smooth_forward"]))


def test_compare_curves_skips_tau_correlation():
    analyzer = YieldCurveAnalyzer()
    result = analyzer.compare_curves("2024-01-01", "2025-12-31")
    assert "Tau" not in result["correlations"]
    assert set(result["correlations"]) == {"Level", "Slope", "Curvature"}
    assert "Tau" in result["differences"]


def test_factor_time_series_parity_with_variable_tau():
    """New fixed-tau historical fit should track the per-date variable-tau path."""
    from nelson_siegel.model import TreasuryNelsonSiegelModel

    rng = np.random.default_rng(7)
    maturities = np.array([0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0])
    n = 200
    dates = pd.date_range("2020-01-01", periods=n, freq="W-FRI")
    level = 0.03 + 0.005 * np.sin(np.linspace(0, 6, n))
    slope = -0.01 + 0.003 * np.cos(np.linspace(0, 5, n))
    curve = 0.005 + 0.002 * rng.standard_normal(n)
    tau = 1.4 + 0.1 * np.sin(np.linspace(0, 4, n))
    Y = np.vstack([
        NelsonSiegelModel.model_function(maturities, level[i], slope[i], curve[i], tau[i])
        for i in range(n)
    ])
    frame = pd.DataFrame(Y, index=dates, columns=maturities)

    # Reference: per-date variable-tau curve_fit (the prior implementation).
    ref_levels, ref_slopes, ref_curvs = [], [], []
    for _, row in frame.iterrows():
        m = TreasuryNelsonSiegelModel()
        m.fit(maturities, row.values)
        ref_levels.append(m.parameters["beta0"])
        ref_slopes.append(m.parameters["beta1"])
        ref_curvs.append(m.parameters["beta2"])

    # New path: fixed-tau closed-form, tau picked once.
    fixed_tau = float(np.median(tau))
    batch = YieldCurveAnalyzer._batch_fit_factors(frame, fixed_tau)

    assert np.corrcoef(batch["Level"].values, ref_levels)[0, 1] >= 0.95
    assert np.corrcoef(batch["Slope"].values, ref_slopes)[0, 1] >= 0.95
    assert np.corrcoef(batch["Curvature"].values, ref_curvs)[0, 1] >= 0.95


def test_analyze_historical_factors_speed_under_one_second():
    analyzer = YieldCurveAnalyzer()
    start = (pd.Timestamp.today() - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = pd.Timestamp.today().strftime("%Y-%m-%d")

    started = time.perf_counter()
    factors = analyzer.analyze_historical_factors("treasury", start_date=start, end_date=end)
    elapsed = time.perf_counter() - started

    assert len(factors) > 100
    assert elapsed < 2.0  # generous bound; real run is well under 1s

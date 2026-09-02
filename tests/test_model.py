"""Tests for the Nelson-Siegel model implementation."""

import numpy as np
import pytest

from nelson_siegel.model import (
    NelsonSiegelModel,
    SvenssonModel,
    TreasuryNelsonSiegelModel,
    TIPSNelsonSiegelModel
)


class TestNelsonSiegelModel:
    """Test cases for the base Nelson-Siegel model."""
    
    def test_model_initialization(self):
        """Test model initialization with default parameters."""
        model = NelsonSiegelModel()
        assert model.fitted is False
        assert model.parameters is None
        assert model.bounds is not None
        assert model.initial_guess is not None
    
    def test_model_initialization_with_custom_params(self):
        """Test model initialization with custom parameters."""
        bounds = ([-1, -2, -3, 0], [10, 20, 30, 5])
        initial_guess = (5.0, 1.0, -1.0, 2.0)
        
        model = NelsonSiegelModel(bounds=bounds, initial_guess=initial_guess)
        assert model.bounds == bounds
        assert model.initial_guess == initial_guess
    
    def test_model_function_basic(self):
        """Test the Nelson-Siegel model function with basic inputs."""
        t = np.array([1, 2, 5, 10])
        beta0, beta1, beta2, tau = 0.05, -0.01, 0.02, 2.0
        
        result = NelsonSiegelModel.model_function(t, beta0, beta1, beta2, tau)
        
        assert isinstance(result, np.ndarray)
        assert len(result) == len(t)
        assert np.all(np.isfinite(result))
    
    def test_model_function_zero_maturity(self):
        """Test model function handles zero maturity correctly."""
        t = np.array([0, 1, 2])
        beta0, beta1, beta2, tau = 0.05, -0.01, 0.02, 2.0
        
        result = NelsonSiegelModel.model_function(t, beta0, beta1, beta2, tau)
        
        # At t=0, the function should equal beta0 + beta1
        expected_zero = beta0 + beta1
        assert np.isclose(result[0], expected_zero, rtol=1e-10)
    
    def test_fit_basic_case(self):
        """Test fitting with basic synthetic data."""
        # Generate synthetic data
        maturities = np.array([1, 2, 5, 10, 30])
        true_params = (0.04, -0.01, 0.005, 2.0)
        yields = NelsonSiegelModel.model_function(maturities, *true_params)
        
        # Add small amount of noise
        np.random.seed(42)
        yields += np.random.normal(0, 0.0001, len(yields))
        
        model = NelsonSiegelModel()
        model.fit(maturities, yields)
        
        assert model.fitted is True
        assert model.parameters is not None
        
        # Check that fitted parameters are reasonable
        factors = model.get_factors()
        assert 'Level' in factors
        assert 'Slope' in factors
        assert 'Curvature' in factors
        assert 'Tau' in factors
        
        # Level is well identified; tau is only weakly identified by five noisy
        # points, so check the fit is at least as good as the true parameters
        # (the least-squares optimum for this sample sits near tau = 2.5).
        assert abs(factors['Level'] - true_params[0]) < 0.01
        assert 0.5 < factors['Tau'] < 5.0
        sse_true = float(((NelsonSiegelModel.model_function(maturities, *true_params) - yields) ** 2).sum())
        assert model.fit_stats()['sse'] <= sse_true + 1e-12
    
    def test_fit_insufficient_data(self):
        """Test that fitting fails with insufficient data points."""
        maturities = np.array([1, 2])  # Only 2 points, need at least 4
        yields = np.array([0.02, 0.025])
        
        model = NelsonSiegelModel()
        
        with pytest.raises(ValueError, match="Need at least 4 data points"):
            model.fit(maturities, yields)
    
    def test_fit_mismatched_lengths(self):
        """Test that fitting fails with mismatched input lengths."""
        maturities = np.array([1, 2, 5, 10])
        yields = np.array([0.02, 0.025, 0.03])  # One less element
        
        model = NelsonSiegelModel()
        
        with pytest.raises(ValueError, match="must have the same length"):
            model.fit(maturities, yields)
    
    def test_fit_with_nans(self):
        """Test fitting with NaN values in data."""
        maturities = np.array([1, 2, 5, 10, 30])
        yields = np.array([0.02, np.nan, 0.03, 0.035, 0.04])
        
        model = NelsonSiegelModel()
        model.fit(maturities, yields)
        
        assert model.fitted is True
        assert model.parameters is not None
    
    def test_fit_too_many_nans(self):
        """Test fitting fails with too many NaN values."""
        maturities = np.array([1, 2, 5, 10, 30])
        yields = np.array([0.02, np.nan, np.nan, np.nan, np.nan])  # Only 1 valid point
        
        model = NelsonSiegelModel()
        
        with pytest.raises(ValueError, match="Insufficient valid data points"):
            model.fit(maturities, yields)
    
    def test_predict_before_fit(self):
        """Test that prediction fails before fitting."""
        model = NelsonSiegelModel()
        maturities = np.array([1, 2, 5])
        
        with pytest.raises(ValueError, match="Model must be fitted before prediction"):
            model.predict(maturities)
    
    def test_predict_after_fit(self):
        """Test prediction after successful fitting."""
        # Fit model first
        maturities = np.array([1, 2, 5, 10, 30])
        yields = np.array([0.02, 0.025, 0.03, 0.035, 0.04])
        
        model = NelsonSiegelModel()
        model.fit(maturities, yields)
        
        # Test prediction
        test_maturities = np.array([3, 7, 15])
        predictions = model.predict(test_maturities)
        
        assert isinstance(predictions, np.ndarray)
        assert len(predictions) == len(test_maturities)
        assert np.all(np.isfinite(predictions))
        assert np.all(predictions > 0)  # Yields should be positive
    
    def test_get_factors_before_fit(self):
        """Test that getting factors fails before fitting."""
        model = NelsonSiegelModel()
        
        with pytest.raises(ValueError, match="Model must be fitted before accessing factors"):
            model.get_factors()
    
    def test_calculate_deviations(self):
        """Test calculation of deviations between observed and fitted yields."""
        # Fit model
        maturities = np.array([1, 2, 5, 10, 30])
        yields = np.array([0.02, 0.025, 0.03, 0.035, 0.04])
        
        model = NelsonSiegelModel()
        model.fit(maturities, yields)
        
        # Calculate deviations
        deviations = model.calculate_deviations(maturities, yields)
        
        assert isinstance(deviations, np.ndarray)
        assert len(deviations) == len(maturities)
        assert np.all(np.isfinite(deviations))
        
        # Deviations should be small for the same data used in fitting
        assert np.max(np.abs(deviations)) < 0.01  # Should fit well
    
    def test_classify_bonds(self):
        """Test bond classification as cheap or expensive."""
        # Fit model
        maturities = np.array([1, 2, 5, 10, 30])
        yields = np.array([0.02, 0.025, 0.03, 0.035, 0.04])
        
        model = NelsonSiegelModel()
        model.fit(maturities, yields)
        
        # Test with slightly different yields
        test_yields = yields + np.array([-0.001, 0.001, -0.001, 0.001, 0.0])
        classifications = model.classify_bonds(maturities, test_yields)
        
        assert len(classifications) == len(maturities)
        assert all(c in ['cheap', 'expensive'] for c in classifications)
        
        # First and third should be cheap (negative deviations)
        assert classifications[0] == 'cheap'
        assert classifications[2] == 'cheap'
        
        # Second and fourth should be expensive (positive deviations)
        assert classifications[1] == 'expensive'
        assert classifications[3] == 'expensive'
    
    def test_model_repr_unfitted(self):
        """Test string representation of unfitted model."""
        model = NelsonSiegelModel()
        repr_str = repr(model)
        
        assert "NelsonSiegelModel" in repr_str
        assert "fitted=False" in repr_str
    
    def test_model_repr_fitted(self):
        """Test string representation of fitted model."""
        # Fit model
        maturities = np.array([1, 2, 5, 10, 30])
        yields = np.array([0.02, 0.025, 0.03, 0.035, 0.04])
        
        model = NelsonSiegelModel()
        model.fit(maturities, yields)
        
        repr_str = repr(model)
        
        assert "NelsonSiegelModel" in repr_str
        assert "fitted=True" in repr_str
        assert "Level=" in repr_str
        assert "Slope=" in repr_str
        assert "Curvature=" in repr_str
        assert "Tau=" in repr_str


class TestFixedTauHelpers:
    """Closed-form Diebold-Li helpers used by the historical fit path."""

    def test_basis_shape_and_t_zero_limits(self):
        maturities = np.array([0.0, 0.5, 1.0, 5.0, 30.0])
        X = NelsonSiegelModel.basis(maturities, tau=1.5)

        assert X.shape == (5, 3)
        assert np.allclose(X[:, 0], 1.0)
        # At t=0, f1 -> 1 and f2 -> 0
        assert np.isclose(X[0, 1], 1.0)
        assert np.isclose(X[0, 2], 0.0)

    def test_basis_rejects_non_positive_tau(self):
        with pytest.raises(ValueError, match="tau must be strictly positive"):
            NelsonSiegelModel.basis(np.array([1.0, 2.0]), tau=0.0)

    def test_fit_fixed_tau_recovers_known_betas(self):
        maturities = np.array([0.5, 1, 2, 3, 5, 7, 10, 20, 30], dtype=float)
        true_tau = 1.7
        true_betas = (0.04, -0.012, 0.018)
        beta0, beta1, beta2 = true_betas
        yields = NelsonSiegelModel.model_function(maturities, beta0, beta1, beta2, true_tau)

        model = NelsonSiegelModel()
        model.fit_fixed_tau(maturities, yields, tau=true_tau)

        assert model.fitted is True
        assert np.isclose(model.parameters['beta0'], beta0, atol=1e-10)
        assert np.isclose(model.parameters['beta1'], beta1, atol=1e-10)
        assert np.isclose(model.parameters['beta2'], beta2, atol=1e-10)
        assert model.parameters['tau'] == true_tau

    def test_fit_fixed_tau_too_few_points(self):
        model = NelsonSiegelModel()
        with pytest.raises(ValueError, match="at least 3 valid points"):
            model.fit_fixed_tau(np.array([1.0, 2.0]), np.array([0.02, 0.025]), tau=1.5)

    def test_fit_fixed_tau_drops_nans(self):
        maturities = np.array([1, 2, 3, 5, np.nan, 10], dtype=float)
        yields = np.array([0.02, 0.025, 0.028, 0.032, 0.035, 0.04], dtype=float)
        model = NelsonSiegelModel()
        model.fit_fixed_tau(maturities, yields, tau=1.5)
        assert model.fitted is True


class TestTreasuryNelsonSiegelModel:
    """Test cases for the Treasury-specific model."""
    
    def test_treasury_model_initialization(self):
        """Test Treasury model has correct default parameters."""
        model = TreasuryNelsonSiegelModel()
        
        # Check bounds
        lower_bounds, upper_bounds = model.bounds
        assert lower_bounds == [0, -5, -5, 0]
        assert upper_bounds == [11, 10, 10, 10]
        
        # Check initial guess
        assert model.initial_guess == (4.0, 0.0, 0.0, 1.0)
    
    def test_treasury_model_fitting(self):
        """Test Treasury model can fit typical Treasury yield data."""
        # Typical Treasury yield curve (inverted)
        maturities = np.array([0.25, 1, 2, 5, 10, 30])
        yields = np.array([0.052, 0.048, 0.045, 0.042, 0.041, 0.043])
        
        model = TreasuryNelsonSiegelModel()
        model.fit(maturities, yields)
        
        assert model.fitted is True
        factors = model.get_factors()
        
        # Level should be positive for Treasury yields
        assert factors['Level'] > 0
        
        # Nelson-Siegel slope is (short - long): positive for an inverted curve
        assert factors['Slope'] > 0
        assert model.predict([0.25])[0] > model.predict([30.0])[0]


class TestTIPSNelsonSiegelModel:
    """Test cases for the TIPS-specific model."""
    
    def test_tips_model_initialization(self):
        """Test TIPS model has correct default parameters."""
        model = TIPSNelsonSiegelModel()
        
        # Check bounds (allows negative level for real yields)
        lower_bounds, upper_bounds = model.bounds
        assert lower_bounds == [-2, -5, -5, 0]
        assert upper_bounds == [8, 10, 10, 10]
        
        # Check initial guess (lower level for real yields)
        assert model.initial_guess == (1.0, 0.0, 0.0, 1.0)
    
    def test_tips_model_fitting_positive_yields(self):
        """Test TIPS model with positive real yields."""
        # Typical TIPS real yield curve
        maturities = np.array([5, 7, 10, 20, 30])
        yields = np.array([0.01, 0.012, 0.015, 0.018, 0.019])
        
        model = TIPSNelsonSiegelModel()
        model.fit(maturities, yields)
        
        assert model.fitted is True
        factors = model.get_factors()
        
        # Level should be positive but lower than Treasury
        assert factors['Level'] > 0
        assert factors['Level'] < 0.03  # Should be reasonable real yield level
    
    def test_tips_model_fitting_negative_yields(self):
        """Test TIPS model can handle negative real yields."""
        # TIPS with some negative real yields (realistic scenario)
        maturities = np.array([5, 7, 10, 20, 30])
        yields = np.array([-0.005, -0.002, 0.001, 0.008, 0.010])
        
        model = TIPSNelsonSiegelModel()
        model.fit(maturities, yields)
        
        assert model.fitted is True
        factors = model.get_factors()
        
        # Level can be negative for TIPS
        # The model should still fit successfully
        assert abs(factors['Level']) < 0.05  # Should be reasonable


MATS = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30], dtype=float)


class TestProfileFit:
    """Default profile-likelihood fitter: grid over tau + closed-form betas."""

    def test_recovers_exact_parameters_on_noiseless_data(self):
        true = (0.04, -0.012, 0.018, 1.7)
        yields = NelsonSiegelModel.model_function(MATS, *true)
        model = NelsonSiegelModel().fit(MATS, yields)
        p = model.parameters
        assert np.isclose(p['beta0'], true[0], atol=1e-8)
        assert np.isclose(p['beta1'], true[1], atol=1e-8)
        assert np.isclose(p['beta2'], true[2], atol=1e-8)
        assert np.isclose(p['tau'], true[3], atol=1e-4)
        assert model.fit_stats()['method'] == 'profile'
        assert model.fit_stats()['rmse'] < 1e-8

    def test_profile_never_worse_than_curve_fit(self):
        rng = np.random.default_rng(3)
        for _ in range(10):
            true = (0.03 + 0.02 * rng.random(), -0.02 * rng.random(), 0.03 * (rng.random() - 0.5),
                    0.3 + 4 * rng.random())
            yields = NelsonSiegelModel.model_function(MATS, *true) + rng.normal(0, 2e-4, len(MATS))
            profile = NelsonSiegelModel().fit(MATS, yields, method='profile')
            legacy = NelsonSiegelModel().fit(MATS, yields, method='curve_fit')
            assert profile.fit_stats()['sse'] <= legacy.fit_stats()['sse'] * (1 + 1e-6) + 1e-14

    def test_is_deterministic(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.01, 0.01, 2.2)
        a = NelsonSiegelModel().fit(MATS, yields).parameters
        b = NelsonSiegelModel().fit(MATS, yields).parameters
        assert a == b

    def test_respects_tau_bounds(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.01, 0.01, 8.0)
        model = NelsonSiegelModel(bounds=([-1, -1, -1, 0.1], [1, 1, 1, 3.0])).fit(MATS, yields)
        assert 0.1 <= model.parameters['tau'] <= 3.0
        # Constrained fit must not beat the unconstrained optimum.
        free = NelsonSiegelModel().fit(MATS, yields)
        assert model.fit_stats()['sse'] >= free.fit_stats()['sse'] - 1e-15

    def test_decay_at_bound_flag(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.01, 0.01, 2.0)
        edge = MATS.max() / NelsonSiegelModel.hump_location_factor
        assert NelsonSiegelModel().fit_fixed_tau(MATS, yields, tau=edge).fit_stats()['decay_at_bound'] is True
        assert NelsonSiegelModel().fit_fixed_tau(MATS, yields, tau=2.0).fit_stats()['decay_at_bound'] is False

    def test_weakly_identified_curvature_still_finds_global_optimum(self):
        # Tiny curvature makes the profile SSE multi-modal in tau; the fitter
        # must still land on the exact (zero-residual) solution.
        mats = np.array([0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0])
        true = (0.03, -0.0085, 0.0027, 1.46)
        model = NelsonSiegelModel().fit(mats, NelsonSiegelModel.model_function(mats, *true))
        assert np.isclose(model.parameters['tau'], true[3], atol=1e-3)
        assert model.fit_stats()['sse'] < 1e-14

    def test_beta_bounds_trigger_bounded_fallback(self):
        # Force a violation: level bounded away from the data's true level.
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.01, 0.01, 2.0)
        model = NelsonSiegelModel(bounds=([0.05, -1, -1, 0.05], [1, 1, 1, 30])).fit(MATS, yields)
        assert model.parameters['beta0'] >= 0.05 - 1e-9
        assert model.fit_stats()['method'] == 'profile+curve_fit'

    def test_hump_constraint_prevents_collinear_blowup(self):
        # Long-only maturities (5-30y) with a gently curved shape: an
        # unconstrained tau ~0.1 gives near-collinear loadings and betas of
        # several hundred percent. The default hump constraint prevents that.
        mats = np.array([5.0, 7.0, 10.0, 20.0, 30.0])
        # A curve that a tiny tau with huge offsetting betas reproduces exactly
        # (this parameter set came out of an unconstrained fit on synthetic TIPS
        # data). Between 5y and 30y it is just a gently curved ~2.35% curve.
        yields = NelsonSiegelModel.model_function(mats, 0.0235, 4.77, -5.0, 0.12)
        assert np.all((yields > 0.015) & (yields < 0.03))

        model = TIPSNelsonSiegelModel().fit(mats, yields)
        assert model.parameters['tau'] >= mats.min() / 1.8 - 1e-9
        assert abs(model.parameters['beta1']) < 0.2 and abs(model.parameters['beta2']) < 0.2
        assert model.fit_stats()['rmse'] < 0.001  # still within 10 bps

        free = TIPSNelsonSiegelModel()
        free.hump_location_factor = None
        free.fit(mats, yields)
        assert free.parameters['tau'] < mats.min() / 1.8  # the unidentifiable region

    def test_unknown_method_rejected(self):
        with pytest.raises(ValueError, match="method must be"):
            NelsonSiegelModel().fit(MATS, np.full(len(MATS), 0.03), method='nope')

    def test_fit_stats_before_fit_raises(self):
        with pytest.raises(ValueError, match="fitted before"):
            NelsonSiegelModel().fit_stats()

    def test_fit_stats_r_squared(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.015, 0.01, 1.5)
        stats = NelsonSiegelModel().fit(MATS, yields).fit_stats()
        assert stats['n_obs'] == len(MATS)
        assert stats['r_squared'] > 0.999999


class TestCurveConstruction:
    """Forward rates and discount factors derived from the fitted curve."""

    def test_forward_rate_matches_numerical_derivative(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.012, 0.018, 1.7)
        model = NelsonSiegelModel().fit(MATS, yields)
        t = np.array([0.5, 2.0, 7.0, 15.0])
        h = 1e-5
        numeric = ((t + h) * model.predict(t + h) - (t - h) * model.predict(t - h)) / (2 * h)
        assert np.allclose(model.forward_rate(t), numeric, atol=1e-8)

    def test_forward_rate_limits(self):
        model = NelsonSiegelModel().fit_fixed_tau(MATS, np.full(len(MATS), 0.03), tau=2.0)
        model.parameters.update({'beta0': 0.05, 'beta1': -0.02, 'beta2': 0.01})
        # f(0) = beta0 + beta1, f(inf) -> beta0
        assert np.isclose(model.forward_rate([0.0])[0], 0.03)
        assert np.isclose(model.forward_rate([1e4])[0], 0.05, atol=1e-8)

    def test_discount_factor(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.012, 0.018, 1.7)
        model = NelsonSiegelModel().fit(MATS, yields)
        t = np.array([1.0, 10.0])
        expected = np.exp(-t * model.predict(t))
        assert np.allclose(model.discount_factor(t), expected)
        assert np.isclose(model.discount_factor([0.0])[0], 1.0)

    def test_derived_quantities_require_fit(self):
        with pytest.raises(ValueError):
            NelsonSiegelModel().forward_rate([1.0])
        with pytest.raises(ValueError):
            NelsonSiegelModel().discount_factor([1.0])


class TestSvenssonModel:
    """Six-parameter Svensson extension reusing the same fitting seam."""

    def test_recovers_parameters(self):
        true = (0.045, -0.02, 0.01, -0.015, 1.2, 8.0)
        yields = SvenssonModel.model_function(MATS, *true)
        model = SvenssonModel().fit(MATS, yields)
        values = [model.parameters[k] for k in SvenssonModel.param_names]
        assert np.allclose(values[:4], true[:4], atol=1e-6)
        assert np.allclose(values[4:], true[4:], rtol=1e-3)
        factors = model.get_factors()
        assert set(factors) == {'Level', 'Slope', 'Curvature', 'Curvature2', 'Tau', 'Tau2'}

    def test_nests_nelson_siegel(self):
        yields = NelsonSiegelModel.model_function(MATS, 0.04, -0.012, 0.018, 1.7)
        assert SvenssonModel().fit(MATS, yields).fit_stats()['rmse'] < 1e-5

    def test_requires_six_points(self):
        with pytest.raises(ValueError, match="at least 6 data points"):
            SvenssonModel().fit(MATS[:5], np.full(5, 0.03))

    def test_forward_rate_matches_numerical_derivative(self):
        true = (0.045, -0.02, 0.01, -0.015, 1.2, 8.0)
        model = SvenssonModel().fit(MATS, SvenssonModel.model_function(MATS, *true))
        t = np.array([0.5, 2.0, 7.0, 15.0])
        h = 1e-5
        numeric = ((t + h) * model.predict(t + h) - (t - h) * model.predict(t - h)) / (2 * h)
        assert np.allclose(model.forward_rate(t), numeric, atol=1e-8)

    def test_fixed_decays_closed_form(self):
        true = (0.045, -0.02, 0.01, -0.015, 1.2, 8.0)
        yields = SvenssonModel.model_function(MATS, *true)
        model = SvenssonModel().fit_fixed_decays(MATS, yields, 1.2, 8.0)
        assert np.allclose([model.parameters[k] for k in ('beta0', 'beta1', 'beta2', 'beta3')],
                           true[:4], atol=1e-10)
        with pytest.raises(ValueError, match="Expected 2 decay"):
            SvenssonModel().fit_fixed_decays(MATS, yields, 1.2)

    def test_repr_lists_all_factors(self):
        true = (0.045, -0.02, 0.01, -0.015, 1.2, 8.0)
        model = SvenssonModel().fit(MATS, SvenssonModel.model_function(MATS, *true))
        assert 'Curvature2=' in repr(model) and 'Tau2=' in repr(model)


class TestCurveModelProtocolAndRegistry:
    """The seam that lets further models plug into the analyzer and the app."""

    def test_builtin_models_satisfy_protocol(self):
        from nelson_siegel.model import CurveModel

        assert isinstance(NelsonSiegelModel(), CurveModel)
        assert isinstance(SvenssonModel(), CurveModel)
        assert isinstance(TreasuryNelsonSiegelModel(), CurveModel)
        assert not isinstance(object(), CurveModel)

    def test_minimal_third_party_model_satisfies_protocol(self):
        """Documents the surface a spline/bootstrap model must provide."""
        from nelson_siegel.model import CurveModel, FactorMeta

        class FlatCurve:
            model_id = "flat"
            display_name = "Flat"
            fitted = False

            def fit(self, maturities, yields):
                self.level = float(np.mean(yields))
                self.fitted = True
                return self

            def predict(self, maturities):
                return np.full(len(np.asarray(maturities)), self.level)

            def forward_rate(self, maturities):
                return self.predict(maturities)

            def discount_factor(self, maturities):
                t = np.asarray(maturities, dtype=float)
                return np.exp(-t * self.level)

            def get_factors(self):
                return {"Level": self.level}

            def fit_stats(self):
                return {"method": "mean", "n_obs": 0, "sse": 0.0, "rmse": 0.0}

            @classmethod
            def factor_meta(cls):
                return (FactorMeta("level", "Level", "L", "rate", "flat"),)

            @classmethod
            def describe(cls):
                return {"id": cls.model_id, "name": cls.display_name, "n_params": 1}

        assert isinstance(FlatCurve(), CurveModel)

    def test_factor_meta_matches_param_names(self):
        for cls in (NelsonSiegelModel, SvenssonModel):
            assert tuple(m.key for m in cls.factor_meta()) == cls.param_names
            assert [m.label for m in cls.factor_meta()] == [cls.factor_labels[k] for k in cls.param_names]
            units = [m.unit for m in cls.factor_meta()]
            assert units[: cls.n_linear] == ["rate"] * cls.n_linear
            assert units[cls.n_linear :] == ["years"] * (len(cls.param_names) - cls.n_linear)

    def test_describe_is_json_friendly(self):
        import json

        for cls in (NelsonSiegelModel, SvenssonModel):
            desc = cls.describe()
            json.dumps(desc)
            assert desc["id"] == cls.model_id
            assert desc["n_params"] == len(cls.param_names)
            assert len(desc["factors"]) == len(cls.param_names)

    def test_registry_lookup_and_presets(self):
        from nelson_siegel.model import MODEL_REGISTRY, get_model_class, list_models, make_model

        assert set(MODEL_REGISTRY) == {"nelson-siegel", "svensson"}
        assert get_model_class("SVENSSON") is SvenssonModel
        assert get_model_class("nelson_siegel") is NelsonSiegelModel
        assert isinstance(make_model("nelson-siegel", "treasury"), TreasuryNelsonSiegelModel)
        assert isinstance(make_model("nelson-siegel", "tips"), TIPSNelsonSiegelModel)
        assert type(make_model("svensson", "treasury")) is SvenssonModel
        assert type(make_model()) is NelsonSiegelModel
        assert [m["id"] for m in list_models()] == ["nelson-siegel", "svensson"]
        with pytest.raises(ValueError, match="Unknown model"):
            get_model_class("spline")

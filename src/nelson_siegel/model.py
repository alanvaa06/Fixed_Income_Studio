"""
Nelson-Siegel family yield curve models.

This module contains the parametric curve models (Nelson-Siegel and the
Svensson extension), the parameter fitting machinery, and yield curve
reconstruction helpers (fitted yields, instantaneous forward rates and
discount factors).

Fitting strategy
----------------
Every model in this family is *linear in its beta parameters* once the decay
parameters (tau) are fixed. The default fitter exploits this: it profiles the
sum of squared errors over the decay parameters (a coarse log-spaced grid
followed by a bounded local refinement) and solves the betas in closed form
by ordinary least squares at each candidate. This is the classical
"profile likelihood" approach and is markedly more robust than a joint
4- or 6-parameter non-linear least squares started from an arbitrary
initial guess, which frequently stalls in local optima or at the tau bound.

The legacy ``scipy.optimize.curve_fit`` path is retained behind
``method="curve_fit"`` for backward compatibility and reproducibility.
"""

from __future__ import annotations

import itertools
import warnings
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple, Type, Union

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit, minimize, minimize_scalar

try:  # Python >= 3.8
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol, runtime_checkable  # type: ignore

ArrayLike = Union[Sequence[float], np.ndarray]


class FactorMeta(NamedTuple):
    """Presentation metadata for one fitted parameter."""

    key: str  #: parameter name as in ``parameters``
    label: str  #: human label used by ``get_factors``
    symbol: str  #: short mathematical symbol for UIs
    unit: str  #: ``"rate"`` (same units as the yields) or ``"years"``
    hint: str  #: one-line interpretation


@runtime_checkable
class CurveModel(Protocol):
    """Contract every curve model in this package satisfies.

    ``NelsonSiegelModel`` and ``SvenssonModel`` implement it; a spline,
    bootstrap or dynamic model should implement the same surface so the
    analyzer and the web app can treat all models uniformly. Yields are
    decimals (0.04 == 4%), maturities are in years.
    """

    model_id: str
    display_name: str
    fitted: bool

    def fit(self, maturities: ArrayLike, yields: ArrayLike) -> "CurveModel": ...

    def predict(self, maturities: ArrayLike) -> np.ndarray: ...

    def forward_rate(self, maturities: ArrayLike) -> np.ndarray: ...

    def discount_factor(self, maturities: ArrayLike) -> np.ndarray: ...

    def get_factors(self) -> Dict[str, float]: ...

    def fit_stats(self) -> Dict[str, Union[float, int, str, bool]]: ...

    @classmethod
    def factor_meta(cls) -> Tuple[FactorMeta, ...]: ...

    @classmethod
    def describe(cls) -> Dict[str, object]: ...

# Practical decay range used for the profile grid when the model bounds are
# unbounded. Outside this range the NS loadings are numerically degenerate
# (tau -> 0 collapses f1/f2 to a step; tau -> inf collapses them to 1 and 0).
_DECAY_GRID_LO = 0.05
_DECAY_GRID_HI = 30.0


def _ols(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """Least-squares solve returning (betas, sum of squared errors)."""
    betas, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ betas
    return betas, float(resid @ resid)


class NelsonSiegelModel:
    """
    Nelson-Siegel yield curve model implementation.

    The Nelson-Siegel model represents the yield curve using four parameters:
    - beta0 (Level): Long-term yield level
    - beta1 (Slope): Short-term yield component
    - beta2 (Curvature): Medium-term yield component
    - tau (Decay): Time-to-maturity scaling parameter

    The model equation is:
    y(t) = beta0 + beta1 * ((1 - exp(-t/tau)) / (t/tau)) + beta2 * (((1 - exp(-t/tau)) / (t/tau)) - exp(-t/tau))

    Subclasses (e.g. :class:`SvenssonModel`) only need to override the class
    attributes below plus :meth:`basis`, :meth:`_forward_basis` and
    :meth:`model_function`; all fitting, prediction and diagnostics are
    inherited.
    """

    #: Identifier used by the model registry and the REST API.
    model_id: str = "nelson-siegel"
    display_name: str = "Nelson-Siegel"
    #: Ordered parameter names. Linear (beta) parameters first, decays last.
    param_names: Tuple[str, ...] = ("beta0", "beta1", "beta2", "tau")
    #: Number of leading parameters that enter linearly.
    n_linear: int = 3
    #: Human-readable factor labels used by :meth:`get_factors`.
    factor_labels: Dict[str, str] = {
        "beta0": "Level",
        "beta1": "Slope",
        "beta2": "Curvature",
        "tau": "Tau",
    }
    _factor_meta: Tuple[FactorMeta, ...] = (
        FactorMeta("beta0", "Level", "\u03b2\u2080", "rate", "Long-run yield; shifts the whole curve"),
        FactorMeta("beta1", "Slope", "\u03b2\u2081", "rate", "Short minus long; negative when upward-sloping"),
        FactorMeta("beta2", "Curvature", "\u03b2\u2082", "rate", "Mid-curve hump; positive = belly above ends"),
        FactorMeta("tau", "Tau", "\u03c4", "years", "Decay; curvature peaks near 1.8\u00d7\u03c4"),
    )
    #: Number of grid points per decay parameter in the profile search.
    decay_grid_size: int = 80
    #: The curvature loading f2 peaks at t ~= 1.8 * tau. By default the decay
    #: search is restricted so that peak lies inside the observed maturity
    #: range; outside it the loadings become near-collinear and the fit
    #: produces huge offsetting betas. Set to ``None`` to disable.
    hump_location_factor: Optional[float] = 1.8

    def __init__(
        self,
        bounds: Optional[Tuple[Sequence[float], Sequence[float]]] = None,
        initial_guess: Optional[Sequence[float]] = None,
    ):
        """
        Initialize the Nelson-Siegel model.

        Parameters:
        -----------
        bounds : tuple of sequences, optional
            Lower and upper bounds for optimization: ((lower_bounds), (upper_bounds)),
            ordered as ``param_names``. The decay bounds delimit the profile
            search; the beta bounds are enforced via a bounded fallback fit.
        initial_guess : sequence of float, optional
            Initial parameter guess for the legacy ``curve_fit`` path.
        """
        self.bounds = bounds if bounds is not None else self._default_bounds()
        self.initial_guess = (
            tuple(initial_guess) if initial_guess is not None else self._default_initial_guess()
        )
        self.parameters: Optional[Dict[str, float]] = None
        self.fitted = False
        self.fit_info: Dict[str, Union[float, int, str, bool]] = {}
        self._fit_data: Optional[Tuple[np.ndarray, np.ndarray]] = None

    # ------------------------------------------------------------------ #
    # Class configuration
    # ------------------------------------------------------------------ #
    @classmethod
    def _default_bounds(cls) -> Tuple[List[float], List[float]]:
        n_decay = len(cls.param_names) - cls.n_linear
        lower = [-np.inf] * cls.n_linear + [0.0] * n_decay
        upper = [np.inf] * len(cls.param_names)
        return lower, upper

    @classmethod
    def _default_initial_guess(cls) -> Tuple[float, ...]:
        return (3.0, 0.0, 0.0, 1.0)

    @classmethod
    def factor_meta(cls) -> Tuple[FactorMeta, ...]:
        """Presentation metadata for each parameter, in ``param_names`` order."""
        return cls._factor_meta

    @classmethod
    def describe(cls) -> Dict[str, object]:
        """JSON-friendly description of the model for UIs and the REST API."""
        return {
            "id": cls.model_id,
            "name": cls.display_name,
            "n_params": len(cls.param_names),
            "min_points": len(cls.param_names),
            "factors": [meta._asdict() for meta in cls.factor_meta()],
        }

    @property
    def n_params(self) -> int:
        return len(self.param_names)

    @property
    def n_decay(self) -> int:
        return self.n_params - self.n_linear

    # ------------------------------------------------------------------ #
    # Model definition
    # ------------------------------------------------------------------ #
    @staticmethod
    def _loadings(t: np.ndarray, tau: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (exp(-t/tau), f1, f2) with the correct limits at t = 0."""
        if tau <= 0:
            raise ValueError("tau must be strictly positive")
        with np.errstate(divide="ignore", invalid="ignore"):
            scaled = t / tau
            exp_term = np.exp(-scaled)
            f1 = np.where(t == 0, 1.0, (1.0 - exp_term) / np.where(scaled == 0, 1.0, scaled))
            f2 = np.where(t == 0, 0.0, f1 - exp_term)
        return exp_term, f1, f2

    @classmethod
    def basis(cls, maturities: ArrayLike, tau: float) -> np.ndarray:
        """Return the Nelson-Siegel design matrix at given maturities and tau.

        Columns: [1, f1(t), f2(t)] where
            f1(t) = (1 - exp(-t/tau)) / (t/tau)   (limit 1 at t=0)
            f2(t) = f1(t) - exp(-t/tau)           (limit 0 at t=0)
        """
        t = np.asarray(maturities, dtype=float)
        _, f1, f2 = cls._loadings(t, tau)
        return np.column_stack([np.ones_like(t), f1, f2])

    @classmethod
    def _forward_basis(cls, maturities: ArrayLike, tau: float) -> np.ndarray:
        """Design matrix of the instantaneous forward curve f(t) = d[t*y(t)]/dt.

        Columns: [1, exp(-t/tau), (t/tau) * exp(-t/tau)].
        """
        t = np.asarray(maturities, dtype=float)
        exp_term, _, _ = cls._loadings(t, tau)
        return np.column_stack([np.ones_like(t), exp_term, (t / tau) * exp_term])

    @staticmethod
    def model_function(
        t: np.ndarray, beta0: float, beta1: float, beta2: float, tau: float
    ) -> np.ndarray:
        """
        Nelson-Siegel model function.

        Parameters:
        -----------
        t : array-like
            Maturities (in years)
        beta0 : float
            Level parameter (long-term yield)
        beta1 : float
            Slope parameter (short-term component)
        beta2 : float
            Curvature parameter (medium-term component)
        tau : float
            Decay parameter (time-to-maturity scaling)

        Returns:
        --------
        np.ndarray
            Predicted yields for given maturities
        """
        t = np.asarray(t, dtype=float)
        _, f1, f2 = NelsonSiegelModel._loadings(t, tau)
        return beta0 + beta1 * f1 + beta2 * f2

    # ------------------------------------------------------------------ #
    # Fitting
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean(maturities: ArrayLike, yields: ArrayLike) -> Tuple[np.ndarray, np.ndarray]:
        maturities = np.asarray(maturities, dtype=float)
        yields = np.asarray(yields, dtype=float)
        if len(maturities) != len(yields):
            raise ValueError("Maturities and yields must have the same length")
        mask = ~(np.isnan(maturities) | np.isnan(yields))
        return maturities[mask], yields[mask]

    def _decay_bounds(self) -> List[Tuple[float, float]]:
        lower, upper = self.bounds
        return [
            (float(lower[i]), float(upper[i])) for i in range(self.n_linear, self.n_params)
        ]

    def _effective_decay_bounds(
        self, maturities: Optional[np.ndarray] = None
    ) -> List[Tuple[float, float]]:
        """Decay search bounds: model bounds, capped to a practical range and,
        when maturities are given, to the identifiable hump-location range."""
        data_lo, data_hi = -np.inf, np.inf
        if maturities is not None and self.hump_location_factor:
            positive = maturities[maturities > 0]
            if positive.size:
                data_lo = float(positive.min()) / self.hump_location_factor
                data_hi = float(positive.max()) / self.hump_location_factor
        out = []
        for lo, hi in self._decay_bounds():
            lo_eff = max(lo, _DECAY_GRID_LO) if np.isfinite(lo) else _DECAY_GRID_LO
            hi_eff = min(hi, _DECAY_GRID_HI) if np.isfinite(hi) else _DECAY_GRID_HI
            lo_c, hi_c = max(lo_eff, data_lo), min(hi_eff, data_hi)
            if hi_c > lo_c:  # otherwise the user's bounds win untouched
                lo_eff, hi_eff = lo_c, hi_c
            if hi_eff <= lo_eff:
                hi_eff = lo_eff * 1.0001
            out.append((lo_eff, hi_eff))
        return out

    def _decay_grids(self, maturities: Optional[np.ndarray] = None) -> List[np.ndarray]:
        return [
            np.geomspace(lo, hi, self.decay_grid_size)
            for lo, hi in self._effective_decay_bounds(maturities)
        ]

    @classmethod
    def _decays_admissible(cls, decays: Sequence[float]) -> bool:
        """Hook for subclasses to exclude degenerate decay combinations."""
        return all(d > 0 for d in decays)

    def _profile_sse(
        self, maturities: np.ndarray, yields: np.ndarray, decays: Sequence[float]
    ) -> Tuple[float, np.ndarray]:
        X = self.basis(maturities, *decays)
        betas, sse = _ols(X, yields)
        return sse, betas

    def _fit_profile(
        self, maturities: np.ndarray, yields: np.ndarray
    ) -> Tuple[np.ndarray, Tuple[float, ...], float]:
        """Grid search over decays with closed-form betas, then local refinement.

        The profile SSE can have several shallow local minima when a curve is
        nearly flat (curvature weakly identified), so the best few grid
        candidates are each refined and the lowest SSE wins.
        """
        grids = self._decay_grids(maturities)
        shape = tuple(len(g) for g in grids)
        losses = np.full(shape, np.inf)
        for idx in itertools.product(*(range(n) for n in shape)):
            decays = tuple(float(g[i]) for g, i in zip(grids, idx))
            if not self._decays_admissible(decays):
                continue
            losses[idx] = self._profile_sse(maturities, yields, decays)[0]
        if not np.isfinite(losses).any():
            raise ValueError("No admissible decay parameters found in the search grid")

        candidates = self._candidate_indices(losses)
        best: Optional[Tuple[float, Tuple[float, ...], np.ndarray]] = None
        for idx in candidates:
            decays = self._refine_decays(maturities, yields, grids, idx)
            sse, betas = self._profile_sse(maturities, yields, decays)
            grid_decays = tuple(float(g[i]) for g, i in zip(grids, idx))
            if sse > losses[idx]:  # refinement must never be worse than its start
                decays = grid_decays
                sse, betas = self._profile_sse(maturities, yields, decays)
            if best is None or sse < best[0]:
                best = (sse, decays, betas)
        assert best is not None
        return best[2], best[1], best[0]

    @staticmethod
    def _candidate_indices(losses: np.ndarray, max_candidates: int = 3) -> List[Tuple[int, ...]]:
        """Indices of the lowest-loss grid points, preferring local minima (1-D)."""
        if losses.ndim == 1:
            left = np.r_[np.inf, losses[:-1]]
            right = np.r_[losses[1:], np.inf]
            is_min = np.isfinite(losses) & (losses <= left) & (losses <= right)
            local = np.where(is_min)[0]
            if len(local) == 0:
                local = np.array([int(np.argmin(losses))])
            order = local[np.argsort(losses[local])]
            return [(int(i),) for i in order[:max_candidates]]
        flat = np.argsort(losses, axis=None)
        picked: List[Tuple[int, ...]] = []
        for f in flat:
            if not np.isfinite(losses.flat[f]):
                break
            idx = tuple(int(v) for v in np.unravel_index(int(f), losses.shape))
            # Skip near-duplicates of an already selected candidate.
            if any(max(abs(a - b) for a, b in zip(idx, p)) <= 1 for p in picked):
                continue
            picked.append(idx)
            if len(picked) == max_candidates:
                break
        return picked

    def _refine_decays(
        self,
        maturities: np.ndarray,
        yields: np.ndarray,
        grids: List[np.ndarray],
        best_idx: Tuple[int, ...],
    ) -> Tuple[float, ...]:
        """Local refinement of the decays starting from one grid point."""
        if len(grids) == 1:
            g, i = grids[0], best_idx[0]
            lo = float(g[max(i - 1, 0)])
            hi = float(g[min(i + 1, len(g) - 1)])
            if hi <= lo:
                return (lo,)
            res = minimize_scalar(
                lambda t: self._profile_sse(maturities, yields, (t,))[0],
                bounds=(lo, hi),
                method="bounded",
                options={"xatol": 1e-6},
            )
            return (float(res.x),)

        # Multi-decay: Nelder-Mead in log space from the grid point, projected
        # onto the full decay bounds (the grid is too coarse to trust one cell).
        log_lo = np.log([float(g[0]) for g in grids])
        log_hi = np.log([float(g[-1]) for g in grids])
        x0 = np.log([g[i] for g, i in zip(grids, best_idx)])

        def objective(x: np.ndarray) -> float:
            decays = tuple(np.exp(np.clip(x, log_lo, log_hi)))
            if not self._decays_admissible(decays):
                return np.inf
            return self._profile_sse(maturities, yields, decays)[0]

        res = minimize(
            objective,
            x0,
            method="Nelder-Mead",
            options={"xatol": 1e-5, "fatol": 0, "maxiter": 600},
        )
        return tuple(float(v) for v in np.exp(np.clip(res.x, log_lo, log_hi)))

    def _betas_within_bounds(self, betas: np.ndarray) -> bool:
        lower, upper = self.bounds
        lo = np.asarray(lower[: self.n_linear], dtype=float)
        hi = np.asarray(upper[: self.n_linear], dtype=float)
        return bool(np.all(betas >= lo) and np.all(betas <= hi))

    def _fit_curve_fit(
        self, maturities: np.ndarray, yields: np.ndarray, p0: Sequence[float]
    ) -> np.ndarray:
        lower, upper = self.bounds
        lo = np.asarray(lower, dtype=float)
        hi = np.asarray(upper, dtype=float)
        # curve_fit requires p0 strictly inside the box.
        p0_arr = np.asarray(p0, dtype=float)
        span = np.where(np.isfinite(hi - lo), hi - lo, 1.0)
        p0_arr = np.clip(p0_arr, lo + 1e-9 * span, hi - 1e-9 * span)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            warnings.simplefilter("ignore", RuntimeWarning)
            optimal, _ = curve_fit(
                self.model_function,
                maturities,
                yields,
                p0=p0_arr,
                bounds=(lo, hi),
                maxfev=10000,
            )
        return np.asarray(optimal, dtype=float)

    def _store_fit(
        self,
        maturities: np.ndarray,
        yields: np.ndarray,
        values: Sequence[float],
        method: str,
    ) -> None:
        self.parameters = {name: float(v) for name, v in zip(self.param_names, values)}
        self.fitted = True
        self._fit_data = (maturities, yields)
        resid = yields - self.predict(maturities)
        sse = float(resid @ resid)
        decays = values[self.n_linear :]
        at_bound = False
        for d, (lo_eff, hi_eff) in zip(decays, self._effective_decay_bounds(maturities)):
            if np.isclose(d, lo_eff, rtol=1e-3) or np.isclose(d, hi_eff, rtol=1e-3):
                at_bound = True
        self.fit_info = {
            "method": method,
            "n_obs": int(len(yields)),
            "sse": sse,
            "rmse": float(np.sqrt(sse / len(yields))),
            "decay_at_bound": at_bound,
        }

    def fit(
        self,
        maturities: ArrayLike,
        yields: ArrayLike,
        initial_guess: Optional[Sequence[float]] = None,
        method: str = "profile",
    ) -> "NelsonSiegelModel":
        """
        Fit the model to observed yield data.

        Parameters:
        -----------
        maturities : array-like
            Yield maturities in years
        yields : array-like
            Observed yields (as decimals, e.g., 0.025 for 2.5%)
        initial_guess : sequence of float, optional
            Starting point for the ``curve_fit`` method. Ignored by ``profile``.
        method : {"profile", "curve_fit"}
            ``profile`` (default): grid search over the decay parameter(s) with
            closed-form betas, then a bounded local refinement. Robust and
            deterministic. If the closed-form betas violate the model's beta
            bounds, a bounded ``curve_fit`` warm-started from the profile
            solution is used instead.
            ``curve_fit``: legacy joint non-linear least squares.

        Returns:
        --------
        self : NelsonSiegelModel
            Returns self for method chaining

        Raises:
        -------
        ValueError
            If fitting fails or inputs are invalid
        """
        maturities = np.asarray(maturities, dtype=float)
        yields = np.asarray(yields, dtype=float)
        if len(maturities) != len(yields):
            raise ValueError("Maturities and yields must have the same length")
        if len(maturities) < self.n_params:
            raise ValueError(
                f"Need at least {self.n_params} data points to fit the "
                f"{self.n_params}-parameter model"
            )
        m_clean, y_clean = self._clean(maturities, yields)
        if len(m_clean) < self.n_params:
            raise ValueError("Insufficient valid data points after removing NaNs")

        if method not in {"profile", "curve_fit"}:
            raise ValueError("method must be 'profile' or 'curve_fit'")

        try:
            if method == "profile":
                betas, decays, _ = self._fit_profile(m_clean, y_clean)
                values: Sequence[float] = np.concatenate([betas, decays])
                used = "profile"
                if not self._betas_within_bounds(betas):
                    values = self._fit_curve_fit(m_clean, y_clean, values)
                    used = "profile+curve_fit"
            else:
                p0 = initial_guess if initial_guess is not None else self.initial_guess
                values = self._fit_curve_fit(m_clean, y_clean, p0)
                used = "curve_fit"
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise optimiser failures
            raise ValueError(f"Model fitting failed: {exc}") from exc

        self._store_fit(m_clean, y_clean, values, used)
        return self

    def fit_fixed_decays(
        self, maturities: ArrayLike, yields: ArrayLike, *decays: float
    ) -> "NelsonSiegelModel":
        """Closed-form least-squares fit with all decay parameters held fixed."""
        if len(decays) != self.n_decay:
            raise ValueError(f"Expected {self.n_decay} decay parameter(s), got {len(decays)}")
        m_clean, y_clean = self._clean(maturities, yields)
        if len(m_clean) < self.n_linear:
            raise ValueError(f"Need at least {self.n_linear} valid points for fixed-tau fit")
        sse, betas = self._profile_sse(m_clean, y_clean, decays)
        self._store_fit(m_clean, y_clean, np.concatenate([betas, decays]), "fixed_decays")
        return self

    def fit_fixed_tau(
        self, maturities: ArrayLike, yields: ArrayLike, tau: float
    ) -> "NelsonSiegelModel":
        """Closed-form least-squares fit with tau held fixed (Diebold-Li style)."""
        return self.fit_fixed_decays(maturities, yields, tau)

    # ------------------------------------------------------------------ #
    # Prediction and diagnostics
    # ------------------------------------------------------------------ #
    def _require_fit(self, action: str) -> Dict[str, float]:
        if not self.fitted or self.parameters is None:
            raise ValueError(f"Model must be fitted before {action}")
        return self.parameters

    def _decays(self) -> Tuple[float, ...]:
        params = self._require_fit("accessing decay parameters")
        return tuple(params[name] for name in self.param_names[self.n_linear :])

    def _betas(self) -> np.ndarray:
        params = self._require_fit("accessing beta parameters")
        return np.array([params[name] for name in self.param_names[: self.n_linear]])

    def predict(self, maturities: ArrayLike) -> np.ndarray:
        """
        Predict yields for given maturities using the fitted model.

        Parameters:
        -----------
        maturities : array-like
            Maturities for which to predict yields

        Returns:
        --------
        np.ndarray
            Predicted yields

        Raises:
        -------
        ValueError
            If model has not been fitted yet
        """
        params = self._require_fit("prediction")
        maturities = np.asarray(maturities, dtype=float)
        return self.model_function(maturities, **params)

    def forward_rate(self, maturities: ArrayLike) -> np.ndarray:
        """Instantaneous forward rate f(t) = d[t * y(t)] / dt implied by the fit.

        Yields are treated as continuously compounded zero rates, so the
        forward curve has the closed form
        f(t) = beta0 + beta1 * exp(-t/tau) + beta2 * (t/tau) * exp(-t/tau).
        """
        F = self._forward_basis(np.asarray(maturities, dtype=float), *self._decays())
        return F @ self._betas()

    def discount_factor(self, maturities: ArrayLike) -> np.ndarray:
        """Discount factors P(t) = exp(-t * y(t)) under continuous compounding."""
        t = np.asarray(maturities, dtype=float)
        return np.exp(-t * self.predict(t))

    def get_factors(self) -> Dict[str, float]:
        """
        Get the fitted factors.

        Returns:
        --------
        dict
            Dictionary containing Level, Slope, Curvature, and Tau factors
            (plus Curvature2/Tau2 for the Svensson model)

        Raises:
        -------
        ValueError
            If model has not been fitted yet
        """
        params = self._require_fit("accessing factors")
        return {self.factor_labels[name]: params[name] for name in self.param_names}

    def fit_stats(self) -> Dict[str, Union[float, int, str, bool]]:
        """Goodness-of-fit summary for the last fit.

        Keys: ``method``, ``n_obs``, ``sse``, ``rmse``, ``r_squared``,
        ``decay_at_bound`` (True when the decay landed on the edge of its
        search range, a sign the decay is weakly identified by the data).
        """
        self._require_fit("accessing fit statistics")
        stats = dict(self.fit_info)
        if self._fit_data is not None:
            _, y = self._fit_data
            tss = float(((y - y.mean()) ** 2).sum())
            stats["r_squared"] = 1.0 - float(stats["sse"]) / tss if tss > 0 else float("nan")
        return stats

    def calculate_deviations(
        self, maturities: ArrayLike, observed_yields: ArrayLike
    ) -> np.ndarray:
        """
        Calculate deviations between observed and fitted yields.

        Parameters:
        -----------
        maturities : array-like
            Yield maturities
        observed_yields : array-like
            Observed yield values

        Returns:
        --------
        np.ndarray
            Deviations (observed - fitted)
        """
        fitted_yields = self.predict(maturities)
        return np.asarray(observed_yields, dtype=float) - fitted_yields

    def classify_bonds(self, maturities: ArrayLike, observed_yields: ArrayLike) -> List[str]:
        """
        Classify bonds as cheap or expensive based on model deviations.

        Parameters:
        -----------
        maturities : array-like
            Yield maturities
        observed_yields : array-like
            Observed yield values

        Returns:
        --------
        list
            List of 'cheap' or 'expensive' classifications
        """
        deviations = self.calculate_deviations(maturities, observed_yields)
        return ["cheap" if dev < 0 else "expensive" for dev in deviations]

    def __repr__(self) -> str:
        """String representation of the model."""
        name = type(self).__name__
        if self.fitted:
            parts = ", ".join(f"{label}={value:.4f}" for label, value in self.get_factors().items())
            return f"{name}(fitted=True, {parts})"
        return f"{name}(fitted=False)"


class TreasuryNelsonSiegelModel(NelsonSiegelModel):
    """Nelson-Siegel model pre-configured for US Treasury yields."""

    def __init__(self) -> None:
        super().__init__(
            bounds=([0, -5, -5, 0], [11, 10, 10, 10]),
            initial_guess=(4.0, 0.0, 0.0, 1.0),
        )


class TIPSNelsonSiegelModel(NelsonSiegelModel):
    """Nelson-Siegel model pre-configured for US TIPS real yields."""

    def __init__(self) -> None:
        super().__init__(
            bounds=([-2, -5, -5, 0], [8, 10, 10, 10]),
            initial_guess=(1.0, 0.0, 0.0, 1.0),
        )


class SvenssonModel(NelsonSiegelModel):
    """
    Svensson (1994) extension of Nelson-Siegel with a second curvature term.

    y(t) = beta0 + beta1 * f1(t, tau1) + beta2 * f2(t, tau1) + beta3 * f2(t, tau2)

    The extra hump lets the curve fit a second bulge (common at the very long
    end). The two decays are kept apart during the search (|ln(tau1/tau2)| >=
    0.1) because tau1 == tau2 makes the design matrix singular.
    """

    model_id = "svensson"
    display_name = "Svensson"
    param_names = ("beta0", "beta1", "beta2", "beta3", "tau1", "tau2")
    n_linear = 4
    factor_labels = {
        "beta0": "Level",
        "beta1": "Slope",
        "beta2": "Curvature",
        "beta3": "Curvature2",
        "tau1": "Tau",
        "tau2": "Tau2",
    }
    _factor_meta = (
        FactorMeta("beta0", "Level", "\u03b2\u2080", "rate", "Long-run yield; shifts the whole curve"),
        FactorMeta("beta1", "Slope", "\u03b2\u2081", "rate", "Short minus long; negative when upward-sloping"),
        FactorMeta("beta2", "Curvature", "\u03b2\u2082", "rate", "First hump, peaks near 1.8\u00d7\u03c4\u2081"),
        FactorMeta("beta3", "Curvature2", "\u03b2\u2083", "rate", "Second hump, peaks near 1.8\u00d7\u03c4\u2082"),
        FactorMeta("tau1", "Tau", "\u03c4\u2081", "years", "Decay of the first hump"),
        FactorMeta("tau2", "Tau2", "\u03c4\u2082", "years", "Decay of the second hump"),
    )
    decay_grid_size = 24
    _min_log_decay_gap = 0.1

    @classmethod
    def _default_initial_guess(cls) -> Tuple[float, ...]:
        return (0.03, 0.0, 0.0, 0.0, 1.0, 5.0)

    @classmethod
    def _decays_admissible(cls, decays: Sequence[float]) -> bool:
        tau1, tau2 = decays
        if tau1 <= 0 or tau2 <= 0:
            return False
        return abs(np.log(tau1 / tau2)) >= cls._min_log_decay_gap

    @classmethod
    def basis(cls, maturities: ArrayLike, tau1: float, tau2: float) -> np.ndarray:  # type: ignore[override]
        t = np.asarray(maturities, dtype=float)
        _, f1, f2 = cls._loadings(t, tau1)
        _, _, g2 = cls._loadings(t, tau2)
        return np.column_stack([np.ones_like(t), f1, f2, g2])

    @classmethod
    def _forward_basis(cls, maturities: ArrayLike, tau1: float, tau2: float) -> np.ndarray:  # type: ignore[override]
        t = np.asarray(maturities, dtype=float)
        e1, _, _ = cls._loadings(t, tau1)
        e2, _, _ = cls._loadings(t, tau2)
        return np.column_stack([np.ones_like(t), e1, (t / tau1) * e1, (t / tau2) * e2])

    @staticmethod
    def model_function(  # type: ignore[override]
        t: np.ndarray,
        beta0: float,
        beta1: float,
        beta2: float,
        beta3: float,
        tau1: float,
        tau2: float,
    ) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        _, f1, f2 = NelsonSiegelModel._loadings(t, tau1)
        _, _, g2 = NelsonSiegelModel._loadings(t, tau2)
        return beta0 + beta1 * f1 + beta2 * f2 + beta3 * g2


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
MODEL_REGISTRY: Dict[str, Type[NelsonSiegelModel]] = {
    NelsonSiegelModel.model_id: NelsonSiegelModel,
    SvenssonModel.model_id: SvenssonModel,
}

_BOND_PRESETS: Dict[str, Dict[str, Type[NelsonSiegelModel]]] = {
    NelsonSiegelModel.model_id: {
        "treasury": TreasuryNelsonSiegelModel,
        "tips": TIPSNelsonSiegelModel,
    },
}


def get_model_class(model_id: str) -> Type[NelsonSiegelModel]:
    """Look up a registered model class by id (case-insensitive)."""
    key = (model_id or NelsonSiegelModel.model_id).lower().replace("_", "-")
    try:
        return MODEL_REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"Unknown model '{model_id}'. Available: {', '.join(sorted(MODEL_REGISTRY))}"
        ) from None


def make_model(model_id: str = NelsonSiegelModel.model_id, bond_type: Optional[str] = None) -> NelsonSiegelModel:
    """Instantiate a registered model, applying the bond-type preset when one exists."""
    cls = get_model_class(model_id)
    presets = _BOND_PRESETS.get(cls.model_id, {})
    if bond_type and bond_type.lower() in presets:
        return presets[bond_type.lower()]()
    return cls()


def list_models() -> List[Dict[str, object]]:
    """Descriptions of all registered models (see :meth:`NelsonSiegelModel.describe`)."""
    return [cls.describe() for cls in MODEL_REGISTRY.values()]

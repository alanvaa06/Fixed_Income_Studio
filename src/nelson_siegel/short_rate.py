"""
One-factor short-rate models: Vasicek (1977) and Cox-Ingersoll-Ross (1985).

Both models describe the instantaneous short rate ``r`` with a mean-reverting
diffusion and admit closed-form zero-coupon bond prices ``P(t) = exp(A(t) - B(t) r0)``,
hence closed-form yields and instantaneous forward rates:

- Vasicek: ``dr = kappa (theta - r) dt + sigma dW``
- CIR:     ``dr = kappa (theta - r) dt + sigma sqrt(r) dW``

Two ways to use them:

1. **Cross-section calibration** (:meth:`ShortRateModel.fit`): fit
   ``(r0, kappa, theta, sigma)`` to today's yields. The models implement the
   :class:`~nelson_siegel.model.CurveModel` surface so they slot into the same
   fitter, diagnostics and web UI as Nelson-Siegel. Only the risk-neutral
   dynamics are identified from a single curve; ``sigma`` is pinned down by
   convexity and is weakly identified, so its search range is bounded.
2. **Time-series estimation** (:func:`estimate_short_rate`): estimate the
   physical-measure dynamics from a history of a short-rate proxy (fed funds,
   the 1-month or 3-month bill) by OLS on the exact discretisation or by
   maximum likelihood. The difference between the physical and the
   risk-neutral parameters is what a term premium is made of; see
   :mod:`nelson_siegel.term_premium`.

Rates are decimals (0.04 == 4%), maturities in years, continuous compounding.
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Type, Union

import numpy as np
import pandas as pd
from scipy.optimize import least_squares, minimize
from scipy.stats import ncx2

from .model import ArrayLike, FactorMeta

_EPS = 1e-12


def _as_array(x: ArrayLike) -> np.ndarray:
    return np.atleast_1d(np.asarray(x, dtype=float))


# --------------------------------------------------------------------------- #
# Closed-form bond pricing
# --------------------------------------------------------------------------- #
def vasicek_ab(t: np.ndarray, kappa: float, theta: float, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
    """Vasicek ``A(t)`` and ``B(t)`` with ``P(t) = exp(A - B r0)``."""
    t = _as_array(t)
    if kappa <= 0:
        raise ValueError("kappa must be strictly positive")
    B = (1.0 - np.exp(-kappa * t)) / kappa
    A = (theta - sigma**2 / (2.0 * kappa**2)) * (B - t) - sigma**2 * B**2 / (4.0 * kappa)
    return A, B


def cir_ab(t: np.ndarray, kappa: float, theta: float, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
    """CIR ``A(t)`` (log form) and ``B(t)`` with ``P(t) = exp(A - B r0)``."""
    t = _as_array(t)
    if kappa <= 0 or sigma <= 0:
        raise ValueError("kappa and sigma must be strictly positive")
    gamma = np.sqrt(kappa**2 + 2.0 * sigma**2)
    e = np.exp(gamma * t)
    D = (gamma + kappa) * (e - 1.0) + 2.0 * gamma
    B = 2.0 * (e - 1.0) / D
    A = (2.0 * kappa * theta / sigma**2) * (np.log(2.0 * gamma) + (gamma + kappa) * t / 2.0 - np.log(D))
    return A, B


class ShortRateModel:
    """Common machinery for one-factor affine short-rate models.

    Subclasses provide ``_ab`` (the affine bond-price coefficients) and
    ``_forward`` (closed-form instantaneous forward). Everything else -
    calibration, prediction, diagnostics, simulation - is shared.
    """

    model_id: str = "short-rate"
    display_name: str = "Short rate"
    family: str = "short-rate"
    param_names: Tuple[str, ...] = ("r0", "kappa", "theta", "sigma")
    factor_labels: Dict[str, str] = {
        "r0": "ShortRate",
        "kappa": "MeanReversion",
        "theta": "LongRunMean",
        "sigma": "Volatility",
    }
    _factor_meta: Tuple[FactorMeta, ...] = (
        FactorMeta("r0", "ShortRate", "r₀", "rate", "Instantaneous short rate today"),
        FactorMeta("kappa", "MeanReversion", "κ", "per-year", "Speed of pull toward the long-run mean"),
        FactorMeta("theta", "LongRunMean", "θ", "rate", "Risk-neutral long-run short rate"),
        FactorMeta("sigma", "Volatility", "σ", "rate", "Short-rate volatility (annualised)"),
    )
    #: Search box for calibration: (lower, upper) per parameter.
    calibration_bounds: Dict[str, Tuple[float, float]] = {
        "r0": (-0.05, 0.30),
        "kappa": (0.01, 3.0),
        "theta": (-0.05, 0.30),
        "sigma": (0.001, 0.05),
    }
    #: Grid of mean-reversion starts for the multi-start calibration.
    kappa_starts: Tuple[float, ...] = (0.05, 0.15, 0.4, 1.0)
    #: Whether the model needs a non-negative short rate.
    requires_positive_rates: bool = False

    def __init__(self, params: Optional[Dict[str, float]] = None):
        self.parameters: Optional[Dict[str, float]] = None
        self.fitted = False
        self.fit_info: Dict[str, Union[float, int, str, bool]] = {}
        self._fit_data: Optional[Tuple[np.ndarray, np.ndarray]] = None
        if params is not None:
            self.set_params(**params)

    # -- protocol metadata ------------------------------------------------ #
    @classmethod
    def factor_meta(cls) -> Tuple[FactorMeta, ...]:
        return cls._factor_meta

    @classmethod
    def describe(cls) -> Dict[str, object]:
        return {
            "id": cls.model_id,
            "name": cls.display_name,
            "family": cls.family,
            "n_params": len(cls.param_names),
            "min_points": 4,
            "supports_history": False,
            "factors": [meta._asdict() for meta in cls.factor_meta()],
        }

    @property
    def n_params(self) -> int:
        return len(self.param_names)

    def set_params(self, r0: float, kappa: float, theta: float, sigma: float) -> "ShortRateModel":
        """Use given parameters without fitting (marks the model as usable)."""
        self._validate(kappa, theta, sigma)
        self.parameters = {"r0": float(r0), "kappa": float(kappa), "theta": float(theta), "sigma": float(sigma)}
        self.fitted = True
        self.fit_info = {"method": "manual", "n_obs": 0, "sse": float("nan"), "rmse": float("nan")}
        self._fit_data = None
        return self

    @classmethod
    def _validate(cls, kappa: float, theta: float, sigma: float) -> None:
        if kappa <= 0:
            raise ValueError("kappa must be strictly positive")
        if sigma <= 0:
            raise ValueError("sigma must be strictly positive")
        if cls.requires_positive_rates and theta <= 0:
            raise ValueError(f"{cls.display_name} needs a positive long-run mean theta")

    # -- model definition (subclass hooks) -------------------------------- #
    @staticmethod
    def _ab(t: np.ndarray, kappa: float, theta: float, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    @staticmethod
    def _forward(t: np.ndarray, r0: float, kappa: float, theta: float, sigma: float) -> np.ndarray:
        raise NotImplementedError

    @classmethod
    def zero_yield(cls, t: ArrayLike, r0: float, kappa: float, theta: float, sigma: float) -> np.ndarray:
        """Continuously compounded zero yield ``y(t) = (B r0 - A) / t`` (``r0`` at ``t=0``)."""
        t = _as_array(t)
        A, B = cls._ab(t, kappa, theta, sigma)
        with np.errstate(divide="ignore", invalid="ignore"):
            y = np.where(t > 0, (B * r0 - A) / np.where(t > 0, t, 1.0), r0)
        return y

    @classmethod
    def model_function(cls, t: np.ndarray, r0: float, kappa: float, theta: float, sigma: float) -> np.ndarray:
        """Alias of :meth:`zero_yield` mirroring the Nelson-Siegel API."""
        return cls.zero_yield(t, r0, kappa, theta, sigma)

    @staticmethod
    def expected_short_rate(t: ArrayLike, r0: float, kappa: float, theta: float) -> np.ndarray:
        """``E[r_t] = theta + (r0 - theta) exp(-kappa t)`` (same for Vasicek and CIR)."""
        t = _as_array(t)
        return theta + (r0 - theta) * np.exp(-kappa * t)

    @staticmethod
    def average_expected_short_rate(t: ArrayLike, r0: float, kappa: float, theta: float) -> np.ndarray:
        """``(1/t) int_0^t E[r_s] ds``: the expectations-hypothesis yield."""
        t = _as_array(t)
        with np.errstate(divide="ignore", invalid="ignore"):
            weight = np.where(t > 0, (1.0 - np.exp(-kappa * t)) / (kappa * np.where(t > 0, t, 1.0)), 1.0)
        return theta + (r0 - theta) * weight

    # -- calibration ------------------------------------------------------ #
    @staticmethod
    def _clean(maturities: ArrayLike, yields: ArrayLike) -> Tuple[np.ndarray, np.ndarray]:
        m = np.asarray(maturities, dtype=float)
        y = np.asarray(yields, dtype=float)
        if len(m) != len(y):
            raise ValueError("Maturities and yields must have the same length")
        mask = ~(np.isnan(m) | np.isnan(y)) & (m > 0)
        return m[mask], y[mask]

    def _bounds_arrays(self) -> Tuple[np.ndarray, np.ndarray]:
        lo = np.array([self.calibration_bounds[p][0] for p in self.param_names])
        hi = np.array([self.calibration_bounds[p][1] for p in self.param_names])
        return lo, hi

    def fit(self, maturities: ArrayLike, yields: ArrayLike, sigma: Optional[float] = None) -> "ShortRateModel":
        """Calibrate ``(r0, kappa, theta, sigma)`` to a yield cross-section.

        Bounded non-linear least squares from several mean-reversion starts;
        the lowest sum of squared errors wins, so the result is deterministic.
        Pass ``sigma`` to hold the volatility fixed (recommended when it was
        estimated from a time series; a single curve barely identifies it).
        """
        m, y = self._clean(maturities, yields)
        n_free = self.n_params - (1 if sigma is not None else 0)
        if len(m) < n_free:
            raise ValueError(f"Need at least {n_free} valid points to calibrate the {self.display_name} model")
        if self.requires_positive_rates and np.any(y <= 0):
            raise ValueError(f"{self.display_name} requires strictly positive yields")

        lo, hi = self._bounds_arrays()
        if sigma is not None:
            if sigma <= 0:
                raise ValueError("sigma must be strictly positive")
            lo[3] = hi[3] = sigma
        short_guess = float(y[np.argmin(m)])
        long_guess = float(y[np.argmax(m)])

        def residuals(p: np.ndarray) -> np.ndarray:
            try:
                return self.zero_yield(m, *p) - y
            except (ValueError, FloatingPointError):
                return np.full_like(y, 1e3)

        best: Optional[Tuple[float, np.ndarray]] = None
        for k0 in self.kappa_starts:
            x0 = np.array([short_guess, k0, long_guess, sigma if sigma is not None else 0.01])
            x0 = np.clip(x0, lo + 1e-9, hi - 1e-9)
            if sigma is not None:
                x0[3] = sigma
            free = np.array([True, True, True, sigma is None])

            def res_free(q: np.ndarray, base: np.ndarray = x0) -> np.ndarray:
                p = base.copy()
                p[free] = q
                return residuals(p)

            try:
                with np.errstate(all="ignore"), warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sol = least_squares(
                        res_free, x0[free], bounds=(lo[free], hi[free]), method="trf",
                        xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=4000,
                    )
            except Exception:  # noqa: BLE001 - try the next start
                continue
            p = x0.copy()
            p[free] = sol.x
            sse = float(np.sum(residuals(p) ** 2))
            if np.isfinite(sse) and (best is None or sse < best[0]):
                best = (sse, p)
        if best is None:
            raise ValueError(f"{self.display_name} calibration failed")

        sse, p = best
        self.parameters = dict(zip(self.param_names, (float(v) for v in p)))
        self.fitted = True
        self._fit_data = (m, y)
        at_bound = any(
            np.isclose(p[i], lo[i], rtol=1e-3, atol=1e-6) or np.isclose(p[i], hi[i], rtol=1e-3, atol=1e-6)
            for i in range(self.n_params)
            if not (sigma is not None and i == 3)
        )
        self.fit_info = {
            "method": "least_squares" + ("+fixed_sigma" if sigma is not None else ""),
            "n_obs": int(len(y)),
            "sse": sse,
            "rmse": float(np.sqrt(sse / len(y))),
            "decay_at_bound": bool(at_bound),
        }
        return self

    # -- prediction and diagnostics --------------------------------------- #
    def _require_fit(self, action: str) -> Dict[str, float]:
        if not self.fitted or self.parameters is None:
            raise ValueError(f"Model must be fitted before {action}")
        return self.parameters

    def predict(self, maturities: ArrayLike) -> np.ndarray:
        p = self._require_fit("prediction")
        return self.zero_yield(_as_array(maturities), p["r0"], p["kappa"], p["theta"], p["sigma"])

    def forward_rate(self, maturities: ArrayLike) -> np.ndarray:
        """Instantaneous forward ``f(t) = -d ln P(t)/dt`` in closed form."""
        p = self._require_fit("forward rates")
        return self._forward(_as_array(maturities), p["r0"], p["kappa"], p["theta"], p["sigma"])

    def discount_factor(self, maturities: ArrayLike) -> np.ndarray:
        p = self._require_fit("discount factors")
        t = _as_array(maturities)
        A, B = self._ab(t, p["kappa"], p["theta"], p["sigma"])
        return np.exp(A - B * p["r0"])

    def expected_path(self, horizons: ArrayLike) -> np.ndarray:
        """Expected short rate ``E[r_t]`` under the fitted parameters."""
        p = self._require_fit("the expected path")
        return self.expected_short_rate(horizons, p["r0"], p["kappa"], p["theta"])

    def expectations_yield(self, maturities: ArrayLike) -> np.ndarray:
        """Average expected short rate to each maturity (no convexity, no risk premium)."""
        p = self._require_fit("the expectations yield")
        return self.average_expected_short_rate(maturities, p["r0"], p["kappa"], p["theta"])

    def get_factors(self) -> Dict[str, float]:
        p = self._require_fit("accessing factors")
        return {self.factor_labels[name]: p[name] for name in self.param_names}

    def fit_stats(self) -> Dict[str, Union[float, int, str, bool]]:
        self._require_fit("accessing fit statistics")
        stats = dict(self.fit_info)
        if self._fit_data is not None:
            _, y = self._fit_data
            tss = float(((y - y.mean()) ** 2).sum())
            stats["r_squared"] = 1.0 - float(stats["sse"]) / tss if tss > 0 else float("nan")
        return stats

    def half_life(self) -> float:
        """Half-life of a short-rate deviation from ``theta`` in years."""
        p = self._require_fit("the half-life")
        return float(np.log(2.0) / p["kappa"])

    def calculate_deviations(self, maturities: ArrayLike, observed_yields: ArrayLike) -> np.ndarray:
        return np.asarray(observed_yields, dtype=float) - self.predict(maturities)

    def classify_bonds(self, maturities: ArrayLike, observed_yields: ArrayLike) -> List[str]:
        return ["cheap" if d < 0 else "expensive" for d in self.calculate_deviations(maturities, observed_yields)]

    # -- simulation ------------------------------------------------------- #
    def simulate(
        self,
        horizon_years: float = 5.0,
        n_paths: int = 200,
        steps_per_year: int = 52,
        seed: Optional[int] = 0,
        r0: Optional[float] = None,
    ) -> pd.DataFrame:
        """Monte Carlo paths of the short rate (rows: time in years, columns: paths).

        Vasicek uses the exact Gaussian transition; CIR uses a full-truncation
        Euler scheme (rates floored at zero inside the diffusion term).
        """
        p = self._require_fit("simulation")
        n_steps = max(1, int(round(horizon_years * steps_per_year)))
        dt = horizon_years / n_steps
        rng = np.random.default_rng(seed)
        start = p["r0"] if r0 is None else float(r0)
        paths = np.empty((n_steps + 1, n_paths))
        paths[0] = start
        kappa, theta, sigma = p["kappa"], p["theta"], p["sigma"]
        for i in range(1, n_steps + 1):
            paths[i] = self._step(paths[i - 1], kappa, theta, sigma, dt, rng)
        index = pd.Index(np.arange(n_steps + 1) * dt, name="years")
        return pd.DataFrame(paths, index=index, columns=[f"path_{k}" for k in range(n_paths)])

    @staticmethod
    def _step(r: np.ndarray, kappa: float, theta: float, sigma: float, dt: float, rng: np.random.Generator) -> np.ndarray:
        raise NotImplementedError

    def __repr__(self) -> str:
        if self.fitted and self.parameters:
            parts = ", ".join(f"{k}={v:.4f}" for k, v in self.parameters.items())
            return f"{type(self).__name__}(fitted=True, {parts})"
        return f"{type(self).__name__}(fitted=False)"


class VasicekModel(ShortRateModel):
    """Vasicek (1977): Gaussian, mean-reverting short rate; rates may go negative."""

    model_id = "vasicek"
    display_name = "Vasicek"

    @staticmethod
    def _ab(t: np.ndarray, kappa: float, theta: float, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
        return vasicek_ab(t, kappa, theta, sigma)

    @staticmethod
    def _forward(t: np.ndarray, r0: float, kappa: float, theta: float, sigma: float) -> np.ndarray:
        t = _as_array(t)
        B = (1.0 - np.exp(-kappa * t)) / kappa
        dB = np.exp(-kappa * t)
        dA = (theta - sigma**2 / (2.0 * kappa**2)) * (dB - 1.0) - sigma**2 * B * dB / (2.0 * kappa)
        return dB * r0 - dA

    @staticmethod
    def _step(r: np.ndarray, kappa: float, theta: float, sigma: float, dt: float, rng: np.random.Generator) -> np.ndarray:
        decay = np.exp(-kappa * dt)
        mean = theta + (r - theta) * decay
        var = sigma**2 * (1.0 - decay**2) / (2.0 * kappa)
        return mean + np.sqrt(var) * rng.standard_normal(len(r))


class CIRModel(ShortRateModel):
    """Cox-Ingersoll-Ross (1985): square-root diffusion; rates stay non-negative."""

    model_id = "cir"
    display_name = "CIR"
    requires_positive_rates = True
    calibration_bounds = {
        "r0": (1e-4, 0.30),
        "kappa": (0.01, 3.0),
        "theta": (1e-4, 0.30),
        "sigma": (0.005, 0.30),
    }

    @staticmethod
    def _ab(t: np.ndarray, kappa: float, theta: float, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
        return cir_ab(t, kappa, theta, sigma)

    @staticmethod
    def _forward(t: np.ndarray, r0: float, kappa: float, theta: float, sigma: float) -> np.ndarray:
        t = _as_array(t)
        gamma = np.sqrt(kappa**2 + 2.0 * sigma**2)
        e = np.exp(gamma * t)
        D = (gamma + kappa) * (e - 1.0) + 2.0 * gamma
        B = 2.0 * (e - 1.0) / D
        dB = 4.0 * gamma**2 * e / D**2
        return dB * r0 + kappa * theta * B

    @staticmethod
    def _step(r: np.ndarray, kappa: float, theta: float, sigma: float, dt: float, rng: np.random.Generator) -> np.ndarray:
        pos = np.maximum(r, 0.0)
        return r + kappa * (theta - pos) * dt + sigma * np.sqrt(pos * dt) * rng.standard_normal(len(r))

    def feller_condition(self) -> bool:
        """``2 kappa theta >= sigma^2``: the origin is unattainable."""
        p = self._require_fit("the Feller condition")
        return bool(2.0 * p["kappa"] * p["theta"] >= p["sigma"] ** 2)


# --------------------------------------------------------------------------- #
# Time-series estimation (physical measure)
# --------------------------------------------------------------------------- #
@dataclass
class ShortRateEstimate:
    """Result of :func:`estimate_short_rate`."""

    model: str
    method: str
    kappa: float
    theta: float
    sigma: float
    r0: float
    dt: float
    n_obs: int
    stationary: bool
    half_life_years: Optional[float]
    log_likelihood: float
    aic: float
    feller: Optional[bool] = None
    #: Discrete-time AR(1) fit underlying the OLS estimate.
    ar_coefficient: Optional[float] = None
    ar_intercept: Optional[float] = None
    resid_std: Optional[float] = None

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)

    def as_model(self) -> ShortRateModel:
        """Instantiate the matching curve model at the estimated parameters."""
        cls = SHORT_RATE_REGISTRY[self.model]
        return cls().set_params(self.r0, self.kappa, self.theta, self.sigma)


def _infer_dt(series: pd.Series, dt: Optional[float]) -> float:
    if dt is not None:
        return float(dt)
    idx = series.index
    if isinstance(idx, pd.DatetimeIndex) and len(idx) > 1:
        days = np.median(np.diff(idx.values).astype("timedelta64[D]").astype(float))
        return float(days) / 365.25
    raise ValueError("Pass dt= (years between observations) for a non-datetime index")


def _vasicek_loglik(params: np.ndarray, r: np.ndarray, dt: float) -> float:
    kappa, theta, sigma = params
    if kappa <= 0 or sigma <= 0:
        return -np.inf
    decay = np.exp(-kappa * dt)
    mean = theta + (r[:-1] - theta) * decay
    var = sigma**2 * (1.0 - decay**2) / (2.0 * kappa)
    resid = r[1:] - mean
    return float(-0.5 * np.sum(np.log(2.0 * np.pi * var) + resid**2 / var))


def _cir_loglik(params: np.ndarray, r: np.ndarray, dt: float) -> float:
    kappa, theta, sigma = params
    if kappa <= 0 or theta <= 0 or sigma <= 0:
        return -np.inf
    c = 2.0 * kappa / (sigma**2 * (1.0 - np.exp(-kappa * dt)))
    df = 4.0 * kappa * theta / sigma**2
    nc = 2.0 * c * r[:-1] * np.exp(-kappa * dt)
    with np.errstate(all="ignore"):
        ll = ncx2.logpdf(2.0 * c * r[1:], df, nc) + np.log(2.0 * c)
    ll = ll[np.isfinite(ll)]
    if ll.size < max(3, len(r) // 2):
        return -np.inf
    return float(ll.sum())


def _ols_vasicek(r: np.ndarray, dt: float) -> Tuple[float, float, float, float, float, float]:
    X = np.column_stack([np.ones(len(r) - 1), r[:-1]])
    coef, *_ = np.linalg.lstsq(X, r[1:], rcond=None)
    a, b = float(coef[0]), float(coef[1])
    resid = r[1:] - X @ coef
    s = float(np.std(resid, ddof=2)) if len(resid) > 2 else float(np.std(resid))
    if 0.0 < b < 1.0:
        kappa = -np.log(b) / dt
        theta = a / (1.0 - b)
        sigma = s * np.sqrt(-2.0 * np.log(b) / (dt * (1.0 - b**2)))
    else:  # unit root or explosive: report the weakest admissible reversion
        kappa = 1e-3
        theta = float(np.mean(r))
        sigma = s / np.sqrt(dt)
    return kappa, theta, sigma, a, b, s


def _ols_cir(r: np.ndarray, dt: float) -> Tuple[float, float, float, float]:
    if np.any(r <= 0):
        raise ValueError("CIR estimation needs strictly positive rates")
    sqrt_r = np.sqrt(r[:-1])
    y = (r[1:] - r[:-1]) / sqrt_r
    X = np.column_stack([dt / sqrt_r, dt * sqrt_r])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    b1, b2 = float(coef[0]), float(coef[1])
    resid = y - X @ coef
    s = float(np.std(resid, ddof=2)) if len(resid) > 2 else float(np.std(resid))
    kappa = -b2 if b2 < 0 else 1e-3
    theta = b1 / kappa if kappa > 0 and b1 > 0 else float(np.mean(r))
    sigma = s / np.sqrt(dt)
    return kappa, max(theta, 1e-6), max(sigma, 1e-6), s


def estimate_short_rate(
    rates: Union[pd.Series, Sequence[float]],
    model: str = "vasicek",
    method: str = "ols",
    dt: Optional[float] = None,
) -> ShortRateEstimate:
    """Estimate physical-measure dynamics from a short-rate history.

    Parameters
    ----------
    rates : Series or sequence
        Short-rate proxy as decimals (fed funds, 1M/3M bill), regularly spaced.
    model : {"vasicek", "cir"}
    method : {"ols", "mle"}
        ``ols`` regresses the exact discretisation (Vasicek: ``r_t`` on
        ``r_{t-1}``; CIR: scaled changes on ``1/sqrt(r)`` and ``sqrt(r)``).
        ``mle`` maximises the exact transition likelihood (Gaussian for
        Vasicek, non-central chi-square for CIR) starting from the OLS values.
    dt : float, optional
        Years between observations; inferred from a DatetimeIndex when omitted.
    """
    model = model.lower()
    method = method.lower()
    if model not in SHORT_RATE_REGISTRY:
        raise ValueError(f"model must be one of {sorted(SHORT_RATE_REGISTRY)}")
    if method not in {"ols", "mle"}:
        raise ValueError("method must be 'ols' or 'mle'")
    series = rates if isinstance(rates, pd.Series) else pd.Series(np.asarray(rates, dtype=float))
    series = series.dropna()
    if len(series) < 20:
        raise ValueError("Need at least 20 observations to estimate short-rate dynamics")
    step = _infer_dt(series, dt)
    r = series.to_numpy(dtype=float)

    ar_coef = ar_int = resid_std = None
    if model == "vasicek":
        kappa, theta, sigma, ar_int, ar_coef, resid_std = _ols_vasicek(r, step)
        loglik_fn = _vasicek_loglik
        bounds = [(1e-4, 20.0), (-0.5, 0.5), (1e-5, 1.0)]
    else:
        kappa, theta, sigma, resid_std = _ols_cir(r, step)
        loglik_fn = _cir_loglik
        bounds = [(1e-4, 20.0), (1e-5, 0.5), (1e-4, 2.0)]

    x = np.array([kappa, theta, sigma])
    if method == "mle":
        x0 = np.clip(x, [b[0] for b in bounds], [b[1] for b in bounds])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = minimize(lambda q: -loglik_fn(q, r, step), x0, method="L-BFGS-B", bounds=bounds)
        if np.isfinite(res.fun) and -res.fun >= loglik_fn(x0, r, step) - 1e-9:
            x = res.x
        kappa, theta, sigma = (float(v) for v in x)

    ll = loglik_fn(np.array([kappa, theta, sigma]), r, step)
    stationary = bool(kappa > 1e-3)
    return ShortRateEstimate(
        model=model,
        method=method,
        kappa=float(kappa),
        theta=float(theta),
        sigma=float(sigma),
        r0=float(r[-1]),
        dt=step,
        n_obs=int(len(r)),
        stationary=stationary,
        half_life_years=float(np.log(2.0) / kappa) if stationary else None,
        log_likelihood=float(ll) if np.isfinite(ll) else float("nan"),
        aic=float(2 * 3 - 2 * ll) if np.isfinite(ll) else float("nan"),
        feller=bool(2 * kappa * theta >= sigma**2) if model == "cir" else None,
        ar_coefficient=ar_coef,
        ar_intercept=ar_int,
        resid_std=resid_std,
    )


SHORT_RATE_REGISTRY: Dict[str, Type[ShortRateModel]] = {
    VasicekModel.model_id: VasicekModel,
    CIRModel.model_id: CIRModel,
}


def get_short_rate_model_class(model_id: str) -> Type[ShortRateModel]:
    key = (model_id or "vasicek").lower().replace("_", "-")
    try:
        return SHORT_RATE_REGISTRY[key]
    except KeyError:
        raise ValueError(f"Unknown short-rate model '{model_id}'. Available: {', '.join(sorted(SHORT_RATE_REGISTRY))}") from None


__all__ = [
    "CIRModel",
    "SHORT_RATE_REGISTRY",
    "ShortRateEstimate",
    "ShortRateModel",
    "VasicekModel",
    "cir_ab",
    "estimate_short_rate",
    "get_short_rate_model_class",
    "vasicek_ab",
]

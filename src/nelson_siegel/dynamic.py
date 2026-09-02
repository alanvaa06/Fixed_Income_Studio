"""
Dynamic Nelson-Siegel (Diebold-Li, 2006) factor forecasting.

Two-step approach: the cross-section fits in :mod:`nelson_siegel.analysis`
turn each historical curve into a small factor vector (Level, Slope,
Curvature; plus Curvature2 for Svensson) with the decay(s) held fixed. This
module models the *time series* of those factors and maps forecasts back to
yield curves through the same loadings.

Three forecasters are provided, all estimated in closed form by OLS:

- ``"rw"``  random walk (no change), the benchmark Diebold-Li compare against;
- ``"ar"``  independent AR(1) per factor, Diebold-Li's preferred specification;
- ``"var"`` a VAR(1) on all factors jointly.

:func:`backtest` runs a rolling-origin, expanding-window evaluation of the
three against realised factors (and yields, when maturities are supplied).
"""

from __future__ import annotations

import warnings
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Type, Union

import numpy as np
import pandas as pd

from .model import NelsonSiegelModel

METHODS = ("rw", "ar", "var")


def _rate_and_decay_columns(
    model_cls: Type[NelsonSiegelModel], columns: Iterable[str]
) -> Tuple[List[str], List[str]]:
    cols = set(columns)
    rate = [m.label for m in model_cls.factor_meta() if m.unit == "rate" and m.label in cols]
    decay = [m.label for m in model_cls.factor_meta() if m.unit == "years"]
    missing_rate = [m.label for m in model_cls.factor_meta() if m.unit == "rate" and m.label not in cols]
    if missing_rate:
        raise ValueError(f"Factor frame is missing columns: {missing_rate}")
    return rate, decay


def _infer_step(index: pd.Index) -> Optional[pd.Timedelta]:
    if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
        diffs = np.diff(index.values).astype("timedelta64[ns]")
        return pd.Timedelta(np.median(diffs))
    return None


class DynamicNelsonSiegel:
    """
    Factor-dynamics model on a Nelson-Siegel (or Svensson) factor history.

    Parameters
    ----------
    method : {"ar", "var", "rw"}
        ``ar`` fits an AR(1) with intercept to each factor separately, ``var``
        a VAR(1) with intercept to all factors jointly, ``rw`` uses the last
        observation as the forecast (random walk).
    model_cls : type
        Curve model whose loadings map factors back to yields. Defaults to
        :class:`~nelson_siegel.model.NelsonSiegelModel`.

    After :meth:`fit`:

    - ``intercept_`` (k,), ``coef_`` (k, k): ``f_t = intercept_ + coef_ @ f_{t-1} + e_t``
    - ``resid_cov_`` (k, k): residual covariance
    - ``factor_names_``, ``decays_``, ``last_``, ``last_date_``, ``step_``
    """

    def __init__(self, method: str = "ar", model_cls: Type[NelsonSiegelModel] = NelsonSiegelModel):
        method = method.lower()
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        self.method = method
        self.model_cls = model_cls
        self.fitted = False

    # ------------------------------------------------------------------ #
    def fit(
        self,
        factors: pd.DataFrame,
        decays: Optional[Sequence[float]] = None,
    ) -> "DynamicNelsonSiegel":
        """Estimate the factor dynamics from a factor history.

        ``factors`` is the frame returned by
        ``YieldCurveAnalyzer.analyze_historical_factors`` (columns Level,
        Slope, Curvature, Tau, ...). The decay(s) are read from the ``Tau``
        (and ``Tau2``) columns unless given explicitly.
        """
        rate_cols, decay_cols = _rate_and_decay_columns(self.model_cls, factors.columns)
        frame = factors[rate_cols].dropna(how="any")
        if len(frame) < 10:
            raise ValueError("Need at least 10 factor observations to estimate dynamics")

        if decays is None:
            missing = [c for c in decay_cols if c not in factors.columns]
            if missing:
                raise ValueError(f"Pass decays= explicitly; frame lacks {missing}")
            decays = tuple(float(factors[c].dropna().iloc[-1]) for c in decay_cols)
        decays = tuple(float(d) for d in decays)
        if len(decays) != len(decay_cols):
            raise ValueError(f"Expected {len(decay_cols)} decay value(s), got {len(decays)}")

        F = frame.to_numpy(dtype=float)
        k = F.shape[1]
        Y, X = F[1:], F[:-1]

        if self.method == "rw":
            intercept = np.zeros(k)
            coef = np.eye(k)
            resid = Y - X
        elif self.method == "ar":
            intercept = np.zeros(k)
            coef = np.zeros((k, k))
            resid = np.empty_like(Y)
            for j in range(k):
                design = np.column_stack([np.ones(len(X)), X[:, j]])
                beta, *_ = np.linalg.lstsq(design, Y[:, j], rcond=None)
                intercept[j], coef[j, j] = beta
                resid[:, j] = Y[:, j] - design @ beta
        else:  # var
            design = np.column_stack([np.ones(len(X)), X])
            beta, *_ = np.linalg.lstsq(design, Y, rcond=None)  # (k+1, k)
            intercept = beta[0]
            coef = beta[1:].T
            resid = Y - design @ beta

        n_params = {"rw": 0, "ar": 2, "var": k + 1}[self.method]
        dof = max(len(Y) - n_params, 1)
        self.intercept_ = intercept
        self.coef_ = coef
        self.resid_cov_ = (resid.T @ resid) / dof
        self.residuals_ = pd.DataFrame(resid, index=frame.index[1:], columns=rate_cols)
        self.factor_names_ = rate_cols
        self.decay_names_ = decay_cols
        self.decays_ = decays
        self.last_ = F[-1]
        self.last_date_ = frame.index[-1]
        self.step_ = _infer_step(frame.index)
        self.n_obs_ = len(frame)
        eig = np.linalg.eigvals(coef)
        self.max_eigenvalue_ = float(np.max(np.abs(eig))) if k else 0.0
        self.fitted = True
        if self.method != "rw" and self.max_eigenvalue_ >= 1.0:
            warnings.warn(
                "Estimated factor dynamics are non-stationary (max |eigenvalue| >= 1); "
                "long-horizon forecasts will not mean-revert.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self

    def _require_fit(self) -> None:
        if not self.fitted:
            raise ValueError("DynamicNelsonSiegel must be fitted before use")

    # ------------------------------------------------------------------ #
    def unconditional_mean(self) -> Optional[np.ndarray]:
        """Long-run factor mean ``(I - A)^-1 c``; ``None`` when not stationary."""
        self._require_fit()
        if self.method == "rw" or self.max_eigenvalue_ >= 1.0:
            return None
        k = len(self.intercept_)
        return np.linalg.solve(np.eye(k) - self.coef_, self.intercept_)

    def persistence(self) -> Dict[str, float]:
        """Own-lag coefficient of each factor (diagonal of the transition matrix)."""
        self._require_fit()
        return {name: float(self.coef_[i, i]) for i, name in enumerate(self.factor_names_)}

    def half_life(self) -> Dict[str, Optional[float]]:
        """Half-life of a shock to each factor in steps, from its own-lag coefficient."""
        self._require_fit()
        out: Dict[str, Optional[float]] = {}
        for name, rho in self.persistence().items():
            if 0 < rho < 1:
                out[name] = float(np.log(0.5) / np.log(rho))
            else:
                out[name] = None
        return out

    def _forecast_index(self, horizon: int) -> pd.Index:
        if self.step_ is not None and isinstance(self.last_date_, pd.Timestamp):
            return pd.DatetimeIndex([self.last_date_ + self.step_ * h for h in range(1, horizon + 1)])
        return pd.RangeIndex(1, horizon + 1, name="step")

    def forecast_factors(self, horizon: int = 12) -> pd.DataFrame:
        """Point forecasts for 1..horizon steps ahead with forecast-error std.

        Columns: each factor, ``<factor>_std`` (iterated-VAR forecast error
        standard deviation), and the constant decay column(s).
        """
        self._require_fit()
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        k = len(self.intercept_)
        f = self.last_.copy()
        A_pow = np.eye(k)
        cov = np.zeros((k, k))
        rows = []
        stds = []
        for _ in range(horizon):
            f = self.intercept_ + self.coef_ @ f
            cov = cov + A_pow @ self.resid_cov_ @ A_pow.T
            A_pow = self.coef_ @ A_pow
            rows.append(f.copy())
            stds.append(np.sqrt(np.clip(np.diag(cov), 0, None)))
        out = pd.DataFrame(np.vstack(rows), index=self._forecast_index(horizon), columns=self.factor_names_)
        std = pd.DataFrame(np.vstack(stds), index=out.index, columns=[f"{c}_std" for c in self.factor_names_])
        out = pd.concat([out, std], axis=1)
        for name, value in zip(self.decay_names_, self.decays_):
            out[name] = value
        return out

    def factors_to_yields(self, factors: np.ndarray, maturities: Sequence[float]) -> np.ndarray:
        """Map factor vectors (n, k) to yields (n, len(maturities)) via the loadings."""
        self._require_fit()
        X = self.model_cls.basis(np.asarray(maturities, dtype=float), *self.decays_)
        return np.atleast_2d(np.asarray(factors, dtype=float)) @ X.T

    def forecast_curve(self, maturities: Sequence[float], horizon: int = 12) -> pd.DataFrame:
        """Forecast yield curves (decimal yields) for each step up to ``horizon``."""
        fc = self.forecast_factors(horizon)
        yields = self.factors_to_yields(fc[self.factor_names_].to_numpy(), maturities)
        return pd.DataFrame(yields, index=fc.index, columns=list(maturities))

    def current_curve(self, maturities: Sequence[float]) -> np.ndarray:
        """Fitted curve implied by the last observed factor vector."""
        return self.factors_to_yields(self.last_, maturities)[0]

    def summary(self) -> Dict[str, object]:
        self._require_fit()
        mean = self.unconditional_mean()
        return {
            "method": self.method,
            "model": self.model_cls.model_id,
            "n_obs": int(self.n_obs_),
            "step_days": float(self.step_.days) if self.step_ is not None else None,
            "last_date": self.last_date_.strftime("%Y-%m-%d") if isinstance(self.last_date_, pd.Timestamp) else None,
            "decays": dict(zip(self.decay_names_, self.decays_)),
            "persistence": self.persistence(),
            "half_life_steps": self.half_life(),
            "stationary": bool(self.max_eigenvalue_ < 1.0) if self.method != "rw" else False,
            "max_eigenvalue": self.max_eigenvalue_,
            "unconditional_mean": dict(zip(self.factor_names_, mean.tolist())) if mean is not None else None,
            "residual_std": dict(zip(self.factor_names_, np.sqrt(np.diag(self.resid_cov_)).tolist())),
        }

    def __repr__(self) -> str:
        if not self.fitted:
            return f"DynamicNelsonSiegel(method={self.method!r}, fitted=False)"
        rho = ", ".join(f"{k}={v:.3f}" for k, v in self.persistence().items())
        return f"DynamicNelsonSiegel(method={self.method!r}, n_obs={self.n_obs_}, persistence: {rho})"


def backtest(
    factors: pd.DataFrame,
    horizons: Sequence[int] = (1, 4, 12),
    methods: Sequence[str] = METHODS,
    min_train: int = 52,
    maturities: Optional[Sequence[float]] = None,
    model_cls: Type[NelsonSiegelModel] = NelsonSiegelModel,
    decays: Optional[Sequence[float]] = None,
) -> pd.DataFrame:
    """Rolling-origin (expanding window) out-of-sample RMSE per method and horizon.

    For every origin ``t >= min_train`` each method is fitted on
    ``factors[:t]`` and its ``h``-step forecast is compared with the realised
    factors at ``t + h - 1``. Returns a frame indexed by ``(method, horizon)``
    with one RMSE column per factor, ``n_forecasts``, and ``yield_rmse``
    (averaged across ``maturities``) when maturities are given. Factor RMSEs
    are in the units of the input (decimal yields).
    """
    rate_cols, _ = _rate_and_decay_columns(model_cls, factors.columns)
    frame = factors.dropna(subset=rate_cols)
    n = len(frame)
    horizons = tuple(int(h) for h in horizons)
    max_h = max(horizons)
    if n < min_train + max_h:
        raise ValueError(f"Need at least min_train + max(horizons) = {min_train + max_h} rows, got {n}")

    F = frame[rate_cols].to_numpy(dtype=float)
    errors: Dict[Tuple[str, int], List[np.ndarray]] = {(m, h): [] for m in methods for h in horizons}
    yield_errors: Dict[Tuple[str, int], List[np.ndarray]] = {(m, h): [] for m in methods for h in horizons}
    basis = None
    dns_for_basis = None
    if maturities is not None:
        dns_for_basis = DynamicNelsonSiegel("rw", model_cls).fit(frame, decays=decays)
        basis = model_cls.basis(np.asarray(maturities, dtype=float), *dns_for_basis.decays_)

    for origin in range(min_train, n - max_h + 1):
        train = frame.iloc[:origin]
        for method in methods:
            model = DynamicNelsonSiegel(method, model_cls)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                model.fit(train, decays=decays)
            fc = model.forecast_factors(max_h)[rate_cols].to_numpy()
            for h in horizons:
                actual = F[origin + h - 1]
                err = fc[h - 1] - actual
                errors[(method, h)].append(err)
                if basis is not None:
                    yield_errors[(method, h)].append(basis @ err)

    rows = []
    for (method, h), errs in errors.items():
        E = np.vstack(errs)
        row: Dict[str, Union[str, int, float]] = {"method": method, "horizon": h, "n_forecasts": len(E)}
        for j, name in enumerate(rate_cols):
            row[f"{name}_rmse"] = float(np.sqrt(np.mean(E[:, j] ** 2)))
        if basis is not None:
            YE = np.vstack(yield_errors[(method, h)])
            row["yield_rmse"] = float(np.sqrt(np.mean(YE**2)))
        rows.append(row)
    return pd.DataFrame(rows).set_index(["method", "horizon"]).sort_index()

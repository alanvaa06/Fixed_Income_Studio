"""
Term premium analysis.

A long yield is the average short rate investors expect over the bond's life
plus a **term premium**, the compensation for bearing duration risk. Neither
half is observed, so this module offers three ways to split them, from the
most structural to the simplest, plus the classic regression tests of the
expectations hypothesis:

- :class:`ACMTermPremiumModel` - the Adrian, Crump and Moench (2013) Gaussian
  affine term-structure model estimated by three linear regressions on a
  monthly zero-coupon panel. Term premium = fitted yield - risk-neutral yield.
- :func:`dns_term_premium` - expectations-hypothesis decomposition using the
  Diebold-Li factor dynamics from :mod:`nelson_siegel.dynamic`: the model
  short rate ``Level + Slope`` is projected forward with the AR/VAR and
  averaged over each maturity.
- :func:`short_rate_term_premium` - the same idea with a Vasicek/CIR physical
  estimate from :mod:`nelson_siegel.short_rate`.
- :func:`campbell_shiller` and :func:`fama_bliss` - regressions whose slope
  equals one under the pure expectations hypothesis; departures measure how
  much term premia move over time.

All yields are annualised, continuously compounded decimals; maturities are
in years unless a name says ``months``.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Type

import numpy as np
import pandas as pd

from .dynamic import DynamicNelsonSiegel
from .model import NelsonSiegelModel
from .short_rate import ShortRateEstimate, ShortRateModel


# --------------------------------------------------------------------------- #
# Panel helpers
# --------------------------------------------------------------------------- #
def zero_panel_from_factors(
    factors: pd.DataFrame,
    maturities: Sequence[float],
    model_cls: Type[NelsonSiegelModel] = NelsonSiegelModel,
    decays: Optional[Sequence[float]] = None,
) -> pd.DataFrame:
    """Evaluate a factor history on a maturity grid (decimal zero yields).

    ``factors`` is the frame from ``YieldCurveAnalyzer.analyze_historical_factors``.
    """
    rate_cols = [m.label for m in model_cls.factor_meta() if m.unit == "rate"]
    decay_cols = [m.label for m in model_cls.factor_meta() if m.unit == "years"]
    frame = factors.dropna(subset=rate_cols)
    if decays is None:
        decays = tuple(float(frame[c].iloc[-1]) for c in decay_cols)
    X = model_cls.basis(np.asarray(maturities, dtype=float), *decays)
    yields = frame[rate_cols].to_numpy(dtype=float) @ X.T
    return pd.DataFrame(yields, index=frame.index, columns=[float(m) for m in maturities])


def to_monthly(panel: pd.DataFrame) -> pd.DataFrame:
    """Month-end sample of a daily/weekly panel (last observation of each month)."""
    if not isinstance(panel.index, pd.DatetimeIndex):
        raise ValueError("panel must be indexed by dates")
    monthly = panel.resample("ME").last()
    return monthly.dropna(how="all")


def interpolate_maturities(panel: pd.DataFrame, maturities: Sequence[float]) -> pd.DataFrame:
    """Linear interpolation across maturities (columns in years) for each date."""
    cols = np.asarray([float(c) for c in panel.columns])
    order = np.argsort(cols)
    cols = cols[order]
    values = panel.to_numpy(dtype=float)[:, order]
    target = np.asarray(list(dict.fromkeys(float(m) for m in maturities)), dtype=float)
    out = np.empty((len(panel), len(target)))
    for i in range(len(panel)):
        row = values[i]
        ok = ~np.isnan(row)
        if ok.sum() < 2:
            out[i] = np.nan
            continue
        out[i] = np.interp(target, cols[ok], row[ok])
    return pd.DataFrame(out, index=panel.index, columns=[float(m) for m in target])


# --------------------------------------------------------------------------- #
# Newey-West OLS used by the regression tests
# --------------------------------------------------------------------------- #
@dataclass
class RegressionResult:
    slope: float
    intercept: float
    slope_se: float
    t_stat_vs_one: float
    t_stat_vs_zero: float
    r_squared: float
    n_obs: int
    lags: int

    def as_dict(self) -> Dict[str, float]:
        return {
            "slope": self.slope,
            "intercept": self.intercept,
            "slope_se": self.slope_se,
            "t_stat_vs_one": self.t_stat_vs_one,
            "t_stat_vs_zero": self.t_stat_vs_zero,
            "r_squared": self.r_squared,
            "n_obs": self.n_obs,
            "lags": self.lags,
        }


def ols_newey_west(x: np.ndarray, y: np.ndarray, lags: int) -> RegressionResult:
    """Simple regression ``y = a + b x`` with Newey-West (Bartlett) standard errors."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 8:
        raise ValueError("Need at least 8 observations for the regression")
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1.0 - lag / (lags + 1.0)
        G = (X[lag:] * resid[lag:, None]).T @ (X[:-lag] * resid[:-lag, None])
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = float(np.sqrt(max(cov[1, 1], 0.0)))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else float("nan")
    return RegressionResult(
        slope=float(beta[1]),
        intercept=float(beta[0]),
        slope_se=se,
        t_stat_vs_one=(float(beta[1]) - 1.0) / se if se > 0 else float("nan"),
        t_stat_vs_zero=float(beta[1]) / se if se > 0 else float("nan"),
        r_squared=r2,
        n_obs=n,
        lags=lags,
    )


# --------------------------------------------------------------------------- #
# Expectations-hypothesis regressions
# --------------------------------------------------------------------------- #
def campbell_shiller(
    panel: pd.DataFrame,
    long_maturity: float,
    short_maturity: float = 1.0,
    steps_per_year: int = 12,
) -> RegressionResult:
    """Campbell-Shiller (1991) yield-change regression.

    ``y_{t+m}(n-m) - y_t(n) = a + b * [m/(n-m)] * (y_t(n) - y_t(m)) + e`` with
    ``n`` the long and ``m`` the short maturity (years) on a regular panel
    (``steps_per_year`` observations per year). Under the expectations
    hypothesis ``b = 1``; the usual finding is ``b < 0`` for long maturities,
    i.e. a time-varying term premium. Newey-West lags equal the overlap.
    """
    n, m = float(long_maturity), float(short_maturity)
    if n <= m:
        raise ValueError("long_maturity must exceed short_maturity")
    h = int(round(m * steps_per_year))
    if h < 1:
        raise ValueError("short_maturity must be at least one step")
    needed = [n, m, n - m]
    grid = interpolate_maturities(panel, needed)
    y_n, y_m, y_nm = (grid[float(k)].to_numpy() for k in needed)
    lhs = y_nm[h:] - y_n[:-h]
    rhs = (m / (n - m)) * (y_n[:-h] - y_m[:-h])
    return ols_newey_west(rhs, lhs, lags=max(h - 1, 0))


def fama_bliss(
    panel: pd.DataFrame,
    maturity: float,
    horizon: float = 1.0,
    steps_per_year: int = 12,
) -> RegressionResult:
    """Fama-Bliss (1987) excess-return regression.

    The ``h``-period log excess return on an ``n``-year zero,
    ``rx_{t+h} = n y_t(n) - (n-h) y_{t+h}(n-h) - h y_t(h)``, is regressed on
    the forward spread ``f_t(n-h,n) - y_t(h)``. Under the expectations
    hypothesis the slope is zero; a slope near one says forward spreads
    forecast returns, not future short rates.
    """
    n, h = float(maturity), float(horizon)
    if n <= h:
        raise ValueError("maturity must exceed horizon")
    steps = int(round(h * steps_per_year))
    grid = interpolate_maturities(panel, [n, n - h, h])
    y_n, y_nh, y_h = grid[n].to_numpy(), grid[n - h].to_numpy(), grid[h].to_numpy()
    rx = n * y_n[:-steps] - (n - h) * y_nh[steps:] - h * y_h[:-steps]
    forward = (n * y_n - (n - h) * y_nh) / h  # h-year forward ending at n
    spread = forward[:-steps] - y_h[:-steps]
    return ols_newey_west(spread, rx, lags=max(steps - 1, 0))


# --------------------------------------------------------------------------- #
# ACM affine term structure model
# --------------------------------------------------------------------------- #
class ACMTermPremiumModel:
    """
    Adrian-Crump-Moench (2013) term premium model.

    Estimation is three linear regressions on monthly data:

    1. a VAR(1) for the pricing factors (principal components of the yield
       panel), ``X_{t+1} = mu + Phi X_t + v_{t+1}``;
    2. bond excess returns on the factor innovations and lagged factors,
       ``rx_{t+1} = a + beta' v_{t+1} + c' X_t + e``;
    3. the market prices of risk ``lambda_0`` and ``lambda_1`` implied by the
       no-arbitrage restriction on ``a`` and ``c``.

    Bond prices then follow the affine recursions ``A_n, B_n``; setting the
    prices of risk to zero yields the risk-neutral curve, and the term premium
    is fitted yield minus risk-neutral yield. See ``fit`` for the panel format.
    """

    def __init__(self, n_factors: int = 3, max_maturity_months: int = 120):
        if not 1 <= n_factors <= 6:
            raise ValueError("n_factors must be between 1 and 6")
        if max_maturity_months < 12:
            raise ValueError("max_maturity_months must be at least 12")
        self.n_factors = int(n_factors)
        self.max_maturity_months = int(max_maturity_months)
        self.fitted = False

    # -- estimation ------------------------------------------------------- #
    def fit(self, panel: pd.DataFrame) -> "ACMTermPremiumModel":
        """Estimate on a monthly zero-yield panel (columns: maturities in years).

        The panel is interpolated to a 1..``max_maturity_months`` monthly grid,
        so it should span at least ``1/12`` to ``max_maturity_months/12`` years
        (short maturities are extrapolated flat when absent).
        """
        if len(panel) < 36:
            raise ValueError("Need at least 36 monthly observations")
        N = self.max_maturity_months
        months = np.arange(1, N + 1)
        grid = interpolate_maturities(panel, months / 12.0).dropna(how="any")
        if len(grid) < 36:
            raise ValueError("Too few complete rows after interpolation")
        Y = grid.to_numpy(dtype=float) / 12.0  # per-month log yields
        T = Y.shape[0]
        K = self.n_factors

        # 1. Factors: principal components of the (demeaned) yield panel.
        mean = Y.mean(axis=0)
        U, S, Vt = np.linalg.svd(Y - mean, full_matrices=False)
        loadings = Vt[:K].T  # N x K
        X = (Y - mean) @ loadings  # T x K
        explained = (S**2 / np.sum(S**2))[:K]

        # VAR(1) with intercept.
        Xl, Xn = X[:-1], X[1:]
        design = np.column_stack([np.ones(T - 1), Xl])
        coef, *_ = np.linalg.lstsq(design, Xn, rcond=None)
        mu = coef[0]
        Phi = coef[1:].T
        V = Xn - design @ coef  # innovations, (T-1) x K
        Sigma = V.T @ V / (T - 1)

        # Short rate loadings r_t = delta0 + delta1' X_t (one-month yield).
        r = Y[:, 0]
        d, *_ = np.linalg.lstsq(np.column_stack([np.ones(T), X]), r, rcond=None)
        delta0, delta1 = float(d[0]), d[1:]

        # 2. Excess returns of n-month bonds held one month, n = 2..N.
        n_idx = np.arange(2, N + 1)  # maturity today
        p_today = -n_idx * Y[:-1, n_idx - 1]
        p_next = -(n_idx - 1) * Y[1:, n_idx - 2]
        RX = p_next - p_today - r[:-1, None]  # (T-1) x (N-1)
        Z = np.column_stack([np.ones(T - 1), V, Xl])
        G, *_ = np.linalg.lstsq(Z, RX, rcond=None)  # (1+2K) x (N-1)
        a = G[0]
        beta = G[1 : 1 + K]  # K x (N-1)
        c = G[1 + K :]  # K x (N-1)
        E = RX - Z @ G
        sigma2 = float(np.mean(E**2))

        # 3. Prices of risk.
        BB = beta @ beta.T
        conv = np.einsum("kn,kj,jn->n", beta, Sigma, beta)  # beta_n' Sigma beta_n
        lam0 = np.linalg.solve(BB, beta @ (a + 0.5 * (conv + sigma2)))
        lam1 = np.linalg.solve(BB, beta @ c.T)

        self.months_ = months
        self.mean_ = mean
        self.loadings_ = loadings
        self.factors_ = pd.DataFrame(X, index=grid.index, columns=[f"PC{i + 1}" for i in range(K)])
        self.explained_variance_ = explained
        self.mu_, self.Phi_, self.Sigma_ = mu, Phi, Sigma
        self.delta0_, self.delta1_ = delta0, delta1
        self.lambda0_, self.lambda1_ = lam0, lam1
        self.sigma2_ = sigma2
        self.beta_ = beta
        self.index_ = grid.index
        self.observed_ = grid  # annualised decimals
        self.A_, self.B_ = self._recursions(lam0, lam1)
        self.A_rn_, self.B_rn_ = self._recursions(np.zeros(K), np.zeros((K, K)))
        self.fitted = True
        return self

    def _recursions(self, lam0: np.ndarray, lam1: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        N, K = self.max_maturity_months, self.n_factors
        A = np.zeros(N + 1)
        B = np.zeros((N + 1, K))
        for n in range(1, N + 1):
            Bp = B[n - 1]
            A[n] = A[n - 1] + Bp @ (self.mu_ - lam0) + 0.5 * (Bp @ self.Sigma_ @ Bp + self.sigma2_) - self.delta0_
            B[n] = Bp @ (self.Phi_ - lam1) - self.delta1_
        return A, B

    # -- outputs ---------------------------------------------------------- #
    def _require_fit(self) -> None:
        if not self.fitted:
            raise ValueError("ACMTermPremiumModel must be fitted first")

    def _yields_from(self, A: np.ndarray, B: np.ndarray, X: np.ndarray) -> np.ndarray:
        """Annualised yields (T x N) from affine coefficients and factors."""
        n = self.months_
        logp = A[1:][None, :] + X @ B[1:].T
        return -logp / n[None, :] * 12.0

    def _column(self, maturity_years: float) -> int:
        n = int(round(float(maturity_years) * 12))
        if not 1 <= n <= self.max_maturity_months:
            raise ValueError(f"maturity must be between 1/12 and {self.max_maturity_months / 12:.1f} years")
        return n - 1

    def fitted_yields(self, maturities: Sequence[float]) -> pd.DataFrame:
        self._require_fit()
        Y = self._yields_from(self.A_, self.B_, self.factors_.to_numpy())
        cols = [self._column(m) for m in maturities]
        return pd.DataFrame(Y[:, cols], index=self.index_, columns=[float(m) for m in maturities])

    def risk_neutral_yields(self, maturities: Sequence[float]) -> pd.DataFrame:
        """Yields with the prices of risk set to zero (expected short rates plus convexity)."""
        self._require_fit()
        Y = self._yields_from(self.A_rn_, self.B_rn_, self.factors_.to_numpy())
        cols = [self._column(m) for m in maturities]
        return pd.DataFrame(Y[:, cols], index=self.index_, columns=[float(m) for m in maturities])

    def expected_average_short_rate(self, maturities: Sequence[float]) -> pd.DataFrame:
        """Pure expectations component: average of ``E_t[r_{t+i}]`` over the bond's life."""
        self._require_fit()
        K = self.n_factors
        N = self.max_maturity_months
        # E_t X_{t+i} = m_i + Phi^i X_t with m_i = sum_{j<i} Phi^j mu.
        a_coef = np.zeros(N + 1)  # cumulative sum of delta0 + delta1' m_i
        b_coef = np.zeros((N + 1, K))  # cumulative sum of Phi^i' delta1
        m_i = np.zeros(K)
        Phi_i = np.eye(K)
        cum_a, cum_b = 0.0, np.zeros(K)
        for i in range(N):
            cum_a += self.delta0_ + self.delta1_ @ m_i
            cum_b = cum_b + Phi_i.T @ self.delta1_
            a_coef[i + 1] = cum_a / (i + 1)
            b_coef[i + 1] = cum_b / (i + 1)
            m_i = self.mu_ + self.Phi_ @ m_i
            Phi_i = self.Phi_ @ Phi_i
        X = self.factors_.to_numpy()
        out = {}
        for m in maturities:
            n = self._column(m) + 1
            out[float(m)] = (a_coef[n] + X @ b_coef[n]) * 12.0
        return pd.DataFrame(out, index=self.index_)

    def term_premium(self, maturities: Sequence[float]) -> pd.DataFrame:
        """Term premium history: fitted minus risk-neutral yield (decimals)."""
        return self.fitted_yields(maturities) - self.risk_neutral_yields(maturities)

    def decompose(self, maturity: float) -> pd.DataFrame:
        """Observed, fitted, risk-neutral, expected-short-rate and term-premium series for one maturity."""
        self._require_fit()
        m = float(maturity)
        fitted = self.fitted_yields([m])[m]
        rn = self.risk_neutral_yields([m])[m]
        eh = self.expected_average_short_rate([m])[m]
        observed = interpolate_maturities(self.observed_, [m])[m]
        return pd.DataFrame(
            {
                "observed": observed,
                "fitted": fitted,
                "risk_neutral": rn,
                "expected_short_rate": eh,
                "term_premium": fitted - rn,
                "convexity": rn - eh,
            }
        )

    def fit_rmse(self) -> float:
        """Root mean squared pricing error across the whole panel (decimals)."""
        self._require_fit()
        Y = self._yields_from(self.A_, self.B_, self.factors_.to_numpy())
        return float(np.sqrt(np.mean((Y - self.observed_.to_numpy()) ** 2)))

    def summary(self) -> Dict[str, object]:
        self._require_fit()
        eig = np.linalg.eigvals(self.Phi_)
        return {
            "n_factors": self.n_factors,
            "n_obs": int(len(self.index_)),
            "start": self.index_[0].strftime("%Y-%m-%d"),
            "end": self.index_[-1].strftime("%Y-%m-%d"),
            "max_maturity_years": self.max_maturity_months / 12.0,
            "explained_variance": [float(v) for v in self.explained_variance_],
            "max_eigenvalue": float(np.max(np.abs(eig))),
            "lambda0": [float(v) for v in self.lambda0_],
            "lambda1": self.lambda1_.tolist(),
            "return_error_std": float(np.sqrt(self.sigma2_)),
            "fit_rmse": self.fit_rmse(),
        }


# --------------------------------------------------------------------------- #
# Expectations-hypothesis decompositions from factor / short-rate dynamics
# --------------------------------------------------------------------------- #
def dns_term_premium(
    dns: DynamicNelsonSiegel,
    factors: pd.DataFrame,
    maturities: Sequence[float],
    steps_per_year: Optional[float] = None,
) -> Dict[str, pd.DataFrame]:
    """Expectations-hypothesis decomposition with Diebold-Li factor dynamics.

    The model short rate is ``y(0) = Level + Slope``. Its expected path under
    the fitted AR(1)/VAR(1) is averaged over each maturity to give the
    expectations component; the term premium is the fitted yield minus that.
    Returns ``{"fitted", "expected_short_rate", "term_premium"}`` frames
    (decimals, one column per maturity) over the factor history.
    """
    if not dns.fitted:
        raise ValueError("Fit the DynamicNelsonSiegel first")
    if steps_per_year is None:
        if dns.step_ is None:
            raise ValueError("Pass steps_per_year for a non-datetime factor history")
        steps_per_year = 365.25 / max(float(dns.step_.days), 1.0)
    rate_cols = dns.factor_names_
    F = factors[rate_cols].dropna().to_numpy(dtype=float)
    index = factors[rate_cols].dropna().index
    K = F.shape[1]
    e = dns.model_cls.basis(np.array([0.0]), *dns.decays_)[0]  # short-rate loading
    mats = [float(m) for m in maturities]
    max_steps = max(1, int(round(max(mats) * steps_per_year)))
    if dns.method == "rw":
        mu, Phi = np.zeros(K), np.eye(K)
    else:
        mu, Phi = dns.intercept_, dns.coef_
    a_cum, b_cum = 0.0, np.zeros(K)
    m_i, Phi_i = np.zeros(K), np.eye(K)
    a_avg = np.zeros(max_steps + 1)
    b_avg = np.zeros((max_steps + 1, K))
    for i in range(max_steps):
        a_cum += e @ m_i
        b_cum = b_cum + Phi_i.T @ e
        a_avg[i + 1] = a_cum / (i + 1)
        b_avg[i + 1] = b_cum / (i + 1)
        m_i = mu + Phi @ m_i
        Phi_i = Phi @ Phi_i
    X = dns.model_cls.basis(np.asarray(mats), *dns.decays_)
    fitted = pd.DataFrame(F @ X.T, index=index, columns=mats)
    expected = {}
    for m in mats:
        n = max(1, int(round(m * steps_per_year)))
        expected[m] = a_avg[n] + F @ b_avg[n]
    expected_df = pd.DataFrame(expected, index=index)
    return {
        "fitted": fitted,
        "expected_short_rate": expected_df,
        "term_premium": fitted - expected_df,
    }


def short_rate_term_premium(
    estimate: ShortRateEstimate,
    maturities: Sequence[float],
    observed_yields: Sequence[float],
    r0: Optional[float] = None,
) -> pd.DataFrame:
    """Term premium today from a physical short-rate estimate.

    Expected average short rate under the estimated (physical) Vasicek/CIR
    dynamics versus the observed zero yields at ``maturities``.
    """
    mats = np.asarray(maturities, dtype=float)
    obs = np.asarray(observed_yields, dtype=float)
    if len(mats) != len(obs):
        raise ValueError("maturities and observed_yields must align")
    start = estimate.r0 if r0 is None else float(r0)
    eh = ShortRateModel.average_expected_short_rate(mats, start, estimate.kappa, estimate.theta)
    return pd.DataFrame(
        {"observed": obs, "expected_short_rate": eh, "term_premium": obs - eh},
        index=pd.Index(mats, name="maturity"),
    )


__all__ = [
    "ACMTermPremiumModel",
    "RegressionResult",
    "campbell_shiller",
    "dns_term_premium",
    "fama_bliss",
    "interpolate_maturities",
    "ols_newey_west",
    "short_rate_term_premium",
    "to_monthly",
    "zero_panel_from_factors",
]

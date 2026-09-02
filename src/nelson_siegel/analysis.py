"""
Yield Curve Analysis Module

This module provides high-level analysis functionality for yield curves
including historical parameter estimation and comparative analysis.

Historical factor estimation follows the Diebold-Li convention: one decay
parameter (tau) per bond type, estimated once by profiling the pooled sum of
squared errors over a sample of historical curves, then a closed-form
least-squares solve for (Level, Slope, Curvature) on every date.
"""

import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple, Type

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from .analytics import (
    SPREAD_DEFINITIONS,
    Bond,
    bond_report,
    carry_roll_down,
    curve_changes,
    curve_spreads,
    forward_rate_table,
    pca_yield_changes,
    rich_cheap,
)
from .data import DataManager
from .dynamic import DynamicNelsonSiegel, backtest
from .model import (
    NelsonSiegelModel,
    TIPSNelsonSiegelModel,
    TreasuryNelsonSiegelModel,
    get_model_class,
    make_model,
)
from .registry import make_any_model
from .short_rate import ShortRateModel, estimate_short_rate, get_short_rate_model_class
from .term_premium import (
    ACMTermPremiumModel,
    campbell_shiller,
    dns_term_premium,
    fama_bliss,
    short_rate_term_premium,
    to_monthly,
    zero_panel_from_factors,
)

_DEFAULT_TAU = {"treasury": 1.37, "tips": 2.0}
_DEFAULT_DECAYS = {
    "nelson-siegel": {"treasury": (1.37,), "tips": (2.0,)},
    "svensson": {"treasury": (1.37, 8.0), "tips": (2.0, 10.0)},
}
_FACTOR_COLUMNS = ["Level", "Slope", "Curvature"]
_BOND_MODELS = {"treasury": TreasuryNelsonSiegelModel, "tips": TIPSNelsonSiegelModel}


def _rate_labels(model_cls: Type[NelsonSiegelModel]) -> List[str]:
    return [m.label for m in model_cls.factor_meta() if m.unit == "rate"]


def _decay_labels(model_cls: Type[NelsonSiegelModel]) -> List[str]:
    return [m.label for m in model_cls.factor_meta() if m.unit == "years"]


def _batch_solve(
    Y: np.ndarray,
    X_full: np.ndarray,
    valid: np.ndarray,
    min_data_points: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Row-wise closed-form OLS grouped by NaN pattern.

    Returns ``(betas, sse)`` with shapes ``(n_rows, 3)`` and ``(n_rows,)``.
    Rows with fewer than ``min_data_points`` valid maturities are NaN.
    """
    n_rows = Y.shape[0]
    betas = np.full((n_rows, X_full.shape[1]), np.nan, dtype=float)
    sse = np.full(n_rows, np.nan, dtype=float)
    if n_rows == 0:
        return betas, sse

    patterns, inverse = np.unique(valid, axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    for p_idx, row_mask in enumerate(patterns):
        if row_mask.sum() < min_data_points:
            continue
        group_idx = np.where(inverse == p_idx)[0]
        X_g = X_full[row_mask]
        Y_g = Y[np.ix_(group_idx, row_mask)]
        b, *_ = np.linalg.lstsq(X_g, Y_g.T, rcond=None)
        resid = Y_g - (X_g @ b).T
        betas[group_idx] = b.T
        sse[group_idx] = (resid**2).sum(axis=1)
    return betas, sse


class YieldCurveAnalyzer:
    """
    High-level analyzer for yield curve data and Nelson-Siegel factors.
    """

    def __init__(self, fred_api_key: Optional[str] = None, *, public_sources: Optional[bool] = None):
        """
        Initialize the yield curve analyzer.

        Parameters:
        -----------
        fred_api_key : str, optional
            FRED API key for data access
        public_sources : bool, optional
            Use key-less public feeds (treasury.gov, FRED CSV, Fed GSW) when no
            key is set; defaults to the environment setting.
        """
        self.data_manager = DataManager(fred_api_key, public_sources=public_sources)
        self.treasury_model = TreasuryNelsonSiegelModel()
        self.tips_model = TIPSNelsonSiegelModel()
        self._global_tau: Dict[str, float] = {}
        self._global_decays: Dict[Tuple[str, str], Tuple[float, ...]] = {}

    @staticmethod
    def _resample_long_range(data: pd.DataFrame) -> pd.DataFrame:
        """Downsample long date ranges for interactive speed."""
        if data.empty:
            return data
        span_days = (data.index.max() - data.index.min()).days
        if span_days <= 365:
            return data
        sampled = data.resample("W-FRI").last().dropna(how="all")
        return sampled if not sampled.empty else data

    @staticmethod
    def _get_data(data_manager: DataManager, bond_type: str, start: Optional[str] = None,
                  end: Optional[str] = None) -> pd.DataFrame:
        if bond_type == "treasury":
            return data_manager.get_treasury_data(start, end)
        return data_manager.get_tips_data(start, end)

    @staticmethod
    def _panel_profile_tau(
        yields_df: pd.DataFrame,
        tau_bounds: Tuple[float, float],
        min_data_points: int = 3,
        n_grid: int = 60,
    ) -> float:
        """Estimate one tau for a panel of curves by minimising the pooled SSE.

        For each candidate tau the betas of every row are solved in closed form,
        so the search is a cheap one-dimensional profile over tau.
        """
        maturities = np.asarray(yields_df.columns, dtype=float)
        Y = yields_df.to_numpy(dtype=float)
        valid = ~np.isnan(Y)
        lo, hi = tau_bounds

        def pooled_sse(tau: float) -> float:
            X = NelsonSiegelModel.basis(maturities, tau)
            _, sse = _batch_solve(Y, X, valid, min_data_points)
            total = np.nansum(sse)
            return float(total) if np.isfinite(total) and not np.all(np.isnan(sse)) else np.inf

        grid = np.geomspace(lo, hi, n_grid)
        losses = np.array([pooled_sse(t) for t in grid])
        if not np.isfinite(losses).any():
            raise ValueError("no rows with enough valid maturities")
        best = int(np.argmin(losses))
        bracket_lo = float(grid[max(best - 1, 0)])
        bracket_hi = float(grid[min(best + 1, n_grid - 1)])
        if bracket_hi <= bracket_lo:
            return float(grid[best])
        res = minimize_scalar(
            pooled_sse, bounds=(bracket_lo, bracket_hi), method="bounded", options={"xatol": 1e-6}
        )
        return float(res.x) if res.fun <= losses[best] else float(grid[best])

    @staticmethod
    def _panel_profile_decays(
        yields_df: pd.DataFrame,
        model: NelsonSiegelModel,
        min_data_points: int = 3,
    ) -> Tuple[float, ...]:
        """Panel estimate of all decay parameters of ``model`` by pooled SSE.

        Reuses the model's own grid + multi-start refinement
        (:meth:`NelsonSiegelModel.search_decays`) with a pooled objective,
        so it works for any number of decays (Nelson-Siegel, Svensson, ...).
        """
        maturities = np.asarray(yields_df.columns, dtype=float)
        Y = yields_df.to_numpy(dtype=float)
        valid = ~np.isnan(Y)

        def pooled_sse(decays: Tuple[float, ...]) -> float:
            X = model.basis(maturities, *decays)
            _, sse = _batch_solve(Y, X, valid, min_data_points)
            if np.all(np.isnan(sse)):
                return np.inf
            total = float(np.nansum(sse))
            return total if np.isfinite(total) else np.inf

        decays, _ = model.search_decays(pooled_sse, model._decay_grids(maturities))
        return decays

    def _estimate_global_decays(
        self,
        bond_type: str,
        model_id: str = "nelson-siegel",
        min_data_points: int = 3,
        data: Optional[pd.DataFrame] = None,
        sample_size: int = 48,
    ) -> Tuple[float, ...]:
        """Pick one set of decay parameters per (bond type, model) from a sample of curves.

        Profiles the pooled sum of squared errors over the decays for up to
        ``sample_size`` evenly spaced historical curves (Diebold-Li style
        panel estimate). Reuses ``data`` when provided so the caller's
        download is not repeated. Falls back to literature defaults if data
        is unavailable or the estimate fails.
        """
        bond_key = bond_type.lower()
        model_cls = get_model_class(model_id)
        cache_key = (bond_key, model_cls.model_id)
        if cache_key in self._global_decays:
            return self._global_decays[cache_key]

        model = make_model(model_cls.model_id, bond_key)
        n_min = max(min_data_points, model.n_params)

        try:
            if data is None:
                data = self._get_data(self.data_manager, bond_key)
            if data is None or data.empty:
                raise ValueError("no data for decay estimation")
            valid_counts = data.notna().sum(axis=1)
            usable = data.loc[valid_counts >= n_min]
            if usable.empty:
                raise ValueError("no rows with enough valid maturities")
            if len(usable) > sample_size:
                pick = np.linspace(0, len(usable) - 1, sample_size).round().astype(int)
                usable = usable.iloc[np.unique(pick)]
            decays = self._panel_profile_decays(usable, model, min_data_points)
        except Exception:
            decays = _DEFAULT_DECAYS.get(model_cls.model_id, {}).get(bond_key)
            if decays is None:
                decays = tuple(float(g[len(g) // 2]) for g in model._decay_grids())
            warnings.warn(
                f"Falling back to default decays={decays} for {bond_key}/{model_cls.model_id}",
                RuntimeWarning,
                stacklevel=2,
            )

        self._global_decays[cache_key] = decays
        if model_cls is NelsonSiegelModel:
            self._global_tau[bond_key] = decays[0]
        return decays

    def _estimate_global_tau(
        self,
        bond_type: str,
        min_data_points: int = 3,
        data: Optional[pd.DataFrame] = None,
        sample_size: int = 48,
    ) -> float:
        """Nelson-Siegel panel tau for a bond type (see :meth:`_estimate_global_decays`)."""
        bond_key = bond_type.lower()
        if bond_key in self._global_tau:
            return self._global_tau[bond_key]
        return self._estimate_global_decays(
            bond_key, "nelson-siegel", min_data_points=min_data_points, data=data,
            sample_size=sample_size,
        )[0]

    @staticmethod
    def _batch_fit_factors(
        yields_df: pd.DataFrame,
        tau: Optional[float] = None,
        min_data_points: int = 3,
        *,
        model_cls: Type[NelsonSiegelModel] = NelsonSiegelModel,
        decays: Optional[Sequence[float]] = None,
    ) -> pd.DataFrame:
        """Closed-form vectorized fit. Groups rows by NaN mask, one lstsq per group.

        Pass ``tau`` for Nelson-Siegel or ``decays`` (and ``model_cls``) for
        any model in the family. Returns the model's rate factors (e.g.
        ``Level, Slope, Curvature``), its constant decay column(s) (``Tau``,
        ...) and ``RMSE`` in the same decimal units as the input yields.
        """
        if decays is None:
            if tau is None:
                raise ValueError("Provide tau (Nelson-Siegel) or decays")
            decays = (float(tau),)
        decays = tuple(float(d) for d in decays)
        rate_cols = _rate_labels(model_cls)
        decay_cols = _decay_labels(model_cls)
        if len(decays) != len(decay_cols):
            raise ValueError(f"{model_cls.display_name} needs {len(decay_cols)} decay(s), got {len(decays)}")
        columns = rate_cols + decay_cols + ["RMSE"]
        if yields_df.empty:
            return pd.DataFrame(columns=columns)

        maturities = np.asarray(yields_df.columns, dtype=float)
        X_full = model_cls.basis(maturities, *decays)
        Y = yields_df.to_numpy(dtype=float)
        valid = ~np.isnan(Y)
        betas, sse = _batch_solve(Y, X_full, valid, max(min_data_points, len(rate_cols)))

        df = pd.DataFrame(betas, index=yields_df.index, columns=rate_cols)
        df = df.dropna(how="any")
        for name, value in zip(decay_cols, decays):
            df[name] = value
        n_valid = valid.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            rmse = np.sqrt(sse / np.where(n_valid > 0, n_valid, np.nan))
        df["RMSE"] = pd.Series(rmse, index=yields_df.index).loc[df.index]
        return df

    def analyze_historical_factors(
        self,
        bond_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_data_points: int = 3,
        verbose: bool = False,
        model: str = "nelson-siegel",
    ) -> pd.DataFrame:
        """
        Calculate historical factors for a bond type.

        Parameters:
        -----------
        bond_type : str
            'treasury' or 'tips'
        start_date : str, optional
            Start date in 'YYYY-MM-DD' format
        end_date : str, optional
            End date in 'YYYY-MM-DD' format
        min_data_points : int
            Minimum number of valid data points required for fitting
        model : str
            Registered model id: ``"nelson-siegel"`` (default) or ``"svensson"``.
            The decays are estimated once per (bond type, model) on a panel
            of curves; the betas are solved in closed form per date.

        Returns:
        --------
        pd.DataFrame
            Historical factors: the model's rate factors (Level, Slope,
            Curvature[, Curvature2]), its decay column(s) (Tau[, Tau2]) and RMSE

        Raises:
        -------
        ValueError
            If bond_type is not supported or data is insufficient
        """
        bond_key = bond_type.lower()
        if bond_key not in _BOND_MODELS:
            raise ValueError("bond_type must be 'treasury' or 'tips'")

        data = self._get_data(self.data_manager, bond_key, start_date, end_date)
        if data.empty:
            raise ValueError(f"No {bond_type} data available for the specified period")

        data = self._resample_long_range(data)
        data = data.dropna(how="all")
        if data.empty:
            raise ValueError(f"No {bond_type} data available for the specified period")

        if verbose:
            print(f"Analyzing {bond_type} data: {len(data)} observations")
            print(
                f"Date range: {data.index[0].strftime('%Y-%m-%d')} to "
                f"{data.index[-1].strftime('%Y-%m-%d')}"
            )
            print(f"Maturities: {list(data.columns)} years")

        model_cls = get_model_class(model)
        max_tenors = int(data.notna().sum(axis=1).max())
        if max_tenors < model_cls.describe()["min_points"]:
            raise ValueError(
                f"{model_cls.display_name} needs at least {model_cls.describe()['min_points']} "
                f"tenors per date; {bond_type} data has at most {max_tenors}."
            )
        decays = self._estimate_global_decays(
            bond_key, model_cls.model_id, min_data_points=min_data_points, data=data
        )
        factors_df = self._batch_fit_factors(
            data, min_data_points=min_data_points, model_cls=model_cls, decays=decays
        )

        if factors_df.empty:
            raise ValueError(f"Could not fit model for any dates in {bond_type} data")

        if verbose:
            print(f"Successfully fitted {len(factors_df)} out of {len(data)} dates")
            failed = len(data) - len(factors_df)
            if failed:
                print(f"Failed dates: {failed} ({100*failed/len(data):.1f}%)")

        return factors_df

    def forecast_factors(
        self,
        bond_type: str,
        horizon: int = 12,
        method: str = "ar",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        maturities: Optional[Sequence[float]] = None,
        factors: Optional[pd.DataFrame] = None,
        model: str = "nelson-siegel",
    ) -> Dict:
        """
        Diebold-Li dynamic forecast of the factors and the implied yield curves.

        Parameters:
        -----------
        bond_type : str
            'treasury' or 'tips'
        horizon : int
            Steps ahead (one step is one row of the factor history: daily for
            ranges up to a year, weekly beyond).
        method : {"ar", "var", "rw"}
            AR(1) per factor (default), VAR(1), or random walk.
        start_date, end_date : str, optional
            Range of the factor history used to estimate the dynamics.
        maturities : sequence of float, optional
            Maturities for the forecast curves; defaults to the bond's quoted tenors.
        factors : pd.DataFrame, optional
            Pre-computed factor history (skips the download and cross-section fits).
        model : str
            Registered curve model id whose loadings map factors to yields.

        Returns:
        --------
        dict
            ``factors`` (history), ``forecast`` (factor paths with std bands),
            ``curves`` (forecast yields by maturity), ``current_curve``,
            ``maturities``, ``summary`` and the fitted ``model``.
        """
        bond_key = bond_type.lower()
        if bond_key not in _BOND_MODELS:
            raise ValueError("bond_type must be 'treasury' or 'tips'")
        model_cls = get_model_class(model)
        if factors is None:
            factors = self.analyze_historical_factors(bond_key, start_date, end_date, model=model)
        if maturities is None:
            maturities = list(self._get_data(self.data_manager, bond_key, start_date, end_date).columns)
        maturities = [float(m) for m in maturities]

        dns = DynamicNelsonSiegel(method, model_cls=model_cls).fit(factors)
        forecast = dns.forecast_factors(horizon)
        curves = dns.forecast_curve(maturities, horizon)
        return {
            "bond_type": bond_key,
            "factors": factors,
            "forecast": forecast,
            "curves": curves,
            "current_curve": dns.current_curve(maturities),
            "maturities": maturities,
            "summary": dns.summary(),
            "model": dns,
        }

    def backtest_factor_forecasts(
        self,
        bond_type: str,
        horizons: Sequence[int] = (1, 4, 12),
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_train: int = 52,
        factors: Optional[pd.DataFrame] = None,
        model: str = "nelson-siegel",
    ) -> pd.DataFrame:
        """Out-of-sample RMSE of random walk vs AR(1) vs VAR(1) (see :func:`nelson_siegel.dynamic.backtest`)."""
        bond_key = bond_type.lower()
        if bond_key not in _BOND_MODELS:
            raise ValueError("bond_type must be 'treasury' or 'tips'")
        model_cls = get_model_class(model)
        if factors is None:
            factors = self.analyze_historical_factors(bond_key, start_date, end_date, model=model)
        maturities = list(self._get_data(self.data_manager, bond_key, start_date, end_date).columns)
        return backtest(
            factors, horizons=horizons, min_train=min_train, maturities=maturities, model_cls=model_cls
        )

    def analyze_single_curve(
        self,
        bond_type: str,
        date: Optional[str] = None,
        yields_data: Optional[Dict] = None,
    ) -> Dict:
        """
        Analyze a single yield curve for a specific date.

        Parameters:
        -----------
        bond_type : str
            'treasury' or 'tips'
        date : str, optional
            Date in 'YYYY-MM-DD' format. If None, uses most recent data.
        yields_data : dict, optional
            Manual yield data as {maturity: yield} pairs

        Returns:
        --------
        dict
            Analysis results including factors, fitted yields, and deviations
        """
        bond_key = bond_type.lower()
        if bond_key not in _BOND_MODELS:
            raise ValueError("bond_type must be 'treasury' or 'tips'")
        model_class = _BOND_MODELS[bond_key]

        if yields_data is None:
            data = self._get_data(self.data_manager, bond_key)
            if date is None:
                date = data.index[-1]
            else:
                date = pd.to_datetime(date)

            if date not in data.index:
                raise ValueError(f"Date {date} not found in {bond_type} data")

            yields = data.loc[date].dropna()
            maturities = np.asarray(yields.index.values, dtype=float)
            yields = np.asarray(yields.values, dtype=float)
        else:
            maturities = np.array(list(yields_data.keys()), dtype=float)
            yields = np.array(list(yields_data.values()), dtype=float)

        model = model_class()
        model.fit(maturities, yields)

        fitted_yields = model.predict(maturities)
        deviations = yields - fitted_yields

        smooth_maturities = np.linspace(maturities.min(), maturities.max(), 100)
        smooth_fitted = model.predict(smooth_maturities)

        return {
            "bond_type": bond_type,
            "date": date,
            "factors": model.get_factors(),
            "fit_stats": model.fit_stats(),
            "maturities": maturities,
            "observed_yields": yields,
            "fitted_yields": fitted_yields,
            "deviations": deviations,
            "rmse": np.sqrt(np.mean(deviations**2)),
            "smooth_maturities": smooth_maturities,
            "smooth_fitted": smooth_fitted,
            "smooth_forward": model.forward_rate(smooth_maturities),
            "bond_classification": model.classify_bonds(maturities, yields),
        }

    def compare_curves(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict:
        """
        Compare Treasury and TIPS yield curves over time.

        Parameters:
        -----------
        start_date : str, optional
            Start date for comparison
        end_date : str, optional
            End date for comparison

        Returns:
        --------
        dict
            Comparison results including aligned factors and statistics
        """
        if verbose:
            print("Analyzing Treasury and TIPS factors...")

        with ThreadPoolExecutor(max_workers=2) as executor:
            treasury_future = executor.submit(
                self.analyze_historical_factors, "treasury", start_date, end_date, 3, verbose
            )
            tips_future = executor.submit(
                self.analyze_historical_factors, "tips", start_date, end_date, 3, verbose
            )
            treasury_factors = treasury_future.result()
            tips_factors = tips_future.result()

        common_dates = treasury_factors.index.intersection(tips_factors.index)
        if len(common_dates) == 0:
            raise ValueError("No common dates found between Treasury and TIPS data")

        treasury_aligned = treasury_factors.loc[common_dates]
        tips_aligned = tips_factors.loc[common_dates]

        factor_correlations = {}
        factor_differences = {}
        for factor in _FACTOR_COLUMNS + ["Tau"]:
            if factor in treasury_aligned.columns and factor in tips_aligned.columns:
                tsy_factor = treasury_aligned[factor]
                tips_factor = tips_aligned[factor]
                # Tau is constant per bond type under the panel estimate, so its
                # correlation is undefined; report it only for the betas.
                if factor != "Tau":
                    factor_correlations[factor] = tsy_factor.corr(tips_factor)
                factor_differences[factor] = {
                    "mean_diff": (tsy_factor - tips_factor).mean(),
                    "std_diff": (tsy_factor - tips_factor).std(),
                    "mean_tsy": tsy_factor.mean(),
                    "mean_tips": tips_factor.mean(),
                    "std_tsy": tsy_factor.std(),
                    "std_tips": tips_factor.std(),
                }

        return {
            "treasury_factors": treasury_factors,
            "tips_factors": tips_factors,
            "common_dates": common_dates,
            "treasury_aligned": treasury_aligned,
            "tips_aligned": tips_aligned,
            "correlations": factor_correlations,
            "differences": factor_differences,
            "summary_stats": {
                "total_observations": len(common_dates),
                "date_range": {
                    "start": common_dates[0].strftime("%Y-%m-%d"),
                    "end": common_dates[-1].strftime("%Y-%m-%d"),
                },
            },
        }

    def generate_report(
        self,
        bond_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save_data: bool = True,
    ) -> Dict:
        """
        Generate a comprehensive analysis report.

        Parameters:
        -----------
        bond_type : str
            'treasury', 'tips', or 'both'
        start_date : str, optional
            Start date for analysis
        end_date : str, optional
            End date for analysis
        save_data : bool
            Whether to save results to CSV files

        Returns:
        --------
        dict
            Comprehensive analysis report
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if bond_type.lower() == "both":
            comparison = self.compare_curves(start_date, end_date)

            if save_data:
                comparison["treasury_factors"].to_csv(f"treasury_factors_{timestamp}.csv")
                comparison["tips_factors"].to_csv(f"tips_factors_{timestamp}.csv")
                summary_df = pd.DataFrame(comparison["differences"]).T
                summary_df.to_csv(f"factor_comparison_{timestamp}.csv")

            return comparison

        factors = self.analyze_historical_factors(bond_type, start_date, end_date)

        summary_stats = {
            "factor_statistics": factors.describe().to_dict(),
            "factor_correlations": factors[_FACTOR_COLUMNS].corr().to_dict(),
            "total_observations": len(factors),
            "date_range": {
                "start": factors.index[0].strftime("%Y-%m-%d"),
                "end": factors.index[-1].strftime("%Y-%m-%d"),
            },
        }

        if save_data:
            factors.to_csv(f"{bond_type}_factors_{timestamp}.csv")
            summary_df = pd.DataFrame(summary_stats["factor_statistics"])
            summary_df.to_csv(f"{bond_type}_summary_{timestamp}.csv")

        return {
            "bond_type": bond_type,
            "factors": factors,
            "summary_stats": summary_stats,
        }

    # ------------------------------------------------------------------ #
    # Short-rate models
    # ------------------------------------------------------------------ #
    SHORT_RATE_PROXIES = ("policy", "1m", "3m", "6m", "1y")

    def short_rate_proxy(
        self,
        proxy: str = "policy",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        frequency: str = "W-FRI",
    ) -> pd.Series:
        """History of a short-rate proxy (decimal), sampled at ``frequency``.

        ``policy`` is the effective fed funds rate; ``1m``, ``3m``, ``6m``
        and ``1y`` are the corresponding Treasury bill/note yields.
        """
        key = proxy.lower()
        if key == "policy":
            series = self.data_manager.get_policy_rate(start_date, end_date)
        elif key in {"1m", "3m", "6m", "1y"}:
            tenor = {"1m": 1 / 12, "3m": 0.25, "6m": 0.5, "1y": 1.0}[key]
            data = self.data_manager.get_treasury_data(start_date, end_date)
            col = min(data.columns, key=lambda c: abs(float(c) - tenor))
            series = data[col]
        else:
            raise ValueError(f"proxy must be one of {self.SHORT_RATE_PROXIES}")
        series = series.dropna()
        if frequency:
            series = series.resample(frequency).last().dropna()
        return series.rename(key)

    def short_rate_analysis(
        self,
        bond_type: str = "treasury",
        model: str = "vasicek",
        method: str = "ols",
        proxy: str = "policy",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        horizon_years: float = 5.0,
        n_paths: int = 200,
        curve_date: Optional[str] = None,
    ) -> Dict:
        """End-to-end short-rate study: physical estimate, cross-section calibration, simulation.

        Returns the time-series estimate (``estimate``), the model calibrated
        to the latest curve with the estimated volatility (``calibrated``),
        the physical model (``physical``), the proxy ``history``, simulated
        path ``quantiles``, expected short-rate paths under both measures, the
        observed and model-implied curves and a term premium table.
        """
        cls = get_short_rate_model_class(model)
        history = self.short_rate_proxy(proxy, start_date, end_date)
        if cls.requires_positive_rates:
            history = history.clip(lower=1e-4)
        estimate = estimate_short_rate(history, cls.model_id, method)

        data = self._get_data(self.data_manager, (bond_type or "treasury").lower(), start_date, end_date)
        data = data.dropna(how="all")
        row = data.iloc[-1] if curve_date is None else data.loc[pd.Timestamp(curve_date)]
        row = row.dropna()
        maturities = np.asarray(row.index, dtype=float)
        yields = row.to_numpy(dtype=float)

        calibrated: ShortRateModel = cls()
        try:
            calibrated.fit(maturities, yields, sigma=estimate.sigma)
        except ValueError:
            calibrated.fit(maturities, yields)
        physical = estimate.as_model()

        sims = physical.simulate(horizon_years, n_paths=n_paths, steps_per_year=52, seed=0)
        quantiles = sims.quantile([0.05, 0.25, 0.5, 0.75, 0.95], axis=1).T
        quantiles.columns = ["p5", "p25", "p50", "p75", "p95"]
        horizons = sims.index.to_numpy()
        smooth = np.linspace(max(0.05, float(maturities.min())), float(maturities.max()), 120)
        term_premium = short_rate_term_premium(estimate, maturities, yields)
        return {
            "model": cls.model_id,
            "model_name": cls.display_name,
            "proxy": history.name,
            "history": history,
            "estimate": estimate,
            "physical": physical,
            "calibrated": calibrated,
            "as_of": row.name,
            "maturities": maturities,
            "observed": yields,
            "fitted": calibrated.predict(maturities),
            "smooth": {
                "maturities": smooth,
                "fitted": calibrated.predict(smooth),
                "forward": calibrated.forward_rate(smooth),
                "expectations": calibrated.expectations_yield(smooth),
            },
            "horizons": horizons,
            "expected_physical": physical.expected_path(horizons),
            "expected_risk_neutral": calibrated.expected_path(horizons),
            "quantiles": quantiles,
            "term_premium": term_premium,
            "sources": self.data_manager.source_summary(),
        }

    # ------------------------------------------------------------------ #
    # Term premium
    # ------------------------------------------------------------------ #
    TERM_PREMIUM_SOURCES = ("gsw", "treasury", "tips")

    def zero_curve_panel(
        self,
        source: str = "gsw",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_maturity_years: float = 10.0,
        model: str = "nelson-siegel",
    ) -> pd.DataFrame:
        """Monthly zero-coupon panel on a 1-month grid up to ``max_maturity_years``.

        ``gsw`` evaluates the Fed's published Svensson parameters; ``treasury``
        / ``tips`` evaluate this package's own factor history for the bond type.
        """
        months = np.arange(1, int(round(max_maturity_years * 12)) + 1)
        grid = months / 12.0
        key = source.lower()
        if key == "gsw":
            zeros = self.data_manager.get_zero_curve(grid, start_date, end_date, kind="nominal")
        elif key in {"treasury", "tips"}:
            factors = self.analyze_historical_factors(key, start_date, end_date, model=model)
            zeros = zero_panel_from_factors(factors, grid, get_model_class(model))
        else:
            raise ValueError(f"source must be one of {self.TERM_PREMIUM_SOURCES}")
        return to_monthly(zeros)

    def term_premium_analysis(
        self,
        source: str = "gsw",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        maturities: Sequence[float] = (2.0, 5.0, 10.0),
        n_factors: int = 3,
        max_maturity_years: float = 10.0,
        dns_method: str = "var",
        model: str = "nelson-siegel",
    ) -> Dict:
        """ACM term premia plus the Diebold-Li expectations split and EH regressions.

        Returns the fitted ``acm`` model, per-maturity ``decomposition`` frames
        (observed, fitted, risk-neutral, expected short rate, term premium,
        convexity), the ``dns`` decomposition on the same maturities (from the
        factor history of ``dns_bond_type``), and Campbell-Shiller / Fama-Bliss
        ``regressions``.
        """
        mats = [float(m) for m in maturities]
        if max(mats) > max_maturity_years:
            raise ValueError("maturities must not exceed max_maturity_years")
        panel = self.zero_curve_panel(source, start_date, end_date, max_maturity_years, model)
        acm = ACMTermPremiumModel(n_factors=n_factors, max_maturity_months=int(round(max_maturity_years * 12))).fit(panel)
        decomposition = {m: acm.decompose(m) for m in mats}

        dns_bond = "tips" if source.lower() == "tips" else "treasury"
        dns_out: Optional[Dict[str, pd.DataFrame]] = None
        dns_summary: Optional[Dict[str, object]] = None
        try:
            factors = self.analyze_historical_factors(dns_bond, start_date, end_date, model=model)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                dns = DynamicNelsonSiegel(dns_method, model_cls=get_model_class(model)).fit(factors)
            dns_out = dns_term_premium(dns, factors, mats)
            dns_summary = dns.summary()
        except ValueError:
            dns_out = None

        regressions: Dict[str, Dict[str, Dict[str, float]]] = {"campbell_shiller": {}, "fama_bliss": {}}
        for m in mats:
            if m > 1.0:
                try:
                    regressions["campbell_shiller"][str(m)] = campbell_shiller(panel, m, 1.0).as_dict()
                    regressions["fama_bliss"][str(m)] = fama_bliss(panel, m, 1.0).as_dict()
                except ValueError:
                    continue
        term_premium = acm.term_premium(mats)
        benchmark, benchmark_stats = self._acm_benchmark(term_premium, start_date, end_date)
        return {
            "source": source.lower(),
            "panel": panel,
            "acm": acm,
            "summary": acm.summary(),
            "maturities": mats,
            "decomposition": decomposition,
            "term_premium": term_premium,
            "dns": dns_out,
            "dns_summary": dns_summary,
            "regressions": regressions,
            "benchmark": benchmark,
            "benchmark_stats": benchmark_stats,
            "sources": self.data_manager.source_summary(),
        }

    def _acm_benchmark(
        self,
        term_premium: pd.DataFrame,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Tuple[Optional[pd.DataFrame], Dict[float, Dict[str, float]]]:
        """NY Fed ACM premia (monthly) on the maturities we estimated, with agreement statistics.

        Returns ``(benchmark, stats)``; ``benchmark`` is ``None`` when no live
        source served the series (there is deliberately no synthetic stand-in).
        ``stats[m]`` holds the overlap count, correlation, mean gap (ours minus
        NY Fed, bps), RMSE of the gap and the latest values.
        """
        try:
            raw = self.data_manager.get_acm_benchmark(start_date, end_date)
        except Exception:  # noqa: BLE001 - the benchmark is optional
            return None, {}
        if raw is None or raw.empty:
            return None, {}
        monthly = to_monthly(raw)
        cols = [m for m in term_premium.columns if float(m) in monthly.columns]
        if not cols:
            return None, {}
        benchmark = monthly[cols].dropna(how="all")
        stats: Dict[float, Dict[str, float]] = {}
        for m in cols:
            joined = pd.concat([term_premium[m].rename("ours"), benchmark[m].rename("nyfed")], axis=1, join="inner").dropna()
            if len(joined) < 12:
                continue
            gap = joined["ours"] - joined["nyfed"]
            stats[float(m)] = {
                "n": int(len(joined)),
                "correlation": float(joined["ours"].corr(joined["nyfed"])),
                "mean_gap_bps": float(gap.mean() * 1e4),
                "rmse_bps": float(np.sqrt((gap**2).mean()) * 1e4),
                "latest_ours_pct": float(joined["ours"].iloc[-1] * 100.0),
                "latest_benchmark_pct": float(joined["nyfed"].iloc[-1] * 100.0),
                "latest_date": joined.index[-1].strftime("%Y-%m-%d"),
            }
        return benchmark, stats

    # ------------------------------------------------------------------ #
    # Curve and bond analytics
    # ------------------------------------------------------------------ #
    def curve_analytics(
        self,
        bond_type: str = "treasury",
        model: str = "nelson-siegel",
        horizon: float = 1.0,
        lookback_days: int = 365,
        end_date: Optional[str] = None,
    ) -> Dict:
        """Snapshot analytics: fit, carry/roll-down, forwards, spreads, rich/cheap, changes, PCA."""
        bond_key = (bond_type or "treasury").lower()
        end = pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
        start = end - pd.Timedelta(days=int(lookback_days) + 10)
        panel = self._get_data(self.data_manager, bond_key, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        panel = panel.dropna(how="all")
        if panel.empty:
            raise ValueError("no curve data available")
        row = panel.iloc[-1].dropna()
        maturities = np.asarray(row.index, dtype=float)
        yields = row.to_numpy(dtype=float)
        curve = make_any_model(model, bond_key).fit(maturities, yields)
        full = [m for m in (0.25, 1, 2, 3, 5, 7, 10, 20, 30) if maturities.min() - 1e-9 <= m <= maturities.max() + 1e-9]
        pairs = [(a, b) for a, b in ((1, 1), (2, 1), (3, 2), (5, 5), (10, 10), (1, 2), (2, 3), (10, 20)) if a + b <= maturities.max() + 1e-9 and a >= maturities.min()]
        spread_defs = {
            name: legs
            for name, legs in SPREAD_DEFINITIONS.items()
            if all(maturities.min() - 1e-9 <= m <= maturities.max() + 1e-9 for m, _ in legs)
        }
        pca = None
        try:
            pca = pca_yield_changes(panel)
        except ValueError:
            pass
        return {
            "bond_type": bond_key,
            "model": curve.model_id,
            "as_of": row.name,
            "curve": curve,
            "maturities": maturities,
            "observed": yields,
            "carry_roll_down": carry_roll_down(curve, full, horizon),
            "forwards": forward_rate_table(curve, pairs) if pairs else pd.DataFrame(),
            "spreads": curve_spreads(curve, spread_defs) if spread_defs else pd.Series(dtype=float),
            "spread_history": curve_spreads(panel, spread_defs) if spread_defs else pd.DataFrame(index=panel.index),
            "rich_cheap": rich_cheap(curve, maturities, yields),
            "changes": curve_changes(panel),
            "pca": pca,
            "sources": self.data_manager.source_summary(),
        }

    def bond_analytics(
        self,
        bond: Bond,
        bond_type: str = "treasury",
        model: str = "nelson-siegel",
        price: Optional[float] = None,
        maturities: Optional[Sequence[float]] = None,
        yields: Optional[Sequence[float]] = None,
    ) -> Dict:
        """Price and risk a bond off the latest curve (or supplied quotes)."""
        bond_key = (bond_type or "treasury").lower()
        if maturities is None or yields is None:
            panel = self._get_data(self.data_manager, bond_key).dropna(how="all")
            row = panel.iloc[-1].dropna()
            maturities = np.asarray(row.index, dtype=float)
            yields = row.to_numpy(dtype=float)
            as_of = row.name
        else:
            maturities = np.asarray(maturities, dtype=float)
            yields = np.asarray(yields, dtype=float)
            as_of = None
        curve = make_any_model(model, bond_key).fit(maturities, yields)
        keys = [k for k in (0.25, 1, 2, 3, 5, 7, 10, 20, 30) if k <= max(maturities.max(), bond.maturity) + 1e-9]
        report = bond_report(bond, curve, price=price, key_tenors=keys)
        report.update({"bond": bond, "curve": curve, "as_of": as_of, "model": curve.model_id})
        return report

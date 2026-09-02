"""
Flask application exposing the Nelson-Siegel model through a REST API and
a single-page web interface.

Endpoints
---------
GET  /                       Serve the dashboard
POST /api/fit                Fit Nelson-Siegel parameters to user-supplied yields
POST /api/curve              Evaluate the model at given maturities for a parameter set
GET  /api/historical         Compute historical Nelson-Siegel factors
GET  /api/snapshot           Return the latest fitted curve for a bond type
GET  /api/compare            Compare Treasury vs TIPS factor histories
GET  /api/health             Health check
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request

from ..analysis import YieldCurveAnalyzer
from ..model import (
    NelsonSiegelModel,
    TIPSNelsonSiegelModel,
    TreasuryNelsonSiegelModel,
)
from ._factors_cache import FactorsCache
from .warmup import cancel_warmup, start_warmup


def _model_for(bond_type: str) -> NelsonSiegelModel:
    bt = (bond_type or "treasury").lower()
    if bt == "tips":
        return TIPSNelsonSiegelModel()
    return TreasuryNelsonSiegelModel()


def _smooth_grid(min_mat: float, max_mat: float, points: int = 200) -> np.ndarray:
    lo = max(0.05, float(min_mat))
    hi = max(lo + 0.5, float(max_mat))
    return np.linspace(lo, hi, points)


def _json_float(value: Any) -> Optional[float]:
    """Return a JSON-safe float (NaN/None -> null)."""
    if value is None:
        return None
    value = float(value)
    return None if np.isnan(value) else value


def _to_pct(arr: np.ndarray) -> List[float]:
    return [float(x) * 100.0 for x in np.asarray(arr).ravel()]


def _factors_in_percent(factors: Dict[str, float]) -> Dict[str, float]:
    """Convert Level/Slope/Curvature decimals to percent; keep Tau in years."""
    return {
        "Level": float(factors["Level"]) * 100.0,
        "Slope": float(factors["Slope"]) * 100.0,
        "Curvature": float(factors["Curvature"]) * 100.0,
        "Tau": float(factors["Tau"]),
    }


def create_app(
    fred_api_key: Optional[str] = None,
    *,
    enable_warmup: bool = True,
    warmup_years: int = 10,
) -> Flask:
    """Build the Flask application with the Nelson-Siegel API wired in."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    def _cache_key(bond_type: str, start_date: Optional[str], end_date: Optional[str]) -> tuple:
        return (
            bond_type.lower(),
            start_date or "",
            end_date or "",
            "auto_weekly_over_1y",
            bool(app.config["FRED_KEY_PRESENT"]),
        )

    def _get_cached_factors(
        bond_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> pd.DataFrame:
        cache: FactorsCache = app.config["FACTORS_CACHE"]
        key = _cache_key(bond_type, start_date, end_date)

        def _compute() -> pd.DataFrame:
            analyzer = app.config["ANALYZER"]
            return analyzer.analyze_historical_factors(
                bond_type=bond_type,
                start_date=start_date,
                end_date=end_date,
            )

        return cache.get_or_compute(key, _compute)

    def configure_data_source(api_key: Optional[str]) -> None:
        normalized_key = api_key.strip() if api_key else None
        cancel_warmup(app)
        analyzer = YieldCurveAnalyzer(fred_api_key=normalized_key)
        app.config["ANALYZER"] = analyzer
        # Share one memoised data manager so snapshot, tau estimation and
        # historical fits never download the same window twice.
        app.config["DATA_MANAGER"] = analyzer.data_manager
        app.config["FRED_KEY_PRESENT"] = bool(normalized_key)
        app.config["FACTORS_CACHE"] = FactorsCache()
        if enable_warmup:
            start_warmup(app, _get_cached_factors, years=warmup_years)

    configure_data_source(fred_api_key or os.environ.get("FRED_API_KEY"))

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            fred_key_present=app.config["FRED_KEY_PRESENT"],
        )

    @app.get("/api/health")
    def health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "fred_api_key": app.config["FRED_KEY_PRESENT"],
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )

    @app.post("/api/fred-key")
    def set_fred_key() -> Any:
        """Set the FRED API key for this running app process only."""
        payload = request.get_json(silent=True) or {}
        api_key = str(payload.get("api_key", "")).strip()
        if not api_key:
            return jsonify({"error": "FRED API key is required."}), 400

        configure_data_source(api_key)
        return jsonify(
            {
                "fred_api_key": app.config["FRED_KEY_PRESENT"],
                "message": "FRED API key set for this session.",
            }
        )

    @app.post("/api/fit")
    def fit_curve() -> Any:
        """Fit Nelson-Siegel parameters to a list of (maturity, yield) pairs."""
        payload = request.get_json(silent=True) or {}
        bond_type = payload.get("bond_type", "treasury")
        points = payload.get("points") or []
        yield_unit = (payload.get("yield_unit") or "percent").lower()

        try:
            maturities = np.array([float(p["maturity"]) for p in points], dtype=float)
            yields = np.array([float(p["yield"]) for p in points], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": f"Invalid input data: {exc}"}), 400

        if yield_unit == "percent":
            yields = yields / 100.0

        if len(maturities) < 4:
            return jsonify({"error": "At least 4 (maturity, yield) points are required."}), 400

        model = _model_for(bond_type)
        try:
            model.fit(maturities, yields)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        fitted = model.predict(maturities)
        deviations = yields - fitted
        smooth_x = _smooth_grid(maturities.min(), maturities.max())
        smooth_y = model.predict(smooth_x)
        classifications = model.classify_bonds(maturities, yields)
        rmse = float(np.sqrt(np.mean(deviations ** 2)))
        stats = model.fit_stats()

        return jsonify(
            {
                "bond_type": bond_type,
                "factors": _factors_in_percent(model.get_factors()),
                "maturities": maturities.tolist(),
                "observed": _to_pct(yields),
                "fitted": _to_pct(fitted),
                "deviations_bps": [float(d) * 10000.0 for d in deviations],
                "rmse_bps": rmse * 10000.0,
                "r_squared": _json_float(stats.get("r_squared")),
                "decay_at_bound": bool(stats.get("decay_at_bound", False)),
                "smooth": {
                    "maturities": smooth_x.tolist(),
                    "yields": _to_pct(smooth_y),
                    "forward": _to_pct(model.forward_rate(smooth_x)),
                },
                "classification": classifications,
            }
        )

    @app.post("/api/curve")
    def evaluate_curve() -> Any:
        """Evaluate the Nelson-Siegel function at custom parameters (in percent)."""
        payload = request.get_json(silent=True) or {}
        try:
            beta0 = float(payload["beta0"])
            beta1 = float(payload["beta1"])
            beta2 = float(payload["beta2"])
            tau = float(payload["tau"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "beta0, beta1, beta2 and tau are required."}), 400

        if tau <= 0:
            return jsonify({"error": "tau must be strictly positive."}), 400

        max_maturity = float(payload.get("max_maturity", 30.0))
        min_maturity = float(payload.get("min_maturity", 0.083))
        points = int(payload.get("points", 250))
        maturities = np.linspace(min_maturity, max_maturity, max(50, min(points, 1000)))

        # Inputs already in percent units; output stays in percent.
        yields = NelsonSiegelModel.model_function(maturities, beta0, beta1, beta2, tau)
        return jsonify(
            {
                "maturities": maturities.tolist(),
                "yields": [float(y) for y in yields],
            }
        )

    @app.get("/api/snapshot")
    def snapshot() -> Any:
        """Return latest available yield curve and its NS fit for a bond type."""
        bond_type = request.args.get("bond_type", "treasury").lower()
        try:
            data_manager = app.config["DATA_MANAGER"]
            if bond_type == "tips":
                data = data_manager.get_tips_data()
            else:
                data = data_manager.get_treasury_data()
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Could not load data: {exc}"}), 502

        if data is None or data.empty:
            return jsonify({"error": "No data available."}), 404

        last_row = data.dropna(how="all").iloc[-1].dropna()
        if len(last_row) < 4:
            return jsonify({"error": "Not enough maturities in latest snapshot."}), 422

        maturities = np.array(last_row.index.tolist(), dtype=float)
        yields = last_row.values.astype(float)

        model = _model_for(bond_type)
        model.fit(maturities, yields)
        fitted = model.predict(maturities)
        smooth_x = _smooth_grid(maturities.min(), maturities.max())
        smooth_y = model.predict(smooth_x)

        return jsonify(
            {
                "bond_type": bond_type,
                "as_of": pd.Timestamp(last_row.name).strftime("%Y-%m-%d"),
                "maturities": maturities.tolist(),
                "observed": _to_pct(yields),
                "fitted": _to_pct(fitted),
                "factors": _factors_in_percent(model.get_factors()),
                "smooth": {
                    "maturities": smooth_x.tolist(),
                    "yields": _to_pct(smooth_y),
                    "forward": _to_pct(model.forward_rate(smooth_x)),
                },
                "rmse_bps": float(np.sqrt(np.mean((yields - fitted) ** 2)) * 10000.0),
                "is_synthetic": not app.config["FRED_KEY_PRESENT"],
            }
        )

    @app.get("/api/historical")
    def historical_factors() -> Any:
        """Return historical Nelson-Siegel factor time series."""
        bond_type = request.args.get("bond_type", "treasury").lower()
        start_date = request.args.get("start")
        end_date = request.args.get("end")

        if bond_type not in {"treasury", "tips"}:
            return jsonify({"error": "bond_type must be 'treasury' or 'tips'."}), 400

        try:
            factors = _get_cached_factors(
                bond_type=bond_type,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 422

        # Down-sample if very long for chart performance
        if len(factors) > 1500:
            step = max(1, len(factors) // 1500)
            factors = factors.iloc[::step]

        # Level/Slope/Curvature are decimals; multiply by 100 to display as %.
        level = (factors["Level"].astype(float) * 100.0)
        slope = (factors["Slope"].astype(float) * 100.0)
        curvature = (factors["Curvature"].astype(float) * 100.0)
        tau = factors["Tau"].astype(float)
        if "RMSE" in factors.columns:
            rmse_bps = factors["RMSE"].astype(float) * 10000.0
        else:
            rmse_bps = pd.Series(np.nan, index=factors.index)
        return jsonify(
            {
                "bond_type": bond_type,
                "dates": [d.strftime("%Y-%m-%d") for d in factors.index],
                "level": level.tolist(),
                "slope": slope.tolist(),
                "curvature": curvature.tolist(),
                "tau": tau.tolist(),
                "rmse_bps": [None if np.isnan(v) else float(v) for v in rmse_bps],
                "is_synthetic": not app.config["FRED_KEY_PRESENT"],
                "summary": {
                    "n_observations": int(len(factors)),
                    "start": factors.index[0].strftime("%Y-%m-%d"),
                    "end": factors.index[-1].strftime("%Y-%m-%d"),
                    "level_mean": float(level.mean()),
                    "slope_mean": float(slope.mean()),
                    "curvature_mean": float(curvature.mean()),
                    "tau": float(tau.iloc[0]),
                    "rmse_bps_mean": None if rmse_bps.isna().all() else float(rmse_bps.mean()),
                },
            }
        )

    @app.get("/api/compare")
    def compare() -> Any:
        """Compare Treasury vs TIPS factor histories on common dates."""
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        try:
            treasury_factors = _get_cached_factors("treasury", start_date, end_date)
            tips_factors = _get_cached_factors("tips", start_date, end_date)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 422

        common_dates = treasury_factors.index.intersection(tips_factors.index)
        if len(common_dates) == 0:
            return jsonify({"error": "No common dates found between Treasury and TIPS data"}), 422

        treasury = treasury_factors.loc[common_dates].copy()
        tips = tips_factors.loc[common_dates].copy()
        for col in ("Level", "Slope", "Curvature"):
            treasury[col] = treasury[col] * 100.0
            tips[col] = tips[col] * 100.0
        # Breakeven inflation (in %) = treasury level - tips level
        breakeven = (treasury["Level"] - tips["Level"]).astype(float)
        # Tau is constant under the closed-form historical fit (one tau per
        # bond type), so its correlation is undefined; skip it.
        correlations: Dict[str, float] = {}
        for factor in ("Level", "Slope", "Curvature"):
            if factor in treasury.columns and factor in tips.columns:
                value = float(treasury[factor].corr(tips[factor]))
                if not np.isnan(value):
                    correlations[factor] = value

        total_observations = int(len(common_dates))
        if len(treasury) > 1500:
            step = max(1, len(treasury) // 1500)
            treasury = treasury.iloc[::step]
            tips = tips.iloc[::step]
            breakeven = breakeven.iloc[::step]

        return jsonify(
            {
                "dates": [d.strftime("%Y-%m-%d") for d in treasury.index],
                "treasury_level": treasury["Level"].astype(float).tolist(),
                "tips_level": tips["Level"].astype(float).tolist(),
                "treasury_slope": treasury["Slope"].astype(float).tolist(),
                "tips_slope": tips["Slope"].astype(float).tolist(),
                "breakeven": breakeven.tolist(),
                "correlations": correlations,
                "summary": {
                    "total_observations": total_observations,
                    "date_range": {
                        "start": common_dates[0].strftime("%Y-%m-%d"),
                        "end": common_dates[-1].strftime("%Y-%m-%d"),
                    },
                },
                "is_synthetic": not app.config["FRED_KEY_PRESENT"],
            }
        )

    @app.errorhandler(404)
    def not_found(_e: Any) -> Any:
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e: Any) -> Any:
        return jsonify({"error": f"Server error: {e}"}), 500

    return app


def run_app(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Start the Flask development server."""
    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_app(debug=True)

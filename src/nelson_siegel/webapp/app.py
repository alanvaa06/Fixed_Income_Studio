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
GET  /api/models             List available curve models and their factors
GET  /api/forecast           Diebold-Li factor and curve forecast (AR/VAR/random walk)
GET  /api/backtest           Out-of-sample RMSE of the three forecasters vs realised factors
GET  /api/health             Health check
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file

from ..analysis import YieldCurveAnalyzer
from ..dynamic import METHODS, DynamicNelsonSiegel, backtest
from ..model import NelsonSiegelModel, SvenssonModel, get_model_class, list_models, make_model
from ._factors_cache import FactorsCache
from .warmup import cancel_warmup, start_warmup


PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def _local_plotly_path() -> Optional[str]:
    """Path to plotly.min.js bundled with the optional ``plotly`` package, if installed.

    Lets the Studio render charts without internet access (the CDN is the
    default; the local copy is used automatically when available).
    """
    try:
        import plotly  # type: ignore
    except ImportError:
        return None
    path = os.path.join(os.path.dirname(plotly.__file__), "package_data", "plotly.min.js")
    return path if os.path.exists(path) else None


def _model_for(bond_type: str, model_id: Optional[str] = None) -> NelsonSiegelModel:
    """Instantiate the requested model with the bond-type preset (raises ValueError)."""
    return make_model(model_id or "nelson-siegel", (bond_type or "treasury").lower())


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


def _factor_payload(model: NelsonSiegelModel) -> Dict[str, Any]:
    """Generic factor payload: rates in percent, decays in years, plus metadata."""
    params = model.parameters or {}
    factor_list = []
    factors: Dict[str, float] = {}
    for meta in model.factor_meta():
        raw = float(params[meta.key])
        value = raw * 100.0 if meta.unit == "rate" else raw
        factors[meta.label] = value
        entry = meta._asdict()
        entry["value"] = value
        factor_list.append(entry)
    return {
        "model": model.model_id,
        "model_name": model.display_name,
        "factors": factors,
        "factor_list": factor_list,
    }


def _factors_in_percent(factors: Dict[str, float]) -> Dict[str, float]:
    """Backward-compatible helper: Level/Slope/Curvature to percent, Tau in years."""
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

    def _cache_key(
        bond_type: str, start_date: Optional[str], end_date: Optional[str], model_id: str
    ) -> tuple:
        return (
            bond_type.lower(),
            start_date or "",
            end_date or "",
            "auto_weekly_over_1y",
            bool(app.config["FRED_KEY_PRESENT"]),
            model_id,
        )

    def _get_cached_factors(
        bond_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
        model_id: str = "nelson-siegel",
    ) -> pd.DataFrame:
        cache: FactorsCache = app.config["FACTORS_CACHE"]
        key = _cache_key(bond_type, start_date, end_date, model_id)

        def _compute() -> pd.DataFrame:
            analyzer = app.config["ANALYZER"]
            return analyzer.analyze_historical_factors(
                bond_type=bond_type,
                start_date=start_date,
                end_date=end_date,
                model=model_id,
            )

        return cache.get_or_compute(key, _compute)

    def _factor_series(factors: pd.DataFrame, model_cls: type) -> Dict[str, Any]:
        """Generic per-factor series: rates in percent, decays in years."""
        series: Dict[str, List[float]] = {}
        meta = []
        for m in model_cls.factor_meta():
            if m.label not in factors.columns:
                continue
            scale = 100.0 if m.unit == "rate" else 1.0
            series[m.label] = (factors[m.label].astype(float) * scale).tolist()
            meta.append(m._asdict())
        return {"series": series, "factor_meta": meta}

    def _parse_model(default: str = "nelson-siegel") -> type:
        return get_model_class(request.args.get("model") or default)

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

    app.config["PLOTLY_LOCAL_PATH"] = _local_plotly_path()

    @app.get("/")
    def index() -> str:
        plotly_src = (
            "/static/vendor/plotly.min.js" if app.config["PLOTLY_LOCAL_PATH"] else PLOTLY_CDN_URL
        )
        return render_template(
            "index.html",
            fred_key_present=app.config["FRED_KEY_PRESENT"],
            plotly_src=plotly_src,
        )

    @app.get("/static/vendor/plotly.min.js")
    def plotly_js() -> Any:
        """Serve the locally installed plotly.js when the ``plotly`` package is present."""
        path = app.config["PLOTLY_LOCAL_PATH"]
        if not path:
            return jsonify({"error": "plotly package not installed; use the CDN."}), 404
        return send_file(path, mimetype="application/javascript", max_age=86400)

    @app.get("/api/health")
    def health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "fred_api_key": app.config["FRED_KEY_PRESENT"],
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )

    @app.get("/api/models")
    def models() -> Any:
        """List the registered curve models with their factor metadata."""
        return jsonify({"models": list_models()})

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
        model_id = payload.get("model") or "nelson-siegel"
        points = payload.get("points") or []
        yield_unit = (payload.get("yield_unit") or "percent").lower()

        try:
            maturities = np.array([float(p["maturity"]) for p in points], dtype=float)
            yields = np.array([float(p["yield"]) for p in points], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": f"Invalid input data: {exc}"}), 400

        if yield_unit == "percent":
            yields = yields / 100.0

        try:
            model = _model_for(bond_type, model_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if len(maturities) < model.n_params:
            return (
                jsonify(
                    {
                        "error": (
                            f"At least {model.n_params} (maturity, yield) points are required "
                            f"for the {model.display_name} model."
                        )
                    }
                ),
                400,
            )

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
                **_factor_payload(model),
                "maturities": maturities.tolist(),
                "observed": _to_pct(yields),
                "fitted": _to_pct(fitted),
                "deviations_bps": [float(d) * 10000.0 for d in deviations],
                "rmse_bps": rmse * 10000.0,
                "n_points": int(len(maturities)),
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

        # Inputs already in percent units; output stays in percent. Supplying
        # beta3 and tau2 evaluates the Svensson extension instead.
        if "beta3" in payload or "tau2" in payload:
            try:
                beta3 = float(payload.get("beta3", 0.0))
                tau2 = float(payload.get("tau2"))
            except (TypeError, ValueError):
                return jsonify({"error": "beta3 and tau2 are required for Svensson."}), 400
            if tau2 <= 0:
                return jsonify({"error": "tau2 must be strictly positive."}), 400
            yields = SvenssonModel.model_function(maturities, beta0, beta1, beta2, beta3, tau, tau2)
        else:
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
        model_id = request.args.get("model") or "nelson-siegel"
        try:
            model = _model_for(bond_type, model_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
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
        if len(last_row) < model.n_params:
            return (
                jsonify(
                    {
                        "error": (
                            f"Latest snapshot has {len(last_row)} maturities; the "
                            f"{model.display_name} model needs {model.n_params}."
                        )
                    }
                ),
                422,
            )

        maturities = np.array(last_row.index.tolist(), dtype=float)
        yields = last_row.values.astype(float)
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
                **_factor_payload(model),
                "r_squared": _json_float(model.fit_stats().get("r_squared")),
                "decay_at_bound": bool(model.fit_stats().get("decay_at_bound", False)),
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
            model_cls = _parse_model()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            factors = _get_cached_factors(
                bond_type=bond_type,
                start_date=start_date,
                end_date=end_date,
                model_id=model_cls.model_id,
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
        decay_cols = [m.label for m in model_cls.factor_meta() if m.unit == "years"]
        return jsonify(
            {
                "bond_type": bond_type,
                "model": model_cls.model_id,
                "model_name": model_cls.display_name,
                "dates": [d.strftime("%Y-%m-%d") for d in factors.index],
                "level": level.tolist(),
                "slope": slope.tolist(),
                "curvature": curvature.tolist(),
                "tau": tau.tolist(),
                **_factor_series(factors, model_cls),
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
                    "decays": {c: float(factors[c].iloc[0]) for c in decay_cols},
                    "rmse_bps_mean": None if rmse_bps.isna().all() else float(rmse_bps.mean()),
                },
            }
        )

    @app.get("/api/forecast")
    def forecast() -> Any:
        """Diebold-Li dynamic forecast of the factor history and the implied curve."""
        bond_type = request.args.get("bond_type", "treasury").lower()
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        method = (request.args.get("method") or "ar").lower()
        if bond_type not in {"treasury", "tips"}:
            return jsonify({"error": "bond_type must be 'treasury' or 'tips'."}), 400
        if method not in METHODS:
            return jsonify({"error": f"method must be one of {', '.join(METHODS)}."}), 400
        try:
            horizon = int(request.args.get("horizon", 12))
        except ValueError:
            return jsonify({"error": "horizon must be an integer."}), 400
        if not 1 <= horizon <= 520:
            return jsonify({"error": "horizon must be between 1 and 520 steps."}), 400
        try:
            model_cls = _parse_model()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            factors = _get_cached_factors(bond_type, start_date, end_date, model_cls.model_id)
            analyzer = app.config["ANALYZER"]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                result = analyzer.forecast_factors(
                    bond_type, horizon=horizon, method=method, start_date=start_date,
                    end_date=end_date, factors=factors, model=model_cls.model_id,
                )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 422

        fc = result["forecast"]
        dns: DynamicNelsonSiegel = result["model"]
        maturities = result["maturities"]
        smooth_x = _smooth_grid(min(maturities), max(maturities))
        current_smooth = dns.current_curve(smooth_x)
        horizon_smooth = dns.factors_to_yields(fc[dns.factor_names_].to_numpy()[-1], smooth_x)[0]

        def series(name: str) -> List[float]:
            return [float(v) * 100.0 for v in fc[name]]

        summary = result["summary"]
        rate_labels = list(dns.factor_names_)
        return jsonify(
            {
                "bond_type": bond_type,
                "model": model_cls.model_id,
                "model_name": model_cls.display_name,
                "method": method,
                "horizon": horizon,
                "factor_names": rate_labels,
                "series": {name: series(name) for name in rate_labels},
                "series_std": {name: series(f"{name}_std") for name in rate_labels},
                "dates": [d.strftime("%Y-%m-%d") for d in fc.index],
                "level": series("Level"),
                "slope": series("Slope"),
                "curvature": series("Curvature"),
                "level_std": series("Level_std"),
                "slope_std": series("Slope_std"),
                "curvature_std": series("Curvature_std"),
                "maturities": maturities,
                "current_curve": _to_pct(result["current_curve"]),
                "forecast_curve": _to_pct(result["curves"].iloc[-1].to_numpy()),
                "smooth": {
                    "maturities": smooth_x.tolist(),
                    "current": _to_pct(current_smooth),
                    "forecast": _to_pct(horizon_smooth),
                },
                "summary": {
                    **summary,
                    "unconditional_mean": (
                        {k: v * 100.0 for k, v in summary["unconditional_mean"].items()}
                        if summary["unconditional_mean"] else None
                    ),
                    "residual_std_bps": {k: v * 10000.0 for k, v in summary["residual_std"].items()},
                    "history_start": factors.index[0].strftime("%Y-%m-%d"),
                },
                "is_synthetic": not app.config["FRED_KEY_PRESENT"],
            }
        )

    @app.get("/api/backtest")
    def backtest_endpoint() -> Any:
        """Rolling-origin RMSE of random walk vs AR(1) vs VAR(1) factor forecasts."""
        bond_type = request.args.get("bond_type", "treasury").lower()
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        if bond_type not in {"treasury", "tips"}:
            return jsonify({"error": "bond_type must be 'treasury' or 'tips'."}), 400
        try:
            horizons = tuple(int(h) for h in (request.args.get("horizons") or "1,4,12").split(","))
            min_train = int(request.args.get("min_train", 52))
        except ValueError:
            return jsonify({"error": "horizons must be comma-separated integers."}), 400
        if any(h < 1 for h in horizons) or len(horizons) > 6:
            return jsonify({"error": "Provide 1-6 positive horizons."}), 400
        try:
            model_cls = _parse_model()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            factors = _get_cached_factors(bond_type, start_date, end_date, model_cls.model_id)
            data_manager = app.config["DATA_MANAGER"]
            data = (
                data_manager.get_treasury_data(start_date, end_date)
                if bond_type == "treasury"
                else data_manager.get_tips_data(start_date, end_date)
            )
            maturities = [float(m) for m in data.columns]
            table = backtest(
                factors, horizons=horizons, min_train=min_train, maturities=maturities,
                model_cls=model_cls,
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 422

        rate_labels = [m.label for m in model_cls.factor_meta() if m.unit == "rate"]
        rows = []
        for (method, horizon), row in table.iterrows():
            rows.append(
                {
                    "method": method,
                    "horizon": int(horizon),
                    "n_forecasts": int(row["n_forecasts"]),
                    "level_rmse_bps": float(row["Level_rmse"]) * 10000.0,
                    "slope_rmse_bps": float(row["Slope_rmse"]) * 10000.0,
                    "curvature_rmse_bps": float(row["Curvature_rmse"]) * 10000.0,
                    "factor_rmse_bps": {
                        name: float(row[f"{name}_rmse"]) * 10000.0 for name in rate_labels
                    },
                    "yield_rmse_bps": float(row["yield_rmse"]) * 10000.0,
                }
            )
        return jsonify(
            {
                "bond_type": bond_type,
                "model": model_cls.model_id,
                "horizons": list(horizons),
                "min_train": min_train,
                "rows": rows,
                "n_observations": int(len(factors)),
                "is_synthetic": not app.config["FRED_KEY_PRESENT"],
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

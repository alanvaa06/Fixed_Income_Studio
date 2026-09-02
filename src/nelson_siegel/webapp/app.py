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
GET  /api/health             Health check and data-source provenance
GET  /api/data-sources       Which source served each dataset (FRED, treasury.gov, GSW, synthetic)
GET  /api/short-rate         Vasicek/CIR: physical estimate, calibration, simulation fan, term premium
GET  /api/term-premium       ACM affine term premia, Diebold-Li EH split, Campbell-Shiller / Fama-Bliss
GET  /api/analytics          Carry & roll-down, forwards, spreads, rich/cheap, curve changes, PCA
POST /api/bond               Price and risk a bond off the fitted curve (duration, convexity, KRDs)
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
from ..analytics import Bond
from ..data import SOURCE_LABELS, SOURCE_SYNTHETIC
from ..dynamic import METHODS, DynamicNelsonSiegel, backtest
from ..model import NelsonSiegelModel, SvenssonModel, get_model_class
from ..registry import AnyCurveModel, get_any_model_class, list_all_models, make_any_model
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


def _model_for(bond_type: str, model_id: Optional[str] = None) -> AnyCurveModel:
    """Instantiate the requested model (any family) with the bond-type preset (raises ValueError)."""
    return make_any_model(model_id or "nelson-siegel", (bond_type or "treasury").lower())


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


def _factor_payload(model: AnyCurveModel) -> Dict[str, Any]:
    """Generic factor payload: rates in percent, decays in years, other units raw."""
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
        "family": getattr(model, "family", "parametric"),
        "factors": factors,
        "factor_list": factor_list,
    }


def _series_pct(values: Any) -> List[Optional[float]]:
    return [_json_float(v * 100.0) if v is not None and not np.isnan(v) else None for v in np.asarray(values, dtype=float)]


def _dates(index: Any) -> List[str]:
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in index]


def _mkey(value: Any) -> str:
    """Stable JSON key for a maturity: 2.0 -> "2", 0.25 -> "0.25" (matches JS String())."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _frame_pct(frame: pd.DataFrame) -> Dict[str, List[Optional[float]]]:
    """Columns of a decimal-rate frame as percent lists keyed by column name (maturities via _mkey)."""
    return {
        (_mkey(c) if isinstance(c, (int, float)) else str(c)): _series_pct(frame[c].to_numpy())
        for c in frame.columns
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
    # Keep dict order in responses (maturity/columns order matters to the UI).
    app.json.sort_keys = False

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

    def _source_info() -> Dict[str, Any]:
        """Provenance of the data behind the current response."""
        dm = app.config["DATA_MANAGER"]
        summary = dm.source_summary()
        return {
            "is_synthetic": dm.is_synthetic,
            "sources": {k: (SOURCE_LABELS.get(v, v) if v else None) for k, v in summary.items()},
            "source_ids": summary,
            "public_sources": bool(dm.public_sources),
            "fred_api_key": bool(app.config["FRED_KEY_PRESENT"]),
        }

    def _cached_result(key: tuple, compute: Any) -> Dict[str, Any]:
        cache: FactorsCache = app.config["RESULT_CACHE"]
        return cache.get_or_compute(key, compute)

    def _window_key(*parts: Any) -> tuple:
        return tuple(parts) + (bool(app.config["FRED_KEY_PRESENT"]),)

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
        app.config["RESULT_CACHE"] = FactorsCache()
        if enable_warmup:
            start_warmup(app, _get_cached_factors, years=warmup_years)

    configure_data_source(fred_api_key or os.environ.get("FRED_API_KEY"))

    app.config["PLOTLY_LOCAL_PATH"] = _local_plotly_path()

    @app.get("/")
    def index() -> str:
        plotly_src = (
            "/static/vendor/plotly.min.js" if app.config["PLOTLY_LOCAL_PATH"] else PLOTLY_CDN_URL
        )
        from .. import __version__

        return render_template(
            "index.html",
            fred_key_present=app.config["FRED_KEY_PRESENT"],
            plotly_src=plotly_src,
            version=__version__,
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
                "version": __import__("nelson_siegel").__version__,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                **_source_info(),
            }
        )

    @app.get("/api/data-sources")
    def data_sources() -> Any:
        """Which source served each dataset so far, plus the available chain."""
        info = _source_info()
        info["chain"] = [
            {"id": "fred-api", "label": SOURCE_LABELS["fred-api"], "needs_key": True},
            {"id": "treasury.gov", "label": SOURCE_LABELS["treasury.gov"], "needs_key": False},
            {"id": "fred-public-csv", "label": SOURCE_LABELS["fred-public-csv"], "needs_key": False},
            {"id": "fed-gsw", "label": SOURCE_LABELS["fed-gsw"], "needs_key": False},
            {"id": SOURCE_SYNTHETIC, "label": SOURCE_LABELS[SOURCE_SYNTHETIC], "needs_key": False},
        ]
        return jsonify(info)

    @app.get("/api/models")
    def models() -> Any:
        """List the registered curve models (parametric and short-rate) with factor metadata."""
        return jsonify({"models": list_all_models()})

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

        min_points = int(model.describe()["min_points"])
        if len(maturities) < min_points:
            return (
                jsonify(
                    {
                        "error": (
                            f"At least {min_points} (maturity, yield) points are required "
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
                "discount_factors": [float(v) for v in model.discount_factor(maturities)],
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
        min_points = int(model.describe()["min_points"])
        if len(last_row) < min_points:
            return (
                jsonify(
                    {
                        "error": (
                            f"Latest snapshot has {len(last_row)} maturities; the "
                            f"{model.display_name} model needs {min_points}."
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
                **_source_info(),
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
                **_source_info(),
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
                **_source_info(),
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
                **_source_info(),
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
                **_source_info(),
            }
        )


    # ------------------------------------------------------------------ #
    # Short-rate models
    # ------------------------------------------------------------------ #
    @app.get("/api/short-rate")
    def short_rate() -> Any:
        """Vasicek / CIR study: physical estimate, curve calibration, simulation fan, term premium."""
        bond_type = request.args.get("bond_type", "treasury").lower()
        model_id = (request.args.get("model") or "vasicek").lower()
        method = (request.args.get("method") or "ols").lower()
        proxy = (request.args.get("proxy") or "policy").lower()
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        if bond_type not in {"treasury", "tips"}:
            return jsonify({"error": "bond_type must be 'treasury' or 'tips'."}), 400
        if model_id not in {"vasicek", "cir"}:
            return jsonify({"error": "model must be 'vasicek' or 'cir'."}), 400
        if method not in {"ols", "mle"}:
            return jsonify({"error": "method must be 'ols' or 'mle'."}), 400
        if proxy not in YieldCurveAnalyzer.SHORT_RATE_PROXIES:
            return jsonify({"error": f"proxy must be one of {', '.join(YieldCurveAnalyzer.SHORT_RATE_PROXIES)}."}), 400
        try:
            horizon = float(request.args.get("horizon", 5))
            n_paths = int(request.args.get("paths", 200))
        except ValueError:
            return jsonify({"error": "horizon and paths must be numeric."}), 400
        if not 0.5 <= horizon <= 30 or not 10 <= n_paths <= 2000:
            return jsonify({"error": "horizon must be 0.5-30 years and paths 10-2000."}), 400

        def _compute() -> Dict[str, Any]:
            analyzer: YieldCurveAnalyzer = app.config["ANALYZER"]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                r = analyzer.short_rate_analysis(
                    bond_type=bond_type, model=model_id, method=method, proxy=proxy,
                    start_date=start_date, end_date=end_date, horizon_years=horizon, n_paths=n_paths,
                )
            est = r["estimate"]
            q = r["quantiles"]
            tp = r["term_premium"]
            hist = r["history"]
            return {
                "bond_type": bond_type,
                "model": r["model"],
                "model_name": r["model_name"],
                "method": method,
                "proxy": r["proxy"],
                "as_of": pd.Timestamp(r["as_of"]).strftime("%Y-%m-%d"),
                "estimate": {
                    **{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in est.as_dict().items()},
                    "kappa": est.kappa,
                    "theta_pct": est.theta * 100.0,
                    "sigma_pct": est.sigma * 100.0,
                    "r0_pct": est.r0 * 100.0,
                    "half_life_years": est.half_life_years,
                    "steps_per_year": 1.0 / est.dt if est.dt else None,
                },
                "calibrated": {
                    **_factor_payload(r["calibrated"]),
                    "rmse_bps": float(r["calibrated"].fit_stats()["rmse"]) * 10000.0,
                    "r_squared": _json_float(r["calibrated"].fit_stats().get("r_squared")),
                    "half_life_years": r["calibrated"].half_life(),
                },
                "history": {"dates": _dates(hist.index), "values": _series_pct(hist.to_numpy())},
                "maturities": [float(m) for m in r["maturities"]],
                "observed": _to_pct(r["observed"]),
                "fitted": _to_pct(r["fitted"]),
                "smooth": {
                    "maturities": [float(m) for m in r["smooth"]["maturities"]],
                    "fitted": _to_pct(r["smooth"]["fitted"]),
                    "forward": _to_pct(r["smooth"]["forward"]),
                    "expectations": _to_pct(r["smooth"]["expectations"]),
                },
                "paths": {
                    "horizons": [float(h) for h in r["horizons"]],
                    "expected_physical": _to_pct(r["expected_physical"]),
                    "expected_risk_neutral": _to_pct(r["expected_risk_neutral"]),
                    **{c: _series_pct(q[c].to_numpy()) for c in q.columns},
                },
                "term_premium": {
                    "maturities": [float(m) for m in tp.index],
                    "observed": _to_pct(tp["observed"].to_numpy()),
                    "expected_short_rate": _to_pct(tp["expected_short_rate"].to_numpy()),
                    "term_premium_bps": [float(v) * 10000.0 for v in tp["term_premium"].to_numpy()],
                },
                **_source_info(),
            }

        try:
            key = _window_key("short-rate", bond_type, model_id, method, proxy, start_date or "", end_date or "", horizon, n_paths)
            return jsonify(_cached_result(key, _compute))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Short-rate analysis failed: {exc}"}), 422

    # ------------------------------------------------------------------ #
    # Term premium
    # ------------------------------------------------------------------ #
    @app.get("/api/term-premium")
    def term_premium() -> Any:
        """ACM term premia, the Diebold-Li expectations split and EH regressions."""
        source = (request.args.get("source") or "gsw").lower()
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        dns_method = (request.args.get("dns_method") or "var").lower()
        if source not in YieldCurveAnalyzer.TERM_PREMIUM_SOURCES:
            return jsonify({"error": f"source must be one of {', '.join(YieldCurveAnalyzer.TERM_PREMIUM_SOURCES)}."}), 400
        if dns_method not in METHODS:
            return jsonify({"error": f"dns_method must be one of {', '.join(METHODS)}."}), 400
        try:
            maturities = [float(m) for m in (request.args.get("maturities") or "2,5,10").split(",")]
            n_factors = int(request.args.get("factors", 3))
            max_maturity = float(request.args.get("max_maturity", 10))
        except ValueError:
            return jsonify({"error": "maturities must be comma-separated numbers; factors an integer."}), 400
        if not 1 <= n_factors <= 5:
            return jsonify({"error": "factors must be between 1 and 5."}), 400
        if not 2 <= max_maturity <= 30 or any(m <= 0 or m > max_maturity for m in maturities) or len(maturities) > 6:
            return jsonify({"error": "Provide 1-6 maturities within (0, max_maturity]; max_maturity 2-30."}), 400

        def _compute() -> Dict[str, Any]:
            analyzer: YieldCurveAnalyzer = app.config["ANALYZER"]
            r = analyzer.term_premium_analysis(
                source=source, start_date=start_date, end_date=end_date, maturities=maturities,
                n_factors=n_factors, max_maturity_years=max_maturity, dns_method=dns_method,
            )
            decomposition = {}
            for m, frame in r["decomposition"].items():
                decomposition[_mkey(m)] = {"dates": _dates(frame.index), **_frame_pct(frame)}
            dns_block = None
            if r["dns"] is not None:
                d = r["dns"]
                dns_block = {
                    "dates": _dates(d["fitted"].index),
                    "fitted": _frame_pct(d["fitted"]),
                    "expected_short_rate": _frame_pct(d["expected_short_rate"]),
                    "term_premium": _frame_pct(d["term_premium"]),
                    "summary": r["dns_summary"],
                }
            tp = r["term_premium"]
            latest = {_mkey(m): float(tp[m].iloc[-1]) * 100.0 for m in tp.columns}
            regressions = {
                name: {_mkey(m): vals for m, vals in table.items()} for name, table in r["regressions"].items()
            }
            return {
                "source": r["source"],
                "maturities": r["maturities"],
                "summary": r["summary"],
                "term_premium": {"dates": _dates(tp.index), **_frame_pct(tp)},
                "latest_term_premium": latest,
                "decomposition": decomposition,
                "dns": dns_block,
                "regressions": regressions,
                **_source_info(),
            }

        try:
            key = _window_key("term-premium", source, start_date or "", end_date or "", tuple(maturities), n_factors, max_maturity, dns_method)
            return jsonify(_cached_result(key, _compute))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Term premium analysis failed: {exc}"}), 422

    # ------------------------------------------------------------------ #
    # Curve analytics and bond calculator
    # ------------------------------------------------------------------ #
    @app.get("/api/analytics")
    def analytics() -> Any:
        """Carry & roll-down, forwards, spreads, rich/cheap, curve changes and PCA for the latest curve."""
        bond_type = request.args.get("bond_type", "treasury").lower()
        model_id = request.args.get("model") or "nelson-siegel"
        if bond_type not in {"treasury", "tips"}:
            return jsonify({"error": "bond_type must be 'treasury' or 'tips'."}), 400
        try:
            get_any_model_class(model_id)
            horizon = float(request.args.get("horizon", 1.0))
            lookback = int(request.args.get("lookback", 365))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not 0.05 <= horizon <= 10 or not 30 <= lookback <= 3650:
            return jsonify({"error": "horizon must be 0.05-10 years, lookback 30-3650 days."}), 400

        def _compute() -> Dict[str, Any]:
            analyzer: YieldCurveAnalyzer = app.config["ANALYZER"]
            r = analyzer.curve_analytics(bond_type=bond_type, model=model_id, horizon=horizon, lookback_days=lookback)
            cr = r["carry_roll_down"]
            fw = r["forwards"]
            rc = r["rich_cheap"]
            ch = r["changes"]
            sh = r["spread_history"]
            pca = r["pca"]
            return {
                "bond_type": bond_type,
                "model": r["model"],
                "as_of": pd.Timestamp(r["as_of"]).strftime("%Y-%m-%d"),
                "horizon": horizon,
                "maturities": [float(m) for m in r["maturities"]],
                "observed": _to_pct(r["observed"]),
                **{k: v for k, v in _factor_payload(r["curve"]).items() if k in {"factors", "factor_list", "model_name", "family"}},
                "carry_roll_down": {
                    "maturities": [float(m) for m in cr.index],
                    "yield": _to_pct(cr["yield"].to_numpy()),
                    "horizon_yield": _to_pct(cr["horizon_yield"].to_numpy()),
                    "forward_yield": _to_pct(cr["forward_yield"].to_numpy()),
                    "carry_bps": [float(v) for v in cr["carry_bps"]],
                    "roll_down_bps": [float(v) for v in cr["roll_down_bps"]],
                    "total_bps": [float(v) for v in cr["total_bps"]],
                },
                "forwards": [
                    {
                        "label": str(label),
                        "start": float(row["start"]),
                        "tenor": float(row["tenor"]),
                        "forward": float(row["forward"]) * 100.0,
                        "spot_to_end": float(row["spot_to_end"]) * 100.0,
                        "spread_vs_spot_bps": float(row["spread_vs_spot_bps"]),
                    }
                    for label, row in fw.iterrows()
                ],
                "spreads": {str(k): float(v) for k, v in r["spreads"].items()},
                "spread_history": {"dates": _dates(sh.index), **{str(c): [_json_float(v) for v in sh[c]] for c in sh.columns}},
                "rich_cheap": [
                    {
                        "maturity": float(m),
                        "observed": float(row["observed"]) * 100.0,
                        "fitted": float(row["fitted"]) * 100.0,
                        "residual_bps": float(row["residual_bps"]),
                        "z": _json_float(row["z"]),
                        "verdict": str(row["verdict"]),
                        "rank": int(row["rank"]),
                    }
                    for m, row in rc.iterrows()
                ],
                "changes": {
                    "as_of": pd.Timestamp(ch.attrs["as_of"]).strftime("%Y-%m-%d"),
                    "maturities": [float(m) for m in ch.index],
                    "yield": _to_pct(ch["yield"].to_numpy()),
                    **{c: [_json_float(v) for v in ch[c]] for c in ch.columns if c.startswith("chg_")},
                },
                "pca": None if pca is None else {
                    "components": [str(c) for c in pca["loadings"].columns],
                    "explained_variance": pca["explained_variance"],
                    "maturities": [float(m) for m in pca["loadings"].index],
                    "loadings": {str(c): [float(v) for v in pca["loadings"][c]] for c in pca["loadings"].columns},
                    "n_obs": pca["n_obs"],
                },
                **_source_info(),
            }

        try:
            key = _window_key("analytics", bond_type, model_id, horizon, lookback, pd.Timestamp.today().strftime("%Y-%m-%d"))
            return jsonify(_cached_result(key, _compute))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Curve analytics failed: {exc}"}), 422

    @app.post("/api/bond")
    def bond_calculator() -> Any:
        """Price and risk a fixed-coupon bond off the fitted curve (optionally from custom quotes)."""
        payload = request.get_json(silent=True) or {}
        bond_type = (payload.get("bond_type") or "treasury").lower()
        model_id = payload.get("model") or "nelson-siegel"
        try:
            bond = Bond(
                maturity=float(payload.get("maturity", 10)),
                coupon=float(payload.get("coupon", 0.0)) / 100.0,
                frequency=int(payload.get("frequency", 2)),
                face=float(payload.get("face", 100.0)),
            )
            price = payload.get("price")
            price = float(price) if price not in (None, "") else None
            get_any_model_class(model_id)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"Invalid bond specification: {exc}"}), 400
        if bond.maturity > 100:
            return jsonify({"error": "maturity must be at most 100 years."}), 400
        maturities = yields = None
        points = payload.get("points")
        if points:
            try:
                maturities = [float(p["maturity"]) for p in points]
                yields = [float(p["yield"]) / 100.0 for p in points]
            except (KeyError, TypeError, ValueError) as exc:
                return jsonify({"error": f"Invalid points: {exc}"}), 400
        try:
            analyzer: YieldCurveAnalyzer = app.config["ANALYZER"]
            r = analyzer.bond_analytics(bond, bond_type=bond_type, model=model_id, price=price, maturities=maturities, yields=yields)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        krd = r["key_rate_durations"]
        times, amounts = r["cash_flows"]
        return jsonify(
            {
                "bond": {"maturity": bond.maturity, "coupon": bond.coupon * 100.0, "frequency": bond.frequency, "face": bond.face},
                "bond_type": bond_type,
                "model": r["model"],
                "as_of": pd.Timestamp(r["as_of"]).strftime("%Y-%m-%d") if r["as_of"] is not None else None,
                "model_price": float(r["model_price"]),
                "market_price": float(r["market_price"]),
                "ytm": float(r["ytm"]) * 100.0,
                "model_ytm": float(r["model_ytm"]) * 100.0,
                "z_spread_bps": float(r["z_spread"]) * 10000.0,
                "macaulay_duration": float(r["macaulay_duration"]),
                "modified_duration": float(r["modified_duration"]),
                "convexity": float(r["convexity"]),
                "dv01": float(r["dv01"]),
                "key_rate_durations": {"tenors": [float(k) for k in krd.index], "values": [float(v) for v in krd]},
                "cash_flows": {"times": [float(t) for t in times], "amounts": [float(a) for a in amounts]},
                **_source_info(),
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

"""Tests for the Nelson-Siegel web application."""

import threading
import time
import pandas as pd

from nelson_siegel.webapp.app import create_app
from nelson_siegel.webapp.warmup import WARMUP_THREAD_KEY


def test_index_requests_fred_api_key_when_missing():
    """The UI should make it obvious where a FRED key can be entered."""
    app = create_app(enable_warmup=False)

    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="fred-api-key"' in html
    assert 'placeholder="Paste your FRED API key"' in html


def test_fred_key_endpoint_updates_runtime_data_source():
    """Submitting a key should switch the running app to FRED-backed mode."""
    app = create_app(enable_warmup=False)

    with app.test_client() as client:
        response = client.post("/api/fred-key", json={"api_key": "abc123"})
        health = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json()["fred_api_key"] is True
    assert health.get_json()["fred_api_key"] is True


def test_fred_key_endpoint_rejects_blank_keys():
    """Blank submissions should not overwrite the current data source."""
    app = create_app(enable_warmup=False)

    with app.test_client() as client:
        response = client.post("/api/fred-key", json={"api_key": "  "})

    assert response.status_code == 400
    assert response.get_json()["error"] == "FRED API key is required."


def _fake_factors_frame() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=40, freq="W-FRI")
    return pd.DataFrame(
        {
            "Level": [0.03] * len(idx),
            "Slope": [-0.01] * len(idx),
            "Curvature": [0.002] * len(idx),
            "Tau": [2.0] * len(idx),
        },
        index=idx,
    )


def test_compare_endpoint_three_year_range_returns_quickly():
    """The compare endpoint should return in interactive time for long ranges."""
    app = create_app(enable_warmup=False)

    with app.test_client() as client:
        started = time.perf_counter()
        response = client.get("/api/compare?start=2023-04-27&end=2026-04-27")
        elapsed = time.perf_counter() - started

    assert response.status_code == 200
    payload = response.get_json()
    assert elapsed < 10.0
    assert len(payload["dates"]) > 0
    assert len(payload["treasury_level"]) == len(payload["dates"])
    assert len(payload["tips_level"]) == len(payload["dates"])
    assert len(payload["breakeven"]) == len(payload["dates"])


def test_compare_endpoint_uses_cache_for_repeat_calls(monkeypatch):
    """Second compare request should be substantially faster via cache hit."""
    app = create_app(enable_warmup=False)
    analyzer = app.config["ANALYZER"]

    def fake_analyze_historical_factors(*args, **kwargs):
        time.sleep(0.2)
        return _fake_factors_frame()

    monkeypatch.setattr(analyzer, "analyze_historical_factors", fake_analyze_historical_factors)

    with app.test_client() as client:
        started = time.perf_counter()
        first = client.get("/api/compare?start=2025-01-01&end=2025-12-31")
        first_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        second = client.get("/api/compare?start=2025-01-01&end=2025-12-31")
        second_elapsed = time.perf_counter() - started

    assert first.status_code == 200
    assert second.status_code == 200
    assert second_elapsed * 5 <= first_elapsed


def test_fred_key_change_invalidates_compare_cache(monkeypatch):
    """Changing the runtime key should reset cached factor frames."""
    app = create_app(enable_warmup=False)
    calls = {"count": 0}

    def fake_analyze_historical_factors(self, *args, **kwargs):
        calls["count"] += 1
        return _fake_factors_frame()

    monkeypatch.setattr(
        "nelson_siegel.analysis.YieldCurveAnalyzer.analyze_historical_factors",
        fake_analyze_historical_factors,
    )

    with app.test_client() as client:
        first = client.get("/api/compare?start=2025-01-01&end=2025-12-31")
        second = client.get("/api/compare?start=2025-01-01&end=2025-12-31")
        set_key = client.post("/api/fred-key", json={"api_key": "new-key"})
        third = client.get("/api/compare?start=2025-01-01&end=2025-12-31")

    assert first.status_code == 200
    assert second.status_code == 200
    assert set_key.status_code == 200
    assert third.status_code == 200
    assert calls["count"] == 4


def test_warmup_populates_cache_for_recent_range(monkeypatch):
    """Background warm-up should populate the cache before user requests hit."""
    calls = {"count": 0}

    def fake(self, *args, **kwargs):
        calls["count"] += 1
        return _fake_factors_frame()

    monkeypatch.setattr(
        "nelson_siegel.analysis.YieldCurveAnalyzer.analyze_historical_factors",
        fake,
    )

    app = create_app(enable_warmup=True, warmup_years=10)
    thread = app.config[WARMUP_THREAD_KEY]
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert calls["count"] == 2  # treasury + tips, no extra calls


def test_fred_key_change_cancels_and_restarts_warmup(monkeypatch):
    """POST /api/fred-key should cancel the prior warm-up thread and start a new one."""
    block = threading.Event()
    started = threading.Event()
    proceed = threading.Event()

    def slow_fake(self, bond_type, start_date=None, end_date=None, **_):
        # First warm-up blocks until released so we can race a key change.
        if not block.is_set():
            started.set()
            proceed.wait(timeout=5.0)
        return _fake_factors_frame()

    monkeypatch.setattr(
        "nelson_siegel.analysis.YieldCurveAnalyzer.analyze_historical_factors",
        slow_fake,
    )

    app = create_app(enable_warmup=True, warmup_years=10)
    first_thread = app.config[WARMUP_THREAD_KEY]
    assert started.wait(timeout=5.0)

    with app.test_client() as client:
        block.set()
        proceed.set()
        # Trigger key change while first warm-up is still in flight.
        response = client.post("/api/fred-key", json={"api_key": "new-key"})

    second_thread = app.config[WARMUP_THREAD_KEY]
    second_thread.join(timeout=5.0)
    first_thread.join(timeout=5.0)

    assert response.status_code == 200
    assert second_thread is not first_thread
    assert not second_thread.is_alive()


def test_snapshot_shares_analyzer_data_manager():
    """Snapshot, tau estimation and history should share one memoised data source."""
    app = create_app(enable_warmup=False)
    assert app.config["DATA_MANAGER"] is app.config["ANALYZER"].data_manager

    with app.test_client() as client:
        first = client.get("/api/snapshot?bond_type=treasury")
        second = client.get("/api/snapshot?bond_type=treasury")

    assert first.status_code == 200
    payload = first.get_json()
    assert payload == second.get_json()
    assert len(payload["smooth"]["forward"]) == len(payload["smooth"]["maturities"])
    # Only one synthetic frame was generated for the default window.
    assert len(app.config["DATA_MANAGER"].treasury_downloader._cache) == 1


def test_fit_endpoint_returns_diagnostics_and_forward_curve():
    app = create_app(enable_warmup=False)
    points = [
        {"maturity": 0.25, "yield": 4.95}, {"maturity": 1, "yield": 4.65},
        {"maturity": 2, "yield": 4.30}, {"maturity": 5, "yield": 3.95},
        {"maturity": 10, "yield": 4.05}, {"maturity": 30, "yield": 4.35},
    ]
    with app.test_client() as client:
        response = client.post("/api/fit", json={"bond_type": "treasury", "points": points})

    assert response.status_code == 200
    payload = response.get_json()
    assert 0.0 <= payload["r_squared"] <= 1.0
    assert isinstance(payload["decay_at_bound"], bool)
    assert len(payload["smooth"]["forward"]) == len(payload["smooth"]["maturities"])
    assert payload["rmse_bps"] < 15.0


def test_historical_endpoint_reports_tau_and_rmse():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        response = client.get("/api/historical?bond_type=tips&start=2025-01-01&end=2025-06-30")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["rmse_bps"]) == len(payload["dates"])
    assert payload["summary"]["tau"] > 0
    assert payload["summary"]["rmse_bps_mean"] >= 0


_POINTS = [
    {"maturity": 0.25, "yield": 4.95}, {"maturity": 0.5, "yield": 4.85},
    {"maturity": 1, "yield": 4.65}, {"maturity": 2, "yield": 4.30},
    {"maturity": 3, "yield": 4.10}, {"maturity": 5, "yield": 3.95},
    {"maturity": 7, "yield": 4.00}, {"maturity": 10, "yield": 4.05},
    {"maturity": 20, "yield": 4.30}, {"maturity": 30, "yield": 4.35},
]


def test_models_endpoint_lists_registered_models():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        payload = client.get("/api/models").get_json()
    ids = [m["id"] for m in payload["models"]]
    assert ids[:2] == ["nelson-siegel", "svensson"]  # parametric family first
    assert set(ids) >= {"vasicek", "cir"}
    svensson = payload["models"][1]
    assert svensson["min_points"] == 6
    assert [f["label"] for f in svensson["factors"]] == [
        "Level", "Slope", "Curvature", "Curvature2", "Tau", "Tau2",
    ]


def test_fit_endpoint_supports_svensson_and_generic_factor_list():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        ns = client.post("/api/fit", json={"bond_type": "treasury", "points": _POINTS}).get_json()
        sv = client.post(
            "/api/fit", json={"bond_type": "treasury", "points": _POINTS, "model": "svensson"}
        ).get_json()

    assert ns["model"] == "nelson-siegel" and set(ns["factors"]) == {"Level", "Slope", "Curvature", "Tau"}
    assert sv["model"] == "svensson" and sv["model_name"] == "Svensson"
    assert [f["label"] for f in sv["factor_list"]] == [
        "Level", "Slope", "Curvature", "Curvature2", "Tau", "Tau2",
    ]
    assert all(f["unit"] in {"rate", "years"} for f in sv["factor_list"])
    assert sv["rmse_bps"] <= ns["rmse_bps"] + 1e-6  # Svensson nests Nelson-Siegel
    assert sv["n_points"] == len(_POINTS)


def test_fit_endpoint_enforces_model_minimum_points_and_unknown_model():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        short = client.post("/api/fit", json={"points": _POINTS[:5], "model": "svensson"})
        unknown = client.post("/api/fit", json={"points": _POINTS, "model": "spline"})
    assert short.status_code == 400 and "6" in short.get_json()["error"]
    assert unknown.status_code == 400 and "Unknown model" in unknown.get_json()["error"]


def test_snapshot_accepts_model_and_rejects_too_few_maturities():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        ok = client.get("/api/snapshot?bond_type=treasury&model=svensson")
        tips = client.get("/api/snapshot?bond_type=tips&model=svensson")  # only 5 maturities
    assert ok.status_code == 200 and ok.get_json()["model"] == "svensson"
    assert tips.status_code == 422


def test_curve_endpoint_evaluates_svensson_when_extra_params_given():
    app = create_app(enable_warmup=False)
    base = {"beta0": 4.0, "beta1": -2.0, "beta2": 1.0, "tau": 2.0}
    with app.test_client() as client:
        ns = client.post("/api/curve", json=base).get_json()
        sv = client.post("/api/curve", json={**base, "beta3": -1.0, "tau2": 8.0}).get_json()
        bad = client.post("/api/curve", json={**base, "beta3": -1.0, "tau2": 0})
    assert len(ns["yields"]) == len(sv["yields"])
    assert ns["yields"] != sv["yields"]
    assert bad.status_code == 400


def test_index_uses_local_plotly_when_package_installed(monkeypatch):
    from nelson_siegel.webapp import app as app_module

    app = create_app(enable_warmup=False)
    if app.config["PLOTLY_LOCAL_PATH"]:
        with app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
            js = client.get("/static/vendor/plotly.min.js")
        assert "/static/vendor/plotly.min.js" in html
        assert js.status_code == 200 and js.mimetype == "application/javascript"
    else:
        with app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
            js = client.get("/static/vendor/plotly.min.js")
        assert app_module.PLOTLY_CDN_URL in html
        assert js.status_code == 404


def test_index_falls_back_to_cdn_without_plotly_package(monkeypatch):
    from nelson_siegel.webapp import app as app_module

    monkeypatch.setattr(app_module, "_local_plotly_path", lambda: None)
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)
        js = client.get("/static/vendor/plotly.min.js")
    assert app_module.PLOTLY_CDN_URL in html
    assert js.status_code == 404


def test_forecast_endpoint_returns_paths_and_curves():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        r = client.get("/api/forecast?bond_type=treasury&start=2022-01-01&end=2025-12-31&horizon=8&method=ar")
        bad_method = client.get("/api/forecast?bond_type=treasury&method=arima")
        bad_h = client.get("/api/forecast?bond_type=treasury&horizon=0")
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert len(j["dates"]) == 8 and len(j["level"]) == 8 and len(j["level_std"]) == 8
    assert len(j["forecast_curve"]) == len(j["maturities"]) == len(j["current_curve"])
    assert len(j["smooth"]["forecast"]) == len(j["smooth"]["maturities"])
    assert j["summary"]["method"] == "ar" and "persistence" in j["summary"]
    assert bad_method.status_code == 400 and bad_h.status_code == 400


def test_backtest_endpoint_reports_three_methods():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        r = client.get("/api/backtest?bond_type=treasury&start=2022-01-01&end=2025-12-31&horizons=1,4&min_train=60")
        bad = client.get("/api/backtest?bond_type=treasury&horizons=x")
    assert r.status_code == 200, r.get_json()
    rows = r.get_json()["rows"]
    assert sorted({row["method"] for row in rows}) == ["ar", "rw", "var"]
    assert all(row["yield_rmse_bps"] >= 0 for row in rows) and len(rows) == 6
    assert bad.status_code == 400


def test_historical_endpoint_supports_svensson_series():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        ns = client.get("/api/historical?bond_type=treasury&start=2024-01-01&end=2025-12-31").get_json()
        sv = client.get("/api/historical?bond_type=treasury&start=2024-01-01&end=2025-12-31&model=svensson").get_json()
        bad = client.get("/api/historical?bond_type=treasury&model=spline")
    assert ns["model"] == "nelson-siegel" and set(ns["series"]) == {"Level", "Slope", "Curvature", "Tau"}
    assert sv["model"] == "svensson" and "Curvature2" in sv["series"] and "Tau2" in sv["summary"]["decays"]
    assert len(sv["series"]["Curvature2"]) == len(sv["dates"])
    assert sv["summary"]["rmse_bps_mean"] <= ns["summary"]["rmse_bps_mean"] + 1e-9
    assert bad.status_code == 400


def test_forecast_and_backtest_accept_model():
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        fc = client.get("/api/forecast?bond_type=treasury&start=2022-01-01&end=2025-12-31&horizon=4&model=svensson")
        bt = client.get("/api/backtest?bond_type=treasury&start=2022-01-01&end=2025-12-31&horizons=1&min_train=60&model=svensson")
    assert fc.status_code == 200, fc.get_json()
    j = fc.get_json()
    assert j["factor_names"] == ["Level", "Slope", "Curvature", "Curvature2"]
    assert len(j["series"]["Curvature2"]) == 4 and len(j["series_std"]["Curvature2"]) == 4
    assert bt.status_code == 200, bt.get_json()
    assert "Curvature2" in bt.get_json()["rows"][0]["factor_rmse_bps"]


def test_index_serves_all_studio_tabs_and_modules():
    """The shell includes every tab partial and the modular scripts."""
    app = create_app(enable_warmup=False)
    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)
    for tab in ("fitter", "explorer", "historical", "compare", "shortrate", "termpremium", "analytics", "learn"):
        assert f'data-tab-pane="{tab}"' in html, tab
    for script in ("core.js", "fitter.js", "lab.js", "historical.js", "compare.js", "shortrate.js", "termpremium.js", "analytics.js", "main.js"):
        assert f"js/{script}" in html, script
    assert "Fixed Income Studio" in html and "v2." in html
    assert 'id="btn-theme"' in html and 'id="synthetic-banner"' in html

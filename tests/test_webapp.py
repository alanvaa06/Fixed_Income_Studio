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

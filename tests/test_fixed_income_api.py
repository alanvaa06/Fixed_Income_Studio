"""Analyzer workflows and REST endpoints for the fixed-income tool set."""

import warnings

import numpy as np
import pandas as pd
import pytest

from nelson_siegel import YieldCurveAnalyzer
from nelson_siegel.analytics import Bond
from nelson_siegel.registry import get_any_model_class, list_all_models, make_any_model
from nelson_siegel.webapp.app import create_app


@pytest.fixture(scope="module")
def analyzer():
    return YieldCurveAnalyzer(public_sources=False)


@pytest.fixture(scope="module")
def client():
    app = create_app(enable_warmup=False)
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_registry_spans_both_families():
    ids = [m["id"] for m in list_all_models()]
    assert ids == ["nelson-siegel", "svensson", "vasicek", "cir"]
    families = {m["id"]: m["family"] for m in list_all_models()}
    assert families["svensson"] == "parametric" and families["cir"] == "short-rate"
    assert {m["id"]: m["supports_history"] for m in list_all_models()}["vasicek"] is False
    assert type(make_any_model("nelson-siegel", "tips")).__name__ == "TIPSNelsonSiegelModel"
    assert make_any_model("Vasicek").model_id == "vasicek"
    with pytest.raises(ValueError):
        get_any_model_class("hull-white")


# --------------------------------------------------------------------------- #
# Analyzer workflows
# --------------------------------------------------------------------------- #
def test_short_rate_proxy_and_analysis(analyzer):
    policy = analyzer.short_rate_proxy("policy", "2022-01-01", "2024-01-01")
    assert policy.name == "policy" and 90 <= len(policy) <= 110  # weekly
    bill = analyzer.short_rate_proxy("3m", "2022-01-01", "2024-01-01")
    assert bill.name == "3m" and len(bill) == len(policy)
    with pytest.raises(ValueError):
        analyzer.short_rate_proxy("overnight")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = analyzer.short_rate_analysis(model="vasicek", method="ols", start_date="2016-01-01", end_date="2026-01-01", horizon_years=3, n_paths=50)
    assert r["model"] == "vasicek" and r["estimate"].n_obs == len(r["history"])
    assert r["calibrated"].fitted and np.isclose(r["calibrated"].parameters["sigma"], r["estimate"].sigma)
    assert r["quantiles"].shape == (157, 5) and list(r["quantiles"].columns) == ["p5", "p25", "p50", "p75", "p95"]
    assert (r["quantiles"]["p95"] >= r["quantiles"]["p5"]).all()
    assert len(r["expected_physical"]) == len(r["horizons"]) == len(r["expected_risk_neutral"])
    assert np.isclose(r["expected_physical"][0], r["estimate"].r0)
    assert list(r["term_premium"].columns) == ["observed", "expected_short_rate", "term_premium"]
    assert r["sources"]["policy_rate"] == "synthetic"

    cir = analyzer.short_rate_analysis(model="cir", method="mle", start_date="2018-01-01", end_date="2026-01-01", n_paths=20)
    assert cir["estimate"].feller is not None and cir["calibrated"].model_id == "cir"


def test_term_premium_analysis_gsw_and_treasury(analyzer):
    r = analyzer.term_premium_analysis("gsw", "2000-01-01", "2026-06-30", maturities=(2, 10))
    assert r["source"] == "gsw" and r["summary"]["n_factors"] == 3
    assert set(r["decomposition"]) == {2.0, 10.0}
    d = r["decomposition"][10.0]
    assert np.allclose(d["fitted"] - d["risk_neutral"], d["term_premium"])
    assert r["term_premium"].shape[1] == 2
    assert r["dns"] is not None and list(r["dns"]["term_premium"].columns) == [2.0, 10.0]
    assert "10.0" in r["regressions"]["campbell_shiller"] and "2.0" in r["regressions"]["fama_bliss"]
    assert r["dns_summary"]["method"] == "var"

    t = analyzer.term_premium_analysis("treasury", "2019-01-01", "2026-06-30", maturities=(5,), n_factors=2, dns_method="ar")
    assert t["summary"]["n_factors"] == 2 and 80 <= t["summary"]["n_obs"] <= 95
    assert abs(t["term_premium"][5.0].iloc[-1]) < 0.05
    with pytest.raises(ValueError):
        analyzer.term_premium_analysis("gsw", maturities=(20,), max_maturity_years=10)
    with pytest.raises(ValueError):
        analyzer.zero_curve_panel("bunds")


def test_curve_and_bond_analytics(analyzer):
    r = analyzer.curve_analytics("treasury", "nelson-siegel", horizon=1.0, lookback_days=200)
    assert r["curve"].fitted and list(r["carry_roll_down"].index) == [2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
    assert "5y5y" in r["forwards"].index and "2s10s" in r["spreads"].index
    assert len(r["spread_history"]) > 100 and r["pca"] is not None
    assert r["rich_cheap"]["rank"].min() == 1 and r["changes"].attrs["as_of"] == r["as_of"]

    tips = analyzer.curve_analytics("tips", "nelson-siegel", horizon=2.0)
    assert list(tips["carry_roll_down"].index) == [5.0, 7.0, 10.0, 20.0, 30.0]
    assert "3m10y" not in tips["spreads"].index and "5s30s" in tips["spreads"].index

    b = analyzer.bond_analytics(Bond(10, 0.04), price=99.0)
    assert b["market_price"] == 99.0 and b["as_of"] is not None and b["modified_duration"] > 7
    custom = analyzer.bond_analytics(Bond(5, 0.03), model="vasicek", maturities=[1, 2, 5, 10, 30], yields=[0.04, 0.041, 0.042, 0.044, 0.046])
    assert custom["as_of"] is None and custom["model"] == "vasicek" and 90 < custom["model_price"] < 100


# --------------------------------------------------------------------------- #
# REST endpoints
# --------------------------------------------------------------------------- #
def test_health_and_data_sources_report_provenance(client):
    h = client.get("/api/health").get_json()
    assert h["status"] == "ok" and h["version"].startswith("2.") and "sources" in h
    assert h["public_sources"] is False  # conftest sets the offline switch
    client.get("/api/snapshot")
    ds = client.get("/api/data-sources").get_json()
    assert ds["sources"]["treasury"] == "Synthetic demo" and ds["is_synthetic"] is True
    assert [c["id"] for c in ds["chain"]][0] == "fred-api" and ds["chain"][-1]["needs_key"] is False


def test_models_endpoint_includes_short_rate_family(client):
    models = {m["id"]: m for m in client.get("/api/models").get_json()["models"]}
    assert set(models) == {"nelson-siegel", "svensson", "vasicek", "cir"}
    assert models["cir"]["family"] == "short-rate" and models["cir"]["min_points"] == 4
    assert [f["unit"] for f in models["vasicek"]["factors"]] == ["rate", "per-year", "rate", "rate"]


def test_fit_and_snapshot_accept_short_rate_models(client):
    points = [{"maturity": m, "yield": y} for m, y in [(0.25, 4.95), (1, 4.65), (2, 4.30), (5, 3.95), (10, 4.05), (30, 4.35)]]
    r = client.post("/api/fit", json={"model": "cir", "points": points})
    assert r.status_code == 200
    j = r.get_json()
    assert j["family"] == "short-rate" and set(j["factors"]) == {"ShortRate", "MeanReversion", "LongRunMean", "Volatility"}
    assert len(j["discount_factors"]) == 6 and 0 < j["discount_factors"][-1] < 1
    assert j["smooth"]["forward"] and j["rmse_bps"] < 40
    too_few = client.post("/api/fit", json={"model": "vasicek", "points": points[:3]})
    assert too_few.status_code == 400 and "At least 4" in too_few.get_json()["error"]
    snap = client.get("/api/snapshot?model=vasicek").get_json()
    assert snap["model"] == "vasicek" and snap["sources"]["treasury"] == "Synthetic demo"
    ns = client.post("/api/fit", json={"points": points}).get_json()
    assert ns["family"] == "parametric" and "Tau" in ns["factors"]


def test_short_rate_endpoint(client):
    r = client.get("/api/short-rate?model=vasicek&method=ols&proxy=policy&start=2016-01-01&horizon=3&paths=50")
    assert r.status_code == 200
    j = r.get_json()
    assert j["model"] == "vasicek" and j["proxy"] == "policy"
    est = j["estimate"]
    assert est["kappa"] > 0 and "theta_pct" in est and est["half_life_years"] is not None
    assert j["calibrated"]["family"] == "short-rate" and j["calibrated"]["rmse_bps"] >= 0
    assert len(j["history"]["dates"]) == len(j["history"]["values"]) == est["n_obs"]
    p = j["paths"]
    assert len(p["horizons"]) == len(p["p50"]) == len(p["expected_physical"]) == 157
    assert p["p95"][-1] >= p["p5"][-1]
    assert len(j["term_premium"]["term_premium_bps"]) == len(j["maturities"])
    assert len(j["smooth"]["expectations"]) == len(j["smooth"]["maturities"])
    # Cached: identical payload on repeat.
    assert client.get("/api/short-rate?model=vasicek&method=ols&proxy=policy&start=2016-01-01&horizon=3&paths=50").get_json() == j
    for bad in ("model=hull-white", "method=gmm", "proxy=overnight", "horizon=99", "paths=5", "bond_type=gilts"):
        assert client.get(f"/api/short-rate?{bad}").status_code == 400


def test_term_premium_endpoint(client):
    r = client.get("/api/term-premium?source=gsw&start=2000-01-01&maturities=2,10&factors=3")
    assert r.status_code == 200
    j = r.get_json()
    assert j["source"] == "gsw" and j["maturities"] == [2.0, 10.0]
    assert set(j["term_premium"]) == {"dates", "2", "10"}
    assert set(j["latest_term_premium"]) == {"2", "10"}
    d = j["decomposition"]["10"]
    assert set(d) >= {"dates", "observed", "fitted", "risk_neutral", "expected_short_rate", "term_premium", "convexity"}
    assert len(d["dates"]) == len(d["term_premium"]) == j["summary"]["n_obs"]
    assert j["dns"] is not None and set(j["dns"]["term_premium"]) == {"2", "10"}
    assert "10" in j["regressions"]["campbell_shiller"]
    assert j["summary"]["explained_variance"][0] > 0.5
    t = client.get("/api/term-premium?source=treasury&start=2019-01-01&maturities=5&factors=2&dns_method=ar")
    assert t.status_code == 200 and t.get_json()["summary"]["n_factors"] == 2
    for bad in ("source=bunds", "factors=9", "maturities=40", "maturities=x", "dns_method=arima", "max_maturity=1"):
        assert client.get(f"/api/term-premium?{bad}").status_code == 400, bad
    short = client.get("/api/term-premium?source=treasury&start=2025-01-01")
    assert short.status_code == 422


def test_analytics_endpoint(client):
    r = client.get("/api/analytics?bond_type=treasury&model=nelson-siegel&horizon=1&lookback=200")
    assert r.status_code == 200
    j = r.get_json()
    cr = j["carry_roll_down"]
    assert cr["maturities"] == [2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
    assert np.allclose(np.array(cr["carry_bps"]) + np.array(cr["roll_down_bps"]), cr["total_bps"])
    assert any(f["label"] == "5y5y" for f in j["forwards"])
    assert "2s10s" in j["spreads"] and len(j["spread_history"]["dates"]) == len(j["spread_history"]["2s10s"])
    assert j["rich_cheap"][0]["rank"] == 1 and j["changes"]["maturities"]
    assert len(j["pca"]["explained_variance"]) == 3 and set(j["pca"]["loadings"]) == {"Level", "Slope", "Curvature"}
    assert j["family"] == "parametric" and "Tau" in j["factors"]
    # The curve chart overlays the fitted model on the observed quotes, so the payload
    # carries a dense grid that must move with the model while the observed row does not.
    sm = j["smooth"]
    assert len(sm["maturities"]) == len(sm["yields"]) == 200
    assert sm["maturities"][0] >= 0.05 and sm["maturities"][-1] == max(j["maturities"])
    sv = client.get("/api/analytics?bond_type=treasury&model=svensson&horizon=1&lookback=200").get_json()
    assert sv["smooth"]["yields"] != sm["yields"]
    assert sv["changes"]["yield"] == j["changes"]["yield"]
    tips = client.get("/api/analytics?bond_type=tips&model=vasicek")
    assert tips.status_code == 200 and tips.get_json()["family"] == "short-rate"
    for bad in ("bond_type=gilts", "model=none", "horizon=50", "lookback=5"):
        assert client.get(f"/api/analytics?{bad}").status_code == 400, bad


def test_bond_endpoint(client):
    r = client.post("/api/bond", json={"maturity": 10, "coupon": 4.0, "frequency": 2, "price": 98.5})
    assert r.status_code == 200
    j = r.get_json()
    assert j["bond"]["coupon"] == 4.0 and j["market_price"] == 98.5
    assert j["ytm"] > j["model_ytm"] and j["z_spread_bps"] > 0
    assert len(j["key_rate_durations"]["tenors"]) == len(j["key_rate_durations"]["values"])
    assert len(j["cash_flows"]["times"]) == 20 and j["cash_flows"]["amounts"][-1] == 102.0
    assert np.isclose(sum(j["key_rate_durations"]["values"]), j["macaulay_duration"], rtol=0.05)
    custom = client.post(
        "/api/bond",
        json={"maturity": 5, "coupon": 3, "model": "svensson", "points": [{"maturity": m, "yield": y} for m, y in [(0.25, 4.9), (1, 4.6), (2, 4.3), (5, 4.0), (7, 4.0), (10, 4.1), (30, 4.4)]]},
    )
    assert custom.status_code == 200 and custom.get_json()["as_of"] is None and custom.get_json()["model"] == "svensson"
    assert client.post("/api/bond", json={"maturity": -1}).status_code == 400
    assert client.post("/api/bond", json={"maturity": 200}).status_code == 400
    assert client.post("/api/bond", json={"maturity": 5, "points": [{"maturity": "x"}]}).status_code == 400
    assert client.post("/api/bond", json={"maturity": 5, "model": "nope"}).status_code == 400


def _fake_benchmark_from(analyzer, noise_bps=5.0):
    """Build a NY-Fed-like frame from the analyzer's own ACM estimate plus noise."""
    r = analyzer.term_premium_analysis("gsw", "2005-01-01", "2026-06-30", maturities=(2, 5, 10))
    tp = r["term_premium"]
    rng = np.random.default_rng(1)
    fake = tp + rng.normal(0, noise_bps * 1e-4, tp.shape) + 0.001  # +10 bps level offset
    fake.columns = [float(c) for c in fake.columns]
    # Daily-ish index inside each month so to_monthly() has something to sample.
    return fake


def test_term_premium_benchmark_is_optional_and_reports_agreement(analyzer, monkeypatch):
    offline = analyzer.term_premium_analysis("gsw", "2005-01-01", "2026-06-30", maturities=(2, 10))
    assert offline["benchmark"] is None and offline["benchmark_stats"] == {}

    fake = _fake_benchmark_from(analyzer)
    monkeypatch.setattr(analyzer.data_manager, "get_term_premium_benchmark", lambda *a, **k: fake)
    r = analyzer.term_premium_analysis("gsw", "2005-01-01", "2026-06-30", maturities=(2, 5, 10))
    assert r["benchmark"] is not None and list(r["benchmark"].columns) == [2.0, 5.0, 10.0]
    stats = r["benchmark_stats"]
    assert set(stats) == {2.0, 5.0, 10.0}
    for m, st in stats.items():
        assert st["n"] > 200 and st["correlation"] > 0.95
        assert abs(st["mean_gap_bps"] + 10) < 2  # ours - theirs = -10 bps by construction
        assert 0 < st["rmse_bps"] < 20 and st["latest_date"] == r["term_premium"].index[-1].strftime("%Y-%m-%d")
    # A benchmark that lacks the requested maturities is ignored gracefully.
    monkeypatch.setattr(analyzer.data_manager, "get_term_premium_benchmark", lambda *a, **k: fake[[2.0]])
    partial = analyzer.term_premium_analysis("gsw", "2005-01-01", "2026-06-30", maturities=(7,))
    assert partial["benchmark"] is None
    monkeypatch.setattr(analyzer.data_manager, "get_term_premium_benchmark", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert analyzer.term_premium_analysis("gsw", "2005-01-01", "2026-06-30", maturities=(2,))["benchmark"] is None


def test_term_premium_endpoint_exposes_benchmark(client, monkeypatch):
    j = client.get("/api/term-premium?source=gsw&start=2005-01-01&maturities=2,10").get_json()
    assert j["benchmark"] is None and j["benchmark_stats"] == {} and "unavailable" in j["benchmark_note"]
    analyzer = client.application.config["ANALYZER"]
    fake = _fake_benchmark_from(analyzer)
    monkeypatch.setattr(analyzer.data_manager, "get_term_premium_benchmark", lambda *a, **k: fake)
    client.application.config["RESULT_CACHE"].invalidate_all()
    j = client.get("/api/term-premium?source=gsw&start=2005-01-01&maturities=2,10").get_json()
    assert set(j["benchmark"]) == {"dates", "2", "10"} and len(j["benchmark"]["dates"]) == len(j["benchmark"]["10"])
    assert set(j["benchmark_stats"]) == {"2", "10"} and j["benchmark_stats"]["10"]["correlation"] > 0.95
    assert "THREEFYTP" in j["benchmark_note"]
    ds = client.get("/api/data-sources").get_json()
    assert any(c["id"] == "fed-kim-wright" for c in ds["chain"])
    client.application.config["RESULT_CACHE"].invalidate_all()

"""Public data sources: feed parsers, the source chain and provenance reporting."""

import numpy as np
import pandas as pd
import pytest

from nelson_siegel import data as data_module
from nelson_siegel.data import (
    SOURCE_FRED_CSV,
    SOURCE_SYNTHETIC,
    SOURCE_TREASURY_GOV,
    DataManager,
    FedGSWDownloader,
    PolicyRateDownloader,
    TIPSDataDownloader,
    TreasuryDataDownloader,
    parse_fred_csv,
    parse_gsw_csv,
    parse_treasury_xml,
    public_data_enabled,
    reset_source_cooldowns,
)

TREASURY_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:Id m:type="Edm.Int32">9001</d:Id>
        <d:NEW_DATE m:type="Edm.DateTime">2026-08-03T00:00:00</d:NEW_DATE>
        <d:BC_1MONTH m:type="Edm.Double">4.35</d:BC_1MONTH>
        <d:BC_2MONTH m:type="Edm.Double">4.33</d:BC_2MONTH>
        <d:BC_3MONTH m:type="Edm.Double">4.30</d:BC_3MONTH>
        <d:BC_6MONTH m:type="Edm.Double">4.20</d:BC_6MONTH>
        <d:BC_1YEAR m:type="Edm.Double">4.05</d:BC_1YEAR>
        <d:BC_2YEAR m:type="Edm.Double">3.90</d:BC_2YEAR>
        <d:BC_3YEAR m:type="Edm.Double">3.88</d:BC_3YEAR>
        <d:BC_5YEAR m:type="Edm.Double">3.95</d:BC_5YEAR>
        <d:BC_7YEAR m:type="Edm.Double">4.05</d:BC_7YEAR>
        <d:BC_10YEAR m:type="Edm.Double">4.20</d:BC_10YEAR>
        <d:BC_20YEAR m:type="Edm.Double">4.70</d:BC_20YEAR>
        <d:BC_30YEAR m:type="Edm.Double">4.85</d:BC_30YEAR>
        <d:BC_30YEARDISPLAY m:type="Edm.Double">4.85</d:BC_30YEARDISPLAY>
      </m:properties>
    </content>
  </entry>
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:NEW_DATE m:type="Edm.DateTime">2026-08-04T00:00:00</d:NEW_DATE>
        <d:BC_1MONTH m:type="Edm.Double">4.36</d:BC_1MONTH>
        <d:BC_3MONTH m:type="Edm.Double">4.31</d:BC_3MONTH>
        <d:BC_6MONTH m:type="Edm.Double">4.21</d:BC_6MONTH>
        <d:BC_1YEAR m:type="Edm.Double">4.06</d:BC_1YEAR>
        <d:BC_2YEAR m:type="Edm.Double">3.91</d:BC_2YEAR>
        <d:BC_3YEAR m:type="Edm.Double">3.89</d:BC_3YEAR>
        <d:BC_5YEAR m:type="Edm.Double">3.96</d:BC_5YEAR>
        <d:BC_7YEAR m:type="Edm.Double">4.06</d:BC_7YEAR>
        <d:BC_10YEAR m:type="Edm.Double">4.21</d:BC_10YEAR>
        <d:BC_20YEAR m:type="Edm.Double">4.71</d:BC_20YEAR>
        <d:BC_30YEAR m:type="Edm.Double">4.86</d:BC_30YEAR>
      </m:properties>
    </content>
  </entry>
</feed>
"""

REAL_XML = TREASURY_XML.replace("BC_", "TC_")

FRED_CSV = """observation_date,DGS1MO,DGS3MO,DGS6MO,DGS1,DGS2,DGS3,DGS5,DGS7,DGS10,DGS20,DGS30
2026-08-03,4.35,4.30,4.20,4.05,3.90,3.88,3.95,4.05,4.20,4.70,4.85
2026-08-04,4.36,.,4.21,4.06,3.91,3.89,3.96,4.06,4.21,4.71,4.86
2026-08-05,.,.,.,.,.,.,.,.,.,.,.
"""

GSW_CSV = """Series Description,Yield curve,,,,,,,,
Board of Governors of the Federal Reserve System,,,,,,,,,
"Gurkaynak, Sack, and Wright (2007)",,,,,,,,,
Date,SVENY01,SVENY02,SVENY10,BETA0,BETA1,BETA2,BETA3,TAU1,TAU2
1975-01-02,7.10,7.20,7.80,8.1,-1.2,-0.5,NA,1.4,NA
2026-08-03,4.05,3.90,4.20,4.9,-0.9,-1.5,-0.8,1.6,9.0
"""


def test_public_data_disabled_by_conftest_env():
    assert public_data_enabled() is False


def test_public_data_env_switches(monkeypatch):
    monkeypatch.delenv(data_module.OFFLINE_ENV, raising=False)
    monkeypatch.delenv(data_module.PUBLIC_DATA_ENV, raising=False)
    assert public_data_enabled() is True
    monkeypatch.setenv(data_module.PUBLIC_DATA_ENV, "0")
    assert public_data_enabled() is False
    monkeypatch.delenv(data_module.PUBLIC_DATA_ENV)
    monkeypatch.setenv(data_module.OFFLINE_ENV, "yes")
    assert public_data_enabled() is False


def test_parse_treasury_xml_nominal_and_real():
    frame = parse_treasury_xml(TREASURY_XML)
    assert list(frame.index) == [pd.Timestamp("2026-08-03"), pd.Timestamp("2026-08-04")]
    assert 1 / 12 in frame.columns and 30.0 in frame.columns and 2 / 12 in frame.columns
    assert np.isclose(frame.loc["2026-08-03", 10.0], 0.042)
    assert np.isnan(frame.loc["2026-08-04", 2 / 12])  # missing tenor stays NaN
    assert list(frame.columns) == sorted(frame.columns)
    real = parse_treasury_xml(REAL_XML)
    assert np.isclose(real.loc["2026-08-04", 5.0], 0.0396)
    assert parse_treasury_xml("<feed xmlns='http://www.w3.org/2005/Atom'/>").empty


def test_parse_fred_csv_handles_missing_markers():
    frame = parse_fred_csv(FRED_CSV)
    assert list(frame.columns)[:2] == ["DGS1MO", "DGS3MO"]
    assert np.isclose(frame.loc["2026-08-03", "DGS10"], 0.042)
    assert np.isnan(frame.loc["2026-08-04", "DGS3MO"])
    assert frame.loc["2026-08-05"].isna().all()


def test_parse_gsw_csv_skips_preamble_and_scales():
    table = parse_gsw_csv(GSW_CSV)
    assert list(table.index) == [pd.Timestamp("1975-01-02"), pd.Timestamp("2026-08-03")]
    assert np.isclose(table.loc["2026-08-03", "SVENY10"], 0.042)
    assert np.isclose(table.loc["2026-08-03", "BETA0"], 0.049)
    assert np.isclose(table.loc["2026-08-03", "TAU2"], 9.0)  # tau stays in years
    assert np.isnan(table.loc["1975-01-02", "BETA3"])
    assert parse_gsw_csv("just prose\nno header").empty


def test_treasury_gov_is_preferred_over_fred_csv(monkeypatch):
    reset_source_cooldowns()
    calls = []

    def fake_get(self, url, params=None):
        calls.append((url, dict(params or {})))
        if "treasury.gov" in url:
            assert params["data"] == "daily_treasury_yield_curve"
            return TREASURY_XML
        raise AssertionError("FRED CSV should not be needed")

    monkeypatch.setattr(TreasuryDataDownloader, "_http_get", fake_get)
    dl = TreasuryDataDownloader(public_sources=True)
    frame = dl.download("2026-08-01", "2026-08-31")
    assert dl.last_source == SOURCE_TREASURY_GOV
    assert dl.is_synthetic is False
    assert len(frame) == 2
    assert 2 / 12 not in frame.columns  # only the configured tenors are kept
    assert list(frame.columns) == sorted(dl.maturity_mapping.values())
    assert np.isclose(frame.loc["2026-08-03", 10.0], 0.042)
    assert calls[0][1]["field_tdr_date_value"] == "2026"
    # Memoised: no second request for the same window.
    n = len(calls)
    dl.download("2026-08-01", "2026-08-31")
    assert len(calls) == n
    assert dl.source_for("2026-08-01", "2026-08-31") == SOURCE_TREASURY_GOV


def test_treasury_gov_fetches_each_year_of_the_window(monkeypatch):
    reset_source_cooldowns()
    years = []

    def fake_get(self, url, params=None):
        years.append(params["field_tdr_date_value"])
        return TREASURY_XML if params["field_tdr_date_value"] == "2026" else "<feed xmlns='http://www.w3.org/2005/Atom'/>"

    monkeypatch.setattr(TreasuryDataDownloader, "_http_get", fake_get)
    dl = TreasuryDataDownloader(public_sources=True)
    frame = dl.download("2024-06-01", "2026-08-31")
    assert sorted(years) == ["2024", "2025", "2026"]
    assert len(frame) == 2


def test_fred_csv_used_when_treasury_gov_fails_and_cooldown_applies(monkeypatch):
    reset_source_cooldowns()
    calls = []

    def fake_get(self, url, params=None):
        calls.append(url)
        if "treasury.gov" in url:
            raise ConnectionError("blocked")
        assert params["id"].startswith("DGS1MO,")
        return FRED_CSV

    monkeypatch.setattr(TreasuryDataDownloader, "_http_get", fake_get)
    dl = TreasuryDataDownloader(public_sources=True)
    frame = dl.download("2026-08-01", "2026-08-31")
    assert dl.last_source == SOURCE_FRED_CSV
    assert len(frame) == 2  # the all-missing row is dropped
    assert np.isclose(frame.loc["2026-08-03", 0.25], 0.043)
    assert any("treasury.gov" in c for c in calls)

    # A new window skips the failed source entirely (process-wide cool-down).
    calls.clear()
    dl.download("2026-07-01", "2026-08-31")
    assert not any("treasury.gov" in c for c in calls)
    assert all("fred" in c for c in calls)
    reset_source_cooldowns()


def test_all_public_sources_failing_falls_back_to_synthetic(monkeypatch):
    reset_source_cooldowns()

    def broken(self, url, params=None):
        raise TimeoutError("no network")

    monkeypatch.setattr(TIPSDataDownloader, "_http_get", broken)
    dl = TIPSDataDownloader(public_sources=True)
    frame = dl.download("2026-01-01", "2026-02-01")
    assert dl.last_source == SOURCE_SYNTHETIC
    assert dl.is_synthetic is True
    assert list(frame.columns) == [5.0, 7.0, 10.0, 20.0, 30.0]
    reset_source_cooldowns()


def test_public_sources_off_never_calls_http(monkeypatch):
    def boom(self, url, params=None):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(TreasuryDataDownloader, "_http_get", boom)
    dl = TreasuryDataDownloader(public_sources=False)
    dl.download("2026-01-01", "2026-02-01")
    assert dl.last_source == SOURCE_SYNTHETIC


def test_synthetic_windows_overlap_consistently():
    dl = TreasuryDataDownloader(public_sources=False)
    a = dl.download("2020-01-01", "2022-01-01")
    b = dl.download("2021-01-01", "2023-01-01")
    common = a.index.intersection(b.index)
    assert len(common) > 200
    assert np.allclose(a.loc[common].to_numpy(), b.loc[common].to_numpy())
    # Realistic magnitudes: percent yields between 0 and 10, upward-sloping on average.
    pct = a * 100
    assert pct.min().min() > 0 and pct.max().max() < 10
    assert pct[30.0].mean() > pct[0.25].mean()


def test_policy_rate_downloader_synthetic_is_stepwise():
    dl = PolicyRateDownloader(public_sources=False)
    series = dl.download_series("2024-01-01", "2024-12-31")
    assert series.name == "policy_rate"
    assert isinstance(series.index, pd.DatetimeIndex)
    steps = (series * 400).round()
    assert np.allclose(series * 400, steps)  # 25bp grid
    assert 1 < series.nunique() < 40


def test_policy_rate_via_fred_csv(monkeypatch):
    reset_source_cooldowns()

    def fake_get(self, url, params=None):
        assert params["id"] == "DFF"
        return "observation_date,DFF\n2026-08-03,4.33\n2026-08-04,4.33\n"

    monkeypatch.setattr(PolicyRateDownloader, "_http_get", fake_get)
    series = PolicyRateDownloader(public_sources=True).download_series("2026-08-01", "2026-08-05")
    assert np.allclose(series.to_numpy(), 0.0433)


def test_gsw_downloader_parses_and_evaluates_parameters(monkeypatch, tmp_path):
    def fake_get(self, url):
        return GSW_CSV

    monkeypatch.setattr(FedGSWDownloader, "_http_get", fake_get)
    dl = FedGSWDownloader(public_sources=True, cache_dir=str(tmp_path))
    table = dl.download()
    assert dl.is_synthetic is False
    assert len(table) == 2
    zeros = dl.zero_yields([1, 2, 10, 0.5], start_date="2026-01-01")
    assert list(zeros.index) == [pd.Timestamp("2026-08-03")]
    b0, b1, b2, b3, t1, t2 = 0.049, -0.009, -0.015, -0.008, 1.6, 9.0
    from nelson_siegel.model import SvenssonModel

    expected = SvenssonModel.model_function(np.array([1.0, 2.0, 10.0, 0.5]), b0, b1, b2, b3, t1, t2)
    assert np.allclose(zeros.iloc[0].to_numpy(), expected)
    # Nelson-Siegel rows (no beta3/tau2) are evaluated with the three-factor formula.
    early = dl.zero_yields([1, 10], end_date="1980-01-01")
    assert len(early) == 1 and np.isfinite(early.iloc[0]).all()
    # The response was cached on disk and reused.
    assert (tmp_path / "gsw_nominal.csv").exists()
    monkeypatch.setattr(FedGSWDownloader, "_http_get", lambda self, url: (_ for _ in ()).throw(AssertionError("cached")))
    again = FedGSWDownloader(public_sources=True, cache_dir=str(tmp_path)).download()
    assert len(again) == 2


def test_gsw_synthetic_fallback_has_long_history():
    dl = FedGSWDownloader(public_sources=False)
    zeros = dl.zero_yields([1, 5, 10, 30], "2000-01-01", "2000-03-01")
    assert dl.is_synthetic
    assert len(zeros) > 30
    assert (zeros.abs() < 0.2).all().all()
    with pytest.raises(ValueError):
        FedGSWDownloader(kind="bogus")


def test_data_manager_reports_sources_and_new_datasets():
    dm = DataManager(public_sources=False)
    assert dm.source_summary() == {"treasury": None, "tips": None, "policy_rate": None, "gsw": None, "acm_benchmark": None}
    dm.get_bond_data("treasury", "2025-01-01", "2025-02-01")
    dm.get_policy_rate("2025-01-01", "2025-02-01")
    dm.get_zero_curve([1, 10], "2025-01-01", "2025-02-01")
    summary = dm.source_summary()
    assert summary["treasury"] == SOURCE_SYNTHETIC
    assert summary["policy_rate"] == SOURCE_SYNTHETIC
    assert summary["gsw"] == SOURCE_SYNTHETIC
    assert dm.is_synthetic is True
    with pytest.raises(ValueError):
        dm.get_bond_data("bonds")
    dm.clear_cache()


def test_acm_benchmark_downloader_via_fred_csv_and_offline(monkeypatch):
    from nelson_siegel.data import ACMBenchmarkDownloader

    reset_source_cooldowns()
    assert ACMBenchmarkDownloader.series["10Y"] == "THREEFYTP10" and ACMBenchmarkDownloader.series["1Y"] == "THREEFYTP1"

    def fake_get(self, url, params=None):
        assert params["id"].startswith("THREEFYTP1,THREEFYTP2")
        return "observation_date,THREEFYTP1,THREEFYTP2,THREEFYTP5,THREEFYTP10\n2026-07-31,0.10,0.25,0.60,1.05\n2026-08-31,0.12,.,0.62,1.10\n"

    monkeypatch.setattr(ACMBenchmarkDownloader, "_http_get", fake_get)
    dl = ACMBenchmarkDownloader(public_sources=True)
    frame = dl.download("2026-07-01", "2026-08-31")
    assert dl.last_source == SOURCE_FRED_CSV
    assert list(frame.columns) == [1.0, 2.0, 5.0, 10.0]  # only the series the export returned
    assert np.isclose(frame.loc["2026-08-31", 10.0], 0.011) and np.isnan(frame.loc["2026-08-31", 2.0])

    offline = ACMBenchmarkDownloader(public_sources=False)
    empty = offline.download("2026-07-01", "2026-08-31")
    assert empty.empty and list(empty.columns) == [float(n) for n in range(1, 11)]
    assert offline.last_source == SOURCE_SYNTHETIC
    dm = DataManager(public_sources=False)
    assert dm.get_acm_benchmark("2026-07-01", "2026-08-31").empty
    assert "acm_benchmark" in dm.source_summary()

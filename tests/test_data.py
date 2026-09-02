"""Tests for the data layer: memoisation, FRED fetch and synthetic fallback."""

import types

import numpy as np
import pandas as pd

from nelson_siegel import data as data_module
from nelson_siegel.data import DataManager, TIPSDataDownloader, TreasuryDataDownloader


def test_synthetic_data_is_deterministic_and_does_not_touch_global_rng():
    np.random.seed(123)
    before = np.random.random()
    np.random.seed(123)
    a = TreasuryDataDownloader().download("2024-01-01", "2024-03-01")
    after = np.random.random()
    b = TreasuryDataDownloader().download("2024-01-01", "2024-03-01")
    assert a.equals(b)
    assert before == after  # the global RNG stream is untouched


def test_download_is_memoised_per_window():
    dl = TreasuryDataDownloader()
    calls = {"n": 0}
    original = dl._create_synthetic_data

    def counting(start, end):
        calls["n"] += 1
        return original(start, end)

    dl._create_synthetic_data = counting
    first = dl.download("2024-01-01", "2024-02-01")
    second = dl.download("2024-01-01", "2024-02-01")
    assert calls["n"] == 1
    assert first.equals(second)
    assert first is not second  # callers get a copy

    dl.download("2024-01-01", "2024-03-01")
    assert calls["n"] == 2

    dl.clear_cache()
    dl.download("2024-01-01", "2024-02-01")
    assert calls["n"] == 3


def test_data_manager_clear_cache_propagates():
    dm = DataManager()
    dm.get_treasury_data("2024-01-01", "2024-02-01")
    dm.get_tips_data("2024-01-01", "2024-02-01")
    assert dm.treasury_downloader._cache and dm.tips_downloader._cache
    dm.clear_cache()
    assert not dm.treasury_downloader._cache and not dm.tips_downloader._cache
    assert dm.uses_fred is False


class _FakeFred:
    calls = []

    def __init__(self, api_key):
        self.api_key = api_key

    def get_series(self, series_id, observation_start=None, observation_end=None):
        _FakeFred.calls.append(series_id)
        if series_id == "DGS3":
            raise RuntimeError("series unavailable")
        idx = pd.date_range(observation_start, observation_end, freq="D")
        return pd.Series(np.linspace(4.0, 4.5, len(idx)), index=idx)


def test_fred_download_uses_all_series_concurrently_and_tolerates_failures(monkeypatch):
    fake_module = types.SimpleNamespace(Fred=_FakeFred)
    monkeypatch.setattr(data_module, "fredapi", fake_module)
    monkeypatch.setattr(data_module, "HAS_FREDAPI", True)
    _FakeFred.calls = []

    dl = TreasuryDataDownloader(api_key="key")
    assert dl.uses_fred is True
    frame = dl.download("2024-01-01", "2024-01-10")

    assert sorted(_FakeFred.calls) == sorted(dl.series.values())
    assert 3.0 not in frame.columns  # failed series dropped, others kept
    assert list(frame.columns) == sorted(frame.columns)
    assert np.isclose(frame.iloc[0, 0], 0.04)  # percent -> decimal
    # Memoised: a second call does not hit the fake API again.
    n_calls = len(_FakeFred.calls)
    dl.download("2024-01-01", "2024-01-10")
    assert len(_FakeFred.calls) == n_calls


def test_fred_total_failure_falls_back_to_synthetic(monkeypatch):
    class Broken:
        def __init__(self, api_key):
            raise RuntimeError("no network")

    monkeypatch.setattr(data_module, "fredapi", types.SimpleNamespace(Fred=Broken))
    monkeypatch.setattr(data_module, "HAS_FREDAPI", True)
    frame = TIPSDataDownloader(api_key="key").download("2024-01-01", "2024-01-10")
    assert not frame.empty
    assert list(frame.columns) == [5.0, 7.0, 10.0, 20.0, 30.0]

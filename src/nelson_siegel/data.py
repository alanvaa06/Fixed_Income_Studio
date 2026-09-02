"""
Data Download and Management Module

This module provides classes for downloading and managing yield curve data
from FRED, with deterministic synthetic data as a fallback for demos and
tests.

Downloads are memoised per (start, end) window on each downloader instance,
so repeated requests for the same range (snapshot, tau estimation, historical
factors) do not re-hit the network. FRED series are fetched concurrently.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import fredapi

    HAS_FREDAPI = True
except ImportError:  # pragma: no cover - exercised only without the optional dep
    fredapi = None
    HAS_FREDAPI = False


class BaseDataDownloader:
    """
    Base class for yield curve data downloaders.

    Subclasses define ``series`` (label -> FRED series id), ``maturity_mapping``
    (label -> maturity in years) and ``_create_synthetic_data``.
    """

    series: Dict[str, str] = {}
    maturity_mapping: Dict[str, float] = {}

    def __init__(self, api_key: Optional[str] = None, default_start_days: int = 3650):
        """
        Initialize the data downloader.

        Parameters:
        -----------
        api_key : str, optional
            FRED API key. Without it (or without ``fredapi``), synthetic data is used.
        default_start_days : int
            Default number of days to look back for data
        """
        self.api_key = api_key
        self.default_start_days = default_start_days
        self._cache: Dict[Tuple[str, str], pd.DataFrame] = {}

    def _get_date_range(self, start_date: Optional[str], end_date: Optional[str]) -> tuple:
        """
        Get properly formatted date range.

        Parameters:
        -----------
        start_date : str, optional
            Start date in 'YYYY-MM-DD' format
        end_date : str, optional
            End date in 'YYYY-MM-DD' format

        Returns:
        --------
        tuple
            (start_date, end_date) as strings
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=self.default_start_days)).strftime(
                "%Y-%m-%d"
            )
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        return start_date, end_date

    @property
    def uses_fred(self) -> bool:
        return bool(HAS_FREDAPI and self.api_key)

    def clear_cache(self) -> None:
        """Drop memoised downloads."""
        self._cache.clear()

    def download(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Download yield curve data.

        Parameters:
        -----------
        start_date : str, optional
            Start date in 'YYYY-MM-DD' format
        end_date : str, optional
            End date in 'YYYY-MM-DD' format

        Returns:
        --------
        pd.DataFrame
            DataFrame with yields indexed by date, columns are maturities in years
        """
        start_date, end_date = self._get_date_range(start_date, end_date)
        key = (start_date, end_date)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()

        frame: Optional[pd.DataFrame] = None
        if self.uses_fred:
            try:
                frame = self._download_from_fred(start_date, end_date)
            except Exception as exc:  # noqa: BLE001 - degrade to synthetic data
                logger.warning("FRED download failed (%s); falling back to synthetic data", exc)

        if frame is None:
            frame = self._create_synthetic_data(start_date, end_date)

        self._cache[key] = frame
        return frame.copy()

    def _download_from_fred(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch all configured series from FRED concurrently."""
        fred = fredapi.Fred(api_key=self.api_key)

        def fetch(item: Tuple[str, str]) -> Tuple[str, Optional[pd.Series]]:
            label, series_id = item
            try:
                series = fred.get_series(
                    series_id, observation_start=start_date, observation_end=end_date
                )
                return label, series / 100.0  # percent -> decimal
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to download %s (%s): %s", label, series_id, exc)
                return label, None

        with ThreadPoolExecutor(max_workers=min(8, max(1, len(self.series)))) as pool:
            results = list(pool.map(fetch, self.series.items()))

        data_dict = {
            self.maturity_mapping[label]: series
            for label, series in results
            if series is not None
        }
        if not data_dict:
            raise ValueError("No data could be downloaded from FRED")

        df = pd.DataFrame(data_dict).sort_index(axis=1)
        df.index = pd.to_datetime(df.index)
        return df.dropna(how="all")

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError("Subclasses must implement _create_synthetic_data")


class TreasuryDataDownloader(BaseDataDownloader):
    """
    Downloads US Treasury yield curve data.
    """

    series = {
        "1M": "DGS1MO",
        "3M": "DGS3MO",
        "6M": "DGS6MO",
        "1Y": "DGS1",
        "2Y": "DGS2",
        "3Y": "DGS3",
        "5Y": "DGS5",
        "10Y": "DGS10",
        "30Y": "DGS30",
    }
    maturity_mapping = {
        "1M": 1 / 12,
        "3M": 0.25,
        "6M": 0.5,
        "1Y": 1.0,
        "2Y": 2.0,
        "3Y": 3.0,
        "5Y": 5.0,
        "10Y": 10.0,
        "30Y": 30.0,
    }

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key, default_start_days=3650)
        # Backward-compatible alias
        self.treasury_series = self.series

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Create deterministic synthetic Treasury data for demos and tests."""
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        maturities = list(self.maturity_mapping.values())
        rng = np.random.default_rng(42)
        base_yield = 3.0
        time_trend = 0.5 * np.sin(np.arange(len(dates)) * 2 * np.pi / 365)

        data = {}
        for mat in maturities:
            yield_level = base_yield + 0.5 * np.log(mat + 0.1) + rng.normal(0, 0.1, len(dates))
            data[mat] = np.maximum(yield_level + time_trend, 0.01) / 100  # percent -> decimal

        return pd.DataFrame(data, index=dates)

    # Backward-compatible name
    _create_synthetic_treasury_data = _create_synthetic_data


class TIPSDataDownloader(BaseDataDownloader):
    """
    Downloads US TIPS (Treasury Inflation-Protected Securities) real yield data.
    """

    series = {
        "5Y": "DFII5",
        "7Y": "DFII7",
        "10Y": "DFII10",
        "20Y": "DFII20",
        "30Y": "DFII30",
    }
    maturity_mapping = {
        "5Y": 5.0,
        "7Y": 7.0,
        "10Y": 10.0,
        "20Y": 20.0,
        "30Y": 30.0,
    }

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key, default_start_days=3650)
        self.tips_series = self.series

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Create deterministic synthetic TIPS data for demos and tests."""
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        maturities = list(self.maturity_mapping.values())
        rng = np.random.default_rng(456)
        base_real_yield = 1.0
        time_trend = 0.2 * np.sin(np.arange(len(dates)) * 2 * np.pi / 365)

        data = {}
        for mat in maturities:
            real_yield = base_real_yield + 0.4 * np.log(mat + 0.1) + rng.normal(0, 0.12, len(dates))
            data[mat] = np.maximum(real_yield + time_trend, -0.01) / 100  # can be negative

        return pd.DataFrame(data, index=dates)

    _create_synthetic_tips_data = _create_synthetic_data


class DataManager:
    """
    Manages multiple data sources and provides unified interface.
    """

    def __init__(self, fred_api_key: Optional[str] = None):
        """
        Initialize data manager.

        Parameters:
        -----------
        fred_api_key : str, optional
            FRED API key for accessing Federal Reserve data
        """
        self.treasury_downloader = TreasuryDataDownloader(fred_api_key)
        self.tips_downloader = TIPSDataDownloader(fred_api_key)

    @property
    def uses_fred(self) -> bool:
        return self.treasury_downloader.uses_fred

    def clear_cache(self) -> None:
        """Drop memoised downloads on both downloaders."""
        self.treasury_downloader.clear_cache()
        self.tips_downloader.clear_cache()

    def get_treasury_data(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Get Treasury yield data."""
        return self.treasury_downloader.download(start_date, end_date)

    def get_tips_data(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Get TIPS yield data."""
        return self.tips_downloader.download(start_date, end_date)

    def get_all_data(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Get both Treasury and TIPS data.

        Returns:
        --------
        dict
            Dictionary with 'treasury' and 'tips' keys containing respective DataFrames
        """
        return {
            "treasury": self.get_treasury_data(start_date, end_date),
            "tips": self.get_tips_data(start_date, end_date),
        }

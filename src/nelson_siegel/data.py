"""
Data download and management.

Every downloader tries a chain of sources and records which one answered:

1. **FRED API** (``fredapi``) when an API key is configured.
2. **Public, key-less sources**:
   - the U.S. Treasury daily par yield curve XML feed (nominal and real curves),
   - FRED's public ``fredgraph.csv`` export (any FRED series, no key needed),
   - the Federal Reserve Board's Gurkaynak-Sack-Wright (GSW) zero-coupon
     curve tables (daily fitted Svensson parameters back to 1961).
3. **Deterministic synthetic data** so every feature works offline.

Public sources are on by default; set ``NELSON_SIEGEL_OFFLINE=1`` to disable
all network access (the test-suite does this) or pass
``public_sources=False``. Downloads are memoised per (start, end) window on
each downloader, and a source that fails is skipped for a few minutes so a
blocked network never stalls the UI twice.
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import fredapi

    HAS_FREDAPI = True
except ImportError:  # pragma: no cover - exercised only without the optional dep
    fredapi = None
    HAS_FREDAPI = False

try:
    import requests

    HAS_REQUESTS = True
except ImportError:  # pragma: no cover
    requests = None
    HAS_REQUESTS = False


# --------------------------------------------------------------------------- #
# Source identifiers and environment switches
# --------------------------------------------------------------------------- #
SOURCE_FRED_API = "fred-api"
SOURCE_TREASURY_GOV = "treasury.gov"
SOURCE_FRED_CSV = "fred-public-csv"
SOURCE_FED_GSW = "fed-gsw"
SOURCE_SYNTHETIC = "synthetic"

SOURCE_LABELS = {
    SOURCE_FRED_API: "FRED API (live)",
    SOURCE_TREASURY_GOV: "U.S. Treasury (public)",
    SOURCE_FRED_CSV: "FRED public CSV (live)",
    SOURCE_FED_GSW: "Fed GSW zero curve (public)",
    SOURCE_SYNTHETIC: "Synthetic demo",
}

OFFLINE_ENV = "NELSON_SIEGEL_OFFLINE"
PUBLIC_DATA_ENV = "NELSON_SIEGEL_PUBLIC_DATA"
HTTP_TIMEOUT = 20.0
USER_AGENT = "nelson-siegel-studio/2.0 (+https://github.com/alanvaa06/Nelson_Siegel_Model)"
#: Seconds to skip a public source after a failed attempt.
SOURCE_COOLDOWN = 600.0

TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FED_GSW_NOMINAL_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
FED_GSW_TIPS_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200805.csv"


#: Process-wide cool-down per public source (a blocked network is probed once).
_SOURCE_DISABLED_UNTIL: Dict[str, float] = {}


def reset_source_cooldowns() -> None:
    """Forget failed-source cool-downs so the next download retries every source."""
    _SOURCE_DISABLED_UNTIL.clear()


def public_data_enabled() -> bool:
    """Whether key-less public sources may be contacted (env-controlled)."""
    if os.environ.get(OFFLINE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    flag = os.environ.get(PUBLIC_DATA_ENV, "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def http_get_text(url: str, params: Optional[Dict[str, str]] = None, timeout: float = HTTP_TIMEOUT) -> str:
    """GET a URL and return its body as text (raises on HTTP errors)."""
    if not HAS_REQUESTS:  # pragma: no cover
        raise RuntimeError("The 'requests' package is required for public data sources")
    response = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


# --------------------------------------------------------------------------- #
# Parsers for the public feeds (pure functions, easy to unit-test)
# --------------------------------------------------------------------------- #
_TREASURY_TENOR_RE = re.compile(r"^(?:BC|TC)_(\d+)(MONTH|YEAR)(?:_?.*)?$", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_treasury_xml(text: str) -> pd.DataFrame:
    """Parse the Treasury daily yield-curve Atom/XML feed.

    Works for both the nominal (``BC_*`` fields) and real (``TC_*``) curves.
    Returns decimal yields indexed by date, columns are maturities in years.
    Fields such as ``BC_30YEARDISPLAY`` are ignored.
    """
    root = ET.fromstring(text)
    rows: Dict[pd.Timestamp, Dict[float, float]] = {}
    for entry in root.iter():
        if _local(entry.tag) != "properties":
            continue
        date_value: Optional[str] = None
        values: Dict[float, float] = {}
        for child in entry:
            name = _local(child.tag)
            txt = (child.text or "").strip()
            if name.upper() in {"NEW_DATE", "DATE"}:
                date_value = txt
                continue
            match = _TREASURY_TENOR_RE.match(name)
            if not match or not txt:
                continue
            if "DISPLAY" in name.upper():
                continue
            count, unit = int(match.group(1)), match.group(2).upper()
            maturity = count / 12.0 if unit == "MONTH" else float(count)
            try:
                values[maturity] = float(txt) / 100.0
            except ValueError:
                continue
        if date_value and values:
            rows[pd.Timestamp(date_value[:10])] = values
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    frame = frame.reindex(sorted(frame.columns), axis=1)
    frame.index.name = None
    return frame


def parse_fred_csv(text: str) -> pd.DataFrame:
    """Parse a ``fredgraph.csv`` export (one or many series) into decimals."""
    frame = pd.read_csv(io.StringIO(text), na_values=[".", ""], skipinitialspace=True)
    if frame.empty or frame.shape[1] < 2:
        return pd.DataFrame()
    date_col = frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col]).set_index(date_col)
    frame.index.name = None
    frame = frame.apply(pd.to_numeric, errors="coerce")
    return frame.sort_index() / 100.0


def parse_gsw_csv(text: str) -> pd.DataFrame:
    """Parse a Federal Reserve GSW table (``feds200628.csv`` / ``feds200805.csv``).

    The file starts with a few lines of prose; the data begins at the first
    line whose first field is ``Date``. Percent values are converted to
    decimals, ``NA`` becomes NaN. Column names are kept (``SVENY01`` ...,
    ``BETA0`` ..., ``TAU1``, ``TAU2``; TIPS files use ``TIPSY02`` ...).
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.split(",")[0].strip().strip('"') == "Date"), None)
    if start is None:
        return pd.DataFrame()
    body = "\n".join(lines[start:])
    frame = pd.read_csv(io.StringIO(body), na_values=["NA", "ND", ""], skipinitialspace=True)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).set_index("Date").sort_index()
    frame.index.name = None
    frame = frame.apply(pd.to_numeric, errors="coerce")
    rate_cols = [c for c in frame.columns if not c.upper().startswith("TAU")]
    frame[rate_cols] = frame[rate_cols] / 100.0
    return frame


# --------------------------------------------------------------------------- #
# Base downloader with the source chain
# --------------------------------------------------------------------------- #
class BaseDataDownloader:
    """
    Base class for yield curve data downloaders.

    Subclasses define ``series`` (label -> FRED series id), ``maturity_mapping``
    (label -> maturity in years) and ``_create_synthetic_data``. Optionally
    ``treasury_xml_dataset`` names the treasury.gov feed to use.
    """

    series: Dict[str, str] = {}
    maturity_mapping: Dict[str, float] = {}
    #: ``data=`` parameter of the treasury.gov XML feed; ``None`` disables it.
    treasury_xml_dataset: Optional[str] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_start_days: int = 3650,
        *,
        public_sources: Optional[bool] = None,
        timeout: float = HTTP_TIMEOUT,
    ):
        """
        Parameters
        ----------
        api_key : str, optional
            FRED API key. Without it public sources are tried, then synthetic data.
        default_start_days : int
            Default look-back window in days.
        public_sources : bool, optional
            Contact key-less public feeds (treasury.gov, FRED CSV). Defaults to
            :func:`public_data_enabled` (environment controlled).
        timeout : float
            HTTP timeout in seconds per request.
        """
        self.api_key = api_key
        self.default_start_days = default_start_days
        self.public_sources = public_data_enabled() if public_sources is None else bool(public_sources)
        self.timeout = timeout
        self._cache: Dict[Tuple[str, str], pd.DataFrame] = {}
        self._sources: Dict[Tuple[str, str], str] = {}
        self.last_source: Optional[str] = None

    # -- configuration ---------------------------------------------------- #
    def _get_date_range(self, start_date: Optional[str], end_date: Optional[str]) -> tuple:
        """Return ``(start, end)`` as ISO strings, filling defaults."""
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=self.default_start_days)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        return start_date, end_date

    @property
    def uses_fred(self) -> bool:
        return bool(HAS_FREDAPI and self.api_key)

    @property
    def is_synthetic(self) -> bool:
        """Whether the most recent download came from the synthetic generator."""
        return self.last_source in (None, SOURCE_SYNTHETIC)

    def clear_cache(self) -> None:
        """Drop memoised downloads and source cool-downs."""
        self._cache.clear()
        self._sources.clear()
        reset_source_cooldowns()

    def source_for(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[str]:
        """Source that served a given window (``None`` when not downloaded yet)."""
        return self._sources.get(self._get_date_range(start_date, end_date))

    # -- HTTP (overridable for tests) ------------------------------------- #
    def _http_get(self, url: str, params: Optional[Dict[str, str]] = None) -> str:
        return http_get_text(url, params=params, timeout=self.timeout)

    @staticmethod
    def _source_available(name: str) -> bool:
        return time.monotonic() >= _SOURCE_DISABLED_UNTIL.get(name, 0.0)

    @staticmethod
    def _disable_source(name: str, exc: Exception) -> None:
        _SOURCE_DISABLED_UNTIL[name] = time.monotonic() + SOURCE_COOLDOWN
        logger.warning("%s unavailable (%s); skipping it for %.0f s", name, exc, SOURCE_COOLDOWN)

    # -- the source chain ------------------------------------------------- #
    def _source_chain(self) -> List[Tuple[str, Callable[[str, str], pd.DataFrame]]]:
        chain: List[Tuple[str, Callable[[str, str], pd.DataFrame]]] = []
        if self.uses_fred:
            chain.append((SOURCE_FRED_API, self._download_from_fred))
        if self.public_sources and HAS_REQUESTS:
            if self.treasury_xml_dataset:
                chain.append((SOURCE_TREASURY_GOV, self._download_from_treasury_gov))
            if self.series:
                chain.append((SOURCE_FRED_CSV, self._download_from_fred_csv))
        return chain

    def download(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Download yield curve data for a window, trying each source in turn.

        Returns a DataFrame of decimal yields indexed by date; columns are
        maturities in years. ``last_source`` records which source answered.
        """
        start_date, end_date = self._get_date_range(start_date, end_date)
        key = (start_date, end_date)
        cached = self._cache.get(key)
        if cached is not None:
            self.last_source = self._sources.get(key)
            return cached.copy()

        frame: Optional[pd.DataFrame] = None
        source = SOURCE_SYNTHETIC
        for name, fetch in self._source_chain():
            if not self._source_available(name):
                continue
            try:
                candidate = fetch(start_date, end_date)
            except Exception as exc:  # noqa: BLE001 - degrade to the next source
                self._disable_source(name, exc)
                continue
            if candidate is not None and not candidate.empty:
                frame, source = candidate, name
                break
            logger.info("%s returned no rows for %s..%s", name, start_date, end_date)

        if frame is None:
            frame = self._create_synthetic_data(start_date, end_date)
            source = SOURCE_SYNTHETIC

        self._cache[key] = frame
        self._sources[key] = source
        self.last_source = source
        return frame.copy()

    # -- individual sources ----------------------------------------------- #
    def _download_from_fred(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch all configured series from FRED concurrently (needs an API key)."""
        fred = fredapi.Fred(api_key=self.api_key)

        def fetch(item: Tuple[str, str]) -> Tuple[str, Optional[pd.Series]]:
            label, series_id = item
            try:
                series = fred.get_series(series_id, observation_start=start_date, observation_end=end_date)
                return label, series / 100.0  # percent -> decimal
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to download %s (%s): %s", label, series_id, exc)
                return label, None

        with ThreadPoolExecutor(max_workers=min(8, max(1, len(self.series)))) as pool:
            results = list(pool.map(fetch, self.series.items()))

        data_dict = {self.maturity_mapping[label]: s for label, s in results if s is not None}
        if not data_dict:
            raise ValueError("No data could be downloaded from FRED")
        df = pd.DataFrame(data_dict).sort_index(axis=1)
        df.index = pd.to_datetime(df.index)
        return df.dropna(how="all")

    def _download_from_fred_csv(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch the configured series through FRED's public CSV export (no key)."""
        ids = list(self.series.values())
        text = self._http_get(
            FRED_CSV_URL, {"id": ",".join(ids), "cosd": start_date, "coed": end_date}
        )
        raw = parse_fred_csv(text)
        if raw.empty:
            raise ValueError("FRED CSV export returned no rows")
        by_id = {sid: label for label, sid in self.series.items()}
        columns = {}
        for col in raw.columns:
            label = by_id.get(str(col).strip().upper())
            if label is not None:
                columns[self.maturity_mapping[label]] = raw[col]
        if not columns:
            raise ValueError("FRED CSV export did not contain the requested series")
        frame = pd.DataFrame(columns).sort_index(axis=1)
        return frame.dropna(how="all")

    def _download_from_treasury_gov(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch the treasury.gov daily curve XML for each year in the window."""
        assert self.treasury_xml_dataset is not None
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        years = list(range(start.year, end.year + 1))
        if len(years) > 40:
            raise ValueError("Window too long for the treasury.gov feed")

        def fetch(year: int) -> pd.DataFrame:
            text = self._http_get(
                TREASURY_XML_URL,
                {"data": self.treasury_xml_dataset, "field_tdr_date_value": str(year)},
            )
            return parse_treasury_xml(text)

        with ThreadPoolExecutor(max_workers=min(6, len(years))) as pool:
            frames = [f for f in pool.map(fetch, years) if not f.empty]
        if not frames:
            raise ValueError("treasury.gov feed returned no rows")
        frame = pd.concat(frames).sort_index()
        frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
        wanted = sorted(set(self.maturity_mapping.values()))
        keep = [c for c in wanted if c in frame.columns]
        if len(keep) < 3:
            raise ValueError("treasury.gov feed lacks the expected tenors")
        return frame[keep].dropna(how="all")

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError("Subclasses must implement _create_synthetic_data")


# --------------------------------------------------------------------------- #
# Synthetic factor process shared by the synthetic generators
# --------------------------------------------------------------------------- #
SYNTHETIC_EPOCH = pd.Timestamp("1985-01-01")
SYNTHETIC_HORIZON = pd.Timestamp("2060-12-31")
_SYNTHETIC_CALENDAR = pd.date_range(SYNTHETIC_EPOCH, SYNTHETIC_HORIZON, freq="B")
_SYNTHETIC_FACTOR_CACHE: Dict[Tuple, pd.DataFrame] = {}


def _synthetic_ns_factors(
    dates: pd.DatetimeIndex,
    *,
    seed: int,
    level: float,
    slope: float,
    curvature: float,
    vol: Tuple[float, float, float],
    persistence: Tuple[float, float, float] = (0.999, 0.997, 0.994),
) -> np.ndarray:
    """Deterministic AR(1) Nelson-Siegel factor path (percent units), shape (n, 3).

    The path is simulated once from a fixed epoch on a business-day calendar
    and sampled at ``dates``, so overlapping windows agree exactly. The RNG is
    private so the global NumPy stream is untouched.
    """
    if len(dates) == 0:
        return np.empty((0, 3))
    key = (seed, level, slope, curvature, tuple(vol), tuple(persistence))
    frame = _SYNTHETIC_FACTOR_CACHE.get(key)
    if frame is None:
        calendar = _SYNTHETIC_CALENDAR
        rng = np.random.default_rng(seed)
        mean = np.array([level, slope, curvature])
        rho = np.array(persistence)
        sig = np.array(vol)
        n = len(calendar)
        x = mean + rng.normal(0, 1, 3) * sig * 5
        shocks = rng.normal(0, 1, (n, 3)) * sig
        path = np.empty((n, 3))
        for i in range(n):
            x = mean + rho * (x - mean) + shocks[i]
            path[i] = x
        # Slow cycles so multi-year samples show regime shifts, not just noise.
        t = np.arange(n) / 260.0
        path += np.column_stack([
            0.8 * np.sin(2 * np.pi * t / 5.5),
            0.9 * np.cos(2 * np.pi * t / 4.0),
            0.5 * np.sin(2 * np.pi * t / 3.0),
        ])
        frame = pd.DataFrame(path, index=calendar)
        _SYNTHETIC_FACTOR_CACHE[key] = frame
    sampled = frame.reindex(dates, method="ffill").bfill().ffill()
    return sampled.to_numpy()


def _ns_panel(
    dates: pd.DatetimeIndex,
    maturities: Sequence[float],
    factors: np.ndarray,
    tau: float,
    noise: float,
    seed: int,
) -> pd.DataFrame:
    """Yields (decimals) from factor paths plus calendar-anchored measurement noise."""
    from .model import NelsonSiegelModel  # local import to avoid a cycle at import time

    mats = np.asarray(maturities, dtype=float)
    X = NelsonSiegelModel.basis(mats, tau)
    yields = factors @ X.T
    if len(dates):
        rng = np.random.default_rng(seed + 7)
        all_noise = rng.normal(0, noise, (len(_SYNTHETIC_CALENDAR), len(mats)))
        noise_frame = pd.DataFrame(all_noise, index=_SYNTHETIC_CALENDAR)
        yields = yields + noise_frame.reindex(dates, method="ffill").bfill().ffill().to_numpy()
    return pd.DataFrame(yields / 100.0, index=dates, columns=list(maturities))


class TreasuryDataDownloader(BaseDataDownloader):
    """Downloads US Treasury constant-maturity (par) yields, 1M to 30Y."""

    series = {
        "1M": "DGS1MO",
        "3M": "DGS3MO",
        "6M": "DGS6MO",
        "1Y": "DGS1",
        "2Y": "DGS2",
        "3Y": "DGS3",
        "5Y": "DGS5",
        "7Y": "DGS7",
        "10Y": "DGS10",
        "20Y": "DGS20",
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
        "7Y": 7.0,
        "10Y": 10.0,
        "20Y": 20.0,
        "30Y": 30.0,
    }
    treasury_xml_dataset = "daily_treasury_yield_curve"

    def __init__(self, api_key: Optional[str] = None, **kwargs: object):
        super().__init__(api_key=api_key, default_start_days=3650, **kwargs)  # type: ignore[arg-type]
        self.treasury_series = self.series  # backward-compatible alias

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Deterministic synthetic Treasury panel driven by an AR(1) factor process."""
        dates = pd.date_range(start=start_date, end=end_date, freq="B")
        if dates.empty:
            dates = pd.date_range(start=start_date, end=end_date, freq="D")
        maturities = list(self.maturity_mapping.values())
        factors = _synthetic_ns_factors(
            dates, seed=42, level=4.2, slope=-1.4, curvature=-0.8, vol=(0.045, 0.05, 0.06)
        )
        frame = _ns_panel(dates, maturities, factors, tau=1.6, noise=0.02, seed=42)
        return frame.clip(lower=0.0001)

    _create_synthetic_treasury_data = _create_synthetic_data


class TIPSDataDownloader(BaseDataDownloader):
    """Downloads US TIPS (Treasury Inflation-Protected Securities) real yields."""

    series = {"5Y": "DFII5", "7Y": "DFII7", "10Y": "DFII10", "20Y": "DFII20", "30Y": "DFII30"}
    maturity_mapping = {"5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "20Y": 20.0, "30Y": 30.0}
    treasury_xml_dataset = "daily_treasury_real_yield_curve"

    def __init__(self, api_key: Optional[str] = None, **kwargs: object):
        super().__init__(api_key=api_key, default_start_days=3650, **kwargs)  # type: ignore[arg-type]
        self.tips_series = self.series

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Deterministic synthetic TIPS panel (real yields, may be negative)."""
        dates = pd.date_range(start=start_date, end=end_date, freq="B")
        if dates.empty:
            dates = pd.date_range(start=start_date, end=end_date, freq="D")
        maturities = list(self.maturity_mapping.values())
        factors = _synthetic_ns_factors(
            dates, seed=456, level=1.9, slope=-1.1, curvature=-0.4, vol=(0.04, 0.045, 0.05)
        )
        return _ns_panel(dates, maturities, factors, tau=2.2, noise=0.015, seed=456)

    _create_synthetic_tips_data = _create_synthetic_data


class PolicyRateDownloader(BaseDataDownloader):
    """Effective federal funds rate (FRED ``DFF``), the natural short-rate proxy."""

    series = {"DFF": "DFF"}
    maturity_mapping = {"DFF": 0.0}
    treasury_xml_dataset = None

    def __init__(self, api_key: Optional[str] = None, **kwargs: object):
        super().__init__(api_key=api_key, default_start_days=3650, **kwargs)  # type: ignore[arg-type]

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Step-shaped synthetic policy path consistent with the synthetic Treasury 1M yield."""
        treasury = TreasuryDataDownloader(public_sources=False)._create_synthetic_data(start_date, end_date)
        short = treasury[1 / 12].resample("W-WED").last().ffill()
        stepped = (short * 400).round() / 400  # 25 bp steps
        daily = stepped.reindex(pd.date_range(start_date, end_date, freq="D")).ffill().bfill()
        return pd.DataFrame({0.0: daily})

    def download_series(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.Series:
        """The policy rate as a decimal Series indexed by date."""
        frame = self.download(start_date, end_date)
        return frame.iloc[:, 0].rename("policy_rate")


class ACMBenchmarkDownloader(BaseDataDownloader):
    """
    New York Fed ACM term premia (Adrian, Crump and Moench), the published
    benchmark for this package's own ACM estimate.

    The series are redistributed by FRED as ``THREEFYTP1`` ... ``THREEFYTP10``
    (term premium on 1- to 10-year zero-coupon bonds, percent, daily), so they
    come through the FRED API or the key-less CSV export like any other series.
    There is no synthetic stand-in: offline the frame is empty, and callers
    should say the benchmark is unavailable rather than invent one.
    """

    series = {f"{n}Y": f"THREEFYTP{n}" for n in range(1, 11)}
    maturity_mapping = {f"{n}Y": float(n) for n in range(1, 11)}
    treasury_xml_dataset = None

    def __init__(self, api_key: Optional[str] = None, **kwargs: object):
        super().__init__(api_key=api_key, default_start_days=365 * 40, **kwargs)  # type: ignore[arg-type]

    def _create_synthetic_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """No synthetic benchmark: an empty frame with the expected columns."""
        return pd.DataFrame(columns=list(self.maturity_mapping.values()), index=pd.DatetimeIndex([]), dtype=float)


class FedGSWDownloader:
    """
    Federal Reserve Board Gurkaynak-Sack-Wright (2007) zero-coupon curve.

    The Board publishes daily Svensson parameters and fitted zero yields
    (1-30 years) since 1961 for nominal Treasuries, and since 1999 for TIPS.
    Being a fitted zero curve with decades of history, it is the natural input
    for affine term-premium models. No API key is required.

    ``download`` returns the full table (decimals, ``TAU`` columns in years);
    :meth:`zero_yields` evaluates the published parameters on any maturity grid.
    """

    def __init__(
        self,
        *,
        kind: str = "nominal",
        public_sources: Optional[bool] = None,
        timeout: float = 60.0,
        cache_dir: Optional[str] = None,
        cache_ttl_hours: float = 24.0,
    ):
        if kind not in {"nominal", "tips"}:
            raise ValueError("kind must be 'nominal' or 'tips'")
        self.kind = kind
        self.url = FED_GSW_NOMINAL_URL if kind == "nominal" else FED_GSW_TIPS_URL
        self.public_sources = public_data_enabled() if public_sources is None else bool(public_sources)
        self.timeout = timeout
        self.cache_dir = cache_dir if cache_dir is not None else os.environ.get(
            "NELSON_SIEGEL_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "nelson_siegel")
        )
        self.cache_ttl_hours = cache_ttl_hours
        self._table: Optional[pd.DataFrame] = None
        self.last_source: Optional[str] = None

    def _http_get(self, url: str) -> str:
        return http_get_text(url, timeout=self.timeout)

    def _cache_path(self) -> str:
        return os.path.join(self.cache_dir, f"gsw_{self.kind}.csv")

    def _read_disk_cache(self) -> Optional[str]:
        path = self._cache_path()
        try:
            age_hours = (time.time() - os.path.getmtime(path)) / 3600.0
            if age_hours <= self.cache_ttl_hours:
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
        except OSError:
            return None
        return None

    def _write_disk_cache(self, text: str) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_path(), "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:  # pragma: no cover - read-only home, etc.
            pass

    def clear_cache(self) -> None:
        self._table = None

    def download(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """Full GSW table for the window (all columns, decimals)."""
        if self._table is None:
            table: Optional[pd.DataFrame] = None
            if self.public_sources and HAS_REQUESTS:
                text = self._read_disk_cache()
                try:
                    if text is None:
                        text = self._http_get(self.url)
                        self._write_disk_cache(text)
                    table = parse_gsw_csv(text)
                    if table.empty:
                        table = None
                except Exception as exc:  # noqa: BLE001
                    logger.warning("GSW download failed (%s); using synthetic zero curve", exc)
            if table is None:
                table = self._create_synthetic_table()
                self.last_source = SOURCE_SYNTHETIC
            else:
                self.last_source = SOURCE_FED_GSW
            self._table = table
        table = self._table
        if start_date:
            table = table.loc[table.index >= pd.Timestamp(start_date)]
        if end_date:
            table = table.loc[table.index <= pd.Timestamp(end_date)]
        return table.copy()

    @property
    def is_synthetic(self) -> bool:
        return self.last_source in (None, SOURCE_SYNTHETIC)

    @staticmethod
    def _param_columns(table: pd.DataFrame) -> Optional[List[str]]:
        cols = ["BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2"]
        return cols if all(c in table.columns for c in cols) else None

    def zero_yields(
        self,
        maturities: Sequence[float],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Continuously-compounded zero yields (decimals) on ``maturities`` (years).

        Uses the published Svensson parameters when present (any maturity),
        otherwise falls back to the tabulated ``SVENY``/``TIPSY`` columns
        (integer years only, nearest available).
        """
        from .model import SvenssonModel

        table = self.download(start_date, end_date)
        mats = np.asarray(maturities, dtype=float)
        params = self._param_columns(table)
        if params is not None:
            P = table[params].to_numpy(dtype=float)
            ok = ~np.isnan(P[:, :3]).any(axis=1) & ~np.isnan(P[:, 4])
            out = np.full((len(table), len(mats)), np.nan)
            for i in np.where(ok)[0]:
                b0, b1, b2, b3, t1, t2 = P[i]
                if np.isnan(b3) or np.isnan(t2) or t2 <= 0:
                    from .model import NelsonSiegelModel

                    out[i] = NelsonSiegelModel.model_function(mats, b0, b1, b2, t1)
                else:
                    out[i] = SvenssonModel.model_function(mats, b0, b1, b2, b3, t1, t2)
            frame = pd.DataFrame(out, index=table.index, columns=list(mats))
            return frame.dropna(how="all")

        prefix = "SVENY" if self.kind == "nominal" else "TIPSY"
        cols = {}
        for m in mats:
            name = f"{prefix}{int(round(m)):02d}"
            if name in table.columns:
                cols[float(m)] = table[name]
        if not cols:
            raise ValueError("GSW table has neither parameters nor tabulated zero yields")
        return pd.DataFrame(cols).dropna(how="all")

    def _create_synthetic_table(self) -> pd.DataFrame:
        """Synthetic GSW-like table (monthly-ish daily data since 1990) with parameters."""
        dates = pd.date_range("1990-01-01", pd.Timestamp.today().normalize(), freq="B")
        if self.kind == "nominal":
            factors = _synthetic_ns_factors(
                dates, seed=2024, level=4.6, slope=-1.9, curvature=-1.0, vol=(0.04, 0.045, 0.05),
                persistence=(0.9995, 0.998, 0.995),
            )
            tau1, tau2 = 1.6, 9.0
        else:
            factors = _synthetic_ns_factors(
                dates, seed=2025, level=1.8, slope=-1.0, curvature=-0.5, vol=(0.035, 0.04, 0.045),
                persistence=(0.9995, 0.998, 0.995),
            )
            tau1, tau2 = 2.2, 10.0
        table = pd.DataFrame(index=dates)
        table["BETA0"] = factors[:, 0] / 100.0
        table["BETA1"] = factors[:, 1] / 100.0
        table["BETA2"] = factors[:, 2] / 100.0
        table["BETA3"] = 0.15 * factors[:, 2] / 100.0
        table["TAU1"] = tau1
        table["TAU2"] = tau2
        return table


class DataManager:
    """
    Manages every data source behind one interface and reports provenance.
    """

    def __init__(
        self,
        fred_api_key: Optional[str] = None,
        *,
        public_sources: Optional[bool] = None,
    ):
        """
        Parameters
        ----------
        fred_api_key : str, optional
            FRED API key. Without it, public key-less sources are used
            (unless disabled), then synthetic data.
        public_sources : bool, optional
            Override the environment default for key-less public feeds.
        """
        self.public_sources = public_data_enabled() if public_sources is None else bool(public_sources)
        kw = {"public_sources": self.public_sources}
        self.treasury_downloader = TreasuryDataDownloader(fred_api_key, **kw)
        self.tips_downloader = TIPSDataDownloader(fred_api_key, **kw)
        self.policy_downloader = PolicyRateDownloader(fred_api_key, **kw)
        self.acm_downloader = ACMBenchmarkDownloader(fred_api_key, **kw)
        self.gsw_downloader = FedGSWDownloader(kind="nominal", public_sources=self.public_sources)
        self.gsw_tips_downloader = FedGSWDownloader(kind="tips", public_sources=self.public_sources)

    @property
    def uses_fred(self) -> bool:
        return self.treasury_downloader.uses_fred

    @property
    def is_synthetic(self) -> bool:
        """True when the last Treasury download did not come from a live source."""
        return self.treasury_downloader.is_synthetic

    def clear_cache(self) -> None:
        """Drop memoised downloads on every downloader."""
        for dl in (self.treasury_downloader, self.tips_downloader, self.policy_downloader, self.acm_downloader):
            dl.clear_cache()
        self.gsw_downloader.clear_cache()
        self.gsw_tips_downloader.clear_cache()

    def source_summary(self) -> Dict[str, Optional[str]]:
        """Last source used by each dataset (``None`` until first download)."""
        return {
            "treasury": self.treasury_downloader.last_source,
            "tips": self.tips_downloader.last_source,
            "policy_rate": self.policy_downloader.last_source,
            "gsw": self.gsw_downloader.last_source,
            "acm_benchmark": self.acm_downloader.last_source,
        }

    def get_treasury_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """Treasury par yields (decimals) by maturity in years."""
        return self.treasury_downloader.download(start_date, end_date)

    def get_tips_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """TIPS real yields (decimals) by maturity in years."""
        return self.tips_downloader.download(start_date, end_date)

    def get_bond_data(self, bond_type: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """Dispatch on ``bond_type`` (``treasury`` or ``tips``)."""
        key = (bond_type or "treasury").lower()
        if key == "tips":
            return self.get_tips_data(start_date, end_date)
        if key == "treasury":
            return self.get_treasury_data(start_date, end_date)
        raise ValueError("bond_type must be 'treasury' or 'tips'")

    def get_policy_rate(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.Series:
        """Effective federal funds rate (decimal) as a daily Series."""
        return self.policy_downloader.download_series(start_date, end_date)

    def get_acm_benchmark(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """NY Fed ACM term premia (decimals) by maturity 1-10 years; empty when no live source answered."""
        return self.acm_downloader.download(start_date, end_date)

    def get_zero_curve(
        self,
        maturities: Sequence[float],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        kind: str = "nominal",
    ) -> pd.DataFrame:
        """GSW zero-coupon yields (decimals) on a maturity grid in years."""
        dl = self.gsw_downloader if kind == "nominal" else self.gsw_tips_downloader
        return dl.zero_yields(maturities, start_date, end_date)

    def get_all_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """Both Treasury and TIPS panels."""
        return {
            "treasury": self.get_treasury_data(start_date, end_date),
            "tips": self.get_tips_data(start_date, end_date),
        }


__all__ = [
    "ACMBenchmarkDownloader",
    "BaseDataDownloader",
    "DataManager",
    "FedGSWDownloader",
    "PolicyRateDownloader",
    "TIPSDataDownloader",
    "TreasuryDataDownloader",
    "SOURCE_LABELS",
    "SOURCE_FED_GSW",
    "SOURCE_FRED_API",
    "SOURCE_FRED_CSV",
    "SOURCE_SYNTHETIC",
    "SOURCE_TREASURY_GOV",
    "parse_fred_csv",
    "parse_gsw_csv",
    "parse_treasury_xml",
    "public_data_enabled",
    "reset_source_cooldowns",
]

"""
Nelson-Siegel Model Library

A Python library for yield curve modeling using the Nelson-Siegel methodology.
Supports both nominal Treasury and real TIPS yield curve analysis.
"""

__version__ = "1.2.0"
__author__ = "Economics Research Team"
__email__ = "research@example.com"

from .model import (
    NelsonSiegelModel,
    SvenssonModel,
    TIPSNelsonSiegelModel,
    TreasuryNelsonSiegelModel,
)
from .data import TreasuryDataDownloader, TIPSDataDownloader, DataManager
from .analysis import YieldCurveAnalyzer
from .plotting import YieldCurvePlotter

# Optional interactive components (requires ipywidgets)
try:
    from .interactive import (
        HAS_IPYWIDGETS,
        HistoricalFactorExplorer,
        InteractiveYieldCurveExplorer,
        create_yield_curve_tutorial,
    )
    HAS_INTERACTIVE = HAS_IPYWIDGETS
except ImportError:
    HAS_INTERACTIVE = False

# Optional web UI (requires Flask)
try:
    from .webapp import create_app, run_app
    HAS_WEBAPP = True
except ImportError:
    HAS_WEBAPP = False

__all__ = [
    "NelsonSiegelModel",
    "SvenssonModel",
    "TreasuryNelsonSiegelModel",
    "TIPSNelsonSiegelModel",
    "TreasuryDataDownloader",
    "TIPSDataDownloader",
    "DataManager",
    "YieldCurveAnalyzer",
    "YieldCurvePlotter",
]

if HAS_INTERACTIVE:
    __all__.extend([
        "InteractiveYieldCurveExplorer",
        "HistoricalFactorExplorer",
        "create_yield_curve_tutorial",
    ])

if HAS_WEBAPP:
    __all__.extend(["create_app", "run_app"])

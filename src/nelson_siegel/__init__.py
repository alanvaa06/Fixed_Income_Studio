"""
Nelson-Siegel Model Library / Fixed Income Studio

Yield-curve modelling (Nelson-Siegel, Svensson), Diebold-Li factor dynamics,
one-factor short-rate models (Vasicek, CIR), term premium analysis (ACM,
expectations-hypothesis decompositions, Campbell-Shiller / Fama-Bliss tests),
bond and curve analytics, and key-less public data sources.
"""

__version__ = "2.0.0"
__author__ = "Economics Research Team"
__email__ = "research@example.com"

from .model import (
    MODEL_REGISTRY,
    CurveModel,
    FactorMeta,
    NelsonSiegelModel,
    SvenssonModel,
    TIPSNelsonSiegelModel,
    TreasuryNelsonSiegelModel,
    get_model_class,
    list_models,
    make_model,
)
from .data import (
    DataManager,
    FedGSWDownloader,
    PolicyRateDownloader,
    TIPSDataDownloader,
    TreasuryDataDownloader,
)
from .short_rate import (
    SHORT_RATE_REGISTRY,
    CIRModel,
    ShortRateEstimate,
    ShortRateModel,
    VasicekModel,
    estimate_short_rate,
)
from .term_premium import (
    ACMTermPremiumModel,
    campbell_shiller,
    dns_term_premium,
    fama_bliss,
    short_rate_term_premium,
)
from .analytics import (
    Bond,
    bond_report,
    carry_roll_down,
    curve_spreads,
    forward_rate_table,
    key_rate_durations,
    pca_yield_changes,
    rich_cheap,
)
from .registry import get_any_model_class, list_all_models, make_any_model
from .analysis import YieldCurveAnalyzer
from .dynamic import DynamicNelsonSiegel, backtest
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
    "CurveModel",
    "FactorMeta",
    "MODEL_REGISTRY",
    "get_model_class",
    "list_models",
    "make_model",
    "NelsonSiegelModel",
    "SvenssonModel",
    "TreasuryNelsonSiegelModel",
    "TIPSNelsonSiegelModel",
    "TreasuryDataDownloader",
    "TIPSDataDownloader",
    "PolicyRateDownloader",
    "FedGSWDownloader",
    "DataManager",
    "YieldCurveAnalyzer",
    "DynamicNelsonSiegel",
    "backtest",
    "YieldCurvePlotter",
    "ShortRateModel",
    "VasicekModel",
    "CIRModel",
    "ShortRateEstimate",
    "SHORT_RATE_REGISTRY",
    "estimate_short_rate",
    "ACMTermPremiumModel",
    "dns_term_premium",
    "short_rate_term_premium",
    "campbell_shiller",
    "fama_bliss",
    "Bond",
    "bond_report",
    "carry_roll_down",
    "curve_spreads",
    "forward_rate_table",
    "key_rate_durations",
    "pca_yield_changes",
    "rich_cheap",
    "get_any_model_class",
    "list_all_models",
    "make_any_model",
]

if HAS_INTERACTIVE:
    __all__.extend([
        "InteractiveYieldCurveExplorer",
        "HistoricalFactorExplorer",
        "create_yield_curve_tutorial",
    ])

if HAS_WEBAPP:
    __all__.extend(["create_app", "run_app"])

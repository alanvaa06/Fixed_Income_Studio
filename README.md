# Nelson-Siegel Studio

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Web UI: Flask](https://img.shields.io/badge/web%20ui-flask-000000.svg)](https://flask.palletsprojects.com/)

A Python toolkit for **Nelson-Siegel yield-curve modelling** of nominal Treasury and real TIPS curves. Ships with a clean Python API, a Jupyter notebook, **and a single-page browser app** ("Nelson-Siegel Studio") for interactive curve fitting, parameter exploration, historical-factor analysis, and Treasury-vs-TIPS comparison.

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│ Market quotes│ ──▶ │ Nelson-Siegel fit │ ──▶ │ Curve + Risk │
└──────────────┘     │ β₀ β₁ β₂ τ        │     │ factors      │
                     └──────────────────┘     └──────────────┘
```

## Highlights

- **Modern web UI** &mdash; Flask + Plotly, dark theme, no build step required.
- **REST API** &mdash; programmatic access to fitting, snapshots, history, and comparison.
- **Treasury & TIPS** out of the box, with FRED-API hookup or realistic synthetic fallback.
- **Educational mode** &mdash; built-in "Learn the Model" tab, slider-based parameter lab, and curve-shape presets (normal / inverted / humped / flat).
- **Historical factor analysis** with breakeven inflation derived from the level differential.
- **Robust fitting** &mdash; profile-likelihood search over the decay parameter with closed-form betas (deterministic, no initial guess), fit diagnostics, instantaneous forward rates and discount factors.
- **Svensson extension** (`SvenssonModel`) built on the same fitting seam; see [`docs/audit-2026-09-02.md`](docs/audit-2026-09-02.md) for how to add further models.
- **Type-hinted**, **tested**, and **packaged** for `pip install -e .`.

## Table of contents

- [Quick start](#quick-start)
- [Web UI: Nelson-Siegel Studio](#web-ui-nelson-siegel-studio)
- [REST API](#rest-api)
- [Python API](#python-api)
- [Jupyter notebook](#jupyter-notebook)
- [Data sources](#data-sources)
- [Project layout](#project-layout)
- [Development](#development)
- [Best practices](#best-practices)
- [Acknowledgements](#acknowledgements)

## Quick start

```bash
# Clone and install with the web UI extras
git clone https://github.com/alanvaa06/nelson-siegel.git
cd nelson-siegel
pip install -e ".[webapp,data]"

# Launch the studio (opens browser on http://127.0.0.1:5000)
python scripts/run_webapp.py
```

To use **live FRED data**, export an API key first:

```bash
export FRED_API_KEY="your-key-here"   # Windows (PowerShell): $env:FRED_API_KEY="..."
python scripts/run_webapp.py
```

Without a key the app falls back to **realistic synthetic data**, so every feature still works for exploration and demos.

Charts load plotly.js from its CDN. For offline or locked-down networks, `pip install plotly` and the Studio serves the bundled copy locally instead (automatic, no configuration).

## Web UI: Nelson-Siegel Studio

A single-page application served by Flask. Five tabs:

| Tab | What you can do |
|---|---|
| **Curve Fitter** | Type in or paste market quotes (a paste box accepts `2Y 4.30`, `3M, 4.95%`, tab-separated, etc.), or click *Load latest snapshot*. Pick **Nelson-Siegel** or **Svensson**; the factor tiles adapt to the model. Shows the smooth fit, the implied forward curve, residuals in basis points, RMSE / R² badges, and exports the fitted table to CSV. |
| **Parameter Lab** | Drag sliders for β₀, β₁, β₂, τ (plus β₃, τ₂ for Svensson). Everything is computed in the browser, so it redraws instantly and overlays each factor's contribution and optionally the forward curve. Presets jump to **Normal / Inverted / Humped / Flat**; *Use last fit* copies the fitted parameters in. |
| **Historical Factors** | Quick-range chips (1Y-10Y) or custom dates; plots the factor series, the panel-estimated τ, and a per-date fit-RMSE chart that flags days the shape could not capture. CSV export. A **Forecast** panel fits Diebold-Li factor dynamics (random walk / AR(1) / VAR(1)), shows factor paths with 90% bands, the implied curve at the horizon, factor half-lives, and a rolling-origin **backtest** of the three forecasters. |
| **Treasury vs TIPS** | Aligns both curves on common dates, overlays the **breakeven inflation** spread (Treasury level − TIPS level), and reports level/slope/curvature correlations. CSV export. |
| **Learn the Model** | Plain-language tour of the equation, factors, curve shapes, and reading signals. |

### Run options

```bash
python scripts/run_webapp.py --host 0.0.0.0 --port 8080      # LAN access
python scripts/run_webapp.py --debug                          # auto-reload during dev
python scripts/run_webapp.py --no-browser                     # headless / CI
nelson-siegel-web                                             # console script (after install)
```

### Programmatic launch

```python
from nelson_siegel.webapp import create_app
app = create_app(fred_api_key="your-key")
app.run(host="0.0.0.0", port=5000)
```

Or mount it inside any WSGI/Gunicorn deployment:

```bash
gunicorn -w 2 -b 0.0.0.0:8000 "nelson_siegel.webapp.app:create_app()"
```

## REST API

All endpoints are JSON. Yields are returned in **percent** (e.g. `4.25`), maturities in **years**, residuals in **basis points**, and τ in **years**.

| Method & path | Purpose |
|---|---|
| `GET  /api/health` | Liveness check + whether a FRED key is configured |
| `GET  /api/models` | Registered curve models with their factor metadata (label, symbol, unit, hint) |
| `POST /api/fit` | Fit a model to user-supplied (maturity, yield) points. Body: `points`, `bond_type`, optional `model` (`nelson-siegel` default, or `svensson`). Returns a generic `factor_list`, RMSE, R² and the forward curve. |
| `POST /api/curve` | Evaluate the NS function at custom parameters (no fit); pass `beta3` and `tau2` to evaluate Svensson |
| `GET  /api/snapshot?bond_type=treasury\|tips&model=...` | Latest available curve + fitted factors |
| `GET  /api/historical?bond_type=...&start=YYYY-MM-DD&end=YYYY-MM-DD&model=nelson-siegel\|svensson` | Factor history (daily up to one year, weekly beyond) with per-date fit RMSE; generic `series` keyed by factor label |
| `GET  /api/compare?start=...&end=...` | Treasury vs TIPS factor history + breakevens |
| `GET  /api/forecast?bond_type=...&start=...&end=...&horizon=12&method=ar\|var\|rw&model=...` | Diebold-Li factor forecast with error bands, current vs forecast curve, persistence and half-lives |
| `GET  /api/backtest?bond_type=...&start=...&end=...&horizons=1,4,12&min_train=52&model=...` | Expanding-window out-of-sample RMSE (factors and yields) for random walk, AR(1), VAR(1) |

### Example: fit a curve via curl

```bash
curl -s -X POST http://127.0.0.1:5000/api/fit \
  -H "Content-Type: application/json" \
  -d '{
        "bond_type": "treasury",
        "yield_unit": "percent",
        "points": [
          {"maturity": 0.25, "yield": 4.95},
          {"maturity": 1,    "yield": 4.65},
          {"maturity": 5,    "yield": 3.95},
          {"maturity": 10,   "yield": 4.05},
          {"maturity": 30,   "yield": 4.35}
        ]
      }' | jq .factors
```

## Python API

```python
import numpy as np
from nelson_siegel import TreasuryNelsonSiegelModel, YieldCurveAnalyzer

# 1. Fit a single curve
model = TreasuryNelsonSiegelModel()
model.fit(
    maturities=np.array([0.25, 1, 2, 5, 10, 30]),
    yields=np.array([0.0495, 0.0465, 0.0430, 0.0395, 0.0405, 0.0435]),
)
print(model.get_factors())            # decimal units (0.04 == 4%)
print(model.predict([3, 7, 20]))      # yields at custom maturities
print(model.forward_rate([3, 7, 20])) # instantaneous forward rates
print(model.discount_factor([1, 10])) # exp(-t * y(t)), continuous compounding
print(model.fit_stats())              # sse, rmse, r_squared, decay_at_bound, ...

# Legacy joint non-linear least squares is still available:
model.fit(maturities, yields, method="curve_fit")

# Svensson (two decays, second curvature hump)
from nelson_siegel import SvenssonModel
svensson = SvenssonModel().fit(
    maturities=np.array([0.25, 1, 2, 5, 7, 10, 20, 30]),
    yields=np.array([0.0495, 0.0465, 0.0430, 0.0395, 0.0398, 0.0405, 0.0430, 0.0435]),
)
print(svensson.get_factors())         # Level, Slope, Curvature, Curvature2, Tau, Tau2

# Model registry / protocol: every model satisfies `CurveModel`
from nelson_siegel import CurveModel, list_models, make_model
assert isinstance(svensson, CurveModel)
print([m["id"] for m in list_models()])          # ['nelson-siegel', 'svensson']
model = make_model("nelson-siegel", bond_type="tips")   # bond-type preset bounds

# 2. High-level analyzer
analyzer = YieldCurveAnalyzer()
result  = analyzer.analyze_single_curve(
    "treasury",
    yields_data={1.0: 0.025, 2.0: 0.028, 5.0: 0.032, 10.0: 0.035, 30.0: 0.038},
)
print("RMSE (decimal):", result["rmse"])

# 3. Historical factors (one panel-estimated tau per bond type, closed-form
#    Level/Slope/Curvature per date, plus per-date fit RMSE)
factors = analyzer.analyze_historical_factors(
    "treasury", start_date="2022-01-01", end_date="2024-12-31",
)
factors[["Level", "Slope", "Curvature"]].plot()

# 4. Dynamic Nelson-Siegel (Diebold-Li): model the factors as AR(1)/VAR(1)
#    and project the curve forward through the same loadings
from nelson_siegel import DynamicNelsonSiegel, backtest
dns = DynamicNelsonSiegel(method="ar").fit(factors)
print(dns.summary()["half_life_steps"])          # shock half-lives per factor
paths = dns.forecast_factors(horizon=12)          # point forecasts + *_std bands
curves = dns.forecast_curve([1, 2, 5, 10, 30], horizon=12)
table = backtest(factors, horizons=(1, 4, 12), maturities=[1, 5, 10])  # vs random walk
```

Fitting notes:

- `fit()` profiles the sum of squared errors over &tau; on a log-spaced grid, solves &beta;<sub>0..2</sub> in closed form at each point, and refines the best local minima with a bounded search. It is deterministic and never worse (in SSE) than the legacy `curve_fit` path.
- &tau; is searched only where the curvature hump (&asymp; 1.8&tau;) falls inside the observed maturity range, which prevents the collinear blow-ups that otherwise appear on long-only curves. `fit_stats()["decay_at_bound"]` tells you when that constraint binds; set `model.hump_location_factor = None` to disable it.
- Historical factors follow the Diebold-Li convention: one decay set per (bond type, model), estimated on a sample of up to 48 curves, then a vectorised least-squares solve per date. Ranges longer than a year are resampled to weekly. Pass `model="svensson"` to `analyze_historical_factors`, `forecast_factors` or `backtest_factor_forecasts` for a two-hump history (needs at least six tenors per date).
- Downloads are memoised per date window on each downloader; call `analyzer.data_manager.clear_cache()` to refetch.

## Jupyter notebook

For a guided, classroom-style walkthrough:

```bash
pip install -e ".[interactive,data]"
jupyter lab examples/Nelson_Siegel_Interactive_Analysis.ipynb
```

The notebook covers the math, factor interpretation, ipywidgets-based explorers, and economic case studies (2008, COVID, etc.).

## Data sources

| Source | When it kicks in | Notes |
|---|---|---|
| **FRED** (`fredapi`) | `FRED_API_KEY` is set **and** `fredapi` is installed | Live daily Treasury (1M-30Y) + TIPS (5Y-30Y) series |
| **Synthetic** | Default fallback | Deterministic seeds; realistic curve shapes for demos & tests |
| **Custom** | Pass any `pandas.DataFrame` | Index = dates, columns = maturities (years), values = decimal yields |

A free FRED API key is available at <https://fred.stlouisfed.org/docs/api/api_key.html>.

## Project layout

```
.
├── src/nelson_siegel/
│   ├── model.py            # NS + Svensson models, profile fitter, forwards/discounts
│   ├── data.py             # FRED + synthetic data downloaders
│   ├── analysis.py         # YieldCurveAnalyzer (fit / history / compare)
│   ├── plotting.py         # matplotlib visualisations
│   ├── interactive.py      # ipywidgets explorers (Jupyter)
│   └── webapp/             # Flask UI + REST API
│       ├── app.py
│       ├── templates/index.html
│       └── static/{css,js}/
├── scripts/
│   ├── run_webapp.py       # one-line launcher
│   └── run_analysis.py     # CLI batch analysis
├── examples/               # basic_usage.py, legacy script, notebook
├── tests/                  # pytest suite
├── docs/                   # extended docs (installation, notebooks, 2026-09 audit)
└── BEST_PRACTICES.md       # contribution + production guidance
```

## Development

```bash
# 1. Editable install with dev + UI extras
pip install -e ".[dev,webapp,data]"

# 2. Run tests with coverage
pytest --cov=src/nelson_siegel --cov-report=term-missing

# 3. Quality gates
black  src/ tests/ scripts/
isort  src/ tests/ scripts/
mypy   src/nelson_siegel
flake8 src/nelson_siegel

# 4. Live-reloading web UI
python scripts/run_webapp.py --debug
```

A pre-commit config can run all of the above on every commit:

```bash
pre-commit install
```

## Best practices

See [`BEST_PRACTICES.md`](BEST_PRACTICES.md) for guidance on:

- Choosing maturities and yield-quote conventions
- Handling missing maturities and zero-bound yields
- Numerical stability of τ (decay parameter)
- Productionising the web UI (gunicorn, reverse proxy, secrets)
- Caching FRED responses
- Versioning factor outputs for downstream models

## Acknowledgements

- Nelson, C. R. and A. F. Siegel (1987). *Parsimonious Modeling of Yield Curves.* Journal of Business, 60(4), 473&ndash;489.
- Federal Reserve Bank of St. Louis &mdash; FRED API.
- Plotly.js, Flask, NumPy, SciPy, pandas &mdash; the open-source stack we stand on.

## License

[MIT](LICENSE) &copy; Economics Research Team

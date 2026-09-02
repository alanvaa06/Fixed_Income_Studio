# Nelson-Siegel Studio

[![CI](https://github.com/alanvaa06/Nelson_Siegel_Model/actions/workflows/ci.yml/badge.svg)](https://github.com/alanvaa06/Nelson_Siegel_Model/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Web UI: Flask](https://img.shields.io/badge/web%20ui-flask-000000.svg)](https://flask.palletsprojects.com/)

A Python toolkit for **parametric yield-curve modelling** of nominal Treasury and real TIPS curves: Nelson-Siegel and Svensson cross-section fits, Diebold-Li factor histories and forecasts, a clean Python API, a REST API, and a single-page browser app ("Nelson-Siegel Studio") for interactive fitting, parameter exploration, historical-factor analysis, forecasting, and Treasury-vs-TIPS comparison.

```
┌──────────────┐     ┌────────────────────┐     ┌──────────────────┐     ┌───────────────┐
│ Market quotes│ ──▶ │ Cross-section fit   │ ──▶ │ Factor history   │ ──▶ │ AR(1)/VAR(1)  │
│ (FRED/paste) │     │ β₀ β₁ β₂ [β₃] τ [τ₂]│     │ Level/Slope/Curv │     │ forecast      │
└──────────────┘     └────────────────────┘     └──────────────────┘     └───────────────┘
```

## Highlights

- **Robust fitting.** Profile-likelihood search over the decay parameter(s) with closed-form betas: deterministic, no initial guess, never worse in squared error than joint non-linear least squares, and restricted to the identifiable τ range so long-only curves cannot blow up into offsetting ±500% betas.
- **Two models on one seam.** `NelsonSiegelModel` and `SvenssonModel` share the fitter, diagnostics (`fit_stats()`), instantaneous **forward rates** and **discount factors**. A `CurveModel` protocol and a model registry make a third model a small drop-in.
- **Factor histories the Diebold-Li way.** One decay set per bond type and model, estimated on a panel of curves; then a vectorised least-squares solve per date with per-date fit RMSE.
- **Dynamic Nelson-Siegel.** Random walk / AR(1) / VAR(1) factor dynamics, forecasts with error bands, curve projection, half-lives, and a rolling-origin backtest.
- **Nelson-Siegel Studio.** Flask + Plotly, dark theme, no build step. Model switch, paste-in quotes, quick date ranges, forecast panel, CSV export, keyboard shortcuts, mobile layout, works offline when the `plotly` package is installed.
- **Data.** FRED (Treasury 1M-30Y, TIPS 5Y-30Y) fetched concurrently and memoised per window, with a deterministic synthetic fallback so every feature works without a key.
- **Tested and CI'd.** 114 pytest cases; GitHub Actions on Python 3.10-3.12.

## Table of contents

- [Quick start](#quick-start)
- [Web UI: Nelson-Siegel Studio](#web-ui-nelson-siegel-studio)
- [REST API](#rest-api)
- [Python API](#python-api)
- [How the models work](#how-the-models-work)
- [Data sources](#data-sources)
- [Project layout](#project-layout)
- [Development](#development)
- [Extending with new models](#extending-with-new-models)
- [References](#references)

## Quick start

```bash
git clone https://github.com/alanvaa06/Nelson_Siegel_Model.git
cd Nelson_Siegel_Model
pip install -e ".[webapp,data]"

# Launch the Studio (opens http://127.0.0.1:5000)
python scripts/run_webapp.py
```

To use **live FRED data**, export a key first (or paste it into the sidebar of the running app):

```bash
export FRED_API_KEY="your-key-here"   # PowerShell: $env:FRED_API_KEY="..."
python scripts/run_webapp.py
```

Without a key the app uses **deterministic synthetic data**, so every tab still works for exploration and demos.

Charts load plotly.js from its CDN. For offline or locked-down networks run `pip install plotly`; the Studio then serves the bundled copy locally, automatically.

## Web UI: Nelson-Siegel Studio

| Tab | What you can do |
|---|---|
| **Curve Fitter** | Type or paste market quotes (`2Y 4.30`, `3M, 4.95%`, tab-separated all work) or *Load latest snapshot*. Pick **Nelson-Siegel** or **Svensson**; the factor tiles adapt to the model. Shows the fitted curve, the implied forward curve, residuals in basis points, RMSE / R² badges, a warning when τ hits the search bound, and exports the fitted table to CSV. |
| **Parameter Lab** | Sliders for β₀, β₁, β₂, τ (plus β₃, τ₂ for Svensson). Computed in the browser, so it redraws instantly and overlays each factor's contribution and optionally the forward curve. Presets for **Normal / Inverted / Humped / Flat**; *Use last fit* copies fitted parameters in. |
| **Historical Factors** | Quick-range chips (1Y-10Y) or custom dates, Nelson-Siegel or Svensson. Plots the factor series, the panel-estimated decay(s), and a per-date fit-RMSE chart. The **Forecast** panel fits random-walk / AR(1) / VAR(1) dynamics, shows factor paths with 90% bands, the curve at the horizon, half-lives, and a rolling-origin **backtest** of the three forecasters. CSV export. |
| **Treasury vs TIPS** | Aligns both curves on common dates, overlays **breakeven inflation** (Treasury level − TIPS level), and reports level / slope / curvature correlations. CSV export. |
| **Learn the Model** | Plain-language tour of the equation, the factors, how the fitter works, and how to read the signals. |

Keyboard: `Alt+1` … `Alt+5` switch tabs; `Enter` in any quote cell fits. Bond type, model and date ranges persist in the browser.

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
app = create_app(fred_api_key="your-key")      # enable_warmup=False to skip the background prefetch
app.run(host="0.0.0.0", port=5000)
```

```bash
gunicorn -w 2 -b 0.0.0.0:8000 "nelson_siegel.webapp.app:create_app()"
```

## REST API

All endpoints are JSON. Yields are returned in **percent**, maturities in **years**, residuals in **basis points**, decays (τ) in **years**. `bond_type` is `treasury` (default) or `tips`; `model` is `nelson-siegel` (default) or `svensson`.

| Method & path | Purpose |
|---|---|
| `GET  /api/health` | Liveness check and whether a FRED key is configured |
| `GET  /api/models` | Registered models with factor metadata (label, symbol, unit, hint, minimum points) |
| `POST /api/fit` | Fit a model to `points: [{maturity, yield}]`. Returns `factor_list`, `factors`, fitted and observed yields, residuals, RMSE, R², `decay_at_bound`, and a smooth curve with forwards |
| `POST /api/curve` | Evaluate the function at custom parameters, no fit (add `beta3`, `tau2` for Svensson) |
| `GET  /api/snapshot?bond_type=&model=` | Latest available curve and its fit |
| `GET  /api/historical?bond_type=&start=&end=&model=` | Factor history (daily up to one year, weekly beyond), generic `series` by factor label, per-date RMSE |
| `GET  /api/forecast?bond_type=&start=&end=&horizon=12&method=ar\|var\|rw&model=` | Diebold-Li forecast: factor paths with std bands, current vs forecast curve, persistence, half-lives |
| `GET  /api/backtest?bond_type=&start=&end=&horizons=1,4,12&min_train=52&model=` | Expanding-window out-of-sample RMSE (per factor and across yields) for random walk, AR(1), VAR(1) |
| `GET  /api/compare?start=&end=` | Treasury vs TIPS factor histories, breakevens, correlations |
| `POST /api/fred-key` | Set the FRED key for the running process and restart the warm-up |

Example:

```bash
curl -s -X POST http://127.0.0.1:5000/api/fit \
  -H "Content-Type: application/json" \
  -d '{"bond_type": "treasury", "model": "svensson", "yield_unit": "percent",
       "points": [{"maturity": 0.25, "yield": 4.95}, {"maturity": 1, "yield": 4.65},
                  {"maturity": 2, "yield": 4.30}, {"maturity": 5, "yield": 3.95},
                  {"maturity": 10, "yield": 4.05}, {"maturity": 30, "yield": 4.35}]}' | jq .factors
```

## Python API

```python
import numpy as np
from nelson_siegel import (
    TreasuryNelsonSiegelModel, SvenssonModel, YieldCurveAnalyzer,
    DynamicNelsonSiegel, backtest, CurveModel, list_models, make_model,
)

# 1. Fit a single curve (yields as decimals: 0.04 == 4%)
maturities = np.array([0.25, 1, 2, 5, 10, 30])
yields = np.array([0.0495, 0.0465, 0.0430, 0.0395, 0.0405, 0.0435])
model = TreasuryNelsonSiegelModel().fit(maturities, yields)
print(model.get_factors())              # Level, Slope, Curvature, Tau
print(model.fit_stats())                # sse, rmse, r_squared, decay_at_bound, method, n_obs
print(model.predict([3, 7, 20]))        # yields at custom maturities
print(model.forward_rate([3, 7, 20]))   # instantaneous forwards d[t*y(t)]/dt
print(model.discount_factor([1, 10]))   # exp(-t * y(t)), continuous compounding
model.fit(maturities, yields, method="curve_fit")   # legacy joint NLS, still available

# 2. Svensson: two decays, a second hump, six or more quotes
svensson = SvenssonModel().fit(
    np.array([0.25, 1, 2, 5, 7, 10, 20, 30]),
    np.array([0.0495, 0.0465, 0.0430, 0.0395, 0.0398, 0.0405, 0.0430, 0.0435]),
)
print(svensson.get_factors())           # Level, Slope, Curvature, Curvature2, Tau, Tau2

# 3. Registry and protocol
assert isinstance(svensson, CurveModel)
print([m["id"] for m in list_models()])              # ['nelson-siegel', 'svensson']
tips_model = make_model("nelson-siegel", bond_type="tips")   # bond-type preset bounds

# 4. Factor history (one panel-estimated decay set per bond type and model)
analyzer = YieldCurveAnalyzer()                      # or YieldCurveAnalyzer(fred_api_key="...")
factors = analyzer.analyze_historical_factors("treasury", "2016-01-01", "2026-09-01")
factors[["Level", "Slope", "Curvature"]].plot()      # also Tau and per-date RMSE columns
svensson_hist = analyzer.analyze_historical_factors("treasury", "2016-01-01", "2026-09-01",
                                                    model="svensson")

# 5. Dynamic Nelson-Siegel (Diebold-Li)
dns = DynamicNelsonSiegel(method="ar").fit(factors)  # "var" or "rw" also available
print(dns.summary()["half_life_steps"])              # shock half-lives per factor
paths = dns.forecast_factors(horizon=12)             # point forecasts + <factor>_std
curves = dns.forecast_curve([1, 2, 5, 10, 30], horizon=12)
table = backtest(factors, horizons=(1, 4, 12), maturities=[1, 5, 10])   # vs random walk
result = analyzer.forecast_factors("treasury", horizon=12, method="var")  # one-call version

# 6. Single curve from the data source, with plots
snapshot = analyzer.analyze_single_curve("treasury")
comparison = analyzer.compare_curves("2022-01-01", "2026-09-01")   # Treasury vs TIPS
```

## How the models work

- **Nelson-Siegel**: `y(t) = β₀ + β₁·f₁(t,τ) + β₂·f₂(t,τ)` with `f₁ = (1 − e^{−t/τ})/(t/τ)` and `f₂ = f₁ − e^{−t/τ}`. **Svensson** adds `β₃·f₂(t,τ₂)`.
- **Fitting.** With the decays fixed, the model is linear in the betas. `fit()` evaluates a log-spaced grid over the decay(s), solves the betas by least squares at each point, refines the best local minima with a bounded search, and keeps the lowest error. If the betas violate the model's bounds it falls back to a bounded `curve_fit` warm-started from that solution (`fit_stats()["method"]` tells you which path ran).
- **Identifiable τ.** The curvature loading peaks at `t ≈ 1.8·τ`; by default the search only allows τ whose peak lies inside the quoted maturities. `fit_stats()["decay_at_bound"]` flags when that constraint binds; set `model.hump_location_factor = None` to disable it.
- **Historical factors.** The decays are estimated once per (bond type, model) by minimising the pooled squared error over a sample of up to 48 curves, then the betas are solved per date in one vectorised least-squares call. Ranges longer than a year are resampled to weekly. Svensson needs at least six tenors per date (Treasuries qualify, TIPS do not).
- **Dynamics.** The factor series are modelled as independent AR(1) processes (Diebold-Li's choice), a VAR(1), or a random walk, all by closed-form OLS. Forecasts iterate the transition, error bands accumulate the residual covariance, and curves come back through the same loadings. `backtest()` refits on an expanding window and reports out-of-sample RMSE per factor and across yields.
- **Units.** Yields are decimals inside the library and percent in the API and UI. Discount factors assume continuously compounded zero rates; FRED constant-maturity series are par yields, so treat them as an approximation.

## Data sources

| Source | When it kicks in | Notes |
|---|---|---|
| **FRED** (`fredapi`) | `FRED_API_KEY` is set (or pasted into the app) **and** `fredapi` is installed | Treasury DGS1MO-DGS30 and TIPS DFII5-DFII30, fetched concurrently and memoised per date window |
| **Synthetic** | Default fallback | Deterministic local RNG; realistic shapes for demos and tests |
| **Custom** | Pass any `pandas.DataFrame` | Index = dates, columns = maturities (years), values = decimal yields |

A free FRED API key is available at <https://fred.stlouisfed.org/docs/api/api_key.html>. Call `analyzer.data_manager.clear_cache()` to force a refetch.

## Project layout

```
.
├── src/nelson_siegel/
│   ├── model.py            # NS + Svensson, profile fitter, CurveModel protocol, registry
│   ├── analysis.py         # YieldCurveAnalyzer: history, forecasts, backtests, compare
│   ├── dynamic.py          # DynamicNelsonSiegel (rw / ar / var) and backtest()
│   ├── data.py             # FRED + synthetic downloaders with per-window memoisation
│   ├── plotting.py         # matplotlib visualisations
│   ├── interactive.py      # ipywidgets explorers (Jupyter)
│   └── webapp/             # Flask UI + REST API
│       ├── app.py
│       ├── warmup.py, _factors_cache.py
│       ├── templates/index.html
│       └── static/{css,js}/
├── scripts/                # run_webapp.py, run_analysis.py
├── examples/               # basic_usage.py, legacy script, notebook
├── tests/                  # pytest suite (model, analysis, dynamic, data, webapp, cache)
├── docs/                   # installation, notebooks, audit-2026-09-02.md
├── .github/workflows/      # CI on Python 3.10-3.12
└── BEST_PRACTICES.md
```

## Development

```bash
pip install -e ".[dev,webapp,data]"
python -m pytest -q               # coverage flags come from pyproject.toml; add --no-cov to skip
black src/ tests/ scripts/ && isort src/ tests/ scripts/
flake8 src/nelson_siegel
python scripts/run_webapp.py --debug
```

`pre-commit install` wires the formatters into every commit. The CI workflow runs the test suite on pushes to `main` and on pull requests.

## Extending with new models

Anything in the "linear in the betas once the decays are fixed" family needs only class attributes and three methods on a `NelsonSiegelModel` subclass (`param_names`, `n_linear`, `factor_labels`, `_factor_meta`; `basis`, `_forward_basis`, `model_function`), then a registry entry. Fitting, diagnostics, forward rates, factor histories, forecasts and the Studio's tiles follow automatically; `SvenssonModel` is the worked example. Non-parametric curves (splines, bootstraps) should implement the `CurveModel` protocol directly. `docs/audit-2026-09-02.md` records the assessment and the remaining seams.

## References

- Nelson, C. R. and A. F. Siegel (1987). *Parsimonious Modeling of Yield Curves.* Journal of Business, 60(4), 473–489.
- Svensson, L. E. O. (1994). *Estimating and Interpreting Forward Interest Rates: Sweden 1992-1994.* NBER Working Paper 4871.
- Diebold, F. X. and C. Li (2006). *Forecasting the Term Structure of Government Bond Yields.* Journal of Econometrics, 130(2), 337–364.
- Federal Reserve Bank of St. Louis, FRED API.
- Plotly.js, Flask, NumPy, SciPy, pandas.

## License

[MIT](LICENSE)

# Architecture

This document describes how the package is organised and how the pieces fit together, from data acquisition to the browser studio.

## Layers

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ webapp/            Flask REST API + single-page studio (templates, static)   │
├──────────────────────────────────────────────────────────────────────────────┤
│ analysis.py        YieldCurveAnalyzer: workflows that combine everything     │
├───────────────┬───────────────┬───────────────────┬──────────────────────────┤
│ model.py      │ short_rate.py │ term_premium.py   │ analytics.py             │
│ NS, Svensson  │ Vasicek, CIR  │ ACM, EH splits,   │ pricing, risk, carry,    │
│ profile fit   │ P/Q estimates │ CS/FB regressions │ forwards, spreads, PCA   │
├───────────────┴───────────────┴───────────────────┴──────────────────────────┤
│ dynamic.py         Diebold-Li factor dynamics and backtests                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ registry.py        One lookup across the parametric and short-rate families  │
├──────────────────────────────────────────────────────────────────────────────┤
│ data.py            Source chain: FRED API → treasury.gov → FRED CSV →        │
│                    synthetic; GSW zero curve; policy rate; provenance        │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Modules

### `model.py` - parametric curves
`NelsonSiegelModel` and `SvenssonModel` implement the `CurveModel` protocol (`fit`, `predict`, `forward_rate`, `discount_factor`, `get_factors`, `fit_stats`, `factor_meta`, `describe`). Fitting profiles the sum of squared errors over the decay parameter(s) with closed-form betas (`basis()` design matrix), then refines locally. `FactorMeta` carries presentation metadata (label, symbol, unit, hint) that the API and UI consume generically. `describe()` reports `family="parametric"` and `supports_history=True`.

### `short_rate.py` - one-factor short-rate models
`ShortRateModel` holds the shared machinery; `VasicekModel` and `CIRModel` supply the affine coefficients `A(t), B(t)` and the closed-form forward. `fit()` is a bounded multi-start least squares over `(r0, kappa, theta, sigma)`; `sigma` may be held fixed. `estimate_short_rate()` returns a `ShortRateEstimate` (physical `kappa, theta, sigma`, half-life, likelihood, Feller flag) by OLS on the exact discretisation or exact MLE. `simulate()` produces Monte Carlo paths; `expected_path()` and `expectations_yield()` feed the term-premium tools.

### `dynamic.py` - Diebold-Li dynamics
`DynamicNelsonSiegel` fits RW / AR(1) / VAR(1) to a factor history, forecasts factors with iterated error bands, maps them back to yields via the model's loadings; `backtest()` runs expanding-window comparisons.

### `term_premium.py`
- `ACMTermPremiumModel`: PCA factors → VAR(1) → excess-return regressions → prices of risk → affine recursions. Outputs fitted, risk-neutral and expected-short-rate yields, the term premium and convexity, over the whole panel.
- `dns_term_premium()`: expectations split using `DynamicNelsonSiegel` (short rate = loading at `t=0`, i.e. Level + Slope), linear in the factors so it evaluates over the full history.
- `short_rate_term_premium()`: observed yields minus the average expected short rate from a `ShortRateEstimate`.
- `campbell_shiller()`, `fama_bliss()`: regressions with Newey-West errors (`ols_newey_west`).
- Panel helpers: `zero_panel_from_factors`, `to_monthly`, `interpolate_maturities`.

### `analytics.py`
Model-agnostic: any object with `predict(maturities)` returning continuously compounded zero yields is a curve. `Bond` + `price_from_curve`, `yield_to_maturity`, `duration_convexity`, `z_spread`, `key_rate_durations` (tent bumps), `bond_report`; `carry_roll_down`, `forward_rate_table`, `curve_spreads` (from a curve or as time series from a panel), `rich_cheap`, `pca_yield_changes`, `curve_changes`.

### `data.py`
`BaseDataDownloader` runs a source chain per window and records `last_source`; failed public sources cool down process-wide for ten minutes. Pure parsers (`parse_treasury_xml`, `parse_fred_csv`, `parse_gsw_csv`) are unit-tested against fixtures. `FedGSWDownloader` caches the Fed table on disk and evaluates the published Svensson parameters on any maturity grid. `PolicyRateDownloader` provides the effective fed funds rate. `ACMBenchmarkDownloader` pulls the New York Fed ACM term premia (FRED `THREEFYTP1`-`THREEFYTP10`) through the same chain and deliberately has no synthetic fallback: offline it returns an empty frame and the UI says the benchmark is unavailable. `DataManager` fronts all of them and exposes `source_summary()`. Environment switches: `NELSON_SIEGEL_OFFLINE`, `NELSON_SIEGEL_PUBLIC_DATA`, `NELSON_SIEGEL_CACHE_DIR`.

Synthetic data is generated from a calendar-anchored AR(1) Nelson-Siegel factor process (fixed business-day calendar 1985-2060, private RNG), so overlapping windows agree exactly and the histories look like real regimes rather than noise.

### `analysis.py`
`YieldCurveAnalyzer` composes the modules into workflows used by the API:
- `analyze_historical_factors`, `forecast_factors`, `backtest_factor_forecasts`, `compare_curves` (as before);
- `short_rate_proxy` / `short_rate_analysis` (estimate, calibrate with the estimated volatility, simulate, term premium by tenor);
- `zero_curve_panel` / `term_premium_analysis` (ACM on GSW or on the app's own factor history, NY Fed ACM benchmark with per-maturity correlation and mean gap, Diebold-Li split, regressions);
- `curve_analytics` and `bond_analytics`.

### `registry.py`
`get_any_model_class`, `make_any_model`, `list_all_models` span `MODEL_REGISTRY` (parametric) and `SHORT_RATE_REGISTRY`. Only parametric models support vectorised factor histories; the API and UI read `supports_history` from `describe()`.

## Web application

`webapp/app.py` builds the Flask app (`create_app`). Historical factors are memoised in a `FactorsCache` (per-key concurrent dedup) and prefetched by a background warm-up; heavier results (short-rate, term-premium, analytics) go through a second cache keyed by request parameters. Responses keep dictionary order (`app.json.sort_keys = False`) and use stable maturity keys (`2`, `10`, `0.25`). Every data-backed payload includes `sources`, `is_synthetic` and `public_sources`.

The frontend has no build step:

```
templates/index.html                 shell (sidebar, topbar, tab partials, script tags)
templates/partials/*.html            one partial per tab
static/js/core.js                    window.Studio: theme + chart registry, settings, helpers, API wrapper,
                                     tab router (hash), data-provenance panel, model catalogue, boot()
static/js/{fitter,lab,historical,compare,shortrate,termpremium,analytics}.js
                                     each calls Studio.registerTab(name, {init, onShow})
static/js/main.js                    Studio.boot() on DOMContentLoaded
static/css/styles.css                design tokens for dark/light themes, components, responsive rules
```

Charts are rendered through `Studio.plot(id, traces, layout)`, which records the last render so a theme toggle re-draws every chart with the new palette. Tabs load lazily on first show. Settings persist in `localStorage`.

## Testing

`tests/conftest.py` forces offline mode. Coverage includes: model closed forms against finite differences, calibration recovery, estimator recovery from simulated paths, ACM recovery of a simulated affine economy's term premium, feed parsers and the source chain with mocked HTTP, analyzer workflows, and every REST endpoint including validation paths. A headless-browser smoke script (Playwright) was used during development to exercise every tab.

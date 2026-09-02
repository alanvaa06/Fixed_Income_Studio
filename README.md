# Fixed Income Studio (Nelson-Siegel Model)

[![CI](https://github.com/alanvaa06/Nelson_Siegel_Model/actions/workflows/ci.yml/badge.svg)](https://github.com/alanvaa06/Nelson_Siegel_Model/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Web UI: Flask](https://img.shields.io/badge/web%20ui-flask-000000.svg)](https://flask.palletsprojects.com/)

A Python toolkit and browser studio for **fixed-income analysis**, from the cross-section of the yield curve to the dynamics of the short rate and the term premium:

```
 Public data          Curve models              Dynamics                    Analysis
┌──────────────┐    ┌─────────────────────┐    ┌───────────────────────┐    ┌──────────────────────────┐
│ treasury.gov │    │ Nelson-Siegel       │    │ Diebold-Li AR/VAR     │    │ Term premium (ACM,       │
│ FRED (key or │ ─▶ │ Svensson            │ ─▶ │ Vasicek / CIR (P & Q) │ ─▶ │ EH splits, CS/FB tests)  │
│  public CSV) │    │ Vasicek, CIR        │    │ Monte Carlo paths     │    │ Carry, forwards, spreads │
│ Fed GSW      │    │ profile-likelihood  │    │ backtests             │    │ rich/cheap, PCA, bonds   │
└──────────────┘    └─────────────────────┘    └───────────────────────┘    └──────────────────────────┘
```

## Highlights

- **Four curve models on one seam.** `NelsonSiegelModel`, `SvenssonModel`, `VasicekModel` and `CIRModel` share the `CurveModel` protocol: `fit`, `predict`, `forward_rate`, `discount_factor`, `get_factors`, `fit_stats`. Parametric models use a deterministic profile-likelihood fitter; short-rate models use bounded multi-start least squares with closed-form bond prices.
- **Short-rate estimation.** Physical dynamics from a fed-funds or bill history by OLS on the exact discretisation or exact maximum likelihood (Gaussian for Vasicek, non-central chi-square for CIR); risk-neutral parameters from today's curve; expected paths under both measures; simulation fans.
- **Term premium analysis.** An Adrian-Crump-Moench (2013) affine model estimated with three regressions on a monthly zero panel (fitted, risk-neutral and expected-short-rate yields, term premium, convexity), a Diebold-Li expectations split, a short-rate-model split, and Campbell-Shiller / Fama-Bliss regressions with Newey-West errors.
- **Desk analytics.** Bond pricing off any curve, yield to maturity, Macaulay/modified duration, convexity, DV01, z-spread, key-rate durations, carry and roll-down, forward tables (1y1y, 5y5y ...), curve spreads and butterflies, rich/cheap ranking, PCA of yield changes, curve-change monitor.
- **Diebold-Li factor dynamics.** Random walk / AR(1) / VAR(1) on Nelson-Siegel or Svensson factor histories, forecasts with error bands, rolling-origin backtests.
- **Public data without a key.** FRED API when a key is set; otherwise the U.S. Treasury daily yield-curve XML, FRED's public `fredgraph.csv` export and the Fed Board's Gurkaynak-Sack-Wright zero-curve tables; every response reports which source answered. A calendar-anchored synthetic factor process keeps every feature working offline.
- **Fixed Income Studio.** Flask + Plotly, no build step: eight tabs, light/dark theme, mobile layout, CSV export, keyboard shortcuts, data-provenance panel.
- **Tested and CI'd.** 178 pytest cases run fully offline; GitHub Actions on Python 3.10-3.12.

## Table of contents

- [Quick start](#quick-start)
- [The Studio](#the-studio)
- [REST API](#rest-api)
- [Python API](#python-api)
- [Models](#models)
- [Data sources](#data-sources)
- [Project layout](#project-layout)
- [Development](#development)
- [References](#references)

## Quick start

```bash
git clone https://github.com/alanvaa06/Nelson_Siegel_Model.git
cd Nelson_Siegel_Model
pip install -e ".[webapp,data]"

python scripts/run_webapp.py          # opens http://127.0.0.1:5000
```

Without any configuration the app pulls the daily Treasury and TIPS curves from treasury.gov, the effective fed funds rate from FRED's public CSV export and the GSW zero curve from the Federal Reserve Board. A FRED API key (environment variable `FRED_API_KEY`, or pasted into the sidebar) switches the Treasury, TIPS and fed-funds series to the FRED API. When no source can be reached the app falls back to deterministic synthetic data and says so in a banner.

```bash
export FRED_API_KEY="your-key"              # optional
export NELSON_SIEGEL_OFFLINE=1              # never touch the network (tests do this)
export NELSON_SIEGEL_PUBLIC_DATA=0          # keep the FRED API, disable key-less feeds
export NELSON_SIEGEL_CACHE_DIR=~/.cache/ns  # where the GSW table is cached (24h)
```

Charts load plotly.js from its CDN; `pip install plotly` makes the Studio serve a local copy instead.

## The Studio

| Tab | What it does |
|---|---|
| **Curve Fitter** | Paste quotes or load the latest curve; fit Nelson-Siegel, Svensson, Vasicek or CIR. Fitted curve, instantaneous forwards, residuals, RMSE / R² badges, factor tiles, CSV export, hand-off to the Lab. |
| **Parameter Lab** | Sliders for β₀, β₁, β₂, τ (+ β₃, τ₂), computed in the browser with per-factor contributions, live read-outs (short end, long end, slope, hump location) and shape presets. |
| **Historical Factors** | Factor histories with panel-estimated decays, per-date fit RMSE, Diebold-Li forecasts with 90% bands and a rolling-origin backtest of random walk vs AR(1) vs VAR(1). |
| **Treasury vs TIPS** | Aligned nominal and real factor histories, breakeven inflation, factor correlations. |
| **Short-Rate Models** | Estimate Vasicek/CIR on fed funds or a bill (OLS or MLE), calibrate the same model to today's curve, compare the physical and risk-neutral long-run means, simulate 300 paths with quantile bands, and read the term premium by tenor. |
| **Term Premium** | ACM affine term premia on the Fed GSW zero curve (or this app's own factor history), overlaid on the New York Fed's published ACM series with correlation and mean-gap statistics, the Diebold-Li expectations split for comparison, a stacked yield decomposition (expectations + term premium + convexity) and Campbell-Shiller / Fama-Bliss tests. |
| **Curve Analytics** | Curve moves over 1D/1W/1M/3M/1Y, today vs 1M/1Y ago, carry and roll-down, forward table, spread and butterfly history, rich/cheap ranking, PCA loadings, and a bond calculator (price, yield, duration, convexity, DV01, z-spread, key-rate durations, cash flows). |
| **Learn** | Plain-language notes on every model, the term-premium decomposition, the analytics glossary and the data sources. |

Keyboard: `Alt+1` … `Alt+8` switch tabs, `Alt+T` toggles the theme, `Enter` in a quote cell fits. Settings persist in the browser; the URL hash points at the current tab.

### Run options

```bash
python scripts/run_webapp.py --host 0.0.0.0 --port 8080      # LAN access
python scripts/run_webapp.py --debug                          # auto-reload
python scripts/run_webapp.py --no-browser                     # headless / CI
gunicorn -w 2 -b 0.0.0.0:8000 "nelson_siegel.webapp.app:create_app()"
```

## REST API

All endpoints return JSON. Yields are in **percent**, maturities in **years**, spreads and residuals in **basis points**, decays in years. Every data-backed response carries `sources` (which feed served each dataset), `is_synthetic` and `public_sources`.

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness, version, data provenance |
| `GET /api/data-sources` | Provenance per dataset and the source chain |
| `GET /api/models` | Registered models (parametric and short-rate) with factor metadata |
| `POST /api/fit` | Fit any model to `points: [{maturity, yield}]`; returns factors, fitted/observed yields, discount factors, residuals, forwards |
| `POST /api/curve` | Evaluate Nelson-Siegel/Svensson at given parameters |
| `GET /api/snapshot?bond_type=&model=` | Latest curve and its fit |
| `GET /api/historical?bond_type=&start=&end=&model=` | Factor history |
| `GET /api/forecast?...&horizon=&method=` | Diebold-Li forecast |
| `GET /api/backtest?...&horizons=&min_train=` | Out-of-sample RMSE by forecaster |
| `GET /api/compare?start=&end=` | Treasury vs TIPS, breakevens |
| `GET /api/short-rate?model=vasicek\|cir&method=ols\|mle&proxy=policy\|1m\|3m\|6m\|1y&start=&end=&horizon=&paths=` | Physical estimate, calibrated model, history, simulation quantiles, expected paths, term premium by tenor |
| `GET /api/term-premium?source=gsw\|treasury\|tips&start=&end=&maturities=2,5,10&factors=3&max_maturity=10&dns_method=var` | ACM term premia and decomposition, NY Fed ACM benchmark with agreement statistics, Diebold-Li split, EH regressions |
| `GET /api/analytics?bond_type=&model=&horizon=&lookback=` | Curve changes, carry/roll-down, forwards, spreads (+history), rich/cheap, PCA |
| `POST /api/bond` | `{maturity, coupon, frequency, price?, model?, bond_type?, points?}` → price, YTM, z-spread, duration, convexity, DV01, key-rate durations, cash flows |
| `POST /api/fred-key` | Set the FRED key for the running process |

```bash
curl -s "http://127.0.0.1:5000/api/term-premium?source=gsw&start=2000-01-01&maturities=2,10" | jq .latest_term_premium
curl -s -X POST http://127.0.0.1:5000/api/bond -H "Content-Type: application/json" \
  -d '{"maturity": 10, "coupon": 4.0, "price": 98.5}' | jq '{ytm, modified_duration, z_spread_bps}'
```

## Python API

```python
import numpy as np
from nelson_siegel import (
    TreasuryNelsonSiegelModel, SvenssonModel, VasicekModel, CIRModel, estimate_short_rate,
    YieldCurveAnalyzer, DynamicNelsonSiegel, ACMTermPremiumModel, dns_term_premium,
    campbell_shiller, Bond, bond_report, carry_roll_down, curve_spreads, DataManager,
)

mats = np.array([0.25, 1, 2, 5, 10, 30])
ylds = np.array([0.0495, 0.0465, 0.0430, 0.0395, 0.0405, 0.0435])

# Curves (yields as decimals)
ns = TreasuryNelsonSiegelModel().fit(mats, ylds)
vas = VasicekModel().fit(mats, ylds)                 # r0, kappa, theta, sigma
print(ns.get_factors(), vas.get_factors(), vas.half_life())

# Short-rate dynamics from a history (weekly fed funds, decimals)
dm = DataManager()                                   # public feeds, or FRED with a key
ff = dm.get_policy_rate("2010-01-01").resample("W-FRI").last()
est = estimate_short_rate(ff, "cir", method="mle")   # kappa, theta, sigma, half-life, Feller
paths = est.as_model().simulate(horizon_years=5, n_paths=500)

# Term premium: ACM on the Fed GSW zero curve
analyzer = YieldCurveAnalyzer()
tp = analyzer.term_premium_analysis("gsw", "1990-01-01", maturities=(2, 5, 10))
print(tp["term_premium"].tail(), tp["regressions"]["campbell_shiller"]["10.0"])

# ... or directly on any monthly zero panel (columns = maturities in years)
acm = ACMTermPremiumModel(n_factors=3).fit(analyzer.zero_curve_panel("gsw", "1990-01-01"))
print(acm.decompose(10.0).tail())                    # observed, fitted, risk_neutral, expected_short_rate, term_premium, convexity

# Diebold-Li expectations split on the Nelson-Siegel factor history
factors = analyzer.analyze_historical_factors("treasury", "2015-01-01")
dns = DynamicNelsonSiegel("var").fit(factors)
print(dns_term_premium(dns, factors, [2, 5, 10])["term_premium"].tail())

# Desk analytics off the fitted curve
print(carry_roll_down(ns, horizon=1.0))
print(curve_spreads(ns))                             # 2s10s, 5s30s, 2s5s10s ... in bps
report = bond_report(Bond(maturity=10, coupon=0.04), ns, price=98.5)
print(report["ytm"], report["modified_duration"], report["key_rate_durations"])
```

## Models

**Nelson-Siegel / Svensson.** `y(t) = β₀ + β₁·f₁(t,τ) + β₂·f₂(t,τ) [+ β₃·f₂(t,τ₂)]`. Linear in the betas once the decays are fixed, so the fitter profiles the sum of squared errors over a decay grid with closed-form betas and refines locally: deterministic, no initial guess, restricted to the identifiable τ range. Historical factors reuse one decay set per bond type and model (Diebold-Li convention).

**Vasicek / CIR.** `dr = κ(θ − r)dt + σ dW` and `dr = κ(θ − r)dt + σ√r dW`. Bond prices `P(t) = exp(A(t) − B(t)·r)` are closed-form, hence yields, forwards and discount factors. Cross-section calibration identifies the risk-neutral drift (σ is weakly identified and bounded, or held at the time-series estimate); `estimate_short_rate` recovers the physical dynamics by OLS or exact MLE. `E[r_t]` and its running average give the expectations-hypothesis yield.

**Diebold-Li dynamics.** AR(1) / VAR(1) / random walk on the factors, iterated forecasts with error bands, curve projection through the same loadings, expanding-window backtests.

**ACM term premium.** Principal components of a monthly zero panel as pricing factors; VAR(1); excess returns regressed on innovations and lagged factors; prices of risk λ₀, λ₁; affine recursions with and without the prices of risk. Term premium = fitted − risk-neutral yield; the convexity term is the difference between the risk-neutral yield and the average expected short rate. Validated on a simulated affine economy in the tests.

**Expectations-hypothesis tests.** Campbell-Shiller (slope of future yield changes on the term spread; 1 under the EH) and Fama-Bliss (excess return on the forward spread; 0 under the EH), both with Newey-West standard errors matching the overlap.

## Data sources

| Source | Needs key | Used for |
|---|---|---|
| FRED API (`fredapi`) | yes | Treasury 1M-30Y (`DGS*`), TIPS 5Y-30Y (`DFII*`), effective fed funds (`DFF`) |
| U.S. Treasury daily yield-curve XML | no | Nominal par curve and real (TIPS) curve |
| FRED public `fredgraph.csv` | no | Any FRED series, same ids as above |
| Fed Board GSW tables (`feds200628.csv`, `feds200805.csv`) | no | Fitted Svensson parameters and zero yields since 1961 (nominal) / 1999 (TIPS) |
| NY Fed ACM term premia (FRED `THREEFYTP1`-`THREEFYTP10`) | no | Published Adrian-Crump-Moench premia, overlaid as a benchmark (no synthetic stand-in) |
| Synthetic | no | Calendar-anchored AR(1) factor process; deterministic, overlapping windows agree |

Each downloader tries FRED API → treasury.gov → FRED CSV → synthetic, memoises per window, cools a failed source down for ten minutes process-wide, and records `last_source`. `DataManager.source_summary()` and every API response expose the provenance.

## Project layout

```
src/nelson_siegel/
├── model.py          Nelson-Siegel, Svensson, CurveModel protocol, profile fitter, registry
├── short_rate.py     Vasicek, CIR, estimate_short_rate, simulation
├── dynamic.py        DynamicNelsonSiegel (RW/AR/VAR), backtest
├── term_premium.py   ACMTermPremiumModel, dns_term_premium, short_rate_term_premium,
│                     campbell_shiller, fama_bliss, panel helpers
├── analytics.py      Bond, pricing/risk, key-rate durations, carry/roll, forwards, spreads, PCA
├── registry.py       Unified model lookup across both families
├── data.py           Downloaders, public feeds, GSW, policy rate, synthetic, DataManager
├── analysis.py       YieldCurveAnalyzer: histories, forecasts, short-rate / term-premium / analytics workflows
├── plotting.py, interactive.py   Matplotlib and Jupyter helpers
└── webapp/           Flask app (app.py), templates/partials/*.html, static/js/*.js, static/css
tests/                178 offline tests (models, data feeds with mocked HTTP, term premium on a simulated affine economy, API)
```

## Development

```bash
pip install -e ".[webapp,data,dev]"
pytest -q --no-cov            # 178 tests, no network
python scripts/run_webapp.py --debug
```

`tests/conftest.py` sets `NELSON_SIEGEL_OFFLINE=1`, so the suite never contacts the network; the public feeds are covered with mocked HTTP responses in `tests/test_data_sources.py`.

## References

- Nelson, C. R. and Siegel, A. F. (1987). Parsimonious modeling of yield curves. *Journal of Business*.
- Svensson, L. E. O. (1994). Estimating and interpreting forward interest rates: Sweden 1992-1994. NBER WP 4871.
- Diebold, F. X. and Li, C. (2006). Forecasting the term structure of government bond yields. *Journal of Econometrics*.
- Vasicek, O. (1977). An equilibrium characterization of the term structure. *Journal of Financial Economics*.
- Cox, J. C., Ingersoll, J. E. and Ross, S. A. (1985). A theory of the term structure of interest rates. *Econometrica*.
- Adrian, T., Crump, R. K. and Moench, E. (2013). Pricing the term structure with linear regressions. *Journal of Financial Economics*.
- Campbell, J. Y. and Shiller, R. J. (1991). Yield spreads and interest rate movements: a bird's eye view. *Review of Economic Studies*.
- Fama, E. F. and Bliss, R. R. (1987). The information in long-maturity forward rates. *American Economic Review*.
- Gurkaynak, R. S., Sack, B. and Wright, J. H. (2007). The U.S. Treasury yield curve: 1961 to the present. *Journal of Monetary Economics*.

## License

MIT. See [LICENSE](LICENSE).

# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: recruiters, hiring managers and quant-minded readers who land on the Studio cold from a CV, a GitHub link or a LinkedIn post. They are evaluating the author (Alan Vaa) as much as the tool: rigour, taste, and whether the numbers can be trusted. Session is short, first viewport matters, they may never open a second tab.

Secondary (confirmed by the author): the author, as a working research and study tool for U.S. Treasury curve, short-rate and term-premium analysis.

## Product Purpose

Fixed Income Studio is a Python toolkit plus a Flask browser studio for fixed-income analysis: fit Nelson-Siegel, Svensson, Vasicek and CIR curves to live or public Treasury and TIPS data, run Diebold-Li factor dynamics, estimate physical and risk-neutral short-rate models, decompose long yields into expected short rates and an Adrian-Crump-Moench term premium, and compute desk analytics (duration, DV01, z-spread, carry, forwards, rich/cheap, PCA). Success: a reader trusts the numbers within a minute and can reproduce them from the REST or Python API.

## Positioning

Four curve models on one protocol, estimated from public data with no API key, with provenance on every number. The ACM term premium replicates the New York Fed series at correlation 1.000 (verified 2026-09-02 against the published xls). A neighbouring notebook or dashboard cannot truthfully claim the model breadth plus the provenance plus the offline-reproducible test suite.

## Operating Context

- Data: FRED API (with key), treasury.gov XML, FRED public CSV, Fed Board GSW tables, Fed Board Kim-Wright term premia. Synthetic calendar-anchored fallback when offline; the UI always says which source answered.
- Studio: eight tabs (Curve Fitter, Parameter Lab, Historical Factors, Treasury vs TIPS, Short-Rate Models, Term Premium, Curve Analytics, Learn). Plotly charts, CSV export, light/dark theme, mobile layout, Alt+N tab shortcuts, settings persisted in localStorage.
- Numbers are read in basis points and percent; correlations, RMSE, t-statistics and R-squared appear in tables. Monospace tabular numerals matter.
- Deployed as a local Flask app from a checkout; no hosted instance is assumed.

## Capabilities and Constraints

- Stack is fixed: Flask, Jinja partials, vanilla JS modules, one CSS file with custom-property tokens, Plotly loaded locally. No build step, no framework, no npm.
- Layout and typography are pinned for the current redesign: Inter for UI, JetBrains Mono for numbers, the sidebar plus tab-pane structure stay. Color tokens and surface material (gradients, glass, glows) are open.
- Light and dark themes must both remain; theme is toggled via `data-theme` on the root.
- Plotly chart colors are defined in `core.js` (`COLOR`, `SERIES`, per-theme axis/grid colors) and must move with any palette change; series must stay distinguishable at 7 lines.
- Console output must be ASCII (Windows). Test suite runs fully offline.
- Terminology follows the literature: bps, tenor, term premium, expectations hypothesis, GSW, Kim-Wright, ACM, Diebold-Li.

## Brand Commitments

- Name: "Fixed Income Studio", monogram "FI" in the sidebar brand mark. Sub-line "Curves · Rates · Premia".
- Voice: precise, literature-aware, no marketing adjectives; copy already reads like a rates desk.
- Author-stated constraint (2026-09-02): the result must not read as a generic dark SaaS or crypto dashboard (blue-purple, glows, neon on black). It should read as an instrument built by someone who knows the subject.

## Evidence on Hand

- Working live estimates from public data; 181 offline tests; CI on Python 3.10-3.12.
- Verified replication: 10y ACM term premium vs NY Fed ACM xls, corr 1.000, gap std 5 bps (scratch analysis 2026-09-02, not yet in the repo).
- No testimonials, users, customers or deployment claims exist. Do not invent any.
- Assets: none beyond the text monogram. No logo file, no photography.

## Product Principles

1. Provenance before polish: every number says where it came from and which model made it.
2. The literature's vocabulary, not the dashboard's: labels and units follow the papers.
3. Reproducible by construction: anything shown in the Studio is reachable from the REST and Python APIs offline.
4. Density with hierarchy: analysts want many numbers on one screen, but one answer per screen must lead.
5. Honest benchmarks: comparisons name the exact series and say when a gap is expected.

## Accessibility & Inclusion

Keyboard-operable controls with visible focus, WCAG AA contrast for text including muted labels and table headers, state announced for screen readers on long estimates. No product-specific standard beyond AA has been set.

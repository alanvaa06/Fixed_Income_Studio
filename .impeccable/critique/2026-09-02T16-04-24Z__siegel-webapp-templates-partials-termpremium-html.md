---
target: termpremium tab
total_score: 22
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
p2_count: 2
target_identity: "file:C:\\Users\\alanv\\OneDrive\\Documentos\\Investments\\Nelson_Siegel_Model\\src\\nelson_siegel\\webapp\\templates\\partials\\termpremium.html"
target_fingerprint: "sha256:b3e1e95ab3e92234f3925fa2f6846fce213ebe5b2bac23fc9c3c8a1775921d59"
target_path: "C:\\Users\\alanv\\OneDrive\\Documentos\\Investments\\Nelson_Siegel_Model\\src\\nelson_siegel\\webapp\\templates\\partials\\termpremium.html"
timestamp: 2026-09-02T16-04-24Z
slug: siegel-webapp-templates-partials-termpremium-html
---
# Critique: Term Premium tab (src/nelson_siegel/webapp/templates/partials/termpremium.html)

Method: dual-agent (A: design review sub-agent, B: detector/browser sub-agent), isolated, parallel. Surface mode: Operate.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of System Status | 2 | Results stay on screen unmarked after a control change or an error; feedback is a 3.8 s toast far from the controls |
| 2 | Match System / Real World | 4 | bps, %, rho, Newey-West t-stats, "t vs 1": rates-desk vocabulary throughout |
| 3 | User Control and Freedom | 2 | Every click persists silently to localStorage; no reset to defaults, no undo, no compare-two-runs |
| 4 | Consistency and Standards | 3 | Same grammar as Short-Rate tab; source note duplicates itself; segmented buttons have aria-pressed, chips do not |
| 5 | Error Prevention | 1 | Date inputs have no min/max, start-after-end not caught, Estimate enabled with zero tenors (silently runs 2/5/10) |
| 6 | Recognition Rather Than Recall | 2 | Factors -> ACM and RW/AR/VAR -> Diebold-Li mapping only explained 2400 px down |
| 7 | Flexibility and Efficiency | 2 | Alt+N tab shortcuts exist; no Enter-to-run, no URL deeplink of parameters, CSV export drops Diebold-Li and benchmark stats |
| 8 | Aesthetic and Minimalist Design | 2 | 21 controls in one wrapped strip, 7-8 equal-weight tiles, 9-12 item legend, nothing behind disclosure |
| 9 | Error Recovery | 1 | "Need at least 36 monthly observations" toast; field not marked invalid, focus not moved, stale chart stays |
| 10 | Help and Documentation | 3 | "How the estimate is built" is tight and correct, but below the fold and unlinked from the controls it explains |
| **Total** | | **22/40** | **Acceptable** |

## Design Specificity Verdict

**LLM assessment.** Authored for a fixed-income audience in content and controls: tenor chips, Fed GSW / Treasury NS / TIPS NS sources, rho-vs-benchmark tile, Campbell-Shiller and Fama-Bliss table, decomposition identity under the observed yield. The visual language is not: glassy gradient cards, blue-purple gradient CTA, radial glows, 11 px uppercase eyebrow labels. Swap the words and it serves a crypto dashboard unchanged. Composition is a flat stack of same-weight cards with no visual argument about what matters; the headline comparison (ours vs benchmark, 10Y) gets one tile and one table row.

**Deterministic scan.** Source scan ran in degraded regex mode (parser modules missing): 1 finding, overused font Inter at index.html:9. In-page detector (injected into the live tab) flagged 71 elements, 34 inside the Term Premium panel: 17 low-contrast (white on #6aa9ff at 2.4:1 on the active segmented buttons and the Estimate button; #6c7894 on #111728 at 4.0:1 on all 14 table headers), 8 tiny-text (11.5 px tile hints), 6 line-length (intro, decomposition note, four methodology bullets at 111-143 chars), 3 dark-glow. Sidebar: 18 more, mostly 10.5 px labels at 3.7:1. The detector missed the metric eyebrow labels because their tile background is a translucent gradient; measured by hand at 3.8-4.2:1. False positives: dark-glow on the accent (intentional token), tiny-text on a Plotly SVG annotation, thin-border-wide-shadow on the transient toast.

**Measured evidence (B).** 0 controls without an accessible name. Focus ring present on real keyboard Tab (global :focus-visible, 1.6 px effective at pane zoom). All 21 controls under 44 px in one dimension; chips 27 px tall. Mobile 375 px: body scrolls horizontally (scrollWidth 932) because the Plotly history chart had not relaid out 2 s after resize; controls wrap to 8 rows. Console: one 422 on the invalid-range request, nothing else.

**Where A and B agree:** muted label contrast (A estimated ~3.9:1, B measured 3.8-4.2:1); the controls wall (both counted 21); faint focus (A: barely visible on active chips; B: present but 1.6 px at 0.7 alpha). **Where they differ:** A saw no horizontal overflow on mobile, B measured it via the Plotly SVG; B's measurement stands, with the caveat that the chart may relayout later than 2 s.

**Visual overlays.** Overlays were drawn in the [Human] tab during Assessment B (71 elements). That tab has since been closed and the dev server stopped, so nothing remains visible.

## Overall Impression

The tab knows its subject and says so in the right units. It does not know what it is for. Replication of a published series, extension to TIPS and Nelson-Siegel sources, or teaching each want a different hero, and the layout refuses to pick. Biggest opportunity: make the benchmark comparison the headline for the focused tenor, and push model settings behind a disclosure.

Separate finding from the modelling investigation done alongside this critique: the series labelled "NY Fed ACM" everywhere on this tab is the Federal Reserve Board's Kim-Wright model (FRED THREEFYTP). Real NY Fed ACM lives in an xls on newyorkfed.org. That copy is factually wrong and needs fixing regardless of any design work.

## What's Working

1. **Domain-correct copy and units.** "Campbell-Shiller: slope = 1 under the EH (negative means premia move a lot)" and the decomposition line "yield 4.80 % = expected short rates 4.41 % + term premium 0.55 % + convexity -0.169 % (model error 1.2 bps)" make the model auditable by a student.
2. **Results persist during recompute.** Charts shimmer instead of blanking; combined with the warm cache, parameter exploration feels instant. Needs a stale cue to be safe.
3. **Structural consistency with sibling tabs.** Header, controls strip, tiles and cards mirror the Short-Rate tab exactly. Grammar learned once.

## Priority Issues

**[P1] Stale results are indistinguishable from fresh ones.** Deselecting the 7Y chip left a "7Y term premium +35 bps" tile on screen; setting start=2030 raised an error toast while the 1961-2026 chart and tiles stayed. Why: a screenshot of stale output is a wrong number in someone's deck. Fix: on any control change set data-stale on #tp-results, dim tiles and charts, show an inline strip "Settings changed. Estimate to refresh" next to the button; on error, same strip in error styling with a "Reset dates" action. Suggested command: $impeccable harden.

**[P1] Error handling is a transient toast with no field-level diagnosis.** No min/max on the date inputs, no client-side start<end check, no aria-invalid, focus never moves, raw 422 in the console. Why: a screen-reader user hears the toast once and cannot find the field; a sighted user watching the chart misses it. Fix: set min/max from the source coverage (1961-06-01 for GSW), validate start<end and >=36 months before the request, render the message inline under the controls with aria-describedby on the offending input and move focus to it. Toast only for success. Suggested command: $impeccable harden.

**[P1] The controls strip is a 21-item wall with unlabeled groups.** Source (3), Sample (4), two dates, Tenors (5), Factors (3), Dynamics (3), Estimate, in one flex-wrap row: 2 rows at 1440 px, 5 at mobile. Factors and RW/AR/VAR never say which model they drive. Why: chunking and minimal-choices both fail, and the Factors->ACM, Dynamics->Diebold-Li mapping is the most confusing thing on the page. Fix: two tiers. Always visible: Source, Sample and dates, Tenors, Estimate. Behind a "Model settings" disclosure: "ACM pricing factors 2/3/5" and "Diebold-Li dynamics RW/AR(1)/VAR(1)" with one-line captions. Label every group the way Tenors and Factors already are. Suggested command: $impeccable distill, then $impeccable layout.

**[P2] The core comparison has no single legible home, and its label is wrong.** Ours-vs-benchmark is split across a tile (rho 0.86, +7 bps), a table row (0.864, +7, RMSE 70) and a dash-dot line among 9-12 legend entries. Nothing states a verdict or shows the gap over time. And the benchmark is Kim-Wright, not ACM. Why: this is the primary task, "are we close and when did we diverge". Fix: for the focused tenor, a compact chart of ours minus benchmark in bps with a shaded +/-25 bps band, headed by a one-line verdict computed from existing stats. Default the history chart to the focused tenor only, cutting the legend to 2-3 items. Rename every "NY Fed ACM" string to "Fed Board Kim-Wright" with one sentence on why it is smoother (survey-anchored). Suggested command: $impeccable clarify, then $impeccable layout.

**[P2] Accessibility and contrast cluster.** Chips carry no aria-pressed (bindChips toggles a class only); results are never announced (only #toast and #fit-metrics are live regions); focus ring is 2 px at 0.7 alpha blue on blue-tinted active chips; #6c7894 labels and table headers sit at 3.8-4.2:1 at 11-12.5 px; white on #6aa9ff on primary and active buttons is 2.4:1; Plotly charts have no role or aria-label and no table equivalent; mobile body scrolls horizontally until the chart relays out; chips are 27 px tall. Fix: mirror aria-pressed in bindChips/setChips; wrap the tiles in an aria-live="polite" region with a one-sentence summary; double-ring focus (2 px accent plus 2 px background inner ring); lift the muted token to at least #8a94ad in dark; darken the accent fill or use dark text on active buttons; pass responsive: true and call Plotly.Plots.resize on the resize observer; raise chip min-height to 32 px. Suggested command: $impeccable audit, then $impeccable polish.

## Persona Red Flags

**Alex (power user).** Enter in a date input does nothing; no shortcut for Estimate; Alt+6 reaches the tab, then it is all mouse. One source per run, no compare-last-run. Export CSV drops Diebold-Li series, benchmark stats and regressions. Parameters live in localStorage, not the URL, so no deeplink to a colleague. Zero tenors selected silently runs 2/5/10. Two export affordances in two places (Plotly modebar PNG vs card-header CSV).

**Sam (screen reader, keyboard only).** Chips announce as "10Y, button" with no state. Eight tiles, two tables and two charts update silently after 15-30 s. Charts are unlabeled SVG; the decomposition sentence is the only textual path. Tables have no caption; headers "CS R2" and "Obs" are abbreviations. Error toast auto-dismisses in 3.8 s and focus never moves. Unverified: whether nav buttons announce their title ("Alt+1") instead of their text.

## Minor Observations

- Red tile for a negative 2Y premium is a sign, not a warning, yet red also means "bad" in the gap column. Use a neutral minus; reserve red for divergence.
- #tp-source-note renders "Fed GSW zero curve . Fed GSW zero curve (public)" (termpremium.js:139).
- "5 factors explain 100.0% of yields" is content-free at 5 PCs; show fit RMSE or only show explained variance when below 100.
- 7 tiles in a grid-4 leaves an orphan row of 3.
- Dates: tiles show ISO, native inputs show locale dd-Mon-yyyy.
- backdrop-filter blur on every card plus Plotly resize made screenshots time out repeatedly; the page is heavy.
- "Agreement with the NY Fed ACM estimate" is an h4 inside the "Term premium history" card; the benchmark is a sub-topic of the wrong card.
- Tablet 768 px: controls wrap to 3 rows and tiles to 2 columns, pushing the first chart below the fold.
- Light theme contrast is fine, but the blue glow on CTA and active segments reads heavier than the rest of the light UI.

## Questions to Consider

- If the NY Fed already publishes ACM, what is this tab for: replication, extension to TIPS and Nelson-Siegel sources, or teaching? The answer decides whether the benchmark is the hero or a footnote.
- Why expose Factors and RW/AR/VAR as primary controls when the explainer itself calls Diebold-Li a sanity check? Would defaults plus a drawer serve 95% of runs?
- Is a 65-year Max the right first impression? The 1961-1985 regime dominates the y-axis at 500 bps and squashes the last 15 years into a 100 px band. A Max sample with a 20-year default zoom would keep the estimate and fix the view.

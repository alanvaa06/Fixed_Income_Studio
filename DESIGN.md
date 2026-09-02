---
name: Fixed Income Studio
description: A statistical release, not a dashboard. White paper, near-black ink, hairline rules, one slate blue for every live element, tabular numerals.
colors:
  # paper (light theme, the default)
  paper: "#ffffff"
  paper-recessed: "#f4f5f7"
  hairline: "#d9dde3"
  hairline-strong: "#b9c0c9"
  chart-grid: "#e4e7eb"
  # ink
  ink: "#111111"
  ink-dim: "#3f4753"
  ink-muted: "#5b6470"
  # the one live color
  slate: "#1f4e79"
  slate-deep: "#17395a"
  on-slate: "#ffffff"
  slate-wash: "rgba(31, 78, 121, 0.10)"
  # semantics
  live-green: "#2e7d32"
  warn-ochre: "#8a5a00"
  danger-brick: "#b42318"
  down-red: "#c0392b"
  up-wash: "rgba(46, 125, 50, 0.12)"
  down-wash: "rgba(192, 57, 43, 0.12)"
  warn-wash: "rgba(138, 90, 0, 0.10)"
  danger-wash: "rgba(180, 35, 24, 0.10)"
  # charcoal (dark theme)
  charcoal: "#121417"
  charcoal-raised: "#16191d"
  charcoal-recessed: "#1e2227"
  hairline-dark: "#2c3138"
  hairline-strong-dark: "#3d434c"
  ink-dark: "#e8eaed"
  ink-dim-dark: "#b3b9c2"
  ink-muted-dark: "#8a929d"
  slate-lifted: "#6da4d8"
  slate-lifted-hover: "#86b6e2"
  on-slate-dark: "#0b0e12"
  slate-wash-dark: "rgba(109, 164, 216, 0.16)"
  # chart inks (Monetary Policy Report set, light theme; dark set in the sidecar)
  chart-treasury: "#2f6ea8"
  chart-tips: "#3a8f4a"
  chart-fitted: "#d97a1f"
  chart-purple: "#7d5aa6"
  chart-pink: "#a83279"
  chart-red: "#c8473a"
  chart-teal: "#2a9db0"
  chart-grey: "#8a949e"
typography:
  headline:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    letterSpacing: "-0.2px"
  numeral:
    fontFamily: "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace"
    fontSize: "22px"
    fontWeight: 600
    fontFeature: "tabular-nums"
  title:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 600
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  label:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  mono:
    fontFamily: "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    fontFeature: "tabular-nums"
  caption:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "11.5px"
    fontWeight: 400
rounded:
  xs: "3px"
  sm: "4px"
  md: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  grid: "14px"
  lg: "16px"
  xl: "20px"
  2xl: "32px"
components:
  button-default:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "9px 14px"
  button-default-hover:
    backgroundColor: "{colors.paper-recessed}"
  button-primary:
    backgroundColor: "{colors.slate}"
    textColor: "{colors.on-slate}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "9px 14px"
  button-primary-hover:
    backgroundColor: "{colors.slate-deep}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-dim}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "9px 14px"
  button-small:
    padding: "6px 10px"
  segmented-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink-dim}"
    typography: "{typography.control}"
    padding: "8px 13px"
  segmented-item-active:
    backgroundColor: "{colors.slate-wash}"
    textColor: "{colors.slate}"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink-dim}"
    rounded: "{rounded.sm}"
    padding: "6px 11px"
    height: "30px"
  chip-active:
    backgroundColor: "transparent"
    textColor: "{colors.slate}"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "8px 11px"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink-dim}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  nav-item-hover:
    backgroundColor: "{colors.paper-recessed}"
    textColor: "{colors.ink}"
  nav-item-active:
    backgroundColor: "transparent"
    textColor: "{colors.slate}"
  card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.md}"
  card-head:
    padding: "12px 20px"
  card-body:
    padding: "18px 20px 22px"
  metric:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.numeral}"
    rounded: "{rounded.md}"
    padding: "12px 16px 14px"
  callout:
    backgroundColor: "{colors.paper-recessed}"
    textColor: "{colors.ink-dim}"
    rounded: "{rounded.sm}"
    padding: "12px 16px"
  badge:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-dim}"
    typography: "{typography.caption}"
    rounded: "{rounded.sm}"
    padding: "3px 9px"
  brand-mark:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.slate}"
    rounded: "{rounded.sm}"
    size: "42px"
  toast:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "12px 16px"
---

# Design System: Fixed Income Studio

## Overview

**Creative North Star: "The Statistical Release"**

The Studio is set like a Federal Reserve statistical release, not like a dashboard. Everything sits on pure white paper in near-black ink; regions are separated by 1 px hairline rules rather than by tone, shadow or fill; and a single slate blue is the only color allowed to mean "live": links, focus edges, the active tab, the selected chip, the range-slider thumb, and one filled Estimate button per viewport. Nothing glows, nothing is blurred, nothing carries a gradient. The reader is meant to recognise a document they already trust before they read a single number.

Density is high but ordered: eight tabs share one shell, each opening with a title and a one-paragraph brief, then a controls strip, then a row of ruled metric tiles carrying monospace numerals, then charts. Type stays small and steady (nothing above 22 px) so the numbers, not the chrome, carry the weight. Chart inks follow the Monetary Policy Report set of seven, chosen so seven lines stay apart on both paper and charcoal. The dark theme is the same document printed on neutral charcoal; it is never tinted, and the slate lifts one step so it keeps reading as ink.

Confirmed rejections: the build refuses the dark-SaaS arrangement of glowing cards on a gradient, blue-purple accent pairs, glass or blur, and any accent that decorates rather than signals.

**Key Characteristics:**
- White paper, near-black ink, 1 px hairline rules; two shades of hairline (region vs control).
- One live color. Slate blue owns every interactive state; only the primary button is filled with it.
- Active states are drawn in accent ink or a 10% wash on paper, never as a solid fill.
- Every measured quantity is set in JetBrains Mono with tabular numerals; prose and labels in Inter.
- No shadows, no blur, no gradients except a 4% loading shimmer; depth is a second, slightly recessed paper.
- Squared corners: 4 px on controls, 6 px on cards and metric tiles.
- Icons are one inline SVG sprite, 16 px, 1.75 stroke, round caps.
- Dark theme is neutral charcoal with the same rules and a lifted accent.

## Colors

A monochrome document with exactly one live hue, a small set of semantic inks kept to signal-only duty, and a seven-ink chart palette borrowed from the Monetary Policy Report.

### Primary
- **Slate** (`{colors.slate}`): the one live color. Link text, focus outline (2 px), the active nav item's text and border, the active segmented item's text, the selected chip's text and border, the slider thumb, the brand-mark border and monogram, `::selection`, and the fill of the primary button. In the dark theme it becomes **Slate Lifted** (`{colors.slate-lifted}`) with **On Slate Dark** (`{colors.on-slate-dark}`) ink so the filled button stays legible on charcoal.
- **Slate Deep** (`{colors.slate-deep}`): primary-button hover only; dark counterpart **Slate Lifted Hover** (`{colors.slate-lifted-hover}`).
- **Slate Wash** (`{colors.slate-wash}`): the 10% tint behind the active segmented item, the only place slate appears as a surface other than the primary button. Dark counterpart `{colors.slate-wash-dark}` at 16%.

### Neutral
- **Paper** (`{colors.paper}`): page, sidebar, cards, metric tiles, inputs, buttons, toast. There is one paper; `--bg-0`, `--bg-1`, `--card` and `--sidebar` all resolve to it in light mode.
- **Paper Recessed** (`{colors.paper-recessed}`): the only second tone. Hover fill for buttons, nav items and chips; background of callouts, formula blocks, inline `code`, `kbd`, and slider readouts. It says "reference, not primary" without a rule.
- **Hairline** (`{colors.hairline}`): the region rule. Card edges and card-head divider, sidebar right edge, nav-group separators, page-head underline, table row rules, callout and formula edges.
- **Hairline Strong** (`{colors.hairline-strong}`): the control rule. Button, input, chip, segmented, badge and toast borders, sticky table-header underline, slider track, dashed provisional zones, link underline at rest.
- **Chart Grid** (`{colors.chart-grid}`): Plotly gridlines only; one step lighter than the region hairline so the grid recedes behind the series. Zero line uses Hairline Strong.
- **Ink** (`{colors.ink}`): headings, body, values, button text, observed-point markers in charts.
- **Ink Dim** (`{colors.ink-dim}`): briefs, metric labels, table headers, nav items at rest, ghost buttons, chart axis text.
- **Ink Muted** (`{colors.ink-muted}`): captions, nav-group headers, metric hints, status labels, footer.
- **Charcoal / Charcoal Raised / Charcoal Recessed** (`{colors.charcoal}` / `{colors.charcoal-raised}` / `{colors.charcoal-recessed}`): the dark theme's page, card and hover surfaces, with **Hairline Dark**, **Hairline Strong Dark** and the three dark inks playing the same roles as their light counterparts. All are neutral greys; none carries a blue cast.

### Semantic
- **Live Green** (`{colors.live-green}`): the "live data" status dot and source labels, positive/best table cells, the `ok` badge border, toast success edge.
- **Warn Ochre** (`{colors.warn-ochre}`): synthetic-data status and banner, stale-results notice, `warn` badge, attention outline on a button. Always paired with **Warn Wash** as its surface.
- **Danger Brick** (`{colors.danger-brick}`): validation errors, invalid input borders, error notices and toasts, row-delete hover. Paired with **Danger Wash**.
- **Down Red** (`{colors.down-red}`): negative numerals, heat-map "down" cells, "rich" pills. Distinct from Danger so a negative number never reads as an error.
- **Up / Down / Warn / Danger Wash**: 10-12% tints used only behind semantic content (heat cells, cheap/rich pills, stale and error notices). Never as decoration.

### Chart Inks
Seven Monetary Policy Report inks in a fixed series order: Treasury slate, TIPS green, purple, fitted orange, pink, teal, grey (`{colors.chart-treasury}`, `{colors.chart-tips}`, `{colors.chart-purple}`, `{colors.chart-fitted}`, `{colors.chart-pink}`, `{colors.chart-teal}`, `{colors.chart-grey}`), plus a brick red (`{colors.chart-red}`) for named-series use. The dark theme lifts each one step (values in the sidecar). Observed points are drawn in the theme's Ink; chart paper matches the card.

### Named Rules
**The One Live Color Rule.** Slate is the only hue that may signal interactivity or currency. If a second accent seems necessary, the answer is a hairline, a weight change, or a semantic ink, never a new hue.

**The Ink-Not-Fill Rule.** Active and selected states are drawn as slate text plus a slate 1 px border (nav, chip) or a 10% slate wash (segmented), on paper. The primary button is the single filled slate element allowed above the fold.

**The Neutral Charcoal Rule.** The dark theme is the same document on grey paper. Surfaces and hairlines stay neutral; only the accent and semantic inks lift one step for contrast. No tinted blacks, no blue-black.

**The Seven Inks Rule.** Chart series take the MPR inks in `SERIES_ORDER`, per theme, via `seriesColor(i)`. Series colors never come from the UI palette and UI accents never come from the chart set.

## Typography

**Headline Font:** Inter (with the system sans stack)
**Body Font:** Inter (with the system sans stack)
**Numeral/Mono Font:** JetBrains Mono (with `ui-monospace`, Menlo, Consolas)

**Character:** A quiet sans for prose and labels, a monospace for anything that is a measurement. The pairing is deliberately unremarkable so the numbers read as data rather than as display type. Both faces are pinned by the author for this redesign.

### Hierarchy
- **Headline** (700, 22px, -0.2px tracking): the tab title in `.page-head h2`. The largest type in the Studio.
- **Numeral** (600, 22px, tabular): the metric-tile value, set in JetBrains Mono. Shares the 22 px ceiling with the headline so a number is never louder than the page it sits on. Negative values take Down Red.
- **Title** (600, 14px): card headings (`.card-head h3`), subheads, status values (600, 13px). The sidebar brand line is a one-off at 700, 15px.
- **Body** (400, 14px, 1.5): base size on `html`. Briefs and notes step to 13px / 12.5px in Ink Dim; the page brief is capped at 720px wide.
- **Control** (500, 13px): buttons, inputs, segmented items, chips (12px), nav items (13.5px, 600 when active). Small buttons drop to 12px.
- **Label** (400-500, 12px): metric labels, table headers (500), form labels, card-head captions.
- **Mono** (400, 12.5-13px, tabular): table numerals (`td.num`), quote-table inputs, slider readouts, badges carrying numbers (11.5px), `kbd` (11px), paste textarea.
- **Caption** (400, 11-11.5px): nav-group headers, status labels, source list, badges, pills (600).

### Named Rules
**The Measured-in-Mono Rule.** Anything that is a quantity (metric values, table numerics, badge numbers, parameter readouts, tenors in code) is set in JetBrains Mono with `tabular-nums`. Anything that names or explains is set in Inter. Never mix the two inside one number.

**The 22-Point Ceiling Rule.** No type exceeds 22px. Hierarchy comes from weight (400 / 500 / 600 / 700), color (Ink / Ink Dim / Ink Muted) and hairline rules, not from size jumps.

**The No-Eyebrow Rule.** There are no uppercase tracked labels anywhere in the build; `.metric .sym` explicitly resets `text-transform` and `letter-spacing`. Labels are sentence case at 11-12px in Ink Dim or Ink Muted.

## Layout

The shell is a two-column CSS grid: a 264px sidebar (`--sidebar-w`) and a fluid main column, on a page of minimum 100vh. The sidebar is sticky, full height, padded 20px 16px, and ruled from the main column by a single right-hand hairline; collapsing it (`body.sidebar-collapsed`) narrows the track to 76px and hides labels, leaving icon-only nav items centred at 10px padding. The main column is padded 22px 32px 60px and capped at 1560px; it does not centre, so the release reads left-anchored like a printed page.

Each tab pane opens with a `.page-head`: title and brief left (brief max 720px), actions right, aligned to the baseline, closed by a hairline with 16px padding and 20px margin below. Content then flows as cards stacked with 20px between them, or as `.grid` rows of 2 to 6 equal columns (plus a 2fr/1fr variant) with a 14px gutter. Metric tiles live in `grid-4` and `grid-6` rows above the first chart.

Spacing rhythm as built: 2-4px inside dense lists, 6-8px between siblings inside a control group, 10-14px between controls and between grid columns, 16-20px between regions, 32px for the main column's horizontal margin. Card interiors are 12px 20px for the head and 18px 20px 22px for the body.

Charts are fixed-height regions: 220px (`small`), 360px (default), 460px (`tall`, 380px under 900px).

Responsive collapse, in order: at 1400px `grid-6` drops to 3 columns; at 1300px `grid-5` to 3; at 1100px two-column grids go single, three- and four-column go to 2, and main padding tightens to 18px 22px; at 900px the sidebar becomes an off-canvas drawer (`min(320px, 86vw)`, slides in 0.2s) behind a flat 35% ink scrim, a Menu button appears in the topbar, main padding drops to 14px 16px, and the page-head actions take full width; at 640px every remaining multi-column grid settles at two columns. The bond form goes to two columns at 900px.

Motion is minimal and functional: 0.15s ease on hover colour and border changes, 0.2s ease on theme swap, pane fade-in and sidebar slide, 0.25s for the toast, a 0.7s linear spinner on busy buttons, and a 1.2s shimmer on loading charts. `prefers-reduced-motion` removes the fade and the shimmer.

## Elevation & Depth

This system has no shadows. There is no `box-shadow` declaration anywhere in the stylesheet, no `backdrop-filter`, and the only gradient is the 4% ink shimmer that sweeps a chart while it loads. Depth is conveyed by two things only: 1 px hairline rules that enclose or divide regions, and a single recessed paper tone (`{colors.paper-recessed}`) for surfaces that are reference rather than primary (callouts, formula blocks, code, hover fills). The mobile drawer sits over a flat 35% ink scrim (55% on charcoal), not a blur.

### Named Rules
**The No-Shadow Rule.** Nothing casts a shadow, at rest or on hover. If an element needs to separate from its surroundings, give it a hairline or set it on recessed paper.

**The Two-Papers Rule.** There are exactly two surface tones per theme: paper and recessed paper. A third tone is not a design decision available to new surfaces.

## Shapes

Squared, ruled, and quiet. Controls (buttons, inputs, chips, segmented groups, badges, nav items, status and API-key cards, callouts, toast, brand mark) take a 4px corner; cards and metric tiles take 6px; inline `code`, `kbd` and chart-offline code take 3px. Every enclosed shape carries a 1 px border in Hairline (regions) or Hairline Strong (controls); no shape is defined by fill alone except the primary button and the semantic pills.

Provisional or optional zones (the paste panel, the chart-offline placeholder) use a dashed Hairline Strong border, the release's way of marking a field the reader may fill or ignore. Circles appear only where they are semantic: the 8-9px status dot, the 16px slider thumb, the 12px busy spinner. The brand mark is a 42px square with a slate border and slate monogram on paper, the ruled-monogram idiom that keeps the primary button as the only filled slate element in the first viewport.

## Components

### Buttons
Flat, ruled, and text-led; the primary is the one filled element.
- **Shape:** squared corners (4px), 1 px border, inline-flex with a 6px icon gap; icons inside buttons are 14px.
- **Default:** paper background, Ink text, Hairline Strong border, 9px 14px padding, 13px/500. Hover fills with recessed paper and darkens the border to Ink Muted.
- **Primary:** Slate fill, On Slate text, Slate border. Hover to Slate Deep. One per viewport (the estimate/fit/apply action).
- **Ghost:** transparent, Ink Dim text, Hairline border. Hover brings text to Ink, border to Hairline Strong, recessed-paper fill. Used for secondary actions (Export CSV, Reset, Cancel, theme toggle, Menu).
- **Small:** 6px 10px padding at 12px; the card-tools and sidebar size.
- **Busy / Disabled / Attention:** busy adds a 12px current-color spinner and 0.8 opacity; disabled drops to 0.55 opacity; attention draws a 2px Warn Ochre outline offset 2px.
- **Focus:** global 2px Slate outline, offset 2px.

### Segmented Control
A single ruled box of options, the Studio's model and source switch.
- **Style:** paper background, Hairline Strong outer border, 4px corners, items divided by Hairline rules, 8px 13px padding, 13px/500 Ink Dim.
- **State:** hover to Ink on recessed paper; active takes the Slate Wash tint with Slate text at 600. `aria-pressed` carries the state.

### Chips
Independent toggles for ranges, tenors and factor counts.
- **Style:** transparent, 1 px Hairline Strong border, Ink Dim text, 4px corners, 6px 11px padding, 12px/500, 30px min-height, 4px gap between chips.
- **State:** hover to Ink with Ink Muted border on recessed paper; active stays transparent with Slate border and Slate text at 600 (ink, not fill).

### Cards / Containers
The ruled box that holds every chart and table.
- **Corner Style:** 6px.
- **Background:** paper (Charcoal Raised in dark).
- **Shadow Strategy:** none; see Elevation & Depth.
- **Border:** 1 px Hairline on all four sides as currently built, with a Hairline divider under the head. The four-sided enclosure is a carry-over from the pinned layout; a top-and-bottom-rule treatment is the release idiom's preferred form and remains open.
- **Internal Padding:** head 12px 20px (title 14px/600 left, tools right, wraps); body 18px 20px 22px; 20px between stacked cards.
- **Stale state:** results marked `data-stale` drop to 0.55 opacity and half saturation while a Warn-bordered notice offers re-estimation.

### Metric Tiles
The signature row: a ruled box, label above, monospace numeral below, hint beneath.
- **Style:** paper, 1 px Hairline, 6px corners, 12px 16px 14px padding, 3px vertical gap.
- **Type:** label 12px Ink Dim; value 22px/600 JetBrains Mono tabular, single line with ellipsis; hint 12px Ink Muted; inline symbols 12.5px mono Ink Dim.
- **State:** `.neg` sets the value in Down Red.

### Inputs / Fields
- **Style:** paper, 1 px Hairline Strong, Ink text, 4px corners, 8px 11px padding, 13px; `color-scheme` follows the theme so native pickers match. Selects reserve 28px right padding. Quote-table inputs are right-aligned JetBrains Mono at 13px with spin buttons removed.
- **Focus:** 2px Slate outline at 0 offset plus a Slate border.
- **Error:** `aria-invalid` turns border and outline Danger Brick; the adjacent `.hint` is Danger Brick at 12.5px.
- **Range:** 4px Hairline Strong track, 16px Slate thumb with a 2px paper ring; readouts sit in a recessed-paper mono pill.

### Navigation
- **Style:** vertical list in the sidebar, grouped under 11px Ink Muted headers separated by Hairline rules. Items are 13.5px/500 Ink Dim on transparent with a transparent 1 px border, 8px 12px padding, 4px corners, 18px icon slot with a 16px sprite icon.
- **States:** hover fills recessed paper and lifts text to Ink; active keeps the transparent background and draws Slate text at 600 with a Slate border.
- **Mobile:** below 900px the sidebar is a fixed drawer with a scrim, toggled by a ghost Menu button; collapsed-mode hiding is undone so the drawer always shows labels.

### Status & Notices
- **Status card:** paper, Hairline, 4px, 10px 12px; a 9px dot in Warn Ochre (synthetic) or Live Green (live) beside an 11px label, 13px/600 value, and an 11.5px source list whose entries colour Live Green or Warn Ochre by provenance.
- **Banner / Notice:** Warn Wash surface with a Warn Ochre border for synthetic data and stale results; Danger Wash with Danger Brick for errors; a neutral notice uses paper with Hairline Strong. 4px corners, 9-10px 14px padding, actions right.
- **Toast:** fixed bottom-right, paper, Hairline Strong, 4px, 12px 16px, fades and lifts 8px over 0.25s; border colours Danger Brick or Live Green by type.

### Badges & Pills
- **Badge:** paper, Hairline Strong, 4px, 3px 9px, 11.5px Ink Dim. Numeric badges switch to JetBrains Mono tabular; `ok` and `warn` borrow Live Green or Warn Ochre for border and text.
- **Pill:** no border, 4px, 2px 8px, 11.5px/600; `cheap` in Live Green on Up Wash, `rich` in Down Red on Down Wash.

### Iconography
One inline SVG `<symbol>` sprite in the shell (`i-curve`, `i-sliders`, `i-history`, `i-compare`, `i-shortrate`, `i-premium`, `i-bars`, `i-book`, `i-menu`, `i-chevron-left`, `i-sun`, `i-moon`), 24-unit viewBox, drawn at 16px with `stroke: currentColor`, `stroke-width: 1.75`, round caps and joins, no fill. Icons inherit the text colour of their control and never carry their own hue.

### Brand Mark
A 42px square on paper with a 1 px Slate border and the "FI" monogram in Slate at 700 with 0.5px tracking, 4px corners. Beside it, the name at 15px/700 and the sub-line at 11px Ink Muted. It is a ruled monogram, not a filled tile, so the primary button stays the only filled slate element above the fold.

## Do's and Don'ts

### Do:
- **Do** use `var(--accent)` for every interactive signal: link colour, `:focus-visible` outline (2px, 2px offset), active nav/chip/segmented text, slider thumb, selection.
- **Do** set every measured quantity in JetBrains Mono with `font-variant-numeric: tabular-nums`, and keep labels in Inter.
- **Do** separate regions with 1 px `var(--line)` rules and controls with 1 px `var(--line-strong)` borders; use `var(--bg-2)` recessed paper as the only second surface.
- **Do** keep corners at 4px for controls and 6px for cards and metric tiles.
- **Do** reserve the `-soft` washes for semantic content (stale, error, heat cells, cheap/rich pills) and the accent wash for the active segmented item.
- **Do** take chart series colours from `seriesColor(i)` so the seven MPR inks and their dark lifts stay in step with the theme.
- **Do** keep hover and state transitions at 0.15-0.2s ease and honour `prefers-reduced-motion`.
- **Do** draw new icons into the shell sprite at 24-unit viewBox, stroke 1.75, round caps, rendered at 16px in `currentColor`.

### Don't:
- **Don't** add a `box-shadow`, `backdrop-filter`, or any gradient other than the loading shimmer.
- **Don't** introduce a second accent hue or tint the dark theme's greys; charcoal stays neutral and the accent lifts instead.
- **Don't** fill an active nav item, chip or segmented item with solid slate; the primary button is the only filled accent element per viewport.
- **Don't** set type above 22px or below 11px; carry hierarchy with weight, ink tone and rules.
- **Don't** use uppercase tracked labels, kickers or eyebrows; the build has none and labels are sentence case.
- **Don't** colour a negative number with the error red; negatives are Down Red, errors are Danger Brick.
- **Don't** let chart series borrow UI colours or UI accents borrow chart inks.

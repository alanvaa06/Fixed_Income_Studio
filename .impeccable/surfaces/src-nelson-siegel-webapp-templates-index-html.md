---
version: 1
slug: "src-nelson-siegel-webapp-templates-index-html"
primary_target: "src/nelson_siegel/webapp/templates/index.html"
related_targets: ["src/nelson_siegel/webapp/static/css/styles.css","src/nelson_siegel/webapp/static/js/core.js"]
---

# Fixed Income Studio shell (all tabs)

Scope: the whole Studio shell, `templates/index.html` with every partial, `static/css/styles.css`, chart theme in `static/js/core.js`. Visitor mode: Operate.

Audience and job: recruiters and quant readers landing cold from a CV or GitHub link; the author as a daily research tool. Task: run an estimate, read the numbers, trust them. Proof: live public data with provenance on every response, 181 offline tests, ACM replication verified against the NY Fed xls.

Constraints (confirmed 2026-09-02): layout and typography stay (Inter UI, JetBrains Mono numerals, sidebar plus tab panes); color tokens and surface material are replaced; light and dark themes both remain; Plotly series must stay distinguishable at seven lines; must not read as a dark SaaS or crypto dashboard.

Chosen direction: Statistical Release (Impeccable's pick, taken by the user over the roll). Memorable moment: the page reads as a Federal Reserve statistical release, white paper, black ink, hairline rules, slate-blue for every live element, tabular numerals, and nothing that glows.

Resolved 2026-09-02: the sidebar brand mark is a ruled monogram (paper ground, 1 px accent border, accent letters), so the primary button is the only filled accent element above the fold. Unresolved: whether the Learn tab wants a wider reading measure.

## Direction contract

THESIS: The Studio is a statistical release, not a dashboard. It refuses the category arrangement of glowing cards on a dark gradient and every accent that decorates.

OWN-WORLD: Pure white paper (#ffffff) and near-black ink (#111111); one slate blue (#1f4e79) owns every live element: links, active tab, primary button, selected chip, focus edge. Hairline rules (#d9dde3) separate regions; no fills, no shadows, no gradients, no blur. Squared radii (4 to 6 px). Chart inks follow the Monetary Policy Report: slate blue, brick red, green, orange, purple, teal, grey, lifted one step on the dark theme, which is neutral charcoal (#121417) with the same rules.

STORY: A reader sees a government release they already trust, finds the estimate and its provenance in the first viewport, and believes the number before reading how it was made.

FIRST VIEWPORT: Unchanged layout: sidebar left as a ruled margin with the monogram, tab title and one-paragraph brief top, the controls strip below it with the single blue Estimate button, metric tiles as ruled boxes with monospace numerals, first chart below. Primary action is the only filled blue element above the fold.

FORM: Statistical Release, candidate 1 of my ordered list (the roll assigned candidate 3, Treasury Engraving; the user chose the pick). Seed key 28d91ac7.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

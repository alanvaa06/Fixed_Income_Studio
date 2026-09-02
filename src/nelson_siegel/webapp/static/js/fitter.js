/* Curve Fitter tab */
(function (S) {
  "use strict";
  const { $, $$, COLOR, state, saveSettings, toast, setBusy, fmt } = S;

  const DEFAULT_TREASURY_ROWS = [
    [0.083, 4.35], [0.25, 4.30], [0.5, 4.20], [1, 4.05], [2, 3.90], [3, 3.88],
    [5, 3.95], [7, 4.05], [10, 4.20], [20, 4.70], [30, 4.85],
  ];
  const DEFAULT_TIPS_ROWS = [[5, 1.55], [7, 1.70], [10, 1.85], [20, 2.00], [30, 2.10]];
  const defaultRowsForBond = (bond) => (bond === "tips" ? DEFAULT_TIPS_ROWS : DEFAULT_TREASURY_ROWS);

  function makeRow(maturity = "", yieldVal = "") {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="number" step="0.01" min="0" value="${maturity}" data-kind="m" aria-label="Maturity in years" /></td>
      <td><input type="number" step="0.001" value="${yieldVal}" data-kind="y" aria-label="Yield in percent" /></td>
      <td><button class="row-del" title="Remove row" aria-label="Remove row">&times;</button></td>`;
    tr.querySelector(".row-del").addEventListener("click", () => tr.remove());
    tr.querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fitCurrentRows(); } });
    });
    return tr;
  }
  function renderQuoteRows(rows) {
    const tbody = $("#quote-tbody");
    tbody.innerHTML = "";
    rows.forEach(([m, y]) => tbody.appendChild(makeRow(m, y)));
  }
  function readQuoteRows() {
    return $$("#quote-tbody tr").map((tr) => ({
      maturity: parseFloat(tr.querySelector('input[data-kind="m"]').value),
      yield: parseFloat(tr.querySelector('input[data-kind="y"]').value),
    })).filter((p) => !isNaN(p.maturity) && !isNaN(p.yield));
  }

  const TENOR_FACTORS = { d: 1 / 365, w: 7 / 365, m: 1 / 12, y: 1 };
  function parseMaturity(token) {
    const m = String(token).trim().match(/^(\d+(?:\.\d+)?)\s*([dwmy])?(?:r|rs|o|os|k|ks|ay|ays|eek|eeks|onth|onths|ear|ears)?$/i);
    if (!m) return NaN;
    return parseFloat(m[1]) * TENOR_FACTORS[(m[2] || "y").toLowerCase()];
  }
  function parseQuoteText(text) {
    const rows = [];
    const errors = [];
    text.split(/\r?\n/).forEach((line, i) => {
      const clean = line.trim();
      if (!clean || clean.startsWith("#")) return;
      const parts = clean.split(/[\s,;:|\t]+/).filter(Boolean);
      if (parts.length < 2) { errors.push(`line ${i + 1}`); return; }
      const maturity = parseMaturity(parts[0]);
      const yieldVal = parseFloat(parts[1].replace("%", ""));
      if (isNaN(maturity) || isNaN(yieldVal)) { errors.push(`line ${i + 1}`); return; }
      rows.push([Number(maturity.toFixed(4)), yieldVal]);
    });
    return { rows, errors };
  }

  function renderFactorTiles(result) {
    const host = $("#fit-metrics");
    host.innerHTML = "";
    const list = result.factor_list || [];
    list.forEach((f) => {
      const unit = f.unit === "years" ? " y" : f.unit === "per-year" ? " /y" : " %";
      const digits = f.unit === "rate" ? 3 : 2;
      host.insertAdjacentHTML("beforeend", S.metricTile(
        `<span class="sym">${f.symbol}</span> &middot; ${f.label}`, fmt(f.value, digits, unit), f.hint || ""));
    });
    host.classList.toggle("grid-6", list.length > 4);
    host.classList.toggle("grid-4", list.length <= 4);
  }

  function plotFit(result) {
    const traces = [
      { x: result.maturities, y: result.observed, mode: "markers", name: "Observed",
        marker: { color: COLOR.obs, size: 9, line: { color: "#1c2742", width: 1 } },
        hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Observed</extra>" },
      { x: result.smooth.maturities, y: result.smooth.yields, mode: "lines", name: `${result.model_name || "Model"} fit`,
        line: { color: COLOR.fitted, width: 3, shape: "spline" }, hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Fit</extra>" },
    ];
    if (result.smooth.forward) {
      traces.push({ x: result.smooth.maturities, y: result.smooth.forward, mode: "lines", name: "Instantaneous forward",
        line: { color: COLOR.purple, width: 1.5, dash: "dot" }, hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Forward</extra>" });
    }
    S.plot("chart-fit", traces, S.layoutWith("Maturity (years)", "Yield (%)"));

    const colors = result.deviations_bps.map((d) => (d >= 0 ? COLOR.red : COLOR.treasury));
    S.plot("chart-residuals", [{
      x: result.maturities, y: result.deviations_bps, type: "bar", marker: { color: colors, opacity: 0.85 },
      text: result.classification, textposition: "none",
      hovertemplate: "%{x:.2f}y · <b>%{y:.1f} bps</b> · %{text}<extra></extra>", name: "Residual",
    }], S.layoutWith("Maturity (years)", "Deviation (bps)", { hovermode: "x" }));

    renderFactorTiles(result);
    const badges = $("#fit-badges");
    badges.innerHTML = "";
    const add = (text, cls = "") => {
      const b = document.createElement("span");
      b.className = `badge ${cls}`.trim();
      b.textContent = text;
      badges.appendChild(b);
    };
    add(result.model_name || "Model");
    add(`RMSE ${result.rmse_bps.toFixed(1)} bps`, result.rmse_bps < 5 ? "ok" : result.rmse_bps < 15 ? "" : "warn");
    if (typeof result.r_squared === "number") add(`R² ${result.r_squared.toFixed(4)}`);
    if (result.n_points) add(`${result.n_points} pts`);
    if (result.decay_at_bound) add(result.family === "short-rate" ? "parameter at search bound" : "τ at search bound", "warn");
    $("#btn-fit-export").disabled = false;
    $("#fit-family-note").textContent = result.family === "short-rate"
      ? "One-factor short-rate model: the whole curve is pinned down by today's short rate, its speed of mean reversion, the long-run mean and volatility. Expect a coarser fit than Nelson-Siegel; the value is in the dynamics."
      : "";
  }

  async function fitCurrentRows() {
    $("#fit-error").textContent = "";
    const points = readQuoteRows();
    const info = S.modelInfo(state.model);
    if (points.length < info.min_points) {
      $("#fit-error").textContent = `${info.name} needs at least ${info.min_points} (maturity, yield) rows.`;
      return;
    }
    const btn = $("#btn-fit");
    setBusy(btn, true, "Fitting…");
    S.setChartLoading(["chart-fit", "chart-residuals"]);
    try {
      const j = await S.postJSON("/api/fit", { bond_type: state.bondType, model: state.model, points, yield_unit: "percent" });
      state.lastFit = j;
      plotFit(j);
    } catch (err) {
      $("#fit-error").textContent = err.message;
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
      S.setChartLoading(["chart-fit", "chart-residuals"], false);
    }
  }

  async function loadSnapshot() {
    const btn = $("#btn-load-snapshot");
    setBusy(btn, true, "Loading…");
    try {
      const j = await S.api(`/api/snapshot?bond_type=${state.bondType}&model=${state.model}`);
      renderQuoteRows(j.maturities.map((m, i) => [m, j.observed[i].toFixed(3)]));
      const src = j.sources && j.sources[state.bondType] ? ` · ${j.sources[state.bondType]}` : "";
      toast(`Loaded ${state.bondType === "tips" ? "TIPS" : "Treasury"} curve as of ${j.as_of}${src}.`, "success");
      await fitCurrentRows();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  }

  function init() {
    $("#btn-add-row").addEventListener("click", () => {
      const row = makeRow();
      $("#quote-tbody").appendChild(row);
      row.querySelector("input").focus();
    });
    $("#btn-reset-rows").addEventListener("click", () => {
      renderQuoteRows(defaultRowsForBond(state.bondType));
      $("#fit-error").textContent = "";
    });
    const pastePanel = $("#paste-panel");
    const togglePaste = (open) => {
      pastePanel.hidden = !open;
      $("#btn-paste-toggle").setAttribute("aria-expanded", open ? "true" : "false");
      if (open) $("#paste-text").focus();
    };
    $("#btn-paste-toggle").addEventListener("click", () => togglePaste(pastePanel.hidden));
    $("#btn-paste-cancel").addEventListener("click", () => togglePaste(false));
    $("#btn-paste-apply").addEventListener("click", () => {
      const { rows, errors } = parseQuoteText($("#paste-text").value);
      const errEl = $("#paste-error");
      if (!rows.length) { errEl.textContent = "No quotes recognised. Use one 'maturity yield' pair per line."; return; }
      errEl.textContent = errors.length ? `Skipped ${errors.join(", ")}.` : "";
      rows.sort((a, b) => a[0] - b[0]);
      renderQuoteRows(rows);
      togglePaste(false);
      fitCurrentRows();
    });
    S.bindSegmented('.seg-btn[data-bond]', "bond", (v) => {
      state.bondType = v; saveSettings();
      renderQuoteRows(defaultRowsForBond(state.bondType));
      fitCurrentRows();
    });
    S.bindSegmented('.seg-btn[data-model]', "model", (v) => { state.model = v; saveSettings(); fitCurrentRows(); });
    $("#btn-fit").addEventListener("click", fitCurrentRows);
    $("#btn-load-snapshot").addEventListener("click", loadSnapshot);
    $("#btn-fit-export").addEventListener("click", () => {
      const f = state.lastFit;
      if (!f) return;
      const rows = f.maturities.map((m, i) => [m, f.observed[i], f.fitted[i], f.deviations_bps[i], f.classification[i]]);
      S.downloadCSV(`curve-fit-${f.bond_type}-${f.model}.csv`, ["maturity_years", "observed_pct", "fitted_pct", "residual_bps", "classification"], rows);
    });
    $("#btn-fit-to-lab").addEventListener("click", () => {
      if (!state.lastFit) { toast("Fit a curve first.", "error"); return; }
      if (state.lastFit.family === "short-rate") { toast("The Parameter Lab covers Nelson-Siegel and Svensson; fit one of those to hand it over.", "error"); return; }
      S.showTab("explorer");
      if (S.lab) S.lab.syncFromFit(state.lastFit);
    });

    S.activateSegmentedByData('.seg-btn[data-bond]', "bond", state.bondType);
    S.activateSegmentedByData('.seg-btn[data-model]', "model", state.model);
    renderQuoteRows(defaultRowsForBond(state.bondType));
    fitCurrentRows();
  }

  S.fitter = { fitCurrentRows, loadSnapshot };
  S.registerTab("fitter", { init });
})(window.Studio);

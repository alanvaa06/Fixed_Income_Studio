/* Nelson-Siegel Studio - frontend logic */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const PLOT_LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#cdd5e3", family: "Inter, sans-serif", size: 12 },
    margin: { l: 56, r: 16, t: 24, b: 44 },
    xaxis: {
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      tickfont: { size: 11 },
      title: { font: { size: 12 } },
    },
    yaxis: {
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      tickfont: { size: 11 },
      title: { font: { size: 12 } },
    },
    legend: { orientation: "h", x: 0, y: 1.12, font: { size: 11.5 } },
    hovermode: "x unified",
    hoverlabel: { bgcolor: "#1c2742", bordercolor: "rgba(255,255,255,0.14)" },
  };
  const PLOT_CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] };

  const COLOR = {
    treasury: "#6aa9ff",
    tips: "#34d399",
    fitted: "#f59e0b",
    obs: "#cbd5e1",
    purple: "#a78bfa",
    red: "#ef4444",
  };

  const hasPlotly = typeof window.Plotly !== "undefined";
  if (!hasPlotly) {
    // The chart library did not load (offline, or the CDN is blocked). Numbers
    // and exports still work; say so instead of leaving empty panels.
    $$(".chart").forEach((el) => {
      el.innerHTML = '<div class="chart-offline">Charts unavailable: plotly.js could not be loaded. '
        + 'Install the <code>plotly</code> Python package to serve it locally, or allow access to cdn.plot.ly.</div>';
    });
  }
  function plot(id, traces, layout) {
    if (!hasPlotly) return;
    Plotly.react(id, traces, layout, PLOT_CONFIG);
  }
  function layoutWith(xTitle, yTitle, extra = {}) {
    return Object.assign({}, PLOT_LAYOUT, {
      xaxis: Object.assign({}, PLOT_LAYOUT.xaxis, { title: xTitle }),
      yaxis: Object.assign({}, PLOT_LAYOUT.yaxis, { title: yTitle }),
    }, extra);
  }

  // ----- Persisted settings -----
  const SETTINGS_KEY = "ns-studio-settings";
  const DEFAULT_SETTINGS = {
    bondType: "treasury",
    model: "nelson-siegel",
    labModel: "nelson-siegel",
    histBondType: "treasury",
    histRange: "1",
    cmpRange: "1",
    showForward: false,
  };
  function loadSettings() {
    try {
      const raw = window.localStorage.getItem(SETTINGS_KEY);
      return Object.assign({}, DEFAULT_SETTINGS, raw ? JSON.parse(raw) : {});
    } catch (_) {
      return Object.assign({}, DEFAULT_SETTINGS);
    }
  }
  const state = loadSettings();
  state.lastFit = null;
  state.lastHist = null;
  state.lastCompare = null;
  state.models = {};
  function saveSettings() {
    try {
      const { bondType, model, labModel, histBondType, histRange, cmpRange, showForward } = state;
      window.localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({ bondType, model, labModel, histBondType, histRange, cmpRange, showForward })
      );
    } catch (_) { /* private mode etc. */ }
  }

  // ----- Small helpers -----
  let toastTimer = null;
  function toast(msg, kind = "info") {
    const el = $("#toast");
    el.textContent = msg;
    el.className = `toast show ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.label = button.dataset.label || button.textContent;
      button.classList.add("busy");
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      if (label) button.textContent = label;
    } else {
      button.classList.remove("busy");
      button.disabled = false;
      button.removeAttribute("aria-busy");
      if (button.dataset.label) button.textContent = button.dataset.label;
    }
  }

  function fmt(value, digits = 3, suffix = "") {
    if (value == null || isNaN(value)) return "—";
    return Number(value).toFixed(digits) + suffix;
  }

  function setSegmented(buttons, activeBtn) {
    buttons.forEach((b) => {
      const on = b === activeBtn;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  function activateSegmentedByData(selector, attr, value) {
    const buttons = $$(selector);
    const target = buttons.find((b) => b.dataset[attr] === value) || buttons[0];
    setSegmented(buttons, target);
    return target;
  }

  function isoDate(d) { return d.toISOString().slice(0, 10); }
  function rangeDates(years) {
    const end = new Date();
    const start = new Date(end);
    start.setFullYear(end.getFullYear() - Number(years));
    return { start: isoDate(start), end: isoDate(end) };
  }

  function downloadCSV(filename, header, rows) {
    const esc = (v) => (v == null ? "" : String(v));
    const csv = [header.join(",")].concat(rows.map((r) => r.map(esc).join(","))).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  }

  // ----- Tabs -----
  const navButtons = $$(".nav-item");
  function showTab(tab) {
    navButtons.forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    $$(".tab-pane").forEach((p) => p.classList.toggle("active", p.dataset.tabPane === tab));
    window.dispatchEvent(new Event("resize")); // reflow charts
  }
  navButtons.forEach((btn) => btn.addEventListener("click", () => showTab(btn.dataset.tab)));
  document.addEventListener("keydown", (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    const idx = parseInt(e.key, 10) - 1;
    if (idx >= 0 && idx < navButtons.length) {
      e.preventDefault();
      showTab(navButtons[idx].dataset.tab);
    }
  });

  // ----- Status / data source -----
  function updateDataStatus(hasFredKey) {
    document.body.dataset.fredKey = hasFredKey ? "true" : "false";
    $("#data-source-text").textContent = hasFredKey ? "FRED API (live)" : "Synthetic demo";
    $("#fred-key-note").textContent = hasFredKey
      ? "Live data enabled for this app session."
      : "Stored only for this running app session.";
  }

  fetch("/api/health")
    .then((r) => r.json())
    .then((j) => updateDataStatus(j.fred_api_key))
    .catch(() => { $("#data-source-text").textContent = "Offline"; });

  $("#fred-key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#fred-api-key");
    const apiKey = input.value.trim();
    if (!apiKey) {
      toast("Paste a FRED API key first.", "error");
      input.focus();
      return;
    }
    const btn = $("#fred-key-form button[type=submit]");
    setBusy(btn, true, "…");
    try {
      const r = await fetch("/api/fred-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Could not set FRED API key.");
      input.value = "";
      updateDataStatus(j.fred_api_key);
      toast("FRED API key applied. Load a snapshot to fetch live data.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  });

  // ----- Model catalogue -----
  const FALLBACK_MODELS = {
    "nelson-siegel": { id: "nelson-siegel", name: "Nelson-Siegel", min_points: 4 },
    "svensson": { id: "svensson", name: "Svensson", min_points: 6 },
  };
  state.models = FALLBACK_MODELS;
  fetch("/api/models")
    .then((r) => r.json())
    .then((j) => {
      const map = {};
      (j.models || []).forEach((m) => { map[m.id] = m; });
      if (Object.keys(map).length) state.models = map;
    })
    .catch(() => {});
  function modelInfo(id) { return state.models[id] || FALLBACK_MODELS[id] || FALLBACK_MODELS["nelson-siegel"]; }

  // ============================================================
  // CURVE FITTER
  // ============================================================
  const DEFAULT_TREASURY_ROWS = [
    [0.25, 4.95], [0.5, 4.85], [1, 4.65], [2, 4.30], [3, 4.10],
    [5, 3.95], [7, 4.00], [10, 4.05], [20, 4.30], [30, 4.35],
  ];
  const DEFAULT_TIPS_ROWS = [
    [5, 1.55], [7, 1.70], [10, 1.85], [20, 2.00], [30, 2.10],
  ];

  function defaultRowsForBond(bond) {
    return bond === "tips" ? DEFAULT_TIPS_ROWS : DEFAULT_TREASURY_ROWS;
  }

  function makeRow(maturity = "", yieldVal = "") {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="number" step="0.01" min="0" value="${maturity}" data-kind="m" aria-label="Maturity in years" /></td>
      <td><input type="number" step="0.001" value="${yieldVal}" data-kind="y" aria-label="Yield in percent" /></td>
      <td><button class="row-del" title="Remove row" aria-label="Remove row">&times;</button></td>
    `;
    tr.querySelector(".row-del").addEventListener("click", () => tr.remove());
    tr.querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); fitCurrentRows(); }
      });
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

  // Parse pasted quotes: "2 4.30", "2Y,4.30%", "3M\t5.2", "10y: 4.05".
  const TENOR_FACTORS = { d: 1 / 365, w: 7 / 365, m: 1 / 12, y: 1 };
  function parseMaturity(token) {
    const m = String(token).trim().match(/^(\d+(?:\.\d+)?)\s*([dwmy])?(?:r|rs|o|os|k|ks|ay|ays|eek|eeks|onth|onths|ear|ears)?$/i);
    if (!m) return NaN;
    const value = parseFloat(m[1]);
    const unit = (m[2] || "y").toLowerCase();
    return value * TENOR_FACTORS[unit];
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
  function togglePaste(open) {
    pastePanel.hidden = !open;
    $("#btn-paste-toggle").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) $("#paste-text").focus();
  }
  $("#btn-paste-toggle").addEventListener("click", () => togglePaste(pastePanel.hidden));
  $("#btn-paste-cancel").addEventListener("click", () => togglePaste(false));
  $("#btn-paste-apply").addEventListener("click", () => {
    const { rows, errors } = parseQuoteText($("#paste-text").value);
    const errEl = $("#paste-error");
    if (!rows.length) {
      errEl.textContent = "No quotes recognised. Use one 'maturity yield' pair per line.";
      return;
    }
    errEl.textContent = errors.length ? `Skipped ${errors.join(", ")}.` : "";
    rows.sort((a, b) => a[0] - b[0]);
    renderQuoteRows(rows);
    togglePaste(false);
    fitCurrentRows();
  });

  $$('.seg-btn[data-bond]').forEach((btn) => {
    btn.addEventListener("click", () => {
      setSegmented($$('.seg-btn[data-bond]'), btn);
      state.bondType = btn.dataset.bond;
      saveSettings();
      renderQuoteRows(defaultRowsForBond(state.bondType));
      fitCurrentRows();
    });
  });
  $$('.seg-btn[data-model]').forEach((btn) => {
    btn.addEventListener("click", () => {
      setSegmented($$('.seg-btn[data-model]'), btn);
      state.model = btn.dataset.model;
      saveSettings();
      fitCurrentRows();
    });
  });

  function renderFactorTiles(result) {
    const host = $("#fit-metrics");
    host.innerHTML = "";
    const list = result.factor_list || [];
    list.forEach((f) => {
      const tile = document.createElement("div");
      tile.className = "metric";
      const unit = f.unit === "years" ? " y" : " %";
      const digits = f.unit === "years" ? 2 : 3;
      tile.innerHTML = `
        <span class="metric-label"><span class="sym">${f.symbol}</span> &middot; ${f.label}</span>
        <span class="metric-value">${fmt(f.value, digits, unit)}</span>
        <span class="metric-hint">${f.hint || ""}</span>`;
      host.appendChild(tile);
    });
    host.classList.toggle("grid-6", list.length > 4);
    host.classList.toggle("grid-4", list.length <= 4);
  }

  function plotFit(result) {
    const obsTrace = {
      x: result.maturities, y: result.observed,
      mode: "markers", name: "Observed",
      marker: { color: COLOR.obs, size: 9, line: { color: "#1c2742", width: 1 } },
      hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Observed</extra>",
    };
    const fitTrace = {
      x: result.smooth.maturities, y: result.smooth.yields,
      mode: "lines", name: `${result.model_name || "Model"} fit`,
      line: { color: COLOR.fitted, width: 3, shape: "spline" },
      hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Fit</extra>",
    };
    const fitTraces = [obsTrace, fitTrace];
    if (result.smooth.forward) {
      fitTraces.push({
        x: result.smooth.maturities, y: result.smooth.forward,
        mode: "lines", name: "Instantaneous forward",
        line: { color: COLOR.purple, width: 1.5, dash: "dot" },
        hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Forward</extra>",
      });
    }
    plot("chart-fit", fitTraces, layoutWith("Maturity (years)", "Yield (%)"));

    const colors = result.deviations_bps.map((d) => (d >= 0 ? COLOR.red : COLOR.treasury));
    const resTrace = {
      x: result.maturities,
      y: result.deviations_bps,
      type: "bar",
      marker: { color: colors, opacity: 0.85 },
      text: result.classification,
      textposition: "none",
      hovertemplate: "%{x:.2f}y · <b>%{y:.1f} bps</b> · %{text}<extra></extra>",
      name: "Residual",
    };
    plot("chart-residuals", [resTrace], layoutWith("Maturity (years)", "Deviation (bps)", { hovermode: "x" }));

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
    if (result.decay_at_bound) add("τ at search bound", "warn");
    $("#btn-fit-export").disabled = false;
  }

  async function fitCurrentRows() {
    $("#fit-error").textContent = "";
    const points = readQuoteRows();
    const info = modelInfo(state.model);
    if (points.length < info.min_points) {
      $("#fit-error").textContent = `${info.name} needs at least ${info.min_points} (maturity, yield) rows.`;
      return;
    }
    const btn = $("#btn-fit");
    setBusy(btn, true, "Fitting…");
    try {
      const r = await fetch("/api/fit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bond_type: state.bondType, model: state.model, points, yield_unit: "percent" }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Fit failed.");
      state.lastFit = j;
      plotFit(j);
    } catch (err) {
      $("#fit-error").textContent = err.message;
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  }

  $("#btn-fit").addEventListener("click", fitCurrentRows);

  $("#btn-load-snapshot").addEventListener("click", async () => {
    const btn = $("#btn-load-snapshot");
    setBusy(btn, true, "Loading…");
    try {
      const r = await fetch(`/api/snapshot?bond_type=${state.bondType}&model=${state.model}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Snapshot failed.");
      renderQuoteRows(j.maturities.map((m, i) => [m, j.observed[i].toFixed(3)]));
      toast(`Loaded snapshot as of ${j.as_of}${j.is_synthetic ? " (synthetic)" : ""}.`, "success");
      await fitCurrentRows();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  });

  $("#btn-fit-export").addEventListener("click", () => {
    const f = state.lastFit;
    if (!f) return;
    const rows = f.maturities.map((m, i) => [m, f.observed[i], f.fitted[i], f.deviations_bps[i], f.classification[i]]);
    downloadCSV(`curve-fit-${f.bond_type}-${f.model}.csv`,
      ["maturity_years", "observed_pct", "fitted_pct", "residual_bps", "classification"], rows);
  });

  // ============================================================
  // PARAMETER LAB
  // ============================================================
  const SLIDERS = ["b0", "b1", "b2", "tau", "b3", "tau2"];
  const SLIDER_RANGE = { b0: [-2, 12], b1: [-6, 6], b2: [-8, 8], tau: [0.1, 10], b3: [-8, 8], tau2: [0.1, 20] };

  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function sliderValue(key) { return parseFloat($("#sl-" + key).value); }
  function setSlider(key, value) {
    const [lo, hi] = SLIDER_RANGE[key];
    $("#sl-" + key).value = clamp(value, lo, hi);
  }
  function updateSliderLabels() {
    SLIDERS.forEach((k) => { $("#lbl-" + k).textContent = sliderValue(k).toFixed(2); });
  }

  // Loadings, evaluated client-side so slider drags never round-trip.
  function loadings(t, tau) {
    if (t === 0) return { e: 1, f1: 1, f2: 0 };
    const e = Math.exp(-t / tau);
    const f1 = (1 - e) / (t / tau);
    return { e, f1, f2: f1 - e };
  }
  const EXPLORER_MATS = Array.from({ length: 250 }, (_, i) => 0.083 + (i * (30 - 0.083)) / 249);

  function labIsSvensson() { return state.labModel === "svensson"; }

  let explorerTimer = null;
  function drawExplorer() {
    clearTimeout(explorerTimer);
    explorerTimer = setTimeout(() => {
      const p = {
        b0: sliderValue("b0"), b1: sliderValue("b1"), b2: sliderValue("b2"), tau: sliderValue("tau"),
        b3: labIsSvensson() ? sliderValue("b3") : 0, tau2: sliderValue("tau2"),
      };
      const mats = EXPLORER_MATS;
      const lvl = mats.map(() => p.b0);
      const slp = mats.map((t) => p.b1 * loadings(t, p.tau).f1);
      const crv = mats.map((t) => p.b2 * loadings(t, p.tau).f2);
      const crv2 = mats.map((t) => p.b3 * loadings(t, p.tau2).f2);
      const curve = mats.map((t, i) => lvl[i] + slp[i] + crv[i] + crv2[i]);
      const fwd = mats.map((t) => {
        const l1 = loadings(t, p.tau);
        const l2 = loadings(t, p.tau2);
        return p.b0 + p.b1 * l1.e + p.b2 * (t / p.tau) * l1.e + p.b3 * (t / p.tau2) * l2.e;
      });

      const traces = [
        { x: mats, y: curve, name: "Curve", mode: "lines",
          line: { color: COLOR.fitted, width: 3, shape: "spline" },
          hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Curve</extra>" },
        { x: mats, y: lvl, name: "β₀ Level", mode: "lines",
          line: { color: COLOR.treasury, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Level</extra>" },
        { x: mats, y: slp, name: "β₁ Slope contrib.", mode: "lines",
          line: { color: COLOR.tips, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Slope</extra>" },
        { x: mats, y: crv, name: "β₂ Curvature contrib.", mode: "lines",
          line: { color: COLOR.purple, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Curvature</extra>" },
      ];
      if (labIsSvensson()) {
        traces.push({ x: mats, y: crv2, name: "β₃ Curvature 2 contrib.", mode: "lines",
          line: { color: "#f472b6", width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Curvature 2</extra>" });
      }
      if (state.showForward) {
        traces.push({ x: mats, y: fwd, name: "Forward curve", mode: "lines",
          line: { color: COLOR.obs, width: 1.5, dash: "dash" }, hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Forward</extra>" });
      }
      plot("chart-explorer", traces, layoutWith("Maturity (years)", "Yield (%)"));
    }, 30);
  }

  function setLabModel(modelId) {
    state.labModel = modelId;
    saveSettings();
    activateSegmentedByData('.seg-btn[data-lab-model]', "labModel", modelId);
    $("#svensson-sliders").hidden = !labIsSvensson();
    $("#lab-formula").innerHTML = labIsSvensson()
      ? "<code>y(t) = β<sub>0</sub> + β<sub>1</sub>·f<sub>1</sub>(t,τ) + β<sub>2</sub>·f<sub>2</sub>(t,τ) + β<sub>3</sub>·f<sub>2</sub>(t,τ<sub>2</sub>)</code>"
      : "<code>y(t) = β<sub>0</sub> + β<sub>1</sub>·f<sub>1</sub>(t,τ) + β<sub>2</sub>·f<sub>2</sub>(t,τ)</code>";
    drawExplorer();
  }
  $$('.seg-btn[data-lab-model]').forEach((btn) => btn.addEventListener("click", () => setLabModel(btn.dataset.labModel)));

  SLIDERS.forEach((k) => {
    $("#sl-" + k).addEventListener("input", () => { updateSliderLabels(); drawExplorer(); });
  });
  $("#lab-show-forward").addEventListener("change", (e) => {
    state.showForward = e.target.checked;
    saveSettings();
    drawExplorer();
  });

  function syncSlidersFromFit(result) {
    if (!result || !result.factor_list) return;
    const byKey = {};
    result.factor_list.forEach((f) => { byKey[f.key] = f.value; });
    setSlider("b0", byKey.beta0);
    setSlider("b1", byKey.beta1);
    setSlider("b2", byKey.beta2);
    setSlider("tau", byKey.tau != null ? byKey.tau : byKey.tau1);
    if (byKey.beta3 != null) setSlider("b3", byKey.beta3);
    if (byKey.tau2 != null) setSlider("tau2", byKey.tau2);
    setLabModel(result.model === "svensson" ? "svensson" : "nelson-siegel");
    updateSliderLabels();
    drawExplorer();
  }
  $("#btn-lab-from-fit").addEventListener("click", () => {
    if (!state.lastFit) { toast("Fit a curve first.", "error"); return; }
    syncSlidersFromFit(state.lastFit);
    toast("Sliders set to the last fit.", "success");
  });

  const PRESETS = {
    normal:   { b0: 4.0,  b1: -2.0, b2: 0.0,  tau: 2.0, b3: 0.0,  tau2: 8.0 },
    inverted: { b0: 4.0,  b1: 1.5,  b2: -0.5, tau: 1.5, b3: 0.0,  tau2: 8.0 },
    humped:   { b0: 3.5,  b1: -1.0, b2: 3.0,  tau: 2.5, b3: 0.0,  tau2: 8.0 },
    flat:     { b0: 4.2,  b1: 0.1,  b2: 0.1,  tau: 2.0, b3: 0.0,  tau2: 8.0 },
  };
  $$('button[data-preset]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = PRESETS[btn.dataset.preset];
      if (!p) return;
      SLIDERS.forEach((k) => setSlider(k, p[k]));
      updateSliderLabels();
      drawExplorer();
    });
  });

  // ============================================================
  // HISTORICAL FACTORS
  // ============================================================
  $$('.seg-btn[data-hist-bond]').forEach((btn) => {
    btn.addEventListener("click", () => {
      setSegmented($$('.seg-btn[data-hist-bond]'), btn);
      state.histBondType = btn.dataset.histBond;
      saveSettings();
    });
  });

  function applyHistRange(years) {
    const { start, end } = rangeDates(years);
    $("#hist-start").value = start;
    $("#hist-end").value = end;
    $$("#hist-chips .chip").forEach((c) => c.classList.toggle("active", c.dataset.histRange === String(years)));
    state.histRange = String(years);
    saveSettings();
  }
  $$("#hist-chips .chip").forEach((chip) => chip.addEventListener("click", () => applyHistRange(chip.dataset.histRange)));
  ["hist-start", "hist-end"].forEach((id) => $("#" + id).addEventListener("change", () => {
    $$("#hist-chips .chip").forEach((c) => c.classList.remove("active"));
  }));

  $("#btn-hist-run").addEventListener("click", async () => {
    const btn = $("#btn-hist-run");
    const params = new URLSearchParams({
      bond_type: state.histBondType,
      start: $("#hist-start").value,
      end: $("#hist-end").value,
    });
    setBusy(btn, true, "Computing…");
    try {
      const r = await fetch(`/api/historical?${params.toString()}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Historical request failed.");
      state.lastHist = j;

      const traces = [
        { x: j.dates, y: j.level, name: "Level (β₀)", line: { color: COLOR.treasury, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.slope, name: "Slope (β₁)", line: { color: COLOR.tips, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.curvature, name: "Curvature (β₂)", line: { color: COLOR.purple, width: 2 }, mode: "lines" },
      ];
      plot("chart-historical", traces, layoutWith("Date", "Factor (%)"));

      if (j.rmse_bps) {
        plot("chart-hist-rmse", [{
          x: j.dates, y: j.rmse_bps, name: "Fit RMSE", mode: "lines", fill: "tozeroy",
          line: { color: COLOR.fitted, width: 1.5 }, fillcolor: "rgba(245, 158, 11, 0.12)",
          hovertemplate: "%{x} · <b>%{y:.1f} bps</b><extra></extra>",
        }], layoutWith("Date", "RMSE (bps)", { hovermode: "x" }));
      }

      $("#h-level").textContent = fmt(j.summary.level_mean, 2, " %");
      $("#h-slope").textContent = fmt(j.summary.slope_mean, 2, " %");
      $("#h-tau").textContent = fmt(j.summary.tau, 2, " y");
      $("#h-rmse").textContent = fmt(j.summary.rmse_bps_mean, 1, " bps");
      $("#h-obs").textContent = j.summary.n_observations.toLocaleString();
      $("#hist-range").textContent = `${j.summary.start} → ${j.summary.end}${j.is_synthetic ? " · synthetic data" : ""}`;
      $("#btn-hist-export").disabled = false;
      toast("Historical factors loaded.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  });

  $("#btn-hist-export").addEventListener("click", () => {
    const h = state.lastHist;
    if (!h) return;
    const rows = h.dates.map((d, i) => [d, h.level[i], h.slope[i], h.curvature[i], h.tau[i], h.rmse_bps ? h.rmse_bps[i] : ""]);
    downloadCSV(`factors-${h.bond_type}-${h.summary.start}-${h.summary.end}.csv`,
      ["date", "level_pct", "slope_pct", "curvature_pct", "tau_years", "rmse_bps"], rows);
  });

  // ============================================================
  // COMPARE
  // ============================================================
  const cmpButton = $("#btn-cmp-run");
  const cmpStatus = $("#cmp-status");
  function setCompareStatus(text) { if (cmpStatus) cmpStatus.textContent = text; }

  function applyCmpRange(years) {
    const { start, end } = rangeDates(years);
    $("#cmp-start").value = start;
    $("#cmp-end").value = end;
    $$("#cmp-chips .chip").forEach((c) => c.classList.toggle("active", c.dataset.cmpRange === String(years)));
    state.cmpRange = String(years);
    saveSettings();
  }
  $$("#cmp-chips .chip").forEach((chip) => chip.addEventListener("click", () => applyCmpRange(chip.dataset.cmpRange)));
  ["cmp-start", "cmp-end"].forEach((id) => $("#" + id).addEventListener("change", () => {
    $$("#cmp-chips .chip").forEach((c) => c.classList.remove("active"));
  }));

  cmpButton.addEventListener("click", async () => {
    setBusy(cmpButton, true, "Computing…");
    setCompareStatus("Aligning Treasury and TIPS…");
    const params = new URLSearchParams({ start: $("#cmp-start").value, end: $("#cmp-end").value });
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);
    try {
      const r = await fetch(`/api/compare?${params.toString()}`, { signal: controller.signal });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Comparison failed.");
      state.lastCompare = j;

      const traces = [
        { x: j.dates, y: j.treasury_level, name: "Treasury Level", line: { color: COLOR.treasury, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.tips_level, name: "TIPS Level", line: { color: COLOR.tips, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.breakeven, name: "Breakeven inflation",
          line: { color: COLOR.fitted, width: 2.5, dash: "dot" }, mode: "lines",
          fill: "tozeroy", fillcolor: "rgba(245, 158, 11, 0.08)" },
      ];
      plot("chart-compare", traces, layoutWith("Date", "Yield / Spread (%)"));

      $("#c-corr-level").textContent = fmt(j.correlations.Level, 3);
      $("#c-corr-slope").textContent = fmt(j.correlations.Slope, 3);
      $("#c-corr-curv").textContent = fmt(j.correlations.Curvature, 3);
      $("#c-obs").textContent = (j.summary.total_observations || j.dates.length).toLocaleString();
      setCompareStatus(`${j.dates.length.toLocaleString()} points${j.is_synthetic ? " · synthetic data" : ""}`);
      $("#btn-cmp-export").disabled = false;
      toast("Comparison ready.", "success");
    } catch (err) {
      if (err.name === "AbortError") {
        setCompareStatus("Timed out. Try a shorter date range.");
        toast("Comparison timed out. Try a shorter date range.", "error");
      } else {
        setCompareStatus("Comparison failed.");
        toast(err.message, "error");
      }
    } finally {
      clearTimeout(timeoutId);
      setBusy(cmpButton, false);
    }
  });

  $("#btn-cmp-export").addEventListener("click", () => {
    const c = state.lastCompare;
    if (!c) return;
    const rows = c.dates.map((d, i) => [d, c.treasury_level[i], c.tips_level[i], c.treasury_slope[i], c.tips_slope[i], c.breakeven[i]]);
    downloadCSV(`treasury-vs-tips-${c.summary.date_range.start}-${c.summary.date_range.end}.csv`,
      ["date", "treasury_level_pct", "tips_level_pct", "treasury_slope_pct", "tips_slope_pct", "breakeven_pct"], rows);
  });

  // ============================================================
  // INITIAL STATE
  // ============================================================
  activateSegmentedByData('.seg-btn[data-bond]', "bond", state.bondType);
  activateSegmentedByData('.seg-btn[data-model]', "model", state.model);
  activateSegmentedByData('.seg-btn[data-hist-bond]', "histBond", state.histBondType);
  applyHistRange(state.histRange);
  applyCmpRange(state.cmpRange);
  $("#lab-show-forward").checked = !!state.showForward;
  renderQuoteRows(defaultRowsForBond(state.bondType));
  updateSliderLabels();
  setLabModel(state.labModel);
  fitCurrentRows();
})();

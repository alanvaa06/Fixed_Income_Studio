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

  const state = {
    bondType: "treasury",
    histBondType: "treasury",
  };

  // ----- Toast -----
  let toastTimer = null;
  function toast(msg, kind = "info") {
    const el = $("#toast");
    el.textContent = msg;
    el.className = `toast show ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
  }

  // ----- Tabs -----
  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".nav-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      $$(".tab-pane").forEach((p) => p.classList.toggle("active", p.dataset.tabPane === tab));
      // Force chart reflow when tab becomes visible
      window.dispatchEvent(new Event("resize"));
    });
  });

  // ----- Status -----
  function updateDataStatus(hasFredKey) {
    document.body.dataset.fredKey = hasFredKey ? "true" : "false";
    $("#data-source-text").textContent = hasFredKey
      ? "FRED API (live)"
      : "Synthetic demo";
    $("#fred-key-note").textContent = hasFredKey
      ? "Live data enabled for this app session."
      : "Stored only for this running app session.";
  }

  fetch("/api/health")
    .then((r) => r.json())
    .then((j) => {
      updateDataStatus(j.fred_api_key);
    })
    .catch(() => {
      $("#data-source-text").textContent = "Offline";
    });

  $("#fred-key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#fred-api-key");
    const apiKey = input.value.trim();
    if (!apiKey) {
      toast("Paste a FRED API key first.", "error");
      input.focus();
      return;
    }

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
    }
  });

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
      <td><input type="number" step="0.01" min="0" value="${maturity}" data-kind="m" /></td>
      <td><input type="number" step="0.001" value="${yieldVal}" data-kind="y" /></td>
      <td><button class="row-del" title="Remove">&times;</button></td>
    `;
    tr.querySelector(".row-del").addEventListener("click", () => tr.remove());
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

  $("#btn-add-row").addEventListener("click", () => {
    $("#quote-tbody").appendChild(makeRow());
  });
  $("#btn-reset-rows").addEventListener("click", () => {
    renderQuoteRows(defaultRowsForBond(state.bondType));
    $("#fit-error").textContent = "";
  });

  $$('.seg-btn[data-bond]').forEach((btn) => {
    btn.addEventListener("click", () => {
      $$('.seg-btn[data-bond]').forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.bondType = btn.dataset.bond;
      renderQuoteRows(defaultRowsForBond(state.bondType));
    });
  });

  function fmt(value, digits = 3, suffix = "") {
    if (value == null || isNaN(value)) return "—";
    return Number(value).toFixed(digits) + suffix;
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
      mode: "lines", name: "Nelson-Siegel fit",
      line: { color: COLOR.fitted, width: 3, shape: "spline" },
      hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>NS Fit</extra>",
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
    const layout = Object.assign({}, PLOT_LAYOUT, {
      xaxis: Object.assign({}, PLOT_LAYOUT.xaxis, { title: "Maturity (years)" }),
      yaxis: Object.assign({}, PLOT_LAYOUT.yaxis, { title: "Yield (%)" }),
    });
    Plotly.react("chart-fit", fitTraces, layout, PLOT_CONFIG);

    const colors = result.deviations_bps.map((d) => (d >= 0 ? COLOR.red : COLOR.treasury));
    const resTrace = {
      x: result.maturities,
      y: result.deviations_bps,
      type: "bar",
      marker: { color: colors, opacity: 0.85 },
      hovertemplate: "%{x:.2f}y · <b>%{y:.1f} bps</b><extra></extra>",
      name: "Residual",
    };
    const resLayout = Object.assign({}, PLOT_LAYOUT, {
      xaxis: Object.assign({}, PLOT_LAYOUT.xaxis, { title: "Maturity (years)" }),
      yaxis: Object.assign({}, PLOT_LAYOUT.yaxis, { title: "Deviation (bps)" }),
      hovermode: "x",
    });
    Plotly.react("chart-residuals", [resTrace], resLayout, PLOT_CONFIG);

    $("#m-level").textContent = fmt(result.factors.Level, 3, " %");
    $("#m-slope").textContent = fmt(result.factors.Slope, 3, " %");
    $("#m-curv").textContent = fmt(result.factors.Curvature, 3, " %");
    $("#m-tau").textContent = fmt(result.factors.Tau, 2, " y");
    const r2 = typeof result.r_squared === "number" && !isNaN(result.r_squared)
      ? ` · R² ${result.r_squared.toFixed(4)}` : "";
    const bound = result.decay_at_bound ? " · τ at search bound" : "";
    $("#fit-rmse").textContent = `RMSE ${result.rmse_bps.toFixed(1)} bps${r2}${bound}`;
  }

  async function fitCurrentRows() {
    $("#fit-error").textContent = "";
    const points = readQuoteRows();
    if (points.length < 4) {
      $("#fit-error").textContent = "Need at least 4 (maturity, yield) rows.";
      return;
    }
    try {
      const r = await fetch("/api/fit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bond_type: state.bondType, points, yield_unit: "percent" }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Fit failed.");
      plotFit(j);
      // Sync sliders to fitted parameters
      syncSlidersFromFactors(j.factors);
      toast("Curve fitted.", "success");
    } catch (err) {
      $("#fit-error").textContent = err.message;
      toast(err.message, "error");
    }
  }

  $("#btn-fit").addEventListener("click", fitCurrentRows);

  $("#btn-load-snapshot").addEventListener("click", async () => {
    try {
      const r = await fetch(`/api/snapshot?bond_type=${state.bondType}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Snapshot failed.");
      renderQuoteRows(j.maturities.map((m, i) => [m, j.observed[i].toFixed(3)]));
      toast(`Loaded snapshot as of ${j.as_of}${j.is_synthetic ? " (synthetic)" : ""}.`, "success");
      await fitCurrentRows();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // Initial state
  renderQuoteRows(defaultRowsForBond("treasury"));
  fitCurrentRows();

  // ============================================================
  // PARAMETER LAB
  // ============================================================
  const sliderIds = ["sl-b0", "sl-b1", "sl-b2", "sl-tau"];
  const labelIds = { "sl-b0": "lbl-b0", "sl-b1": "lbl-b1", "sl-b2": "lbl-b2", "sl-tau": "lbl-tau" };

  function readSliders() {
    return {
      beta0: parseFloat($("#sl-b0").value),
      beta1: parseFloat($("#sl-b1").value),
      beta2: parseFloat($("#sl-b2").value),
      tau: parseFloat($("#sl-tau").value),
    };
  }

  function syncSlidersFromFactors(factors) {
    if (!factors) return;
    $("#sl-b0").value = clamp(factors.Level, -2, 12);
    $("#sl-b1").value = clamp(factors.Slope, -6, 6);
    $("#sl-b2").value = clamp(factors.Curvature, -8, 8);
    $("#sl-tau").value = clamp(factors.Tau, 0.1, 10);
    updateSliderLabels();
    drawExplorer();
  }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

  function updateSliderLabels() {
    $("#lbl-b0").textContent = parseFloat($("#sl-b0").value).toFixed(2);
    $("#lbl-b1").textContent = parseFloat($("#sl-b1").value).toFixed(2);
    $("#lbl-b2").textContent = parseFloat($("#sl-b2").value).toFixed(2);
    $("#lbl-tau").textContent = parseFloat($("#sl-tau").value).toFixed(2);
  }

  // Nelson-Siegel loadings, evaluated client-side so slider drags never
  // round-trip to the server (the /api/curve endpoint remains for API users).
  function nsLoadings(t, tau) {
    if (t === 0) return { f1: 1, f2: 0 };
    const e = Math.exp(-t / tau);
    const f1 = (1 - e) / (t / tau);
    return { f1, f2: f1 - e };
  }
  const EXPLORER_MATS = Array.from({ length: 250 }, (_, i) => 0.083 + (i * (30 - 0.083)) / 249);

  let explorerTimer = null;
  function drawExplorer() {
    clearTimeout(explorerTimer);
    explorerTimer = setTimeout(() => {
      const params = readSliders();
      try {
        const mats = EXPLORER_MATS;
        const tau = params.tau;
        const lvl = mats.map(() => params.beta0);
        const slp = mats.map((t) => params.beta1 * nsLoadings(t, tau).f1);
        const crv = mats.map((t) => params.beta2 * nsLoadings(t, tau).f2);
        const curve = mats.map((t, i) => lvl[i] + slp[i] + crv[i]);

        const traces = [
          {
            x: mats, y: curve, name: "Curve", mode: "lines",
            line: { color: COLOR.fitted, width: 3, shape: "spline" },
            hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Curve</extra>",
          },
          {
            x: mats, y: lvl, name: "β₀ Level", mode: "lines",
            line: { color: COLOR.treasury, width: 1.5, dash: "dot" },
            hovertemplate: "%{y:.3f}%<extra>Level</extra>",
          },
          {
            x: mats, y: slp, name: "β₁ Slope contrib.", mode: "lines",
            line: { color: COLOR.tips, width: 1.5, dash: "dot" },
            hovertemplate: "%{y:.3f}%<extra>Slope</extra>",
          },
          {
            x: mats, y: crv, name: "β₂ Curvature contrib.", mode: "lines",
            line: { color: COLOR.purple, width: 1.5, dash: "dot" },
            hovertemplate: "%{y:.3f}%<extra>Curvature</extra>",
          },
        ];
        const layout = Object.assign({}, PLOT_LAYOUT, {
          xaxis: Object.assign({}, PLOT_LAYOUT.xaxis, { title: "Maturity (years)" }),
          yaxis: Object.assign({}, PLOT_LAYOUT.yaxis, { title: "Yield (%)" }),
        });
        Plotly.react("chart-explorer", traces, layout, PLOT_CONFIG);
      } catch (err) {
        toast(err.message, "error");
      }
    }, 60);
  }

  sliderIds.forEach((id) => {
    $("#" + id).addEventListener("input", () => {
      updateSliderLabels();
      drawExplorer();
    });
  });
  updateSliderLabels();
  drawExplorer();

  const PRESETS = {
    normal:   { b0: 4.0,  b1: -2.0, b2: 0.0,  tau: 2.0 },
    inverted: { b0: 4.0,  b1: 1.5,  b2: -0.5, tau: 1.5 },
    humped:   { b0: 3.5,  b1: -1.0, b2: 3.0,  tau: 2.5 },
    flat:     { b0: 4.2,  b1: 0.1,  b2: 0.1,  tau: 2.0 },
  };
  $$('button[data-preset]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = PRESETS[btn.dataset.preset];
      if (!p) return;
      $("#sl-b0").value = p.b0;
      $("#sl-b1").value = p.b1;
      $("#sl-b2").value = p.b2;
      $("#sl-tau").value = p.tau;
      updateSliderLabels();
      drawExplorer();
    });
  });

  // ============================================================
  // HISTORICAL FACTORS
  // ============================================================
  $$('.seg-btn[data-hist-bond]').forEach((btn) => {
    btn.addEventListener("click", () => {
      $$('.seg-btn[data-hist-bond]').forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.histBondType = btn.dataset.histBond;
    });
  });

  // Default last 12 months
  (function presetHistDates() {
    const today = new Date();
    const start = new Date(today); start.setFullYear(today.getFullYear() - 1);
    $("#hist-end").value = today.toISOString().slice(0, 10);
    $("#hist-start").value = start.toISOString().slice(0, 10);
    $("#cmp-end").value = today.toISOString().slice(0, 10);
    const cmpStart = new Date(today); cmpStart.setFullYear(today.getFullYear() - 1);
    $("#cmp-start").value = cmpStart.toISOString().slice(0, 10);
  })();

  $("#btn-hist-run").addEventListener("click", async () => {
    const params = new URLSearchParams({
      bond_type: state.histBondType,
      start: $("#hist-start").value,
      end: $("#hist-end").value,
    });
    toast("Computing historical factors…");
    try {
      const r = await fetch(`/api/historical?${params.toString()}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Historical request failed.");

      const traces = [
        { x: j.dates, y: j.level, name: "Level (β₀)", line: { color: COLOR.treasury, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.slope, name: "Slope (β₁)", line: { color: COLOR.tips, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.curvature, name: "Curvature (β₂)", line: { color: COLOR.purple, width: 2 }, mode: "lines" },
      ];
      const layout = Object.assign({}, PLOT_LAYOUT, {
        xaxis: Object.assign({}, PLOT_LAYOUT.xaxis, { title: "Date" }),
        yaxis: Object.assign({}, PLOT_LAYOUT.yaxis, { title: "Factor (%)" }),
        hovermode: "x unified",
      });
      Plotly.react("chart-historical", traces, layout, PLOT_CONFIG);

      $("#h-level").textContent = fmt(j.summary.level_mean, 2, " %");
      $("#h-slope").textContent = fmt(j.summary.slope_mean, 2, " %");
      $("#h-obs").textContent = j.summary.n_observations.toLocaleString();
      const tauNote = typeof j.summary.tau === "number" ? ` · τ ${j.summary.tau.toFixed(2)}y` : "";
      const rmseNote = typeof j.summary.rmse_bps_mean === "number" ? ` · mean fit RMSE ${j.summary.rmse_bps_mean.toFixed(1)} bps` : "";
      $("#hist-range").textContent = `${j.summary.start} → ${j.summary.end}${tauNote}${rmseNote}${j.is_synthetic ? " · synthetic" : ""}`;
      toast("Historical factors loaded.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // ============================================================
  // COMPARE
  // ============================================================
  const cmpButton = $("#btn-cmp-run");
  const cmpStatus = $("#cmp-status");

  function setCompareStatus(text) {
    if (cmpStatus) cmpStatus.textContent = text;
  }

  $("#btn-cmp-run").addEventListener("click", async () => {
    cmpButton.disabled = true;
    setCompareStatus("Computing comparison...");
    const params = new URLSearchParams({
      start: $("#cmp-start").value,
      end: $("#cmp-end").value,
    });
    toast("Aligning Treasury and TIPS…");
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);
    try {
      const r = await fetch(`/api/compare?${params.toString()}`, { signal: controller.signal });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Comparison failed.");

      const traces = [
        {
          x: j.dates, y: j.treasury_level, name: "Treasury Level",
          line: { color: COLOR.treasury, width: 2 }, mode: "lines",
        },
        {
          x: j.dates, y: j.tips_level, name: "TIPS Level",
          line: { color: COLOR.tips, width: 2 }, mode: "lines",
        },
        {
          x: j.dates, y: j.breakeven, name: "Breakeven inflation",
          line: { color: COLOR.fitted, width: 2.5, dash: "dot" }, mode: "lines",
          fill: "tozeroy", fillcolor: "rgba(245, 158, 11, 0.08)",
        },
      ];
      const layout = Object.assign({}, PLOT_LAYOUT, {
        xaxis: Object.assign({}, PLOT_LAYOUT.xaxis, { title: "Date" }),
        yaxis: Object.assign({}, PLOT_LAYOUT.yaxis, { title: "Yield / Spread (%)" }),
      });
      Plotly.react("chart-compare", traces, layout, PLOT_CONFIG);

      $("#c-corr-level").textContent = fmt(j.correlations.Level, 3);
      $("#c-corr-slope").textContent = fmt(j.correlations.Slope, 3);
      $("#c-obs").textContent = (j.summary.total_observations || j.dates.length).toLocaleString();
      setCompareStatus(`Loaded ${j.dates.length.toLocaleString()} points.`);
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
      cmpButton.disabled = false;
    }
  });
})();

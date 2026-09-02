/* Fixed Income Studio - shared core: theme, charts, state, API, tabs, status. */
window.Studio = (function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---------------------------------------------------------------- Theme
  const THEME_KEY = "fi-studio-theme";
  // Statistical-release chart theme: ink on paper, hairline grid, one ink per series.
  const THEMES = {
    dark: {
      font: "#b3b9c2", grid: "#2c3138", zero: "#3d434c",
      hoverBg: "#1e2227", hoverBorder: "#3d434c", obs: "#e8eaed", paper: "#16191d",
    },
    light: {
      font: "#3f4753", grid: "#e4e7eb", zero: "#b9c0c9",
      hoverBg: "#ffffff", hoverBorder: "#b9c0c9", obs: "#111111", paper: "#ffffff",
    },
  };
  function getTheme() {
    try { return window.localStorage.getItem(THEME_KEY) || "light"; } catch (_) { return "light"; }
  }
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const btn = $("#btn-theme");
    if (btn) {
      btn.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
      btn.innerHTML = theme === "dark"
        ? '<svg class="icon" aria-hidden="true"><use href="#i-sun"/></svg> Light'
        : '<svg class="icon" aria-hidden="true"><use href="#i-moon"/></svg> Dark';
    }
  }
  function setTheme(theme) {
    try { window.localStorage.setItem(THEME_KEY, theme); } catch (_) { /* ignore */ }
    applyTheme(theme);
    rerenderCharts();
  }
  function toggleTheme() { setTheme(getTheme() === "dark" ? "light" : "dark"); }

  // Monetary Policy Report inks; the dark theme lifts each one step so seven lines stay apart on charcoal.
  const INKS = {
    light: { treasury: "#2f6ea8", tips: "#3a8f4a", fitted: "#d97a1f", purple: "#7d5aa6", pink: "#a83279", red: "#c8473a", teal: "#2a9db0", grey: "#8a949e" },
    dark:  { treasury: "#5b93c9", tips: "#5fae6e", fitted: "#e8964a", purple: "#a07fc9", pink: "#c85aa0", red: "#e0705f", teal: "#4fb7c8", grey: "#9aa3ad" },
  };
  const inks = () => INKS[getTheme()] || INKS.light;
  const COLOR = {
    get treasury() { return inks().treasury; },
    get tips() { return inks().tips; },
    get fitted() { return inks().fitted; },
    get purple() { return inks().purple; },
    get pink() { return inks().pink; },
    get red() { return inks().red; },
    get teal() { return inks().teal; },
    get obs() { return THEMES[getTheme()].obs; },
    get paper() { return THEMES[getTheme()].paper; },
  };
  const SERIES_ORDER = ["treasury", "tips", "purple", "fitted", "pink", "teal", "grey"];
  function seriesColor(i) { return inks()[SERIES_ORDER[i % SERIES_ORDER.length]]; }
  // Kept for callers that read the array at load; prefer seriesColor(i) so the theme applies.
  const SERIES = SERIES_ORDER.map((k) => INKS.light[k]);

  // ---------------------------------------------------------------- Charts
  const hasPlotly = typeof window.Plotly !== "undefined";
  const charts = {};
  const PLOT_CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] };

  function baseLayout() {
    const t = THEMES[getTheme()];
    return {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: t.font, family: "Inter, sans-serif", size: 12 },
      margin: { l: 56, r: 16, t: 24, b: 44 },
      xaxis: { gridcolor: t.grid, zerolinecolor: t.zero, tickfont: { size: 11 }, title: { font: { size: 12 } } },
      yaxis: { gridcolor: t.grid, zerolinecolor: t.zero, tickfont: { size: 11 }, title: { font: { size: 12 } } },
      legend: { orientation: "h", x: 0, y: 1.12, font: { size: 11.5 } },
      hovermode: "x unified",
      hoverlabel: { bgcolor: t.hoverBg, bordercolor: t.hoverBorder, font: { color: t.font } },
    };
  }
  function layoutWith(xTitle, yTitle, extra = {}) {
    const base = baseLayout();
    const layout = Object.assign({}, base, extra);
    layout.xaxis = Object.assign({}, base.xaxis, { title: xTitle }, extra.xaxis || {});
    layout.yaxis = Object.assign({}, base.yaxis, { title: yTitle }, extra.yaxis || {});
    if (extra.yaxis2) layout.yaxis2 = Object.assign({}, base.yaxis, extra.yaxis2);
    return layout;
  }
  function plot(id, traces, layout) {
    charts[id] = { traces, layout };
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove("loading");
    if (!hasPlotly) return;
    window.Plotly.react(id, traces, layout, PLOT_CONFIG);
  }
  function rerenderCharts() {
    Object.keys(charts).forEach((id) => {
      const c = charts[id];
      // Rebuild the theme-dependent layout parts while keeping titles/extras.
      const layout = Object.assign({}, c.layout, baseLayout());
      layout.xaxis = Object.assign({}, baseLayout().xaxis, c.layout.xaxis || {});
      layout.yaxis = Object.assign({}, baseLayout().yaxis, c.layout.yaxis || {});
      if (c.layout.yaxis2) layout.yaxis2 = Object.assign({}, baseLayout().yaxis, c.layout.yaxis2);
      if (c.layout.hovermode) layout.hovermode = c.layout.hovermode;
      if (c.layout.barmode) layout.barmode = c.layout.barmode;
      if (c.layout.legend) layout.legend = Object.assign({}, baseLayout().legend, c.layout.legend);
      c.layout = layout;
      if (hasPlotly && document.getElementById(id)) window.Plotly.react(id, c.traces, layout, PLOT_CONFIG);
    });
  }
  function setChartLoading(ids, on = true) {
    ids.forEach((id) => { const el = document.getElementById(id); if (el) el.classList.toggle("loading", on); });
  }
  function hex2rgba(hex, alpha) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  function bandTraces(x, upper, lower, color, name) {
    return [{
      x: x.concat(x.slice().reverse()), y: upper.concat(lower.slice().reverse()),
      fill: "toself", fillcolor: hex2rgba(color, 0.14), line: { width: 0 },
      hoverinfo: "skip", showlegend: false, name: `${name} band`,
    }];
  }

  // ---------------------------------------------------------------- State
  const SETTINGS_KEY = "fi-studio-settings";
  const DEFAULT_SETTINGS = {
    bondType: "treasury", model: "nelson-siegel", labModel: "nelson-siegel",
    histBondType: "treasury", histModel: "nelson-siegel", histRange: "1", cmpRange: "1",
    showForward: false, fcMethod: "ar", fcHorizon: "12",
    srModel: "vasicek", srMethod: "ols", srProxy: "policy", srRange: "20", srHorizon: "5",
    tpSource: "gsw", tpRange: "max", tpFactors: "5", tpDns: "var", tpFocus: "10", tpMaturities: ["2", "5", "10"],
    anBondType: "treasury", anModel: "nelson-siegel", anHorizon: "1",
    sidebarCollapsed: false, lastTab: "fitter",
  };
  const PERSISTED = Object.keys(DEFAULT_SETTINGS);
  function loadSettings() {
    try {
      const raw = window.localStorage.getItem(SETTINGS_KEY);
      return Object.assign({}, DEFAULT_SETTINGS, raw ? JSON.parse(raw) : {});
    } catch (_) {
      return Object.assign({}, DEFAULT_SETTINGS);
    }
  }
  const state = loadSettings();
  state.models = {};
  function saveSettings() {
    try {
      const out = {};
      PERSISTED.forEach((k) => { out[k] = state[k]; });
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(out));
    } catch (_) { /* private mode etc. */ }
  }

  // ---------------------------------------------------------------- Helpers
  let toastTimer = null;
  function toast(msg, kind = "info") {
    const el = $("#toast");
    if (!el) return;
    el.textContent = msg;
    el.className = `toast show ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3800);
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
  const fmtPct = (v, d = 2) => fmt(v, d, " %");
  const fmtBps = (v, d = 1) => fmt(v, d, " bps");
  function signed(v, digits = 1, suffix = "") {
    if (v == null || isNaN(v)) return "—";
    const s = Number(v).toFixed(digits);
    return (v > 0 ? "+" : "") + s + suffix;
  }
  function tenorLabel(years) {
    const y = Number(years);
    if (y < 1) return `${Math.round(y * 12)}M`;
    return Number.isInteger(y) ? `${y}Y` : `${y.toFixed(2)}Y`;
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
    const target = buttons.find((b) => b.dataset[attr] === String(value)) || buttons[0];
    setSegmented(buttons, target);
    return target;
  }
  function bindSegmented(selector, attr, onChange) {
    $$(selector).forEach((btn) => btn.addEventListener("click", () => {
      setSegmented($$(selector), btn);
      onChange(btn.dataset[attr], btn);
    }));
  }
  function bindChips(containerSel, attr, onChange, { multi = false } = {}) {
    $$(`${containerSel} .chip`).forEach((chip) => chip.addEventListener("click", () => {
      if (multi) {
        chip.classList.toggle("active");
        onChange($$(`${containerSel} .chip.active`).map((c) => c.dataset[attr]));
      } else {
        $$(`${containerSel} .chip`).forEach((c) => c.classList.toggle("active", c === chip));
        onChange(chip.dataset[attr], chip);
      }
    }));
  }
  function setChips(containerSel, attr, values) {
    const wanted = Array.isArray(values) ? values.map(String) : [String(values)];
    $$(`${containerSel} .chip`).forEach((c) => c.classList.toggle("active", wanted.includes(c.dataset[attr])));
  }
  function isoDate(d) { return d.toISOString().slice(0, 10); }
  function rangeDates(years) {
    const end = new Date();
    const start = new Date(end);
    if (years === "max") start.setFullYear(1961, 0, 1);
    else start.setFullYear(end.getFullYear() - Number(years));
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
  function renderTable(el, columns, rows, opts = {}) {
    // columns: [{key, label, fmt, align, cls}] ; rows: array of objects
    let html = "<thead><tr>";
    columns.forEach((c) => { html += `<th class="${c.align || ""}">${c.label}</th>`; });
    html += "</tr></thead><tbody>";
    rows.forEach((row) => {
      html += "<tr>";
      columns.forEach((c) => {
        const raw = row[c.key];
        const text = c.fmt ? c.fmt(raw, row) : (raw == null ? "—" : raw);
        const cls = [c.align || "", c.cls ? c.cls(raw, row) : ""].join(" ").trim();
        html += `<td class="${cls}">${text}</td>`;
      });
      html += "</tr>";
    });
    html += "</tbody>";
    el.innerHTML = html;
    if (opts.caption) el.setAttribute("aria-label", opts.caption);
  }
  function heatClass(bps, scale = 25) {
    if (bps == null || isNaN(bps)) return "";
    const a = Math.min(1, Math.abs(bps) / scale);
    if (a < 0.15) return "";
    return (bps > 0 ? "heat-up" : "heat-down") + (a > 0.6 ? " strong" : "");
  }
  function metricTile(label, value, hint = "", cls = "") {
    return `<div class="metric ${cls}"><span class="metric-label">${label}</span><span class="metric-value">${value}</span><span class="metric-hint">${hint}</span></div>`;
  }

  // ---------------------------------------------------------------- API
  async function api(url, options = {}, { timeout = 90000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const r = await fetch(url, Object.assign({ signal: controller.signal }, options));
      let j = null;
      try { j = await r.json(); } catch (_) { j = null; }
      if (!r.ok) throw new Error((j && j.error) || `Request failed (${r.status}).`);
      if (j && j.sources) updateDataStatus(j);
      return j;
    } catch (err) {
      if (err.name === "AbortError") throw new Error("The request timed out. Try a shorter date range.");
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
  const postJSON = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  // ---------------------------------------------------------------- Tabs
  const tabs = {};
  const shown = new Set();
  function registerTab(name, handlers) { tabs[name] = handlers; }
  function showTab(tab) {
    if (!$(`.tab-pane[data-tab-pane="${tab}"]`)) tab = "fitter";
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    $$(".tab-pane").forEach((p) => p.classList.toggle("active", p.dataset.tabPane === tab));
    state.lastTab = tab;
    saveSettings();
    if (window.location.hash !== `#${tab}`) history.replaceState(null, "", `#${tab}`);
    document.body.classList.remove("sidebar-open");
    window.dispatchEvent(new Event("resize"));
    const handler = tabs[tab];
    if (handler && handler.onShow) handler.onShow(!shown.has(tab));
    shown.add(tab);
    const pane = $(`.tab-pane[data-tab-pane="${tab}"] h2`);
    if (pane) document.title = `${pane.textContent} · Fixed Income Studio`;
  }
  function initTabs() {
    $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => showTab(btn.dataset.tab)));
    document.addEventListener("keydown", (e) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      const idx = parseInt(e.key, 10) - 1;
      const buttons = $$(".nav-item");
      if (idx >= 0 && idx < buttons.length) { e.preventDefault(); showTab(buttons[idx].dataset.tab); }
      if (e.key.toLowerCase() === "t") { e.preventDefault(); toggleTheme(); }
    });
    window.addEventListener("hashchange", () => {
      const tab = window.location.hash.replace("#", "");
      if (tab && tabs[tab]) showTab(tab);
    });
    $("#btn-theme").addEventListener("click", toggleTheme);
    $("#btn-collapse").addEventListener("click", () => {
      state.sidebarCollapsed = !state.sidebarCollapsed;
      document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
      saveSettings();
      window.dispatchEvent(new Event("resize"));
    });
    $("#btn-menu").addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
    $("#sidebar-backdrop").addEventListener("click", () => document.body.classList.remove("sidebar-open"));
    document.body.classList.toggle("sidebar-collapsed", !!state.sidebarCollapsed);
  }

  // ---------------------------------------------------------------- Data status
  const DATASET_LABELS = { treasury: "Treasury", tips: "TIPS", policy_rate: "Fed funds", gsw: "GSW zero curve", kim_wright: "Kim-Wright TP" };
  function updateDataStatus(info) {
    if (!info) return;
    document.body.dataset.fredKey = info.fred_api_key ? "true" : "false";
    document.body.dataset.synthetic = info.is_synthetic ? "true" : "false";
    const sources = info.sources || {};
    const live = Object.values(sources).filter((s) => s && !/synthetic/i.test(s));
    const headline = info.fred_api_key ? "FRED API (live)"
      : live.length ? live[0]
      : info.public_sources ? (Object.values(sources).some(Boolean) ? "Synthetic demo" : "Public feeds") : "Synthetic demo";
    $("#data-source-text").textContent = headline;
    const list = $("#data-source-list");
    if (list) {
      list.innerHTML = Object.keys(DATASET_LABELS).map((k) => {
        const v = sources[k];
        const label = k === "kim_wright" && v && /synthetic/i.test(v) ? "unavailable" : (v || "not loaded");
        const cls = !v ? "idle" : /synthetic/i.test(v) ? "synthetic" : "live";
        return `<li class="${cls}"><span>${DATASET_LABELS[k]}</span><span class="src">${label}</span></li>`;
      }).join("");
    }
    const note = $("#fred-key-note");
    if (note) {
      note.textContent = info.fred_api_key ? "Live FRED data enabled for this app session."
        : info.public_sources ? "Optional: without a key the app reads treasury.gov, FRED's public CSV and the Fed's GSW tables."
        : "Public feeds are disabled (offline mode); synthetic data is in use.";
    }
    const banner = $("#synthetic-banner");
    if (banner) banner.hidden = !info.is_synthetic || !Object.values(sources).some(Boolean);
  }
  async function refreshStatus() {
    try {
      const j = await api("/api/health");
      updateDataStatus(j);
      const v = $("#app-version");
      if (v && j.version) v.textContent = `v${j.version}`;
    } catch (_) {
      $("#data-source-text").textContent = "Offline";
    }
  }
  function initFredKeyForm() {
    $("#fred-key-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = $("#fred-api-key");
      const apiKey = input.value.trim();
      if (!apiKey) { toast("Paste a FRED API key first.", "error"); input.focus(); return; }
      const btn = $("#fred-key-form button[type=submit]");
      setBusy(btn, true, "…");
      try {
        await postJSON("/api/fred-key", { api_key: apiKey });
        input.value = "";
        await refreshStatus();
        toast("FRED API key applied. Reload a snapshot to fetch live data.", "success");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        setBusy(btn, false);
      }
    });
  }

  // ---------------------------------------------------------------- Models
  const FALLBACK_MODELS = {
    "nelson-siegel": { id: "nelson-siegel", name: "Nelson-Siegel", min_points: 4, family: "parametric" },
    "svensson": { id: "svensson", name: "Svensson", min_points: 6, family: "parametric" },
    "vasicek": { id: "vasicek", name: "Vasicek", min_points: 4, family: "short-rate" },
    "cir": { id: "cir", name: "CIR", min_points: 4, family: "short-rate" },
  };
  state.models = FALLBACK_MODELS;
  async function loadModels() {
    try {
      const j = await api("/api/models");
      const map = {};
      (j.models || []).forEach((m) => { map[m.id] = m; });
      if (Object.keys(map).length) state.models = map;
    } catch (_) { /* keep fallback */ }
  }
  function modelInfo(id) { return state.models[id] || FALLBACK_MODELS[id] || FALLBACK_MODELS["nelson-siegel"]; }

  // ---------------------------------------------------------------- Boot
  function boot() {
    applyTheme(getTheme());
    if (!hasPlotly) {
      $$(".chart").forEach((el) => {
        el.innerHTML = '<div class="chart-offline">Charts unavailable: plotly.js could not be loaded. '
          + 'Install the <code>plotly</code> Python package to serve it locally, or allow access to cdn.plot.ly.</div>';
      });
    }
    initTabs();
    initFredKeyForm();
    refreshStatus();
    loadModels();
    Object.keys(tabs).forEach((name) => { if (tabs[name].init) tabs[name].init(); });
    const fromHash = window.location.hash.replace("#", "");
    showTab(fromHash && tabs[fromHash] ? fromHash : (state.lastTab || "fitter"));
  }

  return {
    $, $$, COLOR, SERIES, seriesColor, state, saveSettings, toast, setBusy, fmt, fmtPct, fmtBps, signed, tenorLabel,
    setSegmented, activateSegmentedByData, bindSegmented, bindChips, setChips, isoDate, rangeDates,
    downloadCSV, renderTable, heatClass, metricTile, plot, layoutWith, setChartLoading, hex2rgba, bandTraces,
    api, postJSON, registerTab, showTab, updateDataStatus, refreshStatus, modelInfo, boot, getTheme, hasPlotly,
  };
})();

/* Historical Factors tab: factor histories, Diebold-Li forecast and backtest. */
(function (S) {
  "use strict";
  const { $, $$, COLOR, state, saveSettings, toast, setBusy, fmt } = S;

  const FACTOR_COLORS = { Level: COLOR.treasury, Slope: COLOR.tips, Curvature: COLOR.purple, Curvature2: COLOR.pink };
  const FACTOR_SYMBOL = { Level: "β₀", Slope: "β₁", Curvature: "β₂", Curvature2: "β₃" };
  const rateFactorNames = (j) => (j.factor_meta ? j.factor_meta.filter((m) => m.unit === "rate").map((m) => m.label) : ["Level", "Slope", "Curvature"]);

  function applyRange(years) {
    const { start, end } = S.rangeDates(years);
    $("#hist-start").value = start;
    $("#hist-end").value = end;
    S.setChips("#hist-chips", "histRange", years);
    state.histRange = String(years);
    saveSettings();
  }
  const params = () => new URLSearchParams({ bond_type: state.histBondType, model: state.histModel, start: $("#hist-start").value, end: $("#hist-end").value });

  async function run() {
    const btn = $("#btn-hist-run");
    setBusy(btn, true, "Computing…");
    S.setChartLoading(["chart-historical", "chart-hist-rmse"]);
    try {
      const j = await S.api(`/api/historical?${params().toString()}`);
      state.lastHist = j;
      const traces = rateFactorNames(j).map((name) => ({
        x: j.dates, y: (j.series && j.series[name]) || [], name: `${name} (${FACTOR_SYMBOL[name] || ""})`,
        line: { color: FACTOR_COLORS[name] || COLOR.obs, width: 2 }, mode: "lines",
      }));
      S.plot("chart-historical", traces, S.layoutWith("Date", "Factor (%)"));
      if (j.rmse_bps) {
        S.plot("chart-hist-rmse", [{
          x: j.dates, y: j.rmse_bps, name: "Fit RMSE", mode: "lines", fill: "tozeroy",
          line: { color: COLOR.fitted, width: 1.5 }, fillcolor: S.hex2rgba(COLOR.fitted, 0.12),
          hovertemplate: "%{x} · <b>%{y:.1f} bps</b><extra></extra>",
        }], S.layoutWith("Date", "RMSE (bps)", { hovermode: "x" }));
      }
      $("#h-level").textContent = fmt(j.summary.level_mean, 2, " %");
      $("#h-slope").textContent = fmt(j.summary.slope_mean, 2, " %");
      const decays = j.summary.decays || { Tau: j.summary.tau };
      $("#h-tau").textContent = Object.values(decays).map((v) => fmt(v, 2)).join(" / ") + " y";
      $("#h-tau-label").innerHTML = Object.keys(decays).length > 1 ? '<span class="sym">τ₁ / τ₂</span> (panel)' : '<span class="sym">τ</span> (panel)';
      $("#h-rmse").textContent = fmt(j.summary.rmse_bps_mean, 1, " bps");
      $("#h-obs").textContent = j.summary.n_observations.toLocaleString();
      const src = j.sources && j.sources[j.bond_type] ? ` · ${j.sources[j.bond_type]}` : "";
      $("#hist-range").textContent = `${j.model_name || "Nelson-Siegel"} · ${j.summary.start} → ${j.summary.end}${src}`;
      ["btn-hist-export", "btn-fc-run", "btn-bt-run"].forEach((id) => { $("#" + id).disabled = false; $("#" + id).title = ""; });
      toast("Historical factors loaded.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
      S.setChartLoading(["chart-historical", "chart-hist-rmse"], false);
    }
  }

  function renderForecastMetrics(j) {
    const host = $("#fc-metrics");
    const s = j.summary;
    const stepLabel = s.step_days >= 6 ? "weeks" : "days";
    const hl = s.half_life_steps || {};
    const fmtHl = (v, rho) => (v != null ? `${v.toFixed(1)} ${stepLabel}` : rho >= 1 ? "∞ (unit root)" : "n/a");
    const names = j.factor_names || ["Level", "Slope", "Curvature"];
    host.classList.toggle("grid-5", names.length > 3);
    host.classList.toggle("grid-4", names.length <= 3);
    host.innerHTML = names.map((name) => {
      const rho = s.persistence[name];
      return S.metricTile(`${name} half-life`, fmtHl(hl[name], rho), rho <= 0 ? `persistence ${fmt(rho, 3)} · no mean reversion` : `persistence ${fmt(rho, 3)}`);
    }).join("") + S.metricTile(`Level in ${j.horizon} ${stepLabel}`, fmt(j.level[j.level.length - 1], 2, " %"),
      s.unconditional_mean ? `long-run mean ${fmt(s.unconditional_mean.Level, 2, " %")}` : "non-stationary dynamics");
  }

  function plotForecast(j) {
    const h = state.lastHist;
    const tail = h ? Math.max(0, h.dates.length - Math.max(60, j.horizon * 4)) : 0;
    const names = j.factor_names || ["Level", "Slope", "Curvature"];
    const traces = [];
    if (h && h.series) {
      names.forEach((name) => {
        if (!h.series[name]) return;
        traces.push({ x: h.dates.slice(tail), y: h.series[name].slice(tail), name, mode: "lines", line: { color: FACTOR_COLORS[name] || COLOR.obs, width: 1.5 } });
      });
    }
    names.forEach((name) => {
      const y = (j.series && j.series[name]) || j[name.toLowerCase()];
      const sd = (j.series_std && j.series_std[name]) || j[name.toLowerCase() + "_std"];
      if (!y || !sd) return;
      const color = FACTOR_COLORS[name] || COLOR.treasury;
      traces.push(...S.bandTraces(j.dates, y.map((v, i) => v + 1.645 * sd[i]), y.map((v, i) => v - 1.645 * sd[i]), color, name));
      traces.push({ x: j.dates, y, name: `${name} forecast`, mode: "lines", line: { color, width: 2, dash: "dash" },
        hovertemplate: `%{x} · <b>%{y:.3f}%</b><extra>${name} forecast</extra>` });
    });
    S.plot("chart-forecast-factors", traces, S.layoutWith("Date", "Factor (%)"));
    S.plot("chart-forecast-curve", [
      { x: j.smooth.maturities, y: j.smooth.current, name: `Current (${j.summary.last_date})`, mode: "lines", line: { color: COLOR.fitted, width: 2.5 } },
      { x: j.smooth.maturities, y: j.smooth.forecast, name: `Forecast (+${j.horizon} steps)`, mode: "lines", line: { color: COLOR.obs, width: 2, dash: "dash" } },
      { x: j.maturities, y: j.current_curve, name: "Current tenors", mode: "markers", marker: { color: COLOR.fitted, size: 7 }, showlegend: false },
      { x: j.maturities, y: j.forecast_curve, name: "Forecast tenors", mode: "markers", marker: { color: COLOR.obs, size: 7 }, showlegend: false },
    ], S.layoutWith("Maturity (years)", "Yield (%)"));
  }

  async function forecast() {
    const btn = $("#btn-fc-run");
    const p = params();
    p.set("method", state.fcMethod);
    p.set("horizon", state.fcHorizon);
    setBusy(btn, true, "Forecasting…");
    try {
      const j = await S.api(`/api/forecast?${p.toString()}`);
      $("#fc-empty").hidden = true;
      $("#fc-results").hidden = false;
      renderForecastMetrics(j);
      plotForecast(j);
      window.dispatchEvent(new Event("resize"));
      toast(`${j.method.toUpperCase()} forecast ready.`, "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  }

  async function backtest() {
    const btn = $("#btn-bt-run");
    const p = params();
    p.set("horizons", "1,4,12");
    setBusy(btn, true, "Backtesting…");
    try {
      const j = await S.api(`/api/backtest?${p.toString()}`);
      const names = { rw: "Random walk", ar: "AR(1)", var: "VAR(1)" };
      const byH = {};
      j.rows.forEach((row) => { (byH[row.horizon] = byH[row.horizon] || {})[row.method] = row; });
      const horizons = Object.keys(byH).map(Number).sort((a, b) => a - b);
      let html = "<thead><tr><th>Horizon (steps)</th>";
      ["rw", "ar", "var"].forEach((m) => { html += `<th>${names[m]}</th>`; });
      html += "<th>Best</th></tr></thead><tbody>";
      horizons.forEach((hz) => {
        const cells = ["rw", "ar", "var"].map((m) => (byH[hz][m] ? byH[hz][m].yield_rmse_bps : NaN));
        const best = ["rw", "ar", "var"][cells.indexOf(Math.min(...cells))];
        html += `<tr><td>${hz}</td>`;
        ["rw", "ar", "var"].forEach((m, i) => { html += `<td class="${m === best ? "best" : ""}">${fmt(cells[i], 1)}</td>`; });
        html += `<td>${names[best]}</td></tr>`;
      });
      html += "</tbody>";
      $("#bt-table").innerHTML = html;
      $("#bt-note").textContent = `· yield RMSE across tenors, ${j.rows[0].n_forecasts.toLocaleString()} forecast origins, first ${j.min_train} steps for training`;
      $("#bt-results").hidden = false;
      toast("Backtest ready.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  }

  function exportCSV() {
    const h = state.lastHist;
    if (!h) return;
    const cols = h.factor_meta ? h.factor_meta.map((m) => m.label) : ["Level", "Slope", "Curvature", "Tau"];
    const header = ["date"].concat(cols.map((c) => c.toLowerCase()), ["rmse_bps"]);
    const rows = h.dates.map((d, i) => [d].concat(cols.map((c) => (h.series && h.series[c] ? h.series[c][i] : "")), [h.rmse_bps ? h.rmse_bps[i] : ""]));
    S.downloadCSV(`factors-${h.bond_type}-${h.model || "ns"}-${h.summary.start}-${h.summary.end}.csv`, header, rows);
  }

  function init() {
    S.bindSegmented('.seg-btn[data-hist-bond]', "histBond", (v) => { state.histBondType = v; saveSettings(); });
    S.bindSegmented('.seg-btn[data-hist-model]', "histModel", (v) => { state.histModel = v; saveSettings(); });
    S.bindChips("#hist-chips", "histRange", applyRange);
    ["hist-start", "hist-end"].forEach((id) => $("#" + id).addEventListener("change", () => $$("#hist-chips .chip").forEach((c) => c.classList.remove("active"))));
    $("#btn-hist-run").addEventListener("click", run);
    S.bindSegmented('.seg-btn[data-fc-method]', "fcMethod", (v) => { state.fcMethod = v; saveSettings(); });
    S.bindChips("#fc-chips", "fcHorizon", (v) => { state.fcHorizon = v; saveSettings(); });
    $("#btn-fc-run").addEventListener("click", forecast);
    $("#btn-bt-run").addEventListener("click", backtest);
    $("#btn-hist-export").addEventListener("click", exportCSV);

    S.activateSegmentedByData('.seg-btn[data-hist-bond]', "histBond", state.histBondType);
    S.activateSegmentedByData('.seg-btn[data-hist-model]', "histModel", state.histModel);
    S.activateSegmentedByData('.seg-btn[data-fc-method]', "fcMethod", state.fcMethod);
    S.setChips("#fc-chips", "fcHorizon", state.fcHorizon);
    applyRange(state.histRange);
  }

  S.registerTab("historical", { init, onShow: (first) => { if (first && !state.lastHist) run(); } });
})(window.Studio);

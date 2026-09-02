/* Short-Rate Models tab: Vasicek / CIR estimation, calibration and simulation. */
(function (S) {
  "use strict";
  const { $, $$, COLOR, state, saveSettings, toast, setBusy, fmt } = S;

  function applyRange(years) {
    const { start, end } = S.rangeDates(years);
    $("#sr-start").value = start;
    $("#sr-end").value = end;
    S.setChips("#sr-chips", "srRange", years);
    state.srRange = String(years);
    saveSettings();
  }

  function futureDates(asOf, horizons) {
    const base = new Date(asOf);
    return horizons.map((h) => {
      const d = new Date(base);
      d.setDate(d.getDate() + Math.round(h * 365.25));
      return S.isoDate(d);
    });
  }

  function renderMetrics(j) {
    const e = j.estimate;
    const c = j.calibrated.factors;
    const hl = e.half_life_years != null ? `${e.half_life_years.toFixed(1)} y half-life` : "no mean reversion";
    const feller = e.feller == null ? "" : e.feller ? " · Feller ✓" : " · Feller ✗";
    $("#sr-metrics").innerHTML = [
      S.metricTile("κ · mean reversion (P)", fmt(e.kappa, 3, " /y"), hl),
      S.metricTile("θ · long-run mean (P)", S.fmtPct(e.theta_pct), `${e.method.toUpperCase()} on ${e.n_obs} obs${feller}`),
      S.metricTile("σ · volatility", S.fmtPct(e.sigma_pct), j.model === "cir" ? "scales with √r" : "absolute, annualised"),
      S.metricTile("r₀ · latest proxy", S.fmtPct(e.r0_pct), `${j.proxy === "policy" ? "fed funds" : j.proxy.toUpperCase() + " bill"} · ${j.history.dates[j.history.dates.length - 1]}`),
      S.metricTile("θ · long-run mean (Q)", S.fmtPct(c.LongRunMean), `κ = ${fmt(c.MeanReversion, 2)} /y from today's curve`),
      S.metricTile("Curve fit", S.fmtBps(j.calibrated.rmse_bps), `R² ${fmt(j.calibrated.r_squared, 3)} · as of ${j.as_of}`),
    ].join("");
    const gap = c.LongRunMean - e.theta_pct;
    $("#sr-insight").innerHTML = `Under the physical measure the short rate is pulled toward <b>${S.fmtPct(e.theta_pct)}</b>; the curve prices as if it were pulled toward <b>${S.fmtPct(c.LongRunMean)}</b>. `
      + `That gap of <b>${S.signed(gap * 100, 0, " bps")}</b> is the market price of interest-rate risk expressed as a long-run rate: ${gap > 0 ? "investors demand a positive term premium." : "investors are paying up for duration (negative term premium)."}`;
  }

  function plotPaths(j) {
    const h = j.history;
    const p = j.paths;
    const future = futureDates(j.as_of, p.horizons);
    const traces = [
      { x: h.dates, y: h.values, name: "Short-rate proxy", mode: "lines", line: { color: COLOR.obs, width: 1.5 },
        hovertemplate: "%{x} · <b>%{y:.2f}%</b><extra>History</extra>" },
      ...S.bandTraces(future, p.p95, p.p5, COLOR.treasury, "5-95%"),
      ...S.bandTraces(future, p.p75, p.p25, COLOR.treasury, "25-75%"),
      { x: future, y: p.p50, name: "Median path", mode: "lines", line: { color: COLOR.treasury, width: 2 } },
      { x: future, y: p.expected_physical, name: "Expected (physical)", mode: "lines", line: { color: COLOR.tips, width: 2, dash: "dash" } },
      { x: future, y: p.expected_risk_neutral, name: "Expected (risk-neutral, from curve)", mode: "lines", line: { color: COLOR.fitted, width: 2, dash: "dot" } },
    ];
    S.plot("chart-sr-paths", traces, S.layoutWith("Date", "Short rate (%)"));
  }

  function plotCurve(j) {
    const s = j.smooth;
    S.plot("chart-sr-curve", [
      { x: j.maturities, y: j.observed, mode: "markers", name: "Observed", marker: { color: COLOR.obs, size: 8 } },
      { x: s.maturities, y: s.fitted, mode: "lines", name: `${j.model_name} curve`, line: { color: COLOR.fitted, width: 3 } },
      { x: s.maturities, y: s.expectations, mode: "lines", name: "Expectations-only yield", line: { color: COLOR.tips, width: 2, dash: "dash" } },
      { x: s.maturities, y: s.forward, mode: "lines", name: "Instantaneous forward", line: { color: COLOR.purple, width: 1.5, dash: "dot" } },
    ], S.layoutWith("Maturity (years)", "Yield (%)"));
    const tp = j.term_premium;
    S.plot("chart-sr-tp", [{
      x: tp.maturities.map(S.tenorLabel), y: tp.term_premium_bps, type: "bar", name: "Term premium",
      marker: { color: tp.term_premium_bps.map((v) => (v >= 0 ? COLOR.treasury : COLOR.red)) },
      hovertemplate: "%{x} · <b>%{y:.0f} bps</b><extra></extra>",
    }], S.layoutWith("Tenor", "Observed − expected (bps)", { hovermode: "x" }));
  }

  async function run() {
    const btn = $("#btn-sr-run");
    setBusy(btn, true, "Estimating…");
    S.setChartLoading(["chart-sr-paths", "chart-sr-curve", "chart-sr-tp"]);
    const params = new URLSearchParams({
      model: state.srModel, method: state.srMethod, proxy: state.srProxy, start: $("#sr-start").value, end: $("#sr-end").value,
      horizon: state.srHorizon, paths: 300,
    });
    try {
      const j = await S.api(`/api/short-rate?${params.toString()}`);
      state.lastShortRate = j;
      renderMetrics(j);
      plotPaths(j);
      plotCurve(j);
      $("#sr-results").hidden = false;
      $("#sr-empty").hidden = true;
      $("#btn-sr-export").disabled = false;
      window.dispatchEvent(new Event("resize"));
      toast(`${j.model_name} estimated on ${j.estimate.n_obs} weekly observations.`, "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
      S.setChartLoading(["chart-sr-paths", "chart-sr-curve", "chart-sr-tp"], false);
    }
  }

  function exportCSV() {
    const j = state.lastShortRate;
    if (!j) return;
    const future = futureDates(j.as_of, j.paths.horizons);
    const rows = future.map((d, i) => [d, j.paths.horizons[i], j.paths.p5[i], j.paths.p25[i], j.paths.p50[i], j.paths.p75[i], j.paths.p95[i], j.paths.expected_physical[i], j.paths.expected_risk_neutral[i]]);
    S.downloadCSV(`short-rate-${j.model}-${j.as_of}.csv`, ["date", "years_ahead", "p5", "p25", "p50", "p75", "p95", "expected_physical", "expected_risk_neutral"], rows);
  }

  function init() {
    S.bindSegmented('.seg-btn[data-sr-model]', "srModel", (v) => { state.srModel = v; saveSettings(); });
    S.bindSegmented('.seg-btn[data-sr-method]', "srMethod", (v) => { state.srMethod = v; saveSettings(); });
    $("#sr-proxy").addEventListener("change", (e) => { state.srProxy = e.target.value; saveSettings(); });
    S.bindChips("#sr-chips", "srRange", applyRange);
    S.bindChips("#sr-horizon-chips", "srHorizon", (v) => { state.srHorizon = v; saveSettings(); });
    ["sr-start", "sr-end"].forEach((id) => $("#" + id).addEventListener("change", () => $$("#sr-chips .chip").forEach((c) => c.classList.remove("active"))));
    $("#btn-sr-run").addEventListener("click", run);
    $("#btn-sr-export").addEventListener("click", exportCSV);

    S.activateSegmentedByData('.seg-btn[data-sr-model]', "srModel", state.srModel);
    S.activateSegmentedByData('.seg-btn[data-sr-method]', "srMethod", state.srMethod);
    $("#sr-proxy").value = state.srProxy;
    S.setChips("#sr-horizon-chips", "srHorizon", state.srHorizon);
    applyRange(state.srRange);
  }

  S.registerTab("shortrate", { init, onShow: (first) => { if (first && !state.lastShortRate) run(); } });
})(window.Studio);

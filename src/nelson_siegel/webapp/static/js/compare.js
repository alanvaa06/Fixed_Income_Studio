/* Treasury vs TIPS tab */
(function (S) {
  "use strict";
  const { $, $$, COLOR, state, saveSettings, toast, setBusy, fmt } = S;

  function applyRange(years) {
    const { start, end } = S.rangeDates(years);
    $("#cmp-start").value = start;
    $("#cmp-end").value = end;
    S.setChips("#cmp-chips", "cmpRange", years);
    state.cmpRange = String(years);
    saveSettings();
  }
  const setStatus = (text) => { $("#cmp-status").textContent = text; };

  async function run() {
    const btn = $("#btn-cmp-run");
    setBusy(btn, true, "Computing…");
    setStatus("Aligning Treasury and TIPS…");
    S.setChartLoading(["chart-compare"]);
    const params = new URLSearchParams({ start: $("#cmp-start").value, end: $("#cmp-end").value });
    try {
      const j = await S.api(`/api/compare?${params.toString()}`, {}, { timeout: 45000 });
      state.lastCompare = j;
      S.plot("chart-compare", [
        { x: j.dates, y: j.treasury_level, name: "Treasury Level", line: { color: COLOR.treasury, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.tips_level, name: "TIPS Level", line: { color: COLOR.tips, width: 2 }, mode: "lines" },
        { x: j.dates, y: j.breakeven, name: "Breakeven inflation", line: { color: COLOR.fitted, width: 2.5, dash: "dot" }, mode: "lines",
          fill: "tozeroy", fillcolor: "rgba(245, 158, 11, 0.08)" },
      ], S.layoutWith("Date", "Yield / Spread (%)"));
      $("#c-corr-level").textContent = fmt(j.correlations.Level, 3);
      $("#c-corr-slope").textContent = fmt(j.correlations.Slope, 3);
      $("#c-corr-curv").textContent = fmt(j.correlations.Curvature, 3);
      $("#c-obs").textContent = (j.summary.total_observations || j.dates.length).toLocaleString();
      const be = j.breakeven[j.breakeven.length - 1];
      $("#c-breakeven").textContent = fmt(be, 2, " %");
      const src = j.sources && j.sources.treasury ? ` · ${j.sources.treasury}` : "";
      setStatus(`${j.dates.length.toLocaleString()} points${src}`);
      $("#btn-cmp-export").disabled = false;
      toast("Comparison ready.", "success");
    } catch (err) {
      setStatus(err.message);
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
      S.setChartLoading(["chart-compare"], false);
    }
  }

  function init() {
    S.bindChips("#cmp-chips", "cmpRange", applyRange);
    ["cmp-start", "cmp-end"].forEach((id) => $("#" + id).addEventListener("change", () => $$("#cmp-chips .chip").forEach((c) => c.classList.remove("active"))));
    $("#btn-cmp-run").addEventListener("click", run);
    $("#btn-cmp-export").addEventListener("click", () => {
      const c = state.lastCompare;
      if (!c) return;
      const rows = c.dates.map((d, i) => [d, c.treasury_level[i], c.tips_level[i], c.treasury_slope[i], c.tips_slope[i], c.breakeven[i]]);
      S.downloadCSV(`treasury-vs-tips-${c.summary.date_range.start}-${c.summary.date_range.end}.csv`,
        ["date", "treasury_level_pct", "tips_level_pct", "treasury_slope_pct", "tips_slope_pct", "breakeven_pct"], rows);
    });
    applyRange(state.cmpRange);
  }

  S.registerTab("compare", { init, onShow: (first) => { if (first && !state.lastCompare) run(); } });
})(window.Studio);

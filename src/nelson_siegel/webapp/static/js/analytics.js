/* Curve Analytics tab: carry & roll, forwards, spreads, rich/cheap, PCA, bond calculator. */
(function (S) {
  "use strict";
  const { $, $$, COLOR, SERIES, state, saveSettings, toast, setBusy, fmt } = S;

  const LOOKBACKS = [["chg_1_bps", "1D"], ["chg_5_bps", "1W"], ["chg_21_bps", "1M"], ["chg_63_bps", "3M"], ["chg_252_bps", "1Y"]];

  function renderMetrics(j) {
    const sp = j.spreads;
    const tenIdx = j.changes.maturities.indexOf(10);
    const chg10 = tenIdx >= 0 ? j.changes.chg_1_bps[tenIdx] : null;
    const tiles = [
      S.metricTile("2s10s", S.fmtBps(sp["2s10s"], 0), sp["2s10s"] < 0 ? "inverted" : "upward sloping"),
      S.metricTile("5s30s", S.fmtBps(sp["5s30s"], 0), "long-end steepness"),
      S.metricTile("2s5s10s fly", S.fmtBps(sp["2s5s10s"], 0), "belly vs wings"),
      S.metricTile("3m10y", S.fmtBps(sp["3m10y"], 0), "bills vs bonds"),
      S.metricTile("10Y move", S.signed(chg10, 0, " bps"), `1 day · as of ${j.as_of}`),
    ].filter((t) => !t.includes(">—<") || true);
    $("#an-metrics").innerHTML = tiles.join("");
    const src = j.sources && j.sources[j.bond_type];
    const bond = j.bond_type === "tips" ? "TIPS" : "Treasury";
    $("#an-source-note").textContent =
      `${j.model_name || j.model} fitted to ${bond} quotes as of ${j.as_of}${src ? " · " + src : ""}` +
      " · spreads, carry, forwards and rich/cheap come from the fit; the moves table is observed quotes";
  }

  function renderChanges(j) {
    const ch = j.changes;
    const rows = ch.maturities.map((m, i) => {
      const row = { tenor: S.tenorLabel(m), yield: ch.yield[i] };
      LOOKBACKS.forEach(([k]) => { row[k] = ch[k] ? ch[k][i] : null; });
      return row;
    });
    S.renderTable($("#an-changes-table"), [
      { key: "tenor", label: "Tenor" },
      { key: "yield", label: "Yield", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      ...LOOKBACKS.map(([k, label]) => ({ key: k, label, fmt: (v) => S.signed(v, 0), align: "num", cls: (v) => S.heatClass(v, label === "1D" ? 10 : label === "1Y" ? 100 : 30) })),
    ], rows);
    const traces = [{
      x: ch.maturities, y: ch.yield, name: `Today (${ch.as_of})`, mode: "markers",
      marker: { color: COLOR.obs, size: 9, line: { color: COLOR.paper, width: 1 } },
      hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Observed today</extra>",
    }];
    if (j.smooth && j.smooth.maturities) {
      traces.push({
        x: j.smooth.maturities, y: j.smooth.yields, name: `${j.model_name || j.model} fit`, mode: "lines",
        line: { color: COLOR.fitted, width: 3, shape: "spline" },
        hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Model fit</extra>",
      });
    }
    [["chg_21_bps", "1M ago", COLOR.treasury], ["chg_252_bps", "1Y ago", COLOR.purple]].forEach(([k, name, color]) => {
      if (!ch[k] || ch[k].every((v) => v == null)) return;
      traces.push({ x: ch.maturities, y: ch.yield.map((y, i) => (ch[k][i] == null ? null : y - ch[k][i] / 100)), name, mode: "lines", line: { color, width: 1.5, dash: "dot" } });
    });
    S.plot("chart-an-curve", traces, S.layoutWith("Maturity (years)", "Yield (%)"));
  }

  function renderCarry(j) {
    const cr = j.carry_roll_down;
    const rows = cr.maturities.map((m, i) => ({ tenor: S.tenorLabel(m), yield: cr.yield[i], hz: cr.horizon_yield[i], fwd: cr.forward_yield[i], carry: cr.carry_bps[i], roll: cr.roll_down_bps[i], total: cr.total_bps[i] }));
    S.renderTable($("#an-carry-table"), [
      { key: "tenor", label: "Tenor" },
      { key: "yield", label: "Yield", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "hz", label: `Yield in ${state.anHorizon}y`, fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "fwd", label: "Forward", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "carry", label: "Carry", fmt: (v) => S.signed(v, 0), align: "num", cls: (v) => S.heatClass(v, 60) },
      { key: "roll", label: "Roll-down", fmt: (v) => S.signed(v, 0), align: "num", cls: (v) => S.heatClass(v, 60) },
      { key: "total", label: "Total", fmt: (v) => S.signed(v, 0), align: "num", cls: (v) => (v > 0 ? "best" : "neg") },
    ], rows);
    const x = cr.maturities.map(S.tenorLabel);
    S.plot("chart-an-carry", [
      { x, y: cr.carry_bps, name: "Carry", type: "bar", marker: { color: COLOR.treasury } },
      { x, y: cr.roll_down_bps, name: "Roll-down", type: "bar", marker: { color: COLOR.tips } },
      { x, y: cr.total_bps, name: "Total", mode: "lines+markers", line: { color: COLOR.fitted, width: 2 } },
    ], S.layoutWith("Tenor", "bps over the horizon", { barmode: "relative", hovermode: "x" }));
  }

  function renderForwards(j) {
    S.renderTable($("#an-forwards-table"), [
      { key: "label", label: "Forward" },
      { key: "forward", label: "Rate", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "spot_to_end", label: "Spot to end", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "spread_vs_spot_bps", label: "vs spot", fmt: (v) => S.signed(v, 0, " bps"), align: "num", cls: (v) => S.heatClass(v, 40) },
    ], j.forwards);
    const sh = j.spread_history;
    const names = Object.keys(sh).filter((k) => k !== "dates" && ["2s10s", "5s30s", "3m10y", "2s5s10s"].includes(k));
    S.plot("chart-an-spreads", names.map((k, i) => ({ x: sh.dates, y: sh[k], name: k, mode: "lines", line: { color: S.seriesColor(i), width: 1.8 } })),
      S.layoutWith("Date", "Spread (bps)", { yaxis: { zeroline: true } }));
  }

  function renderRichCheap(j) {
    S.renderTable($("#an-rich-table"), [
      { key: "rank", label: "#" },
      { key: "maturity", label: "Tenor", fmt: (v) => S.tenorLabel(v) },
      { key: "observed", label: "Observed", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "fitted", label: "Model", fmt: (v) => S.fmtPct(v, 3), align: "num" },
      { key: "residual_bps", label: "Residual", fmt: (v) => S.signed(v, 1, " bps"), align: "num", cls: (v) => S.heatClass(v, 8) },
      { key: "z", label: "z", fmt: (v) => fmt(v, 2), align: "num" },
      { key: "verdict", label: "Verdict", fmt: (v) => `<span class="pill ${v}">${v}</span>` },
    ], j.rich_cheap);
  }

  function renderPCA(j) {
    if (!j.pca) { $("#an-pca-note").textContent = "Not enough history for a PCA."; return; }
    const p = j.pca;
    const names = p.components || Object.keys(p.loadings);
    S.plot("chart-an-pca", names.map((n, i) => ({ x: p.maturities, y: p.loadings[n], name: `${n} (${(p.explained_variance[i] * 100).toFixed(1)}%)`, mode: "lines+markers", line: { color: S.seriesColor(i), width: 2 } })),
      S.layoutWith("Maturity (years)", "Loading", { yaxis: { zeroline: true } }));
    const total = p.explained_variance.reduce((a, b) => a + b, 0) * 100;
    $("#an-pca-note").textContent = `${p.n_obs} daily changes · three components explain ${total.toFixed(1)}% of curve moves.`;
  }

  async function run() {
    const btn = $("#btn-an-run");
    setBusy(btn, true, "Computing…");
    S.setChartLoading(["chart-an-curve", "chart-an-carry", "chart-an-spreads", "chart-an-pca"]);
    const params = new URLSearchParams({ bond_type: state.anBondType, model: state.anModel, horizon: state.anHorizon, lookback: 365 });
    try {
      const j = await S.api(`/api/analytics?${params.toString()}`);
      state.lastAnalytics = j;
      renderMetrics(j);
      renderChanges(j);
      renderCarry(j);
      renderForwards(j);
      renderRichCheap(j);
      renderPCA(j);
      $("#an-results").hidden = false;
      $("#an-empty").hidden = true;
      window.dispatchEvent(new Event("resize"));
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
      S.setChartLoading(["chart-an-curve", "chart-an-carry", "chart-an-spreads", "chart-an-pca"], false);
    }
  }

  async function priceBond() {
    const btn = $("#btn-bond-run");
    setBusy(btn, true, "Pricing…");
    const body = {
      bond_type: state.anBondType, model: state.anModel,
      maturity: parseFloat($("#bond-maturity").value), coupon: parseFloat($("#bond-coupon").value),
      frequency: parseInt($("#bond-frequency").value, 10), price: $("#bond-price").value,
    };
    try {
      const j = await S.postJSON("/api/bond", body);
      const hasPrice = body.price !== "" && body.price != null;
      $("#bond-metrics").innerHTML = [
        S.metricTile("Model price", fmt(j.model_price, 3), `yield ${S.fmtPct(j.model_ytm, 3)} off the curve`),
        S.metricTile(hasPrice ? "Market yield" : "Yield to maturity", S.fmtPct(j.ytm, 3), hasPrice ? `price ${fmt(j.market_price, 3)} · z-spread ${S.signed(j.z_spread_bps, 0, " bps")}` : "at the model price"),
        S.metricTile("Modified duration", fmt(j.modified_duration, 2), `Macaulay ${fmt(j.macaulay_duration, 2)} y`),
        S.metricTile("Convexity", fmt(j.convexity, 1), `DV01 ${fmt(j.dv01, 4)} per 100 face`),
      ].join("");
      const krd = j.key_rate_durations;
      S.plot("chart-bond-krd", [{ x: krd.tenors.map(S.tenorLabel), y: krd.values, type: "bar", name: "Key-rate duration", marker: { color: COLOR.treasury } }],
        S.layoutWith("Key rate", "Duration (years)", { hovermode: "x" }));
      const cf = j.cash_flows;
      S.renderTable($("#bond-cashflows"), [
        { key: "t", label: "Years", fmt: (v) => v.toFixed(2), align: "num" },
        { key: "a", label: "Cash flow", fmt: (v) => v.toFixed(3), align: "num" },
      ], cf.times.map((t, i) => ({ t, a: cf.amounts[i] })));
      $("#bond-results").hidden = false;
      window.dispatchEvent(new Event("resize"));
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
    }
  }

  function init() {
    S.bindSegmented('.seg-btn[data-an-bond]', "anBond", (v) => { state.anBondType = v; saveSettings(); run(); });
    S.bindSegmented('.seg-btn[data-an-model]', "anModel", (v) => { state.anModel = v; saveSettings(); run(); });
    S.bindChips("#an-horizon-chips", "anHorizon", (v) => { state.anHorizon = v; saveSettings(); run(); });
    $("#btn-an-run").addEventListener("click", run);
    $("#btn-bond-run").addEventListener("click", priceBond);
    $("#bond-form").addEventListener("submit", (e) => { e.preventDefault(); priceBond(); });
    S.activateSegmentedByData('.seg-btn[data-an-bond]', "anBond", state.anBondType);
    S.activateSegmentedByData('.seg-btn[data-an-model]', "anModel", state.anModel);
    S.setChips("#an-horizon-chips", "anHorizon", state.anHorizon);
  }

  S.registerTab("analytics", { init, onShow: (first) => { if (first && !state.lastAnalytics) run(); } });
})(window.Studio);

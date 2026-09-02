/* Term Premium tab: ACM affine model, Diebold-Li EH split, EH regressions. */
(function (S) {
  "use strict";
  const { $, $$, COLOR, SERIES, state, saveSettings, toast, setBusy, fmt } = S;

  function applyRange(years) {
    const { start, end } = S.rangeDates(years);
    $("#tp-start").value = start;
    $("#tp-end").value = end;
    S.setChips("#tp-chips", "tpRange", years);
    state.tpRange = String(years);
    saveSettings();
  }
  function maturities() {
    const m = (state.tpMaturities || ["2", "5", "10"]).map(Number).filter((v) => v > 0).sort((a, b) => a - b);
    return m.length ? m : [2, 5, 10];
  }

  function renderMetrics(j) {
    const tiles = j.maturities.map((m, i) => {
      const tp = j.latest_term_premium[String(m)];
      const dnsTp = j.dns && j.dns.term_premium[String(m)] ? j.dns.term_premium[String(m)].slice(-1)[0] : null;
      return S.metricTile(`${S.tenorLabel(m)} term premium`, S.signed(tp * 100, 0, " bps"),
        dnsTp != null ? `Diebold-Li EH split: ${S.signed(dnsTp * 100, 0, " bps")}` : "ACM, latest month", tp >= 0 ? "" : "neg");
    });
    const s = j.summary;
    tiles.push(S.metricTile("Model fit", S.fmtBps(s.fit_rmse * 1e4), `${s.n_factors} factors explain ${(s.explained_variance.reduce((a, b) => a + b, 0) * 100).toFixed(1)}% of yields`));
    tiles.push(S.metricTile("Factor persistence", fmt(s.max_eigenvalue, 3), s.max_eigenvalue < 1 ? "largest VAR eigenvalue · stationary" : "unit root: premia are level-dependent"));
    tiles.push(S.metricTile("Sample", `${s.n_obs} months`, `${s.start} → ${s.end}`));
    const bs = j.benchmark_stats || {};
    const focusKey = Object.keys(bs).includes(String(state.tpFocus)) ? String(state.tpFocus) : Object.keys(bs)[0];
    if (focusKey) {
      const b = bs[focusKey];
      tiles.push(S.metricTile(`vs NY Fed ACM · ${S.tenorLabel(focusKey)}`, `ρ ${b.correlation.toFixed(2)}`,
        `mean gap ${S.signed(b.mean_gap_bps, 0, " bps")} over ${b.n} months`, Math.abs(b.mean_gap_bps) > 50 ? "neg" : ""));
    } else {
      tiles.push(S.metricTile("vs NY Fed ACM", "n/a", j.benchmark ? "no overlapping months" : "needs a live FRED source"));
    }
    const host = $("#tp-metrics");
    host.innerHTML = tiles.join("");
    host.className = `grid grid-${tiles.length <= 6 ? tiles.length : 4}`;
  }

  function plotHistory(j) {
    const tp = j.term_premium;
    const traces = [];
    j.maturities.forEach((m, i) => {
      const color = SERIES[i % SERIES.length];
      traces.push({ x: tp.dates, y: tp[String(m)].map((v) => v * 100), name: `${S.tenorLabel(m)} ACM`, mode: "lines", line: { color, width: 2 },
        hovertemplate: `%{x} · <b>%{y:.0f} bps</b><extra>${S.tenorLabel(m)} ACM</extra>` });
      if (j.dns && j.dns.term_premium[String(m)]) {
        traces.push({ x: j.dns.dates, y: j.dns.term_premium[String(m)].map((v) => v * 100), name: `${S.tenorLabel(m)} Diebold-Li`, mode: "lines",
          line: { color, width: 1.2, dash: "dot" }, hovertemplate: `%{x} · <b>%{y:.0f} bps</b><extra>${S.tenorLabel(m)} DL</extra>` });
      }
      if (j.benchmark && j.benchmark[String(m)]) {
        traces.push({ x: j.benchmark.dates, y: j.benchmark[String(m)].map((v) => (v == null ? null : v * 100)), name: `${S.tenorLabel(m)} NY Fed ACM`, mode: "lines",
          line: { color, width: 2.2, dash: "dashdot" }, opacity: 0.8, hovertemplate: `%{x} · <b>%{y:.0f} bps</b><extra>${S.tenorLabel(m)} NY Fed</extra>` });
      }
    });
    S.plot("chart-tp-history", traces, S.layoutWith("Date", "Term premium (bps)", { yaxis: { zeroline: true } }));
  }

  function plotDecomposition(j) {
    const focus = j.maturities.includes(Number(state.tpFocus)) ? Number(state.tpFocus) : j.maturities[j.maturities.length - 1];
    state.tpFocus = String(focus);
    const d = j.decomposition[String(focus)];
    if (!d) return;
    $$("#tp-focus-chips .chip").forEach((c) => c.classList.toggle("active", c.dataset.tpFocus === String(focus)));
    S.plot("chart-tp-decomp", [
      { x: d.dates, y: d.expected_short_rate, name: "Expected average short rate", mode: "lines", stackgroup: "one",
        line: { color: COLOR.tips, width: 1 }, fillcolor: S.hex2rgba(COLOR.tips, 0.35), hovertemplate: "%{x} · <b>%{y:.2f}%</b><extra>Expectations</extra>" },
      { x: d.dates, y: d.term_premium, name: "Term premium", mode: "lines", stackgroup: "one",
        line: { color: COLOR.treasury, width: 1 }, fillcolor: S.hex2rgba(COLOR.treasury, 0.35), hovertemplate: "%{x} · <b>%{y:.2f}%</b><extra>Term premium</extra>" },
      { x: d.dates, y: d.convexity, name: "Convexity", mode: "lines", stackgroup: "one",
        line: { color: COLOR.purple, width: 1 }, fillcolor: S.hex2rgba(COLOR.purple, 0.35), hovertemplate: "%{x} · <b>%{y:.2f}%</b><extra>Convexity</extra>" },
      { x: d.dates, y: d.observed, name: `${S.tenorLabel(focus)} observed yield`, mode: "lines", line: { color: COLOR.obs, width: 2 }, hovertemplate: "%{x} · <b>%{y:.2f}%</b><extra>Observed</extra>" },
    ], S.layoutWith("Date", "Yield (%)"));
    const last = d.dates.length - 1;
    $("#tp-decomp-note").textContent = `${S.tenorLabel(focus)} on ${d.dates[last]}: yield ${S.fmtPct(d.observed[last])} = expected short rates ${S.fmtPct(d.expected_short_rate[last])} + term premium ${S.fmtPct(d.term_premium[last])} + convexity ${S.fmtPct(d.convexity[last], 3)} (model error ${S.fmtBps((d.observed[last] - d.fitted[last]) * 100, 1)}).`;
  }

  function renderBenchmark(j) {
    const host = $("#tp-benchmark-wrap");
    $("#tp-benchmark-note").textContent = j.benchmark_note || "";
    const bs = j.benchmark_stats || {};
    const keys = Object.keys(bs);
    if (!keys.length) { host.hidden = true; return; }
    host.hidden = false;
    S.renderTable($("#tp-benchmark"), [
      { key: "m", label: "Maturity", fmt: (v) => S.tenorLabel(v) },
      { key: "latest_ours_pct", label: "Ours (latest)", fmt: (v) => S.signed(v * 100, 0, " bps"), align: "num" },
      { key: "latest_benchmark_pct", label: "NY Fed (latest)", fmt: (v) => S.signed(v * 100, 0, " bps"), align: "num" },
      { key: "correlation", label: "Correlation", fmt: (v) => v.toFixed(3), align: "num", cls: (v) => (v > 0.8 ? "best" : v < 0.5 ? "neg" : "") },
      { key: "mean_gap_bps", label: "Mean gap", fmt: (v) => S.signed(v, 0, " bps"), align: "num", cls: (v) => S.heatClass(v, 60) },
      { key: "rmse_bps", label: "RMSE of gap", fmt: (v) => S.fmtBps(v, 0), align: "num" },
      { key: "n", label: "Months", align: "num" },
      { key: "latest_date", label: "Last common" },
    ], keys.map((k) => Object.assign({ m: Number(k) }, bs[k])));
  }

  function renderRegressions(j) {
    const cs = j.regressions.campbell_shiller || {};
    const fb = j.regressions.fama_bliss || {};
    const rows = j.maturities.filter((m) => cs[String(m)] || fb[String(m)]).map((m) => ({
      maturity: S.tenorLabel(m),
      cs: cs[String(m)], fb: fb[String(m)],
    }));
    const t = (r) => (r ? `${r.slope.toFixed(2)} <span class="muted">(t vs 1: ${r.t_stat_vs_one.toFixed(2)})</span>` : "—");
    const f = (r) => (r ? `${r.slope.toFixed(2)} <span class="muted">(t vs 0: ${r.t_stat_vs_zero.toFixed(2)})</span>` : "—");
    S.renderTable($("#tp-regressions"), [
      { key: "maturity", label: "Maturity" },
      { key: "cs", label: "Campbell-Shiller slope", fmt: t, cls: (r) => (r && r.slope < 0 ? "neg" : "") },
      { key: "fb", label: "Fama-Bliss slope", fmt: f, cls: (r) => (r && r.t_stat_vs_zero > 2 ? "best" : "") },
      { key: "cs", label: "CS R²", fmt: (r) => (r ? r.r_squared.toFixed(3) : "—") },
      { key: "fb", label: "FB R²", fmt: (r) => (r ? r.r_squared.toFixed(3) : "—") },
      { key: "cs", label: "Obs", fmt: (r) => (r ? r.n_obs : "—") },
    ], rows);
  }

  async function run() {
    const btn = $("#btn-tp-run");
    setBusy(btn, true, "Estimating…");
    S.setChartLoading(["chart-tp-history", "chart-tp-decomp"]);
    const params = new URLSearchParams({
      source: state.tpSource, start: $("#tp-start").value, end: $("#tp-end").value,
      maturities: maturities().join(","), factors: state.tpFactors, dns_method: state.tpDns,
    });
    try {
      const j = await S.api(`/api/term-premium?${params.toString()}`, {}, { timeout: 120000 });
      state.lastTermPremium = j;
      renderMetrics(j);
      plotHistory(j);
      $("#tp-focus-chips").innerHTML = j.maturities.map((m) => `<button class="chip" data-tp-focus="${m}">${S.tenorLabel(m)}</button>`).join("");
      $$("#tp-focus-chips .chip").forEach((c) => c.addEventListener("click", () => { state.tpFocus = c.dataset.tpFocus; saveSettings(); plotDecomposition(j); }));
      plotDecomposition(j);
      renderBenchmark(j);
      renderRegressions(j);
      const src = j.sources && (state.tpSource === "gsw" ? j.sources.gsw : j.sources[state.tpSource]);
      $("#tp-source-note").textContent = `${state.tpSource === "gsw" ? "Fed GSW zero curve" : state.tpSource === "tips" ? "TIPS factor history" : "Treasury factor history"}${src ? " · " + src : ""}`;
      $("#tp-results").hidden = false;
      $("#tp-empty").hidden = true;
      $("#btn-tp-export").disabled = false;
      window.dispatchEvent(new Event("resize"));
      toast("Term premium estimated.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(btn, false);
      S.setChartLoading(["chart-tp-history", "chart-tp-decomp"], false);
    }
  }

  function exportCSV() {
    const j = state.lastTermPremium;
    if (!j) return;
    const tp = j.term_premium;
    const header = ["date"].concat(j.maturities.map((m) => `tp_${S.tenorLabel(m)}_pct`));
    const rows = tp.dates.map((d, i) => [d].concat(j.maturities.map((m) => tp[String(m)][i])));
    if (j.benchmark) {
      const byDate = {};
      j.benchmark.dates.forEach((d, i) => { byDate[d] = i; });
      const bkeys = j.maturities.filter((m) => j.benchmark[String(m)]);
      bkeys.forEach((m) => header.push(`nyfed_tp_${S.tenorLabel(m)}_pct`));
      rows.forEach((row, i) => {
        const bi = byDate[tp.dates[i]];
        bkeys.forEach((m) => row.push(bi == null ? "" : j.benchmark[String(m)][bi]));
      });
    }
    S.downloadCSV(`term-premium-${j.source}-${tp.dates[0]}-${tp.dates[tp.dates.length - 1]}.csv`, header, rows);
  }

  function init() {
    S.bindSegmented('.seg-btn[data-tp-source]', "tpSource", (v) => { state.tpSource = v; saveSettings(); });
    S.bindSegmented('.seg-btn[data-tp-dns]', "tpDns", (v) => { state.tpDns = v; saveSettings(); });
    S.bindChips("#tp-chips", "tpRange", applyRange);
    S.bindChips("#tp-factor-chips", "tpFactors", (v) => { state.tpFactors = v; saveSettings(); });
    S.bindChips("#tp-mat-chips", "tpMat", (vals) => { state.tpMaturities = vals; saveSettings(); }, { multi: true });
    ["tp-start", "tp-end"].forEach((id) => $("#" + id).addEventListener("change", () => $$("#tp-chips .chip").forEach((c) => c.classList.remove("active"))));
    $("#btn-tp-run").addEventListener("click", run);
    $("#btn-tp-export").addEventListener("click", exportCSV);

    S.activateSegmentedByData('.seg-btn[data-tp-source]', "tpSource", state.tpSource);
    S.activateSegmentedByData('.seg-btn[data-tp-dns]', "tpDns", state.tpDns);
    S.setChips("#tp-factor-chips", "tpFactors", state.tpFactors);
    S.setChips("#tp-mat-chips", "tpMat", state.tpMaturities || ["2", "5", "10"]);
    applyRange(state.tpRange);
  }

  S.registerTab("termpremium", { init, onShow: (first) => { if (first && !state.lastTermPremium) run(); } });
})(window.Studio);

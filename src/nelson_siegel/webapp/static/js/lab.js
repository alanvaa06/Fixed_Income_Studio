/* Parameter Lab tab: Nelson-Siegel / Svensson evaluated in the browser. */
(function (S) {
  "use strict";
  const { $, $$, COLOR, state, saveSettings, toast } = S;

  const SLIDERS = ["b0", "b1", "b2", "tau", "b3", "tau2"];
  const SLIDER_RANGE = { b0: [-2, 12], b1: [-6, 6], b2: [-8, 8], tau: [0.1, 10], b3: [-8, 8], tau2: [0.1, 20] };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const sliderValue = (key) => parseFloat($("#sl-" + key).value);
  function setSlider(key, value) {
    const [lo, hi] = SLIDER_RANGE[key];
    $("#sl-" + key).value = clamp(value, lo, hi);
  }
  function updateSliderLabels() {
    SLIDERS.forEach((k) => { $("#lbl-" + k).textContent = sliderValue(k).toFixed(2); });
  }
  function loadings(t, tau) {
    if (t === 0) return { e: 1, f1: 1, f2: 0 };
    const e = Math.exp(-t / tau);
    const f1 = (1 - e) / (t / tau);
    return { e, f1, f2: f1 - e };
  }
  const MATS = Array.from({ length: 250 }, (_, i) => 0.083 + (i * (30 - 0.083)) / 249);
  const isSvensson = () => state.labModel === "svensson";

  let timer = null;
  function draw() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const p = {
        b0: sliderValue("b0"), b1: sliderValue("b1"), b2: sliderValue("b2"), tau: sliderValue("tau"),
        b3: isSvensson() ? sliderValue("b3") : 0, tau2: sliderValue("tau2"),
      };
      const lvl = MATS.map(() => p.b0);
      const slp = MATS.map((t) => p.b1 * loadings(t, p.tau).f1);
      const crv = MATS.map((t) => p.b2 * loadings(t, p.tau).f2);
      const crv2 = MATS.map((t) => p.b3 * loadings(t, p.tau2).f2);
      const curve = MATS.map((t, i) => lvl[i] + slp[i] + crv[i] + crv2[i]);
      const fwd = MATS.map((t) => {
        const l1 = loadings(t, p.tau);
        const l2 = loadings(t, p.tau2);
        return p.b0 + p.b1 * l1.e + p.b2 * (t / p.tau) * l1.e + p.b3 * (t / p.tau2) * l2.e;
      });
      const traces = [
        { x: MATS, y: curve, name: "Curve", mode: "lines", line: { color: COLOR.fitted, width: 3, shape: "spline" },
          hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Curve</extra>" },
        { x: MATS, y: lvl, name: "β₀ Level", mode: "lines", line: { color: COLOR.treasury, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Level</extra>" },
        { x: MATS, y: slp, name: "β₁ Slope contrib.", mode: "lines", line: { color: COLOR.tips, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Slope</extra>" },
        { x: MATS, y: crv, name: "β₂ Curvature contrib.", mode: "lines", line: { color: COLOR.purple, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Curvature</extra>" },
      ];
      if (isSvensson()) {
        traces.push({ x: MATS, y: crv2, name: "β₃ Curvature 2 contrib.", mode: "lines", line: { color: COLOR.pink, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.3f}%<extra>Curvature 2</extra>" });
      }
      if (state.showForward) {
        traces.push({ x: MATS, y: fwd, name: "Forward curve", mode: "lines", line: { color: COLOR.obs, width: 1.5, dash: "dash" }, hovertemplate: "%{x:.2f}y · <b>%{y:.3f}%</b><extra>Forward</extra>" });
      }
      S.plot("chart-explorer", traces, S.layoutWith("Maturity (years)", "Yield (%)"));
      // Quick read-outs
      const y0 = curve[0], y30 = curve[curve.length - 1];
      const peakIdx = curve.indexOf(Math.max(...curve));
      $("#lab-readout").innerHTML = [
        S.metricTile("Short end y(≈0)", S.fmtPct(p.b0 + p.b1), "β₀ + β₁"),
        S.metricTile("Long end y(30)", S.fmtPct(y30), "approaches β₀"),
        S.metricTile("Slope 30y − 3m", S.fmtBps((y30 - y0) * 100, 0), y30 > y0 ? "upward sloping" : "inverted"),
        S.metricTile("Hump location", `${(1.8 * p.tau).toFixed(1)} y`, "curvature peaks near 1.8·τ"),
      ].join("");
    }, 30);
  }

  function setModel(modelId) {
    state.labModel = modelId;
    saveSettings();
    S.activateSegmentedByData('.seg-btn[data-lab-model]', "labModel", modelId);
    $("#svensson-sliders").hidden = !isSvensson();
    $("#lab-formula").innerHTML = isSvensson()
      ? "<code>y(t) = β<sub>0</sub> + β<sub>1</sub>·f<sub>1</sub>(t,τ) + β<sub>2</sub>·f<sub>2</sub>(t,τ) + β<sub>3</sub>·f<sub>2</sub>(t,τ<sub>2</sub>)</code>"
      : "<code>y(t) = β<sub>0</sub> + β<sub>1</sub>·f<sub>1</sub>(t,τ) + β<sub>2</sub>·f<sub>2</sub>(t,τ)</code>";
    draw();
  }

  function syncFromFit(result) {
    if (!result || !result.factor_list) return;
    const byKey = {};
    result.factor_list.forEach((f) => { byKey[f.key] = f.value; });
    setSlider("b0", byKey.beta0);
    setSlider("b1", byKey.beta1);
    setSlider("b2", byKey.beta2);
    setSlider("tau", byKey.tau != null ? byKey.tau : byKey.tau1);
    if (byKey.beta3 != null) setSlider("b3", byKey.beta3);
    if (byKey.tau2 != null) setSlider("tau2", byKey.tau2);
    setModel(result.model === "svensson" ? "svensson" : "nelson-siegel");
    updateSliderLabels();
    draw();
    toast("Sliders set to the last fit.", "success");
  }

  const PRESETS = {
    normal:   { b0: 4.0, b1: -2.0, b2: 0.0,  tau: 2.0, b3: 0.0, tau2: 8.0 },
    inverted: { b0: 4.0, b1: 1.5,  b2: -0.5, tau: 1.5, b3: 0.0, tau2: 8.0 },
    humped:   { b0: 3.5, b1: -1.0, b2: 3.0,  tau: 2.5, b3: 0.0, tau2: 8.0 },
    flat:     { b0: 4.2, b1: 0.1,  b2: 0.1,  tau: 2.0, b3: 0.0, tau2: 8.0 },
  };

  function init() {
    S.bindSegmented('.seg-btn[data-lab-model]', "labModel", setModel);
    SLIDERS.forEach((k) => $("#sl-" + k).addEventListener("input", () => { updateSliderLabels(); draw(); }));
    $("#lab-show-forward").addEventListener("change", (e) => { state.showForward = e.target.checked; saveSettings(); draw(); });
    $("#btn-lab-from-fit").addEventListener("click", () => {
      if (!state.lastFit) { toast("Fit a curve first.", "error"); return; }
      if (state.lastFit.family === "short-rate") { toast("Fit a Nelson-Siegel or Svensson curve first.", "error"); return; }
      syncFromFit(state.lastFit);
    });
    $$('button[data-preset]').forEach((btn) => btn.addEventListener("click", () => {
      const p = PRESETS[btn.dataset.preset];
      if (!p) return;
      SLIDERS.forEach((k) => setSlider(k, p[k]));
      updateSliderLabels();
      draw();
    }));
    $("#lab-show-forward").checked = !!state.showForward;
    updateSliderLabels();
    setModel(state.labModel);
  }

  S.lab = { syncFromFit };
  S.registerTab("explorer", { init, onShow: () => draw() });
})(window.Studio);

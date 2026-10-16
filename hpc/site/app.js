// Dashboard of the sweep runner: reads status.json (published by hpc/runner.py) every minute.
// Plain JavaScript, no libraries. All text from status.json is inserted as text, never as HTML.
"use strict";

const STALE_S = 15 * 60;  // no update for this long: the runner or the PC may be down
const LAYOUT = {
  opposite_walls: { label: "opposite walls", color: "#3987e5" },
  same_wall: { label: "same wall", color: "#d95926" },
  adjacent_walls: { label: "adjacent walls", color: "#199e70" },
};
let status = null;

// --- small helpers ------------------------------------------------------------------------------
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}
function svgEl(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}
const nowS = () => Date.now() / 1000;
function duration(s) {
  if (s === null || s === undefined) return "–";
  s = Math.max(0, Math.round(s));
  if (s >= 3600) return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} min`;
  if (s >= 60) return `${Math.floor(s / 60)} min`;
  return `${s} s`;
}
function clock(t) {
  if (!t) return "–";
  const d = new Date(t * 1000);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? hm : `${d.toLocaleDateString([], { weekday: "short" })} ${hm}`;
}
const num = (v, digits = 0) => (v === null || v === undefined ? "–" : Number(v).toFixed(digits));
function replace(id, ...children) {
  const node = document.getElementById(id);
  node.replaceChildren(...children.flat());
  return node;
}

// --- header and alerts ----------------------------------------------------------------------------
function renderHeader(s) {
  const age = nowS() - s.updated;
  const stale = age > STALE_S;
  const state = stale ? "offline?" : s.runner.state;
  const badge = document.getElementById("badge");
  badge.textContent = state;
  badge.className = `badge ${stale ? "stale" : s.runner.state}`;
  document.getElementById("updated").textContent = `updated ${duration(age)} ago (${clock(s.updated)})`;
  document.getElementById("host").textContent =
    `${s.runner.host} · code ${s.runner.code} · OpenFOAM ${s.runner.openfoam || "–"}`;
  const alerts = [];
  if (stale) alerts.push(["red", `No update since ${clock(s.updated)}. The runner, WSL or the PC may be down, or GitHub may be unreachable.`]);
  if (s.runner.control_error) alerts.push(["red", `Control not applied: ${s.runner.control_error}`]);
  if (s.runner.offline_since) alerts.push(["", `GitHub not reachable from the PC since ${clock(s.runner.offline_since)}; cases keep running.`]);
  if (s.runner.message) alerts.push(["", `Runner paused itself: ${s.runner.message}`]);
  const box = document.getElementById("alert");
  box.hidden = alerts.length === 0;
  box.className = `alert ${alerts.some(([c]) => c === "red") ? "red" : ""}`;
  box.replaceChildren(...alerts.map(([, text]) => el("div", {}, text)));
}

// --- runs ---------------------------------------------------------------------------------------
function renderRuns(s) {
  const rows = s.runs.map((run) => {
    const c = run.counts;
    const parts = ["done", "failed", "running", "skipped"].map((key) =>
      el("span", { class: `s-${key}`, style: `width:${(100 * c[key]) / Math.max(run.total, 1)}%`, title: `${c[key]} ${key}` }));
    const finished = run.finished ? `finished ${clock(run.finished)}` : `ETA ${clock(run.eta)}`;
    return el("div", { class: "run" },
      el("div", { class: "run-name" }, run.run_id),
      el("div", { class: "bar" }, parts),
      el("div", { class: "count" }, `${c.done + c.failed + c.skipped}/${run.total}`),
      el("div", { class: "run-stats" },
        `done ${c.done} · failed ${c.failed} · running ${c.running} · waiting ${c.pending}` +
        (c.skipped ? ` · skipped ${c.skipped}` : "") +
        ` — ${run.per_hour}/h · ${finished} · per case A ${run.minutes_per_case.A} min, B ${run.minutes_per_case.B} min` +
        ` · ${run.slots} × ${run.procs} cores · code ${run.code}`));
  });
  replace("runs", el("h2", {}, "Runs"),
    rows.length ? rows : el("div", { class: "empty" },
      `No run started. Add it to "runs" in hpc/control.yaml and set "state: run".`));
}

// --- running cases ---------------------------------------------------------------------------------
function sparkline(series) {
  const svg = svgEl("svg", { class: "spark", viewBox: "0 0 200 46", preserveAspectRatio: "none" });
  const values = (series && series.values) || [];
  if (values.length < 2) return svg;
  const ys = values.map((v) => (series.log ? Math.log10(Math.max(v, 1e-12)) : v));
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const span = hi - lo || 1;
  const points = ys.map((y, i) => `${(200 * i) / (ys.length - 1)},${42 - (38 * (y - lo)) / span}`).join(" ");
  svg.append(svgEl("polyline", { points, fill: "none", stroke: "#3987e5", "stroke-width": "1.5",
    "vector-effect": "non-scaling-stroke" }));
  return svg;
}
function renderRunning(s) {
  const cards = s.running.map((c) => {
    const pct = c.progress === null || c.progress === undefined ? null : Math.round(100 * c.progress);
    const series = c.series || {};
    const last = series.values && series.values.length ? series.values[series.values.length - 1] : null;
    return el("div", { class: "card" },
      el("div", { class: "card-head" }, el("span", {}, c.case_id), el("span", { class: `chip ${c.method}` }, `method ${c.method}`)),
      el("div", { class: "line" }, el("span", {}, `${LAYOUT[c.layout]?.label || c.layout} · ${c.stage}`),
        el("span", {}, pct === null ? "" : `${pct} %`)),
      el("div", { class: "pbar" }, el("span", { style: `width:${pct || 0}%` })),
      el("div", { class: "line" }, el("span", {}, `running ${duration(c.elapsed_s)}`),
        el("span", {}, c.attempt > 1 ? `attempt ${c.attempt}` : "")),
      sparkline(series),
      el("div", { class: "line" }, el("span", {}, series.label || ""),
        el("span", {}, last === null ? "" : series.log ? Number(last).toExponential(1) : num(last, 1))));
  });
  replace("running", cards.length ? cards : el("div", { class: "empty" }, "No case running."));
}

// --- machine ------------------------------------------------------------------------------------------
function renderMachine(s) {
  const m = s.machine;
  const cpu = el("div", { class: "cpu", title: "load per CPU thread" },
    m.cpu.map((v, i) => el("div", { title: `thread ${i}: ${v} %` }, el("span", { style: `height:${v}%` }))));
  const ram = (100 * m.ram_used_gb) / Math.max(m.ram_total_gb, 1);
  replace("machine", cpu,
    el("dl", { class: "kv" },
      el("dt", {}, "CPU"), el("dd", {}, `${num(m.cpu.reduce((a, b) => a + b, 0) / m.cpu.length)} % of ${m.cpu.length} threads · load ${m.load.join(" ")}`),
      el("dt", {}, "RAM"), el("dd", {}, `${m.ram_used_gb} / ${m.ram_total_gb} GB`, el("div", { class: "hbar" }, el("span", { style: `width:${ram}%` }))),
      el("dt", {}, "disk"), el("dd", {}, `${m.disk_free_gb} GB free`),
      el("dt", {}, "runner"), el("dd", {}, `up since ${clock(s.runner.started)} · control: ${s.runner.control}`)));
}

// --- latest case ----------------------------------------------------------------------------------------
function renderLatest(s) {
  const latest = s.latest;
  document.getElementById("latest-id").textContent = latest ? latest.case_id : "";
  for (const name of ["setup", "flow"]) {
    const img = document.getElementById(`pic-${name}`);
    if (latest) img.src = `img/latest_${name}.jpg?v=${encodeURIComponent(latest.case_id)}`;
    else img.removeAttribute("src");
  }
  const pair = (label, value) => el("span", {}, el("b", {}, label), value);
  replace("latest-values", latest ? [
    pair("layout", LAYOUT[latest.layout]?.label || latest.layout), pair("method", latest.method),
    pair("wind", `${num(latest.wind_speed_ms, 1)} m/s`),
    pair("t90", latest.t90_s === null ? "not reached in 600 s" : `${num(latest.t90_s)} s`),
    pair("τ", `${num(latest.tau_s)} s`), pair("airflow", `${num(latest.airflow_m3h)} m³/h`),
  ] : el("span", { class: "empty" }, "No finished case with pictures yet."));
}

// --- results chart: tau over wind speed, log scale ------------------------------------------------------
function renderChart(s) {
  const data = s.results.filter((r) => r.tau_s && r.wind_speed_ms);
  const box = document.getElementById("chart");
  if (!data.length) {
    box.replaceChildren(el("div", { class: "empty" }, "No results yet."));
    return;
  }
  const W = 900, H = 300, L = 52, R = 12, T = 10, B = 34;
  const taus = data.map((r) => r.tau_s);
  const ylo = Math.log10(Math.min(20, ...taus) * 0.9), yhi = Math.log10(Math.max(1000, ...taus) * 1.1);
  const x = (w) => L + ((W - L - R) * (w - 1)) / 4;
  const y = (t) => T + (H - T - B) * (1 - (Math.log10(t) - ylo) / (yhi - ylo));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "time constant over wind speed" });
  for (const t of [10, 20, 50, 100, 200, 500, 1000, 2000, 5000]) {
    if (Math.log10(t) < ylo || Math.log10(t) > yhi) continue;
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), stroke: "#34383f", "stroke-width": 1 }));
    const label = svgEl("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end" });
    label.textContent = `${t} s`;
    svg.append(label);
  }
  for (let w = 1; w <= 5; w++) {
    const label = svgEl("text", { x: x(w), y: H - 12, "text-anchor": "middle" });
    label.textContent = `${w} m/s`;
    svg.append(label);
  }
  const tip = document.getElementById("tip");
  for (const r of data) {
    const dot = svgEl("circle", { cx: x(r.wind_speed_ms), cy: y(r.tau_s), r: 4.5, fill: LAYOUT[r.layout]?.color || "#8b9099",
      stroke: "#22252a", "stroke-width": 2 });
    const hit = svgEl("circle", { cx: x(r.wind_speed_ms), cy: y(r.tau_s), r: 10, fill: "transparent" });
    hit.addEventListener("mousemove", (event) => {
      tip.hidden = false;
      tip.textContent = `${r.case_id} · ${LAYOUT[r.layout]?.label} · method ${r.method}\n` +
        `wind ${num(r.wind_speed_ms, 1)} m/s · τ ${num(r.tau_s)} s · t90 ${r.t90_s === null ? "> 600" : num(r.t90_s)} s`;
      tip.style.whiteSpace = "pre";
      tip.style.left = `${event.clientX + 14}px`;
      tip.style.top = `${event.clientY + 14}px`;
    });
    hit.addEventListener("mouseleave", () => { tip.hidden = true; });
    svg.append(dot, hit);
  }
  const legend = el("div", { class: "legend" }, Object.values(LAYOUT).map((l) =>
    el("span", {}, el("i", { style: `background:${l.color}` }), l.label)),
    el("span", {}, `${data.length} cases · lower = faster air replacement`));
  box.replaceChildren(svg, legend);
}

// --- tables -------------------------------------------------------------------------------------------
function renderFinished(s) {
  const head = el("tr", {}, ["case", "layout", "method", "t90", "τ", "airflow", "run time", "finished"].map((h) => el("th", {}, h)));
  const rows = s.finished.map((r) => el("tr", {},
    el("td", { class: r.status === "failed" ? "failed" : "" }, r.case_id),
    el("td", {}, LAYOUT[r.layout]?.label || r.layout), el("td", {}, r.method),
    el("td", {}, r.status === "failed" ? "failed" : r.t90_s === null ? "> 600 s" : `${num(r.t90_s)} s`),
    el("td", {}, r.tau_s === null ? "–" : `${num(r.tau_s)} s`),
    el("td", {}, r.airflow_m3h === null ? "–" : `${num(r.airflow_m3h)} m³/h`),
    el("td", {}, duration(r.seconds)), el("td", {}, clock(r.finished))));
  replace("finished", el("thead", {}, head), el("tbody", {}, rows));
}
function renderFailures(s) {
  const items = s.failures.map((f) => el("details", {},
    el("summary", {}, `${f.case_id} `, el("span", { class: "err" },
      `${f.status === "pending" ? "will retry" : "failed"} after ${f.attempts} attempt(s): ${f.error}`)),
    el("pre", {}, f.log_tail || "")));
  replace("failures", items.length ? items : el("div", { class: "empty" }, "None."));
}
function renderEvents(s) {
  replace("events", s.events.map((e) => el("li", {}, el("time", {}, clock(e.t)), el("span", {}, e.text))));
}

// --- loading --------------------------------------------------------------------------------------------
function render() {
  if (!status) return;
  const parts = [renderHeader, renderRuns, renderRunning, renderMachine, renderLatest, renderChart,
    renderFinished, renderFailures, renderEvents];
  for (const part of parts) {
    try { part(status); } catch (error) { console.error(part.name, error); }  // one broken part must not blank the page
  }
}
async function load() {
  try {
    const response = await fetch(`status.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    status = await response.json();
    render();
  } catch (error) {
    const box = document.getElementById("alert");
    box.hidden = false;
    box.className = "alert red";
    box.textContent = `status.json could not be loaded (${error.message}). The runner may not have published yet.`;
  }
}
load();
setInterval(load, 60 * 1000);
setInterval(() => status && renderHeader(status), 15 * 1000);  // keep "updated … ago" current
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

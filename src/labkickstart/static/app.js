// Minimal vanilla-JS dashboard. No build step.
const MAX_POINTS = 2000;

const fmtBytes = (n) => n < 1024 ? `${n} B` : n < 1024*1024 ? `${(n/1024).toFixed(1)} KB` : `${(n/1024/1024).toFixed(1)} MB`;

function el(tag, opts = {}, children = []) {
  const e = document.createElement(tag);
  if (opts.text != null) e.textContent = opts.text;
  if (opts.class) e.className = opts.class;
  if (opts.href) e.href = opts.href;
  for (const c of children) if (c) e.appendChild(c);
  return e;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function loadDevices() {
  const devs = await api("/api/devices");
  const tb = document.querySelector("#devices tbody");
  tb.replaceChildren();
  for (const d of devs) {
    const code = el("code", { text: d.device_id });
    const pill = el("span", {
      class: `pill ${d.connected ? "ok" : "off"}`,
      text: d.connected ? "connected" : "offline",
    });
    tb.appendChild(el("tr", {}, [
      el("td", { text: d.name }),
      el("td", {}, [code]),
      el("td", { text: d.rssi ?? "" }),
      el("td", {}, [pill]),
    ]));
  }
}

async function loadRuns() {
  const data = await api("/api/runs");
  const tb = document.querySelector("#runs tbody");
  tb.replaceChildren();
  const activeId = data.active?.run_id;
  for (const r of data.runs) {
    if (r.run_id === activeId) continue;  // recording — show in run-status, not history
    const link = el("a", { href: `/api/runs/${encodeURIComponent(r.run_id)}/csv`, text: "Download CSV" });
    tb.appendChild(el("tr", {}, [
      el("td", {}, [el("code", { text: r.run_id })]),
      el("td", { text: r.name }),
      el("td", { text: fmtBytes(r.size_bytes) }),
      el("td", {}, [link]),
    ]));
  }
  setRunUI(data.active);
}

function setRunUI(active) {
  const arm = document.getElementById("arm");
  const stop = document.getElementById("stop");
  const status = document.getElementById("run-status");
  if (active) {
    arm.disabled = true;
    stop.disabled = false;
    status.textContent = `recording: ${active.name} (${active.run_id})`;
    status.classList.add("live");
  } else {
    arm.disabled = false;
    stop.disabled = true;
    status.textContent = "idle";
    status.classList.remove("live");
  }
}

// Chart state: parallel arrays uPlot expects.
const series = new Map(); // channel -> number[]
let xs = [];
let plot;
// Set when a run starts (first sample's t). Display x = sample.t - tOffset.
// null means "live monitor mode" — show the raw stream timestamp.
let tOffset = null;

function ensurePlot() {
  if (plot) return;
  const opts = {
    width: document.getElementById("chart").clientWidth,
    height: 320,
    scales: { x: { time: false } },
    axes: [{ label: "t (s)" }, { label: "value" }],
    series: [{}],
  };
  plot = new uPlot(opts, [[]], document.getElementById("chart"));
  window.addEventListener("resize", () =>
    plot.setSize({ width: document.getElementById("chart").clientWidth, height: 320 }));
}

const COLORS = ["#1f6feb", "#d23", "#2ea043", "#a371f7", "#fb8500"];

function ensureSeries(channel) {
  if (series.has(channel)) return;
  series.set(channel, new Array(xs.length).fill(null));
  const idx = series.size;
  plot.addSeries({ label: channel, stroke: COLORS[(idx - 1) % COLORS.length], width: 2 }, idx);
}

function pushSample(s) {
  ensurePlot();
  ensureSeries(s.channel);
  // If a run is active, anchor t=0 to the first sample we receive after Arm.
  if (tOffset !== null && tOffset === Infinity) tOffset = s.t;
  const x = tOffset != null ? s.t - tOffset : s.t;
  if (xs.length === 0 || x > xs[xs.length - 1]) {
    xs.push(x);
    for (const arr of series.values()) arr.push(null);
  }
  const arr = series.get(s.channel);
  arr[arr.length - 1] = s.value;

  if (xs.length > MAX_POINTS) {
    const drop = xs.length - MAX_POINTS;
    xs = xs.slice(drop);
    for (const [k, v] of series) series.set(k, v.slice(drop));
  }

  plot.setData([xs, ...Array.from(series.values())]);
}

function clearChart() {
  xs = [];
  for (const k of series.keys()) series.set(k, []);
  if (plot) plot.setData([xs, ...Array.from(series.values())]);
}

function connectWS() {
  const status = document.getElementById("ws-status");
  const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/stream";
  const ws = new WebSocket(url);
  ws.onopen = () => { status.textContent = "live"; status.classList.add("live"); };
  ws.onclose = () => {
    status.textContent = "disconnected — retrying…";
    status.classList.remove("live");
    setTimeout(connectWS, 1000);
  };
  ws.onmessage = (e) => pushSample(JSON.parse(e.data));
}

document.getElementById("arm").addEventListener("click", async () => {
  const name = document.getElementById("run-name").value.trim() || "run";
  await api("/api/arm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  // Reset chart and arm the t-offset so x-axis starts at 0 for this run.
  clearChart();
  tOffset = Infinity;  // sentinel: "use the next sample's t as offset"
  await loadRuns();
});

document.getElementById("stop").addEventListener("click", async () => {
  await api("/api/stop", { method: "POST" });
  tOffset = null;  // back to monitor mode
  await loadRuns();
});

document.getElementById("clear-chart").addEventListener("click", clearChart);

document.getElementById("delete-all").addEventListener("click", async () => {
  if (!confirm("Delete ALL stored runs? This cannot be undone.")) return;
  const r = await fetch("/api/runs", { method: "DELETE" });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    alert(`Could not delete: ${body.detail || r.status}`);
    return;
  }
  await loadRuns();
});

(async function init() {
  ensurePlot();
  await loadDevices();
  await loadRuns();
  connectWS();
})();

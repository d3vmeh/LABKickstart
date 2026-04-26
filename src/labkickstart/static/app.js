// Minimal vanilla-JS dashboard. No build step.
const MAX_POINTS = 2000;

const fmtBytes = (n) => n < 1024 ? `${n} B` : n < 1024*1024 ? `${(n/1024).toFixed(1)} KB` : `${(n/1024/1024).toFixed(1)} MB`;

function el(tag, opts = {}, children = []) {
  const e = document.createElement(tag);
  if (opts.text != null) e.textContent = opts.text;
  if (opts.class) e.className = opts.class;
  if (opts.href) e.href = opts.href;
  if (opts.id) e.id = opts.id;
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) e.setAttribute(k, v);
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
  // Cache friendly names for chart titles.
  for (const d of devs) deviceLabels.set(d.address, d.name);
  refreshChartTitles();
  const tb = document.querySelector("#devices tbody");
  tb.replaceChildren();
  if (devs.length === 0) {
    tb.appendChild(el("tr", {}, [
      el("td", {
        attrs: { colspan: "5" },
        class: "lg-empty",
        text: "No devices yet — hit Scan to discover ESP32 modules in range.",
      }),
    ]));
    return;
  }
  for (const d of devs) {
    const status = deviceStatusPill(d);
    const action = deviceAction(d);
    tb.appendChild(el("tr", {}, [
      el("td", { text: d.name }),
      el("td", {}, [el("code", { text: d.address })]),
      el("td", { text: d.rssi == null ? "" : `${d.rssi}` }),
      el("td", {}, [status]),
      el("td", {}, [action]),
    ]));
  }
}

function deviceStatusPill(d) {
  if (d.connecting) return el("span", { class: "pill off", text: "connecting" });
  if (d.connected)  return el("span", { class: "pill ok",  text: "connected" });
  if (d.error)      return el("span", { class: "pill off", text: "error" });
  return el("span", { class: "pill off", text: "available" });
}

function deviceAction(d) {
  if (d.internal) return document.createTextNode("");  // mock/legacy: no toggle
  if (d.connected || d.connecting) {
    const btn = document.createElement("button");
    btn.className = "danger";
    btn.textContent = "Disconnect";
    btn.disabled = d.connecting;
    btn.onclick = () => bleDisconnect(d.address);
    return btn;
  }
  const btn = document.createElement("button");
  btn.className = "primary";
  btn.textContent = "Connect";
  btn.onclick = () => bleConnect(d.address);
  return btn;
}

async function bleScan() {
  const status = document.getElementById("ble-status");
  const btn = document.getElementById("ble-scan");
  btn.disabled = true;
  status.textContent = "scanning…";
  status.classList.add("live");
  try {
    const r = await fetch("/api/ble/scan", { method: "POST" });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${r.status}`);
    }
    status.textContent = "scan complete";
  } catch (e) {
    status.textContent = `scan failed: ${e.message || e}`;
    status.classList.remove("live");
  } finally {
    btn.disabled = false;
    setTimeout(() => { status.classList.remove("live"); status.textContent = "idle"; }, 1500);
    await loadDevices();
  }
}

async function bleConnect(address) {
  const r = await fetch(`/api/ble/connect/${encodeURIComponent(address)}`, { method: "POST" });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    alert(`Connect failed: ${body.detail || r.status}`);
  }
  await loadDevices();
}

async function bleDisconnect(address) {
  const r = await fetch(`/api/ble/disconnect/${encodeURIComponent(address)}`, { method: "POST" });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    alert(`Disconnect failed: ${body.detail || r.status}`);
  }
  await loadDevices();
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
    stop.disabled = true;
    status.classList.remove("live");
    if (kitState.activeId) {
      arm.disabled = false;
      status.textContent = "idle";
    } else {
      arm.disabled = true;
      status.textContent = "apply a kit to enable";
    }
  }
}

// ---------- Kits ----------
const kitState = {
  available: [],          // [{id, name, description, params: [{key, label, unit, default, required}]}]
  selectedId: null,       // id in the dropdown (may differ from activeId until Apply)
  activeId: null,         // id confirmed applied on the server
  activeParams: {},
};

async function loadKits() {
  const data = await api("/api/kits");
  kitState.available = data.kits;
  kitState.activeId = data.active?.id ?? null;
  kitState.activeParams = data.active?.params ?? {};
  if (!kitState.selectedId) {
    kitState.selectedId = kitState.activeId ?? data.kits[0]?.id ?? null;
  }
  renderKitPicker();
  renderKitParams();
  renderKitStatus();
}

function renderKitPicker() {
  const sel = document.getElementById("kit-select");
  sel.replaceChildren();
  for (const k of kitState.available) {
    const o = document.createElement("option");
    o.value = k.id;
    o.textContent = k.name;
    if (k.id === kitState.selectedId) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => {
    kitState.selectedId = sel.value;
    renderSelectedKit();
  };
  renderSelectedKit();
}

// Render everything that depends on the *selected* kit (i.e. what the
// dropdown is currently pointing at, regardless of whether the user has
// hit Apply yet).
function renderSelectedKit() {
  const kit = kitState.available.find(k => k.id === kitState.selectedId);
  document.getElementById("kit-desc").textContent = kit?.description ?? "";
  renderKitDiagrams(kit?.diagrams ?? []);
  renderKitParams();
  renderKitTriggers(kit?.triggers ?? []);
  loadLabGuide();
}

function renderKitTriggers(triggers) {
  const host = document.getElementById("run-triggers");
  host.replaceChildren();
  if (!triggers.length) return;
  host.appendChild(el("div", { class: "trig-head", text: "Stop conditions" }));
  for (const t of triggers) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = `trig-${t.id}`;
    cb.dataset.triggerId = t.id;

    const num = document.createElement("input");
    num.type = "number";
    num.step = "0.001";
    num.value = String(t.default_value);
    num.dataset.triggerInput = t.id;

    const row = el("div", { class: "trig-row" }, [
      cb,
      el("label", { class: "lbl", attrs: { for: `trig-${t.id}` }, text: t.label }),
      num,
      el("span", { class: "unit", text: t.unit }),
    ]);
    host.appendChild(row);
  }
}

function collectActiveTriggers() {
  const out = [];
  document.querySelectorAll('#run-triggers input[type=checkbox]').forEach(cb => {
    if (!cb.checked) return;
    const tid = cb.dataset.triggerId;
    const numEl = document.querySelector(`#run-triggers input[data-trigger-input="${tid}"]`);
    const v = Number(numEl?.value);
    if (Number.isFinite(v)) out.push({ id: tid, threshold: v });
  });
  return out;
}

function renderKitDiagrams(diagrams) {
  const host = document.getElementById("kit-diagrams");
  host.replaceChildren();
  if (!diagrams.length) return;
  for (const d of diagrams) {
    const summary = el("summary", { text: d.title });
    const body = el("div", { class: "diagram-body" }, [
      el("img", { attrs: { src: d.url, alt: `${d.title} diagram`, loading: "lazy" } }),
    ]);
    if (d.caption) body.appendChild(el("p", { text: d.caption }));
    const det = document.createElement("details");
    det.className = "diagram";
    det.appendChild(summary);
    det.appendChild(body);
    host.appendChild(det);
  }
}

function renderKitParams() {
  const host = document.getElementById("kit-params");
  host.replaceChildren();
  const kit = kitState.available.find(k => k.id === kitState.selectedId);
  if (!kit) return;
  for (const p of kit.params) {
    const isActive = kitState.activeId === kit.id;
    const current = isActive && kitState.activeParams[p.key] != null
      ? kitState.activeParams[p.key]
      : p.default;
    const input = el("input", {
      id: `kp-${p.key}`,
      attrs: { type: "number", step: "0.001", "data-key": p.key,
               value: String(current),
               placeholder: p.required ? "required" : "optional" },
    });
    if (!p.required) input.removeAttribute("placeholder"); // we'll show via label
    const label = el("label", {
      class: "param-group",
      attrs: { for: `kp-${p.key}` },
    }, [document.createTextNode(`${p.label}${p.required ? "" : " (optional)"}: `), input,
        document.createTextNode(` ${p.unit}`)]);
    host.appendChild(label);
  }
}

function renderKitStatus() {
  const status = document.getElementById("kit-status");
  if (kitState.activeId) {
    const k = kitState.available.find(x => x.id === kitState.activeId);
    const parts = Object.entries(kitState.activeParams)
      .map(([k, v]) => `${k}=${v}`).join(", ");
    status.textContent = `active: ${k?.name ?? kitState.activeId}${parts ? " · " + parts : ""}`;
    status.classList.add("live");
  } else {
    status.textContent = "no kit selected";
    status.classList.remove("live");
  }
}

// ---------- Lab guide ----------
const labGuideState = {
  kitId: null,
  guide: null,
  busy: false,
  error: null,
};

async function loadLabGuide() {
  const kitId = kitState.selectedId;
  if (!kitId) return;
  labGuideState.kitId = kitId;
  labGuideState.error = null;
  labGuideState.busy = false;
  try {
    const r = await fetch(`/api/kits/${encodeURIComponent(kitId)}/lab_guide`);
    if (r.status === 404) {
      labGuideState.guide = null;
    } else if (r.ok) {
      labGuideState.guide = await r.json();
    } else {
      const body = await r.json().catch(() => ({}));
      labGuideState.guide = null;
      labGuideState.error = body.detail || `HTTP ${r.status}`;
    }
  } catch (e) {
    labGuideState.guide = null;
    labGuideState.error = String(e);
  }
  renderLabGuide();
}

async function uploadLabGuide({ file, text }) {
  if (!labGuideState.kitId) return;
  labGuideState.busy = true;
  labGuideState.error = null;
  renderLabGuide();
  try {
    const fd = new FormData();
    if (file) fd.append("file", file);
    if (text) fd.append("text", text);
    const r = await fetch(
      `/api/kits/${encodeURIComponent(labGuideState.kitId)}/lab_guide`,
      { method: "POST", body: fd },
    );
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${r.status}`);
    }
    labGuideState.guide = await r.json();
  } catch (e) {
    labGuideState.error = String(e.message || e);
  } finally {
    labGuideState.busy = false;
    renderLabGuide();
  }
}

function renderLabGuide() {
  const host = document.getElementById("kit-lab-guide");
  host.replaceChildren();

  const summary = el("summary", { text: "Lab guide" });
  const body = el("div", { class: "diagram-body" });
  const det = document.createElement("details");
  det.className = "diagram";
  if (labGuideState.guide || labGuideState.busy || labGuideState.error) {
    det.open = true;
  }
  det.appendChild(summary);
  det.appendChild(body);
  host.appendChild(det);

  if (labGuideState.busy) {
    body.appendChild(el("div", { class: "lg-busy", text: "Generating…" }));
    return;
  }
  if (labGuideState.error) {
    body.appendChild(el("div", { class: "lg-error", text: labGuideState.error }));
    body.appendChild(buildUploadRow("Generate"));
    return;
  }
  if (!labGuideState.guide) {
    body.appendChild(el("div", { class: "lg-empty", text: "No guide uploaded yet." }));
    body.appendChild(buildUploadRow("Generate"));
    return;
  }
  // Loaded state: materials + steps
  const g = labGuideState.guide;
  if (Array.isArray(g.materials) && g.materials.length) {
    const sec = el("div", { class: "lg-section" }, [el("h4", { text: "Materials" })]);
    const ul = el("ul", { class: "lg-materials" });
    for (const m of g.materials) {
      const parts = [
        document.createTextNode(m.item),
      ];
      if (m.quantity && m.quantity > 1) {
        parts.push(document.createTextNode(" "));
        parts.push(el("span", { class: "qty", text: `× ${m.quantity}` }));
      }
      if (m.note) {
        parts.push(document.createTextNode(" — "));
        parts.push(el("span", { class: "note", text: m.note }));
      }
      ul.appendChild(el("li", {}, parts));
    }
    sec.appendChild(ul);
    body.appendChild(sec);
  }
  if (Array.isArray(g.steps) && g.steps.length) {
    const sec = el("div", { class: "lg-section" }, [el("h4", { text: "Steps" })]);
    const stack = el("div", { class: "lg-steps" });
    for (const s of g.steps) {
      const card = el("div", { class: "lg-step" });
      card.appendChild(el("div", { class: "lg-step-action" }, [
        el("span", { class: "n", text: `${s.n}.` }),
        el("span", { text: s.action }),
      ]));
      const why = document.createElement("details");
      why.appendChild(el("summary"));
      why.appendChild(el("div", { class: "lg-reason", text: s.reason }));
      card.appendChild(why);
      stack.appendChild(card);
    }
    sec.appendChild(stack);
    body.appendChild(sec);
  }
  body.appendChild(buildLoadedFooter());
}

function buildLoadedFooter() {
  const row = el("div", { class: "lg-replace" });

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "application/pdf,.pdf";
  fileInput.style.display = "none";
  fileInput.onchange = () => {
    const f = fileInput.files && fileInput.files[0];
    if (f) uploadLabGuide({ file: f });
  };
  const replace = document.createElement("a");
  replace.textContent = "Replace";
  replace.onclick = (e) => { e.preventDefault(); fileInput.click(); };

  const sep = el("span", { text: "·" });

  const clear = document.createElement("a");
  clear.textContent = "Clear";
  clear.onclick = async (e) => {
    e.preventDefault();
    if (!confirm("Delete the lab guide for this kit?")) return;
    const r = await fetch(
      `/api/kits/${encodeURIComponent(labGuideState.kitId)}/lab_guide`,
      { method: "DELETE" },
    );
    if (!r.ok && r.status !== 204) {
      const body = await r.json().catch(() => ({}));
      alert(`Could not clear: ${body.detail || r.status}`);
      return;
    }
    labGuideState.guide = null;
    labGuideState.error = null;
    renderLabGuide();
  };

  row.appendChild(replace);
  row.appendChild(sep);
  row.appendChild(clear);
  row.appendChild(fileInput);
  return row;
}

function buildUploadRow(submitLabel) {
  // Tabs + matching input + submit button.
  const wrap = el("div");
  const tabs = el("div", { class: "lg-tabs" });
  const pdfTab = document.createElement("button");
  pdfTab.type = "button";
  pdfTab.className = "lg-tab active";
  pdfTab.textContent = "PDF";
  const textTab = document.createElement("button");
  textTab.type = "button";
  textTab.className = "lg-tab";
  textTab.textContent = "Paste text";
  tabs.appendChild(pdfTab);
  tabs.appendChild(textTab);
  wrap.appendChild(tabs);

  const pdfPanel = el("div", { class: "lg-upload-row" });
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "application/pdf,.pdf";
  pdfPanel.appendChild(fileInput);
  pdfPanel.appendChild(el("span", { class: "hint", text: "Takes about 10 seconds." }));

  const textPanel = el("div");
  textPanel.style.display = "none";
  const textarea = document.createElement("textarea");
  textarea.className = "lg-text";
  textarea.placeholder = "Paste your lab guide text here…";
  textPanel.appendChild(textarea);

  wrap.appendChild(pdfPanel);
  wrap.appendChild(textPanel);

  const submitRow = el("div", { class: "lg-replace" });
  const btn = document.createElement("button");
  btn.className = "primary";
  btn.textContent = submitLabel;
  btn.onclick = () => {
    if (pdfTab.classList.contains("active")) {
      const f = fileInput.files && fileInput.files[0];
      if (!f) { alert("Choose a PDF first."); return; }
      uploadLabGuide({ file: f });
    } else {
      const t = textarea.value.trim();
      if (!t) { alert("Paste some text first."); return; }
      uploadLabGuide({ text: t });
    }
  };
  submitRow.appendChild(btn);
  wrap.appendChild(submitRow);

  const switchTo = (which) => {
    if (which === "pdf") {
      pdfTab.classList.add("active"); textTab.classList.remove("active");
      pdfPanel.style.display = ""; textPanel.style.display = "none";
    } else {
      textTab.classList.add("active"); pdfTab.classList.remove("active");
      pdfPanel.style.display = "none"; textPanel.style.display = "";
    }
  };
  pdfTab.onclick = () => switchTo("pdf");
  textTab.onclick = () => switchTo("text");

  return wrap;
}

async function applyKit() {
  const kit = kitState.available.find(k => k.id === kitState.selectedId);
  if (!kit) return;
  const params = {};
  for (const p of kit.params) {
    const input = document.getElementById(`kp-${p.key}`);
    const raw = input.value.trim();
    if (raw === "") {
      if (p.required) {
        alert(`${p.label} is required`);
        return;
      }
      continue;
    }
    const num = Number(raw);
    if (!Number.isFinite(num)) { alert(`${p.label} must be a number`); return; }
    params[p.key] = num;
  }
  const r = await fetch("/api/kit", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ id: kit.id, params }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    alert(`Could not apply kit: ${body.detail || r.status}`);
    return;
  }
  await loadKits();
  await loadRuns();  // re-evaluate Arm enable state
}

// Per-device chart state. Each device_id gets its own chart card with its
// own xs / series / uPlot instance + a row of channel toggles.
const charts = new Map();   // device_id -> ChartState
const deviceLabels = new Map();  // device_id -> friendly name (from /api/devices)
// Set when a run starts (first sample's t). Display x = sample.t - tOffset.
// null means "live monitor mode" — show the raw stream timestamp.
let tOffset = null;

// Lab-notebook palette: deep teal, warm rust, moss, brass, plum, slate.
const COLORS = ["#0c4a48", "#9a3a2a", "#316e3c", "#b9863c", "#5a3f6e", "#3a4a5e"];

// Raw event channels (e.g. "gate_A_break_us") use scales orders of magnitude
// different from the derived physics quantities, so they'd swamp the chart.
// They're still recorded to CSV server-side; we just don't plot them.
const RAW_CHANNEL_RE = /_(?:us|raw|ns|ms)$/;

function chartTitleFor(deviceId) {
  return deviceLabels.get(deviceId) || deviceId;
}

function ensureChart(deviceId) {
  let c = charts.get(deviceId);
  if (c) return c;

  const card = el("div", { class: "chart-card" });
  const titleEl = el("span", { class: "chart-card-title", text: chartTitleFor(deviceId) });
  const metaEl  = el("span", { class: "chart-card-meta", text: deviceId });
  card.appendChild(el("div", { class: "chart-card-head" }, [titleEl, metaEl]));
  const togglesEl = el("div", { class: "chart-toggles" });
  card.appendChild(togglesEl);
  const plotMount = el("div");
  card.appendChild(plotMount);

  document.getElementById("charts").appendChild(card);
  document.getElementById("charts-empty").style.display = "none";

  const opts = {
    width: plotMount.clientWidth || 800,
    height: 240,
    scales: { x: { time: false } },
    axes: [{ label: "t (s)" }, { label: "value" }],
    series: [{}],
    legend: { show: true, live: false },
  };
  const plot = new uPlot(opts, [[]], plotMount);
  const onResize = () => plot.setSize({ width: plotMount.clientWidth, height: 240 });
  window.addEventListener("resize", onResize);

  c = {
    deviceId,
    card, titleEl, metaEl, togglesEl, plotMount,
    plot,
    xs: [],
    series: new Map(),       // channel -> { data: number[], visible: boolean, color: string, toggleEl, swatchEl }
    onResize,
  };
  charts.set(deviceId, c);
  return c;
}

function ensureSeries(c, channel) {
  if (c.series.has(channel)) return c.series.get(channel);
  const color = COLORS[c.series.size % COLORS.length];
  const data = new Array(c.xs.length).fill(null);
  const idx = c.series.size + 1;  // 0 is x-axis
  c.plot.addSeries({ label: channel, stroke: color, width: 2 }, idx);

  // Build the toggle UI for this channel.
  const swatch = el("span", { class: "swatch" });
  swatch.style.background = color;
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = true;
  const labelEl = el("label", { class: "chart-toggle" }, [
    input, swatch, document.createTextNode(channel),
  ]);
  input.addEventListener("change", () => {
    const s = c.series.get(channel);
    s.visible = input.checked;
    labelEl.classList.toggle("off", !input.checked);
    c.plot.setSeries(idx, { show: input.checked });
  });
  c.togglesEl.appendChild(labelEl);

  const entry = { data, visible: true, color, idx, toggleEl: labelEl, swatchEl: swatch };
  c.series.set(channel, entry);
  return entry;
}

function pushSample(s) {
  if (RAW_CHANNEL_RE.test(s.channel)) return;
  const c = ensureChart(s.device_id);
  ensureSeries(c, s.channel);
  // If a run is active, anchor t=0 to the first sample we receive after Arm.
  if (tOffset !== null && tOffset === Infinity) tOffset = s.t;
  const x = tOffset != null ? s.t - tOffset : s.t;

  if (c.xs.length === 0 || x > c.xs[c.xs.length - 1]) {
    c.xs.push(x);
    for (const entry of c.series.values()) entry.data.push(null);
  }
  c.series.get(s.channel).data[c.series.get(s.channel).data.length - 1] = s.value;

  if (c.xs.length > MAX_POINTS) {
    const drop = c.xs.length - MAX_POINTS;
    c.xs = c.xs.slice(drop);
    for (const entry of c.series.values()) entry.data = entry.data.slice(drop);
  }

  c.plot.setData([c.xs, ...Array.from(c.series.values()).map(e => e.data)]);
}

function clearChart() {
  for (const c of charts.values()) {
    c.xs = [];
    for (const entry of c.series.values()) entry.data = [];
    c.plot.setData([c.xs, ...Array.from(c.series.values()).map(e => e.data)]);
  }
}

function refreshChartTitles() {
  for (const c of charts.values()) {
    c.titleEl.textContent = chartTitleFor(c.deviceId);
  }
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
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m && m.type === "run_state") {
      // Server-side run start/stop (including auto-stop trigger fires).
      // Update the Run UI immediately so we don't have to wait for the
      // periodic poll. Also refresh history so a just-finished run shows up.
      setRunUI(m.active);
      loadRuns().catch(() => {});
    } else {
      pushSample(m);
    }
  };
}

document.getElementById("arm").addEventListener("click", async () => {
  const name = document.getElementById("run-name").value.trim() || "run";
  const triggers = collectActiveTriggers();
  const r = await fetch("/api/arm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, triggers }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    alert(`Could not arm: ${body.detail || r.status}`);
    return;
  }
  // Reset chart and arm the t-offset so x-axis starts at 0 for this run.
  clearChart();
  tOffset = Infinity;  // sentinel: "use the next sample's t as offset"
  await loadRuns();
});

document.getElementById("kit-apply").addEventListener("click", applyKit);
document.getElementById("ble-scan").addEventListener("click", bleScan);
document.getElementById("ble-forget").addEventListener("click", async () => {
  await fetch("/api/ble/forget", { method: "POST" });
  await loadDevices();
});

// Refresh device list every 2s so connection state stays fresh during
// connect/disconnect transitions and as samples accumulate.
setInterval(() => { loadDevices().catch(() => {}); }, 2000);

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
  await loadDevices();
  await loadKits();
  await loadRuns();
  connectWS();
})();

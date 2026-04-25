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
    renderKitParams();
  };
  const kit = kitState.available.find(k => k.id === kitState.selectedId);
  document.getElementById("kit-desc").textContent = kit?.description ?? "";
  renderKitDiagrams(kit?.diagrams ?? []);
  loadLabGuide();
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

// Lab-notebook palette: deep teal, warm rust, moss, brass, plum, slate.
const COLORS = ["#0c4a48", "#9a3a2a", "#316e3c", "#b9863c", "#5a3f6e", "#3a4a5e"];

function ensureSeries(channel) {
  if (series.has(channel)) return;
  series.set(channel, new Array(xs.length).fill(null));
  const idx = series.size;
  plot.addSeries({ label: channel, stroke: COLORS[(idx - 1) % COLORS.length], width: 2 }, idx);
}

// Raw event channels (e.g. "gate_A_break_us") use scales orders of magnitude
// different from the derived physics quantities, so they'd swamp the chart.
// They're still recorded to CSV server-side; we just don't plot them.
const RAW_CHANNEL_RE = /_(?:us|raw|ns|ms)$/;

function pushSample(s) {
  if (RAW_CHANNEL_RE.test(s.channel)) return;
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
  const r = await fetch("/api/arm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
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
  await loadKits();
  await loadRuns();
  connectWS();
})();

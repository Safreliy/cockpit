const metricDefs = [
  { key: "active_connections", label: "Active connections", unit: "", threshold: 24 },
  { key: "waiting_connections", label: "Waiting connections", unit: "", threshold: 2 },
  { key: "connections", label: "Connections", unit: "" },
  { key: "xact_rate", label: "Transaction rate", unit: "/s" },
  { key: "read_blocks_rate", label: "Read blocks", unit: "/s" },
  { key: "cache_hit_rate", label: "Cache hits", unit: "/s" },
  { key: "blk_read_time_ms_rate", label: "Read time", unit: "ms/s", threshold: 50 },
  { key: "active_vacuum_sessions", label: "Manual VACUUM", unit: "", threshold: 1 },
  { key: "active_autovacuum_sessions", label: "Autovacuum", unit: "", threshold: 1 },
  { key: "vacuum_max_elapsed_seconds", label: "VACUUM duration", unit: "s", threshold: 30 }
];

const API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8088" : "";

let stream = [];
let detections = [];
let signals = [];
let incidents = [];
let operationalEvents = [];
let experiments = [];
let experimentSettings = {};
let detectorCatalog = [];
let aiAgent = { enabled: false };
let selectedDetectorId = "all";
let selectedMetric = metricDefs.find((metric) => metric.key === "xact_rate");
let selectedIncidentId = null;
let selectedWindow = 900;
let zoomRange = null;
let dragStartX = null;
let showAllOps = false;
let userSelectedIncident = false;
let reportRenderedIncidentId = null;
let reportRenderedVersion = "";

const statusBand = document.getElementById("statusBand");
const statusLabel = document.getElementById("statusLabel");
const statusSubtitle = document.getElementById("statusSubtitle");
const sampleCount = document.getElementById("sampleCount");
const loadState = document.getElementById("loadState");
const retentionState = document.getElementById("retentionState");
const metricPicker = document.getElementById("metricPicker");
const windowPicker = document.getElementById("windowPicker");
const resetZoom = document.getElementById("resetZoom");
const chartRange = document.getElementById("chartRange");
const chart = document.getElementById("liveChart");
const chartTooltip = document.getElementById("chartTooltip");
const metricsStrip = document.getElementById("metricsStrip");
const incidentSteps = document.getElementById("incidentSteps");
const startLoad = document.getElementById("startLoad");
const stopLoad = document.getElementById("stopLoad");
const stopLoadFromDrawer = document.getElementById("stopLoadFromDrawer");
const loadClients = document.getElementById("loadClients");
const loadSeconds = document.getElementById("loadSeconds");
const loadJobs = document.getElementById("loadJobs");
const loadRate = document.getElementById("loadRate");
const loadMode = document.getElementById("loadMode");
const benchmarkEngine = document.getElementById("benchmarkEngine");
const benchmarkProfile = document.getElementById("benchmarkProfile");
const benchmarkScript = document.getElementById("benchmarkScript");
const openBenchmarkLab = document.getElementById("openBenchmarkLab");
const benchmarkDrawer = document.getElementById("benchmarkDrawer");
const benchmarkBackdrop = document.getElementById("benchmarkBackdrop");
const closeBenchmarkLab = document.getElementById("closeBenchmarkLab");
const benchmarkState = document.getElementById("benchmarkState");
const loadOutput = document.getElementById("loadOutput");
const detectorPicker = document.getElementById("detectorPicker");
const openExperimentLab = document.getElementById("openExperimentLab");
const runAiHealthcheck = document.getElementById("runAiHealthcheck");
const openReport = document.getElementById("openReport");
const drawer = document.getElementById("reportDrawer");
const backdrop = document.getElementById("drawerBackdrop");
const closeReport = document.getElementById("closeReport");
const experimentDrawer = document.getElementById("experimentDrawer");
const experimentBackdrop = document.getElementById("experimentBackdrop");
const closeExperimentLab = document.getElementById("closeExperimentLab");
const experimentSetting = document.getElementById("experimentSetting");
const experimentValue = document.getElementById("experimentValue");
const applyExperiment = document.getElementById("applyExperiment");
const experimentList = document.getElementById("experimentList");
const statusActions = document.querySelectorAll(".status-action");
const refreshIncident = document.getElementById("refreshIncident");
const runAiInvestigation = document.getElementById("runAiInvestigation");
const aiChatStatus = document.getElementById("aiChatStatus");
const aiChatMessages = document.getElementById("aiChatMessages");
const aiChatForm = document.getElementById("aiChatForm");
const aiChatInput = document.getElementById("aiChatInput");
const sendAiChat = document.getElementById("sendAiChat");

let chatMessagesByIncident = {};
let chatHistoryLoaded = new Set();
let activeChatAbort = null;
let activeChatIncidentId = null;

function formatValue(value) {
  if (value == null) return "--";
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function formatClock(epochSeconds) {
  if (!epochSeconds) return "--";
  return new Date(epochSeconds * 1000).toLocaleTimeString();
}

function formatRangeLabel(firstT, lastT) {
  if (!firstT || !lastT) return "Waiting for telemetry";
  return `${new Date(firstT * 1000).toLocaleString()} - ${new Date(lastT * 1000).toLocaleTimeString()}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdown(value) {
  const escaped = escapeHtml(value);
  const blocks = escaped.split(/```/);
  let html = "";
  blocks.forEach((block, index) => {
    if (index % 2 === 1) {
      html += "<pre><code>" + block.replace(/^\w+\n/, "") + "</code></pre>";
      return;
    }
    const lines = block.split("\n");
    let inList = false;
    lines.forEach((line) => {
      const bullet = line.match(/^\s*[-*]\s+(.+)/);
      if (bullet) {
        if (!inList) {
          html += "<ul>";
          inList = true;
        }
        html += "<li>" + bullet[1] + "</li>";
        return;
      }
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      if (!line.trim()) return;
      let text = line
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      if (/^#{1,4}\s+/.test(text)) {
        text = text.replace(/^#{1,4}\s+/, "");
        html += "<h4>" + text + "</h4>";
      } else {
        html += "<p>" + text + "</p>";
      }
    });
    if (inList) html += "</ul>";
  });
  return html || "<p></p>";
}

function scale(value, min, max, outMin, outMax) {
  if (max === min) return (outMin + outMax) / 2;
  return outMin + ((value - min) * (outMax - outMin)) / (max - min);
}

function unscale(value, inMin, inMax, outMin, outMax) {
  if (inMax === inMin) return (outMin + outMax) / 2;
  return outMin + ((value - inMin) * (outMax - outMin)) / (inMax - inMin);
}

function svgPoint(event) {
  const rect = chart.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * 860,
    y: ((event.clientY - rect.top) / rect.height) * 320,
    pageX: event.clientX,
    pageY: event.clientY
  };
}

function visibleStreamForChart() {
  if (!stream.length) return [];
  if (zoomRange) {
    return stream.filter((point) => point.t >= zoomRange[0] && point.t <= zoomRange[1]);
  }
  if (selectedWindow === "all") return stream;
  const lastT = stream.at(-1).t;
  return stream.filter((point) => point.t >= lastT - Number(selectedWindow));
}

function selectedIncident() {
  const activeStatuses = new Set(["candidate", "active", "recovering", "acknowledged", "open"]);
  return incidents.find((item) => item.id === selectedIncidentId) ?? incidents.find((item) => activeStatuses.has(item.status)) ?? incidents.at(-1) ?? null;
}

function renderMetricPicker() {
  metricPicker.innerHTML = "";
  metricDefs.forEach((metric) => {
    const option = document.createElement("option");
    option.value = metric.key;
    option.textContent = metric.label;
    metricPicker.appendChild(option);
  });
  metricPicker.value = selectedMetric.key;
}

function normalizeDetection(detection) {
  return {
    id: detection.id ?? detection.type + "-" + detection.t,
    ...detection
  };
}

function normalizeIncident(incident) {
  return {
    id: incident.id ?? "inc-" + incident.type + "-" + incident.created_at,
    ...incident
  };
}

function upsertIncident(incident) {
  const normalized = normalizeIncident(incident);
  const index = incidents.findIndex((item) => item.id === normalized.id);
  if (index >= 0) {
    incidents[index] = normalized;
  } else {
    incidents.push(normalized);
    incidents = incidents.slice(-200);
  }
  return normalized;
}

function ingestSnapshot(snapshot) {
  stream = snapshot.stream ?? [];
  detections = (snapshot.detections ?? []).map(normalizeDetection);
  signals = (snapshot.signals ?? snapshot.detections ?? []).map(normalizeDetection);
  incidents = (snapshot.incidents ?? []).map(normalizeIncident);
  operationalEvents = snapshot.operational_events ?? [];
  experiments = snapshot.experiments ?? [];
  experimentSettings = snapshot.experiment_settings ?? {};
  detectorCatalog = snapshot.detectors ?? [];
  aiAgent = snapshot.ai_agent ?? { enabled: false };
  selectedDetectorId = selectedDetectorFromCatalog();
  renderDetectorPicker();
  renderExperimentSettings();
  renderLoad(snapshot.load);
  retentionState.textContent = `${snapshot.retention?.telemetry_points ?? stream.length} pts`;
  render();
}

function ingestEvent(event) {
  if (event.type === "snapshot") {
    ingestSnapshot(event.snapshot);
    return;
  }
  if (event.type === "telemetry") {
    stream.push(event.point);
    stream = stream.slice(-720);
  }
  if (event.type === "detection") {
    detections.push(normalizeDetection(event.detection));
    detections = detections.slice(-200);
  }
  if (event.type === "signal") {
    signals.push(normalizeDetection(event.signal));
    signals = signals.slice(-200);
  }
  if (event.type === "incident") {
    const incident = upsertIncident(event.incident);
    if (!selectedIncidentId && !userSelectedIncident) {
      selectedIncidentId = incident.id;
    }
  }
  if (event.type === "operational_event") {
    operationalEvents.push(event.event);
    operationalEvents = operationalEvents.slice(-300);
  }
  if (event.type === "experiment") {
    upsertExperiment(event.experiment);
  }
  if (event.type === "load") {
    renderLoad(event.load);
  }
  if (event.type === "detectors") {
    detectorCatalog = event.detectors ?? [];
    selectedDetectorId = selectedDetectorFromCatalog();
    renderDetectorPicker();
  }
  if (dragStartX != null) return;
  renderForEvent(event.type);
}

function renderLoad(load) {
  if (!load) return;
  loadState.textContent = load.running ? "running" : "idle";
  const config = load.config ?? {};
  benchmarkState.textContent = load.running
    ? `${config.engine ?? "workload"} · ${config.clients ?? "--"} clients · ${config.rate ? config.rate + " TPS" : "unlimited"}`
    : "idle";
  const output = load.output ?? [];
  loadOutput.textContent = output.length ? output.join("\n") : "No workload output yet.";
  if (!load.running && load.returncode != null && load.returncode !== 0) {
    loadState.textContent = "failed";
    benchmarkState.textContent = "failed";
    statusSubtitle.textContent = (load.output ?? []).at(-1) ?? "Load finished with an error.";
  }
  startLoad.disabled = load.running;
  stopLoad.disabled = !load.running;
  stopLoadFromDrawer.disabled = !load.running;
}

function selectedDetectorFromCatalog() {
  if (!detectorCatalog.length) return selectedDetectorId;
  const enabled = detectorCatalog.filter((detector) => detector.enabled);
  if (!enabled.length || enabled.length === detectorCatalog.length) return "all";
  if (enabled.length === 1) return enabled[0].id;
  return "custom";
}

function detectorLabel() {
  if (!detectorCatalog.length || selectedDetectorId === "all") return "all";
  const detector = detectorCatalog.find((item) => item.id === selectedDetectorId);
  return detector?.name ?? selectedDetectorId;
}

function renderDetectorPicker() {
  if (!detectorPicker) return;
  detectorPicker.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = "All detectors";
  detectorPicker.appendChild(allOption);
  if (selectedDetectorId === "custom") {
    const customOption = document.createElement("option");
    customOption.value = "custom";
    customOption.textContent = "Custom selection";
    customOption.disabled = true;
    detectorPicker.appendChild(customOption);
  }
  detectorCatalog.forEach((detector) => {
    const option = document.createElement("option");
    option.value = detector.id;
    option.textContent = detector.name + " (" + detector.engine + ")";
    detectorPicker.appendChild(option);
  });
  detectorPicker.value = selectedDetectorId;
}

function renderStatus() {
  sampleCount.textContent = String(stream.length);
  const incident = selectedIncident();
  const openStatuses = new Set(["candidate", "active", "recovering", "acknowledged", "open"]);
  const openCount = incidents.filter((item) => openStatuses.has(item.status)).length;
  statusBand.classList.remove("state-ok", "state-warn", "state-bad");
  if (!openCount) {
    statusBand.classList.add("state-ok");
    statusLabel.textContent = "Live telemetry connected";
    statusSubtitle.textContent = (incidents.length ? "No open incidents. Recent incidents are available for review." : "No current incidents.") + " Detector: " + detectorLabel();
    openReport.disabled = !incidents.length;
    return;
  }
  statusBand.classList.add(incident?.severity === "critical" ? "state-bad" : "state-warn");
  statusLabel.textContent = incident.summary;
  statusSubtitle.textContent = `${openCount} active incident${openCount === 1 ? "" : "s"} - ${incident.status} / ${incident.investigation?.phase ?? "queued"} - Detector: ${detectorLabel()}`;
  openReport.disabled = false;
}

function renderChart() {
  const width = 860;
  const height = 320;
  const margin = { left: 58, right: 24, top: 30, bottom: 48 };
  const x1 = margin.left;
  const x2 = width - margin.right;
  const y1 = height - margin.bottom;
  const y2 = margin.top;
  if (!stream.length) {
    chart.innerHTML = '<rect width="860" height="320" fill="#fff"></rect><text x="52" y="160" fill="#607080">Waiting for telemetry...</text>';
    chartRange.textContent = "Waiting for telemetry";
    return;
  }
  const visibleStream = visibleStreamForChart();
  if (!visibleStream.length) {
    zoomRange = null;
    renderChart();
    return;
  }
  const values = visibleStream.map((point) => point[selectedMetric.key] ?? 0);
  const threshold = selectedMetric.threshold;
  const min = Math.min(...values, threshold ?? Infinity);
  const max = Math.max(...values, threshold ?? -Infinity);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.12;
  const firstT = visibleStream[0].t;
  const lastT = visibleStream.at(-1).t;
  chartRange.textContent = formatRangeLabel(firstT, lastT);
  resetZoom.disabled = !zoomRange;
  const points = visibleStream
    .map((point) => {
      const x = scale(point.t, firstT, lastT, x1, x2);
      const y = scale(point[selectedMetric.key] ?? 0, yMin, yMax, y1, y2);
      return x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = yMax - (yMax - yMin) * ratio;
    const y = scale(value, yMin, yMax, y1, y2);
    return '<line class="grid-line" x1="' + x1 + '" x2="' + x2 + '" y1="' + y + '" y2="' + y + '"></line><text class="tick-label" x="' + (x1 - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + formatValue(value) + '</text>';
  }).join("");
  const xTickCount = Math.min(6, Math.max(2, visibleStream.length));
  const xTicks = Array.from({ length: xTickCount }, (_, index) => {
    const t = firstT + ((lastT - firstT) * index) / (xTickCount - 1 || 1);
    const x = scale(t, firstT, lastT, x1, x2);
    return '<line class="grid-line vertical" x1="' + x + '" x2="' + x + '" y1="' + y2 + '" y2="' + y1 + '"></line><text class="tick-label" x="' + x + '" y="' + (y1 + 24) + '" text-anchor="middle">' + formatClock(t) + '</text>';
  }).join("");
  const thresholdY = threshold == null ? "" : '<line class="threshold" x1="' + x1 + '" x2="' + x2 + '" y1="' + scale(threshold, yMin, yMax, y1, y2) + '" y2="' + scale(threshold, yMin, yMax, y1, y2) + '"></line>';
  const markers = incidents
    .map((incident) => {
      const markerT = incident.last_seen_at ?? incident.created_at;
      if (markerT < firstT || markerT > lastT) return "";
      const point = stream.reduce((best, item) => Math.abs(item.t - markerT) < Math.abs(best.t - markerT) ? item : best, stream[0]);
      const startT = Math.max(incident.started_at ?? incident.created_at ?? markerT, firstT);
      const endT = Math.min(incident.resolved_at ?? incident.last_seen_at ?? markerT, lastT);
      const bandX = scale(startT, firstT, lastT, x1, x2);
      const bandWidth = Math.max(8, scale(endT, firstT, lastT, x1, x2) - bandX);
      const x = scale(markerT, firstT, lastT, x1, x2);
      const y = scale(point[selectedMetric.key] ?? 0, yMin, yMax, y1, y2);
      const active = selectedIncident()?.id === incident.id ? " selected" : "";
      const resolved = incident.status === "resolved" || incident.status === "false_positive" ? " resolved" : "";
      return '<g class="incident-marker' + active + resolved + '" data-incident-id="' + incident.id + '" role="button" tabindex="0"><rect class="incident-band" x="' + bandX + '" y="' + y2 + '" width="' + bandWidth + '" height="' + (y1 - y2) + '"></rect><line class="anomaly-line" x1="' + x + '" x2="' + x + '" y1="' + y2 + '" y2="' + y1 + '"></line><circle class="anomaly-dot" cx="' + x + '" cy="' + y + '" r="7"></circle><circle class="anomaly-hit" cx="' + x + '" cy="' + y + '" r="18"></circle></g>';
    })
    .join("");
  chart.innerHTML =
    '<rect width="' + width + '" height="' + height + '" fill="#fff"></rect>' +
    '<rect class="plot-bg" x="' + x1 + '" y="' + y2 + '" width="' + (x2 - x1) + '" height="' + (y1 - y2) + '"></rect>' +
    yTicks +
    xTicks +
    '<line class="axis" x1="' + x1 + '" x2="' + x2 + '" y1="' + y1 + '" y2="' + y1 + '"></line>' +
    '<line class="axis" x1="' + x1 + '" x2="' + x1 + '" y1="' + y1 + '" y2="' + y2 + '"></line>' +
    thresholdY +
    '<polyline class="series" points="' + points + '"></polyline>' +
    '<rect class="plot-hit" x="' + x1 + '" y="' + y2 + '" width="' + (x2 - x1) + '" height="' + (y1 - y2) + '"></rect>' +
    markers +
    '<rect class="brush" id="chartBrush" x="0" y="' + y2 + '" width="0" height="' + (y1 - y2) + '" visibility="hidden"></rect>' +
    '<text x="' + x1 + '" y="18" fill="#17202a" font-size="13" font-weight="700">' + selectedMetric.label + ": " + formatValue(stream.at(-1)[selectedMetric.key]) + " " + selectedMetric.unit + '</text>' +
    '<text class="axis-title" x="' + ((x1 + x2) / 2) + '" y="' + (height - 8) + '" text-anchor="middle">time</text>';
  chart.querySelectorAll(".incident-marker").forEach((marker) => {
    marker.addEventListener("click", () => selectIncident(marker.dataset.incidentId, true));
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIncident(marker.dataset.incidentId, true);
      }
    });
  });
  const hit = chart.querySelector(".plot-hit");
  const brush = chart.querySelector("#chartBrush");
  hit.onpointerdown = (event) => {
    event.preventDefault();
    const point = svgPoint(event);
    dragStartX = Math.max(x1, Math.min(x2, point.x));
    brush.setAttribute("x", dragStartX);
    brush.setAttribute("width", 0);
    brush.setAttribute("visibility", "visible");
    hit.setPointerCapture(event.pointerId);
  };
  chart.onpointermove = (event) => {
    event.preventDefault();
    const point = svgPoint(event);
    if (dragStartX != null) {
      const currentX = Math.max(x1, Math.min(x2, point.x));
      brush.setAttribute("x", Math.min(dragStartX, currentX));
      brush.setAttribute("width", Math.abs(currentX - dragStartX));
      return;
    }
    const boundedX = Math.max(x1, Math.min(x2, point.x));
    const t = unscale(boundedX, x1, x2, firstT, lastT);
    const nearest = visibleStream.reduce((best, item) => Math.abs(item.t - t) < Math.abs(best.t - t) ? item : best, visibleStream[0]);
    chartTooltip.hidden = false;
    chartTooltip.style.left = Math.min(point.pageX + 12, window.innerWidth - 190) + "px";
    chartTooltip.style.top = Math.max(point.pageY - 58, 8) + "px";
    chartTooltip.innerHTML = "<strong>" + formatClock(nearest.t) + "</strong><span>" + selectedMetric.label + ": " + formatValue(nearest[selectedMetric.key]) + " " + selectedMetric.unit + "</span>";
  };
  chart.onpointerup = (event) => {
    event.preventDefault();
    if (dragStartX == null) return;
    const point = svgPoint(event);
    const endX = Math.max(x1, Math.min(x2, point.x));
    brush.setAttribute("visibility", "hidden");
    if (Math.abs(endX - dragStartX) > 24) {
      const left = Math.min(dragStartX, endX);
      const right = Math.max(dragStartX, endX);
      zoomRange = [unscale(left, x1, x2, firstT, lastT), unscale(right, x1, x2, firstT, lastT)];
      renderChart();
    }
    dragStartX = null;
  };
  chart.onpointerleave = () => {
    chartTooltip.hidden = true;
  };
}

function captureChartImage() {
  if (!chart || !chart.innerHTML.trim()) return Promise.resolve(null);
  return new Promise((resolve) => {
    const clone = chart.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", "860");
    clone.setAttribute("height", "320");
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = `
      .plot-bg{fill:#f7f9fc}.grid-line{stroke:#d8dee8;stroke-width:1}.grid-line.vertical{stroke-dasharray:3 5}
      .axis{stroke:#6d7a8a;stroke-width:1.2}.axis-title,.tick-label{fill:#607080;font-family:Inter,Arial,sans-serif;font-size:11px}
      .series{fill:none;stroke:#2563eb;stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round}
      .threshold{stroke:#ef4444;stroke-width:1.4;stroke-dasharray:4 5}.incident-band{fill:rgba(239,68,68,.1)}
      .anomaly-line{stroke:#ef4444;stroke-width:1.5;stroke-dasharray:4 5}.anomaly-dot{fill:#ef4444;stroke:#fff;stroke-width:2}
      .anomaly-hit,.plot-hit,.brush{display:none}.incident-marker.resolved .anomaly-dot{fill:#64748b}
    `;
    clone.insertBefore(style, clone.firstChild);
    const svgText = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([svgText], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = 860;
      canvas.height = 320;
      const context = canvas.getContext("2d");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/png"));
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    image.src = url;
  });
}

function renderMetricsStrip() {
  const point = stream.at(-1) ?? {};
  const primary = ["active_connections", "waiting_connections", "xact_rate", "vacuum_max_elapsed_seconds"];
  metricsStrip.innerHTML = "";
  primary.forEach((key) => {
    const def = metricDefs.find((metric) => metric.key === key);
    const alert = def.threshold != null && (point[key] ?? 0) >= def.threshold;
    const card = document.createElement("div");
    card.className = "metric-card" + (alert ? " alert" : "");
    card.innerHTML = "<span>" + def.label + "</span><strong>" + formatValue(point[key]) + " " + def.unit + "</strong>";
    metricsStrip.appendChild(card);
  });
}

function upsertExperiment(experiment) {
  const index = experiments.findIndex((item) => item.id === experiment.id);
  if (index >= 0) {
    experiments[index] = experiment;
  } else {
    experiments.unshift(experiment);
    experiments = experiments.slice(0, 100);
  }
}

function renderExperimentSettings() {
  const selected = experimentSetting.value;
  experimentSetting.innerHTML = "";
  Object.entries(experimentSettings).forEach(([name, meta]) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name + " - " + meta.description;
    experimentSetting.appendChild(option);
  });
  if (selected && experimentSettings[selected]) {
    experimentSetting.value = selected;
  }
  if (!experimentValue.value && experimentSetting.value) {
    experimentValue.value = experimentSettings[experimentSetting.value]?.risky ?? "";
  }
}

function renderExperiments() {
  experimentList.innerHTML = "";
  if (!experiments.length) {
    const empty = document.createElement("li");
    empty.className = "step empty";
    empty.innerHTML = "<strong>No experiments yet</strong><span>Apply a controlled setting change to create a DBA-cause signal.</span>";
    experimentList.appendChild(empty);
    return;
  }
  experiments.forEach((experiment) => {
    const li = document.createElement("li");
    li.className = "experiment-item status-" + experiment.status;
    li.innerHTML =
      "<div><strong>" + experiment.setting + " = " + experiment.value + "</strong><span>" + experiment.status + " at " + formatClock(experiment.t) + "</span><span>previous: " + (experiment.previous?.setting ?? "--") + "</span></div>" +
      '<button type="button" data-experiment-id="' + experiment.id + '"' + (experiment.status === "rolled_back" ? " disabled" : "") + ">Rollback</button>";
    li.querySelector("button").addEventListener("click", async () => {
      const data = await postJson("/api/experiments/rollback", { id: experiment.id });
      if (data.experiment) {
        upsertExperiment(data.experiment);
        renderExperiments();
      }
    });
    experimentList.appendChild(li);
  });
}

function renderIncidents() {
  incidentSteps.innerHTML = "";
  const sorted = incidents.slice().sort((left, right) => (right.last_seen_at ?? right.created_at) - (left.last_seen_at ?? left.created_at));
  if (!sorted.length) {
    const empty = document.createElement("li");
    empty.className = "step empty";
    empty.innerHTML = "<strong>No incidents yet</strong><span>Start pgbench load to create live signal movement.</span>";
    incidentSteps.appendChild(empty);
    return;
  }
  sorted.forEach((incident) => {
    const li = document.createElement("li");
    li.className = "step done status-" + incident.status + (selectedIncident()?.id === incident.id ? " selected" : "");
    li.setAttribute("role", "button");
    li.setAttribute("tabindex", "0");
    li.innerHTML =
      '<div class="step-head"><strong>' + incident.type + '</strong><span class="status-pill">' + incident.status + "</span></div>" +
      "<span>" + formatClock(incident.started_at ?? incident.created_at) + " - " + formatClock(incident.last_seen_at ?? incident.created_at) + " · signals " + (incident.signal_count ?? incident.sample_count ?? 1) + " · conf " + formatValue((incident.confidence ?? 0) * 100) + "%</span>" +
      '<div class="investigation-mini"><span>' + (incident.investigation?.phase ?? "queued") + '</span><div><i style="width:' + (incident.investigation?.progress ?? 0) + '%"></i></div></div>';
    li.addEventListener("click", () => selectIncident(incident.id, true));
    li.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIncident(incident.id, true);
      }
    });
    incidentSteps.appendChild(li);
  });
}

function incidentReportVersion(incident) {
  if (!incident) return "";
  return [
    incident.id,
    incident.status,
    incident.last_seen_at,
    incident.resolved_at,
    incident.signal_count,
    incident.updated_at,
    incident.investigation?.phase,
    incident.investigation?.progress,
    incident.ai_investigation?.status,
    incident.ai_investigation?.updated_at,
    incident.ai_verdict?.verdict,
    incident.image_attachments?.length ?? 0,
    showAllOps ? "all-ops" : "latest-ops"
  ].join("|");
}

function renderReport(options = {}) {
  const incident = selectedIncident();
  if (!incident) return;
  const reportOpen = drawer.classList.contains("open");
  const version = incidentReportVersion(incident);
  if (!options.force && reportOpen && reportRenderedIncidentId === incident.id && reportRenderedVersion === version) return;
  const previousScroll = drawer.scrollTop;
  const selection = window.getSelection();
  if (!options.force && reportOpen && selection && selection.type === "Range") return;
  document.getElementById("reportTitle").textContent = incident.type;
  const detector = incident.detector ?? { name: "Unknown detector", engine: "unknown" };
  const evidenceRows = (incident.evidence ?? []).map((item) => (
    "<tr><td>" + item.metric + "</td><td>" + formatValue(item.value) + "</td><td>" + (item.threshold ?? item.role ?? "") + "</td></tr>"
  )).join("");
  const allOps = (incident.operational_events ?? operationalEvents).slice().sort((left, right) => (right.t ?? 0) - (left.t ?? 0));
  const visibleOps = showAllOps ? allOps : allOps.slice(0, 5);
  const hiddenOpsCount = Math.max(0, allOps.length - visibleOps.length);
  const relatedOps = visibleOps.map((item) => (
    '<li><strong>' + item.type + '</strong><span>' + formatClock(item.t) + ' - ' + item.summary + '</span></li>'
  )).join("");
  const investigation = incident.investigation ?? {};
  const investigationSteps = (investigation.steps ?? []).map((item) => (
    '<li class="investigation-step ' + item.status + '"><span class="status-pill">' + item.status + '</span><div><strong>' + item.label + '</strong><p>' + item.detail + '</p></div></li>'
  )).join("");
  const timeline = (incident.timeline ?? []).slice(-12).reverse().map((item) => (
    '<li><strong>' + item.type + '</strong><span>' + formatClock(item.t) + ' - ' + item.metric + ' = ' + formatValue(item.value) + ' - score ' + formatValue(item.score) + '</span></li>'
  )).join("");
  const ai = incident.ai_investigation ?? {};
  const aiVerdict = incident.ai_verdict ?? ai.verdict;
  const aiChain = (aiVerdict?.causal_chain ?? []).map((item) => (
    '<li><span>' + (item.stage ?? "evidence") + '</span><p>' + (item.detail ?? "") + '</p></li>'
  )).join("");
  const aiEvidence = (aiVerdict?.supporting_evidence ?? []).map((item) => "<li>" + item + "</li>").join("");
  const aiNegativeEvidence = (aiVerdict?.negative_evidence ?? []).map((item) => "<li>" + item + "</li>").join("");
  const aiVisualObservations = (aiVerdict?.visual_observations ?? []).map((item) => "<li>" + item + "</li>").join("");
  const aiActions = (aiVerdict?.recommended_actions ?? []).map((item) => "<li>" + item + "</li>").join("");
  const aiNeedsMoreData = (aiVerdict?.needs_more_data ?? []).map((item) => "<li>" + item + "</li>").join("");
  const visualStatus = incident.visual_input_status
    ? '<p class="visual-status">Visual inputs: ' + incident.visual_input_status.accepted + ' accepted from ' + incident.visual_input_status.requested + ' requested.</p>'
    : "";
  const visualEvidence = (incident.image_attachments ?? []).map((item) => (
    '<figure class="visual-evidence"><img src="' + item.image_url + '" alt="Dashboard chart captured for AI analysis"><figcaption>' + (item.source ?? "dashboard chart") + " captured " + formatClock(item.captured_at) + '</figcaption></figure>'
  )).join("");
  const visualEvidenceBlock = visualEvidence || visualStatus
    ? '<div class="report-block"><strong>Visual evidence for AI</strong>' + visualStatus + visualEvidence + '</div>'
    : "";
  const aiBlock = aiVerdict
    ? '<div class="report-block ai-verdict"><div class="ai-verdict-head"><div><strong>AI verdict</strong><h3>' + (aiVerdict.verdict ?? "Verdict ready") + '</h3></div><span class="status-pill">' + formatValue((aiVerdict.confidence ?? 0) * 100) + '% confidence</span></div><p class="ai-root-cause">' + (aiVerdict.root_cause ?? "") + '</p><div class="ai-section"><strong>Causal chain</strong><ol class="ai-chain">' + (aiChain || '<li><span>pending</span><p>No causal chain returned.</p></li>') + '</ol></div><div class="ai-section"><strong>Visual observations</strong><ul class="next-actions">' + (aiVisualObservations || "<li>No visual observations returned.</li>") + '</ul></div><div class="ai-evidence-grid"><div><strong>Supporting evidence</strong><ul class="next-actions">' + (aiEvidence || "<li>No supporting evidence returned.</li>") + '</ul></div><div><strong>Negative evidence</strong><ul class="next-actions">' + (aiNegativeEvidence || "<li>No negative evidence returned.</li>") + '</ul></div></div><div class="ai-evidence-grid"><div><strong>Recommended actions</strong><ul class="next-actions">' + (aiActions || "<li>No recommended actions returned.</li>") + '</ul></div><div><strong>Needs more data</strong><ul class="next-actions">' + (aiNeedsMoreData || "<li>No extra data requested.</li>") + '</ul></div></div></div>'
    : '<div class="report-block ai-verdict pending"><strong>AI verdict</strong><p>' + (ai.status === "running" ? "AI investigation is running." : ai.status === "failed" ? "AI investigation failed: " + (ai.error ?? "unknown error") : "AI investigation has not been started for this incident.") + '</p></div>';
  runAiInvestigation.disabled = ai.status === "running" || !aiAgent.enabled;
  runAiInvestigation.title = aiAgent.enabled ? "Run AI root-cause investigation" : "AI agent backend is not configured";
  document.getElementById("tab-diagnosis").innerHTML =
    '<div class="report-block"><strong>Status</strong><p><span class="status-pill">' + incident.status + "</span> confidence " + formatValue((incident.confidence ?? 0) * 100) + "%</p></div>" +
    '<div class="report-block"><strong>Incident period</strong><p>' + formatClock(incident.started_at ?? incident.created_at) + " - " + formatClock(incident.resolved_at ?? incident.last_seen_at) + " - signals " + (incident.signal_count ?? 1) + " - fingerprint " + (incident.fingerprint ?? incident.type) + '</p></div>' +
    '<div class="report-block"><strong>Investigation process</strong><div class="investigation-header"><div><span class="status-pill">' + (investigation.state ?? "queued") + '</span><strong>' + (investigation.phase ?? "queued") + '</strong><p>' + (investigation.summary ?? "Waiting for incident evidence.") + '</p></div><div class="progress-ring" style="--progress:' + Math.max(0, Math.min(100, investigation.progress ?? 0)) + '%"><span>' + formatValue(investigation.progress ?? 0) + '%</span></div></div><ol class="investigation-list">' + investigationSteps + '</ol></div>' +
    aiBlock +
    visualEvidenceBlock +
    '<div class="report-block"><strong>Detector</strong><p>' + detector.name + " - engine: " + detector.engine + '</p></div>' +
    '<div class="report-block"><strong>Detected metric</strong><p>' + incident.metric + " = " + formatValue(incident.value) + " threshold " + formatValue(incident.threshold) + '</p></div>' +
    '<div class="report-block"><strong>Time window</strong><p>' + formatClock(incident.created_at) + " - " + formatClock(incident.last_seen_at) + " - samples " + incident.sample_count + '</p></div>' +
    '<div class="report-block"><strong>Detector interpretation</strong><p>' + incident.summary + '</p></div>' +
    '<div class="report-block"><strong>Signal timeline</strong><ol class="ops-list">' + (timeline || '<li><span>No signals captured yet.</span></li>') + '</ol></div>' +
    '<div class="report-block"><div class="report-block-head"><strong>DBA and maintenance context</strong>' + (allOps.length > 5 ? '<button id="toggleOps" type="button">' + (showAllOps ? 'Show latest 5' : 'Show all ' + allOps.length) + '</button>' : '') + '</div><ol class="ops-list">' + (relatedOps || '<li><span>No config reload, pg_settings change, or long VACUUM event near this incident yet.</span></li>') + '</ol>' + (!showAllOps && hiddenOpsCount ? '<p class="ops-summary">' + hiddenOpsCount + ' older events hidden.</p>' : '') + '</div>' +
    '<div class="report-block"><strong>Evidence</strong><table class="report-table"><thead><tr><th>Metric</th><th>Value</th><th>Comparator</th></tr></thead><tbody>' + evidenceRows + '</tbody></table></div>';
  const toggleOps = document.getElementById("toggleOps");
  if (toggleOps) {
    toggleOps.addEventListener("click", () => {
      showAllOps = !showAllOps;
      renderReport({ force: true });
    });
  }
  reportRenderedIncidentId = incident.id;
  reportRenderedVersion = version;
  if (!options.force && reportOpen) {
    drawer.scrollTop = previousScroll;
  }
  renderAiChat();
  loadAiChatHistory(incident.id);
}

function chatMessagesForIncident(id) {
  if (!chatMessagesByIncident[id]) chatMessagesByIncident[id] = [];
  return chatMessagesByIncident[id];
}

function appendChatMessage(incidentId, role, content, meta = "") {
  const messages = chatMessagesForIncident(incidentId);
  messages.push({ role, content, meta, t: Math.floor(Date.now() / 1000) });
  if (messages.length > 80) messages.splice(0, messages.length - 80);
}

async function loadAiChatHistory(incidentId) {
  if (chatHistoryLoaded.has(incidentId)) return;
  const incident = incidents.find((item) => item.id === incidentId);
  if (!incident?.ai_investigation?.chat_id) return;
  chatHistoryLoaded.add(incidentId);
  try {
    const response = await fetch(API_BASE + "/api/chats/" + encodeURIComponent(incidentId) + "/messages");
    if (!response.ok) return;
    const data = await response.json();
    if (!Array.isArray(data.messages) || !data.messages.length) return;
    if (chatMessagesForIncident(incidentId).length === 0) {
      chatMessagesByIncident[incidentId] = data.messages;
      renderAiChat({ stickToBottom: true });
    }
  } catch (error) {
    chatHistoryLoaded.delete(incidentId);
  }
}

function renderAiChat(options = {}) {
  const incident = selectedIncident();
  if (!incident) return;
  const messages = chatMessagesForIncident(incident.id);
  const nearBottom = aiChatMessages.scrollHeight - aiChatMessages.scrollTop - aiChatMessages.clientHeight < 48;
  const chatBusy = Boolean(activeChatAbort) && activeChatIncidentId === incident.id;
  aiChatStatus.textContent = aiAgent.enabled
    ? (chatBusy ? aiChatStatus.textContent : incident.ai_investigation?.status === "running" ? "AI investigation running" : "ready")
    : "not configured";
  sendAiChat.disabled = !aiAgent.enabled || chatBusy;
  aiChatInput.disabled = !aiAgent.enabled || chatBusy;
  aiChatMessages.innerHTML = messages.length
    ? messages.map((item) => '<div class="chat-message ' + item.role + '"><strong>' + escapeHtml(item.role) + '</strong><div class="chat-markdown">' + renderMarkdown(item.content) + '</div>' + (item.meta ? '<span>' + escapeHtml(item.meta) + '</span>' : '') + '</div>').join("")
    : '<div class="chat-empty">Start a scoped conversation about this incident or healthcheck.</div>';
  if (options.stickToBottom || nearBottom) {
    aiChatMessages.scrollTop = aiChatMessages.scrollHeight;
  }
}
async function loadIncident(id) {
  const response = await fetch(API_BASE + "/api/incidents/" + encodeURIComponent(id));
  if (!response.ok) return null;
  const data = await response.json();
  if (!data.incident) return null;
  return upsertIncident(data.incident);
}

function selectIncident(id, open) {
  if (selectedIncidentId !== id) showAllOps = false;
  userSelectedIncident = true;
  selectedIncidentId = id;
  renderStatus();
  renderChart();
  renderIncidents();
  renderReport({ force: true });
  loadIncident(id).then((incident) => {
    if (incident) {
      renderStatus();
      renderChart();
      renderIncidents();
      renderReport({ force: true });
    }
  });
  if (open) openDrawer();
}

function render() {
  if (dragStartX != null) return;
  renderStatus();
  renderChart();
  renderMetricsStrip();
  renderIncidents();
  renderExperiments();
  renderReport({ force: true });
}

function renderForEvent(type) {
  if (dragStartX != null) return;
  if (type === "telemetry") {
    renderStatus();
    renderChart();
    renderMetricsStrip();
    return;
  }
  if (type === "load") {
    renderStatus();
    return;
  }
  if (type === "detectors") {
    renderStatus();
    return;
  }
  if (type === "incident") {
    renderStatus();
    renderChart();
    renderIncidents();
    renderReport();
    return;
  }
  if (type === "signal" || type === "detection") {
    renderStatus();
    renderReport();
    return;
  }
  if (type === "experiment") {
    renderExperiments();
    return;
  }
  if (type === "operational_event") {
    renderReport();
    return;
  }
  render();
}

async function postJson(url, payload) {
  const response = await fetch(API_BASE + url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {})
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ message: response.statusText }));
    throw new Error(data.message);
  }
  return response.json();
}

async function streamAiChat(incidentId, message) {
  activeChatAbort = new AbortController();
  activeChatIncidentId = incidentId;
  sendAiChat.disabled = true;
  aiChatInput.disabled = true;
  aiChatStatus.textContent = "connecting";
  let assistantIndex = null;
  let buffer = "";
  let doneReceived = false;
  try {
    const response = await fetch(API_BASE + "/api/incidents/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: incidentId, message }),
      signal: activeChatAbort.signal,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({ message: response.statusText }));
      throw new Error(data.message);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const messages = chatMessagesForIncident(incidentId);
    messages.push({ role: "assistant", content: "", meta: "streaming", t: Math.floor(Date.now() / 1000) });
    assistantIndex = messages.length - 1;
    renderAiChat({ stickToBottom: true });
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const line = frame.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        const type = String(event.type ?? "");
        if (type === "chunk") {
          messages[assistantIndex].content += event.content ?? "";
          messages[assistantIndex].meta = "answering";
        } else if (type === "reasoning") {
          aiChatStatus.textContent = "reasoning";
        } else if (type === "tool_calls" || type === "tool_call_delta") {
          aiChatStatus.textContent = "calling MCP tools";
        } else if (type === "tool_results") {
          aiChatStatus.textContent = "reading tool results";
        } else if (type === "compact_started" || type === "compact") {
          aiChatStatus.textContent = "compacting context";
        } else if (type === "subagent_started" || type === "subagent_progress") {
          aiChatStatus.textContent = "subagent working";
        } else if (type === "done") {
          messages[assistantIndex].meta = "done";
          aiChatStatus.textContent = "ready";
          doneReceived = true;
          activeChatAbort = null;
          activeChatIncidentId = null;
          await reader.cancel().catch(() => {});
          renderAiChat();
          return;
        } else if (type === "error") {
          messages[assistantIndex].meta = "error";
          messages[assistantIndex].content += "\n" + (event.error ?? "stream error");
          aiChatStatus.textContent = "error";
          doneReceived = true;
          activeChatAbort = null;
          activeChatIncidentId = null;
          await reader.cancel().catch(() => {});
          renderAiChat();
          return;
        } else if (type === "cockpit_status") {
          aiChatStatus.textContent = "connected";
        }
        renderAiChat();
      }
    }
  } finally {
    activeChatAbort = null;
    activeChatIncidentId = null;
    if (!doneReceived && assistantIndex != null) {
      const messages = chatMessagesForIncident(incidentId);
      if (messages[assistantIndex]?.meta === "streaming" || messages[assistantIndex]?.meta === "answering") {
        messages[assistantIndex].meta = "done";
      }
    }
    renderAiChat();
  }
}

function openDrawer() {
  renderReport({ force: true });
  backdrop.hidden = false;
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  backdrop.hidden = true;
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
}

function openExperiments() {
  renderExperimentSettings();
  renderExperiments();
  experimentBackdrop.hidden = false;
  experimentDrawer.classList.add("open");
  experimentDrawer.setAttribute("aria-hidden", "false");
}

function closeExperiments() {
  experimentBackdrop.hidden = true;
  experimentDrawer.classList.remove("open");
  experimentDrawer.setAttribute("aria-hidden", "true");
}

function openBenchmark() {
  benchmarkBackdrop.hidden = false;
  benchmarkDrawer.classList.add("open");
  benchmarkDrawer.setAttribute("aria-hidden", "false");
}

function closeBenchmark() {
  benchmarkBackdrop.hidden = true;
  benchmarkDrawer.classList.remove("open");
  benchmarkDrawer.setAttribute("aria-hidden", "true");
}

function applyBenchmarkProfile() {
  const profile = benchmarkProfile.value;
  if (profile === "steady") {
    loadMode.value = "mixed";
    benchmarkScript.value = "default";
    loadClients.value = 24;
    loadJobs.value = 4;
    loadSeconds.value = 900;
    loadRate.value = 300;
  } else if (profile === "burst") {
    loadMode.value = "mixed";
    benchmarkScript.value = "default";
    loadClients.value = 96;
    loadJobs.value = 8;
    loadSeconds.value = 180;
    loadRate.value = 0;
  } else if (profile === "readonly") {
    loadMode.value = "readonly";
    benchmarkScript.value = "select_only";
    loadClients.value = 48;
    loadJobs.value = 6;
    loadSeconds.value = 600;
    loadRate.value = 500;
  } else if (profile === "planner") {
    loadMode.value = "readonly";
    benchmarkScript.value = "planner_range";
    loadClients.value = 16;
    loadJobs.value = 4;
    loadSeconds.value = 600;
    loadRate.value = 40;
  } else if (profile === "sort") {
    loadMode.value = "readonly";
    benchmarkScript.value = "sort_spill";
    loadClients.value = 8;
    loadJobs.value = 4;
    loadSeconds.value = 600;
    loadRate.value = 20;
  } else if (profile === "aggregate") {
    loadMode.value = "readonly";
    benchmarkScript.value = "aggregate_scan";
    loadClients.value = 8;
    loadJobs.value = 4;
    loadSeconds.value = 600;
    loadRate.value = 30;
  } else if (profile === "update") {
    loadMode.value = "mixed";
    benchmarkScript.value = "simple_update";
    loadClients.value = 32;
    loadJobs.value = 4;
    loadSeconds.value = 600;
    loadRate.value = 200;
  }
}

function benchmarkPayload() {
  return {
    engine: benchmarkEngine.value,
    profile: benchmarkProfile.value,
    script: benchmarkScript.value,
    clients: Number(loadClients.value),
    jobs: Number(loadJobs.value),
    seconds: Number(loadSeconds.value),
    rate: Number(loadRate.value),
    mode: loadMode.value
  };
}

async function startBenchmark() {
  startLoad.disabled = true;
  try {
    const data = await postJson("/api/load/start", benchmarkPayload());
    renderLoad(data.load);
  } catch (error) {
    statusSubtitle.textContent = error.message;
    startLoad.disabled = false;
  }
}

async function stopBenchmark() {
  try {
    const data = await postJson("/api/load/stop", {});
    renderLoad(data.load);
  } catch (error) {
    statusSubtitle.textContent = error.message;
  }
}

startLoad.addEventListener("click", async () => {
  await startBenchmark();
});

stopLoad.addEventListener("click", async () => {
  await stopBenchmark();
});

stopLoadFromDrawer.addEventListener("click", stopBenchmark);
openBenchmarkLab.addEventListener("click", openBenchmark);
closeBenchmarkLab.addEventListener("click", closeBenchmark);
benchmarkBackdrop.addEventListener("click", closeBenchmark);
benchmarkProfile.addEventListener("change", applyBenchmarkProfile);

detectorPicker.addEventListener("change", async () => {
  selectedDetectorId = detectorPicker.value;
  detectorPicker.disabled = true;
  try {
    const enabled = selectedDetectorId === "all" ? [] : [selectedDetectorId];
    const data = await postJson("/api/detectors", { enabled_detector_ids: enabled });
    detectorCatalog = data.detectors ?? detectorCatalog;
    selectedDetectorId = selectedDetectorFromCatalog();
    renderDetectorPicker();
    renderStatus();
  } catch (error) {
    statusSubtitle.textContent = error.message;
  } finally {
    detectorPicker.disabled = false;
  }
});

openExperimentLab.addEventListener("click", openExperiments);
closeExperimentLab.addEventListener("click", closeExperiments);
experimentBackdrop.addEventListener("click", closeExperiments);
experimentSetting.addEventListener("change", () => {
  experimentValue.value = experimentSettings[experimentSetting.value]?.risky ?? "";
});
applyExperiment.addEventListener("click", async () => {
  applyExperiment.disabled = true;
  try {
    const data = await postJson("/api/experiments/apply", {
      setting: experimentSetting.value,
      value: experimentValue.value
    });
    if (data.experiment) {
      upsertExperiment(data.experiment);
      renderExperiments();
    }
  } catch (error) {
    statusSubtitle.textContent = error.message;
  } finally {
    applyExperiment.disabled = false;
  }
});

statusActions.forEach((button) => {
  button.addEventListener("click", async () => {
    const incident = selectedIncident();
    if (!incident) return;
    const data = await postJson("/api/incidents/status", {
      id: incident.id,
      status: button.dataset.status
    });
    if (data.incident) {
      upsertIncident(data.incident);
      renderStatus();
      renderIncidents();
      renderReport({ force: true });
    }
  });
});

refreshIncident.addEventListener("click", async () => {
  const incident = selectedIncident();
  if (!incident) return;
  const updated = await loadIncident(incident.id);
  if (updated) {
    renderStatus();
    renderIncidents();
    renderReport({ force: true });
  }
});

aiChatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const incident = selectedIncident();
  const message = aiChatInput.value.trim();
  if (!incident || !message) return;
  if (!aiAgent.enabled) {
    aiChatStatus.textContent = "not configured";
    return;
  }
  appendChatMessage(incident.id, "user", message);
  aiChatInput.value = "";
  renderAiChat({ stickToBottom: true });
  try {
    await streamAiChat(incident.id, message);
  } catch (error) {
    appendChatMessage(incident.id, "assistant", error.message, "error");
    aiChatStatus.textContent = "error";
    renderAiChat();
  }
});

runAiInvestigation.addEventListener("click", async () => {
  const incident = selectedIncident();
  if (!incident) return;
  if (!aiAgent.enabled) {
    statusSubtitle.textContent = "AI agent backend is not configured.";
    return;
  }
  runAiInvestigation.disabled = true;
  try {
    statusSubtitle.textContent = "Capturing chart and starting AI investigation...";
    const chartImage = await captureChartImage();
    const capturedAt = Math.floor(Date.now() / 1000);
    if (chartImage) {
      upsertIncident({
        ...incident,
        image_attachments: [{
          type: "image_url",
          image_url: chartImage,
          detail: "high",
          source: "dashboard_chart",
          captured_at: capturedAt,
        }],
        visual_input_status: {
          requested: 1,
          accepted: 1,
          attached_to_agent_request: true,
          updated_at: capturedAt,
        },
      });
      renderReport({ force: true });
    } else {
      statusSubtitle.textContent = "Could not capture chart image; starting AI investigation with textual telemetry only.";
    }
    const payload = chartImage ? {
      id: incident.id,
      image_attachments: [{
        type: "image_url",
        image_url: chartImage,
        detail: "high",
        source: "dashboard_chart",
        captured_at: capturedAt,
      }],
    } : { id: incident.id };
    const data = await postJson("/api/incidents/ai", payload);
    if (data.incident) {
      upsertIncident(data.incident);
      selectIncident(data.incident.id, true);
      renderStatus();
      renderIncidents();
      renderReport({ force: true });
    }
  } catch (error) {
    statusSubtitle.textContent = error.message;
  } finally {
    runAiInvestigation.disabled = false;
  }
});

runAiHealthcheck.addEventListener("click", async () => {
  if (!aiAgent.enabled) {
    statusSubtitle.textContent = "AI agent backend is not configured.";
    return;
  }
  runAiHealthcheck.disabled = true;
  try {
    statusSubtitle.textContent = "Capturing chart and starting AI healthcheck...";
    const chartImage = await captureChartImage();
    const capturedAt = Math.floor(Date.now() / 1000);
    const payload = chartImage ? {
      image_attachments: [{
        type: "image_url",
        image_url: chartImage,
        detail: "high",
        source: "dashboard_chart",
        captured_at: capturedAt,
      }],
    } : {};
    const data = await postJson("/api/ai/healthcheck", payload);
    if (data.incident) {
      upsertIncident(data.incident);
      selectIncident(data.incident.id, true);
      statusSubtitle.textContent = "AI healthcheck started.";
    }
  } catch (error) {
    statusSubtitle.textContent = error.message;
  } finally {
    runAiHealthcheck.disabled = false;
  }
});

metricPicker.addEventListener("change", () => {
  selectedMetric = metricDefs.find((metric) => metric.key === metricPicker.value);
  renderChart();
});
windowPicker.addEventListener("change", () => {
  selectedWindow = windowPicker.value === "all" ? "all" : Number(windowPicker.value);
  zoomRange = null;
  renderChart();
});
resetZoom.addEventListener("click", () => {
  zoomRange = null;
  renderChart();
});
openReport.addEventListener("click", openDrawer);
closeReport.addEventListener("click", closeDrawer);
backdrop.addEventListener("click", closeDrawer);

renderMetricPicker();
render();

fetch(API_BASE + "/api/snapshot")
  .then((response) => response.json())
  .then(ingestSnapshot)
  .catch(() => {
    statusLabel.textContent = "Backend unavailable";
    statusSubtitle.textContent = "Start it with python tools/cockpit_backend.py.";
  });

const events = new EventSource(API_BASE + "/events");
events.onmessage = (message) => ingestEvent(JSON.parse(message.data));
events.onerror = () => {
  statusBand.classList.remove("state-ok", "state-warn", "state-bad");
  statusBand.classList.add("state-bad");
  statusLabel.textContent = "SSE disconnected";
  statusSubtitle.textContent = "Waiting for backend connection to recover.";
};

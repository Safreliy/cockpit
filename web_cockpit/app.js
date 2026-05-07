const data = window.COCKPIT_DATA;

const metricDefs = [
  { key: "payments_p95_ms", label: "Payments p95", unit: "ms", threshold: 500 },
  { key: "storage_read_latency_p95_ms", label: "Storage latency p95", unit: "ms" },
  { key: "short_query_wait_p95_ms", label: "Query wait p95", unit: "ms" },
  { key: "reporting_concurrency", label: "Reporting concurrency", unit: "sessions" },
  { key: "cpu_utilization_pct", label: "CPU utilization", unit: "%", threshold: 85 },
  { key: "network_loss_pct", label: "Network loss", unit: "%", threshold: 1 },
  { key: "replication_lag_sec", label: "Replication lag", unit: "s", threshold: 5 }
];

const stream = data.runtimeStream?.length ? data.runtimeStream : data.stream;
const incidents = data.incidents?.length
  ? data.incidents
  : [
      {
        id: "mvp-episode",
        title: data.episode.business_status,
        summary: data.episode.probable_cause + " via " + data.episode.mechanism,
        detection_at: data.episode.evidence.at(-1)?.started_at ?? 0,
        window_start: data.episode.evidence[0]?.started_at ?? 0,
        window_end: data.episode.evidence.at(-1)?.started_at ?? 0,
        impact_metric: data.episode.impact_metric ?? "payments_p95_ms",
        probable_cause: data.episode.probable_cause,
        mechanism: data.episode.mechanism,
        confidence: data.episode.confidence,
        recommended_action: data.episode.recommended_action,
        chain: data.episode.evidence.map((item) => ({
          role: item.metric === "payments_p95_ms" ? "Impact" : "Evidence",
          metric: item.metric,
          label: item.statement,
          time: item.started_at
        })),
        rejected_causes: data.episode.rejected_causes
      }
    ];

let currentIndex = 0;
let selectedMetric = metricDefs[0];
let selectedIncidentId = null;
let selectedHypothesisByIncident = {};
let playing = true;
let timer = null;

const statusBand = document.getElementById("statusBand");
const statusLabel = document.getElementById("statusLabel");
const statusSubtitle = document.getElementById("statusSubtitle");
const clock = document.getElementById("clock");
const flowName = document.getElementById("flowName");
const confidence = document.getElementById("confidence");
const openReport = document.getElementById("openReport");
const playPause = document.getElementById("playPause");
const resetStream = document.getElementById("resetStream");
const speed = document.getElementById("speed");
const chart = document.getElementById("liveChart");
const metricPicker = document.getElementById("metricPicker");
const metricsStrip = document.getElementById("metricsStrip");
const detectionSteps = document.getElementById("detectionSteps");
const causalChain = document.getElementById("causalChain");
const drawer = document.getElementById("reportDrawer");
const backdrop = document.getElementById("drawerBackdrop");
const closeReport = document.getElementById("closeReport");

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return String(minutes).padStart(2, "0") + ":" + String(rest).padStart(2, "0");
}

function formatValue(value) {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function scale(value, min, max, outMin, outMax) {
  if (max === min) return (outMin + outMax) / 2;
  return outMin + ((value - min) * (outMax - outMin)) / (max - min);
}

function currentPoint() {
  return stream[currentIndex];
}

function currentTime() {
  return currentPoint().t;
}

function visibleIncidents() {
  return incidents.filter((incident) => incident.detection_at <= currentTime());
}

function selectedIncident() {
  if (selectedIncidentId) {
    return incidents.find((incident) => incident.id === selectedIncidentId) ?? null;
  }
  return visibleIncidents().at(-1) ?? null;
}

function selectedHypothesis(incident) {
  if (!incident) return null;
  const selectedCause = selectedHypothesisByIncident[incident.id] ?? incident.probable_cause;
  return incident.hypotheses.find((item) => item.cause === selectedCause) ?? incident.hypotheses[0];
}

function chainForHypothesis(incident, hypothesis) {
  if (!incident || !hypothesis) return [];
  if (hypothesis.cause === incident.probable_cause) return incident.chain;
  const impact = incident.chain[0];
  const evidence = hypothesis.matched_signals.map((metric) => {
    const source = incident.chain.find((item) => item.metric === metric);
    return {
      role: source?.role ?? "Evidence",
      metric,
      label: source?.label ?? "supporting signal moved",
      time: source?.time ?? incident.detection_at
    };
  });
  return [
    impact,
    ...evidence.reverse(),
    {
      role: "Candidate cause",
      metric: hypothesis.cause,
      label: hypothesis.cause,
      time: evidence.at(-1)?.time ?? incident.detection_at
    }
  ];
}

function detectionState() {
  const selected = selectedIncident();
  if (selected) return "bad";
  const next = incidents.find((incident) => incident.window_start <= currentTime() && incident.detection_at > currentTime());
  if (next) return "warn";
  return "ok";
}

function updateStatus() {
  const state = detectionState();
  const selected = selectedIncident();
  statusBand.classList.remove("state-ok", "state-warn", "state-bad");
  statusBand.classList.add("state-" + state);
  clock.textContent = formatTime(currentTime());
  flowName.textContent = "payments";

  if (state === "ok") {
    statusLabel.textContent = "Healthy telemetry stream";
    statusSubtitle.textContent = "No business-impact anomaly has been detected.";
    confidence.textContent = "--";
    openReport.disabled = true;
  } else if (state === "warn") {
    statusLabel.textContent = "Investigation window";
    statusSubtitle.textContent = "Related signals are moving; waiting for an impact anomaly before forming a causal episode.";
    confidence.textContent = "collecting";
    openReport.disabled = true;
  } else {
    statusLabel.textContent = selected.title;
    statusSubtitle.textContent = selected.summary;
    confidence.textContent = Math.round(selected.confidence * 100) + "%";
    openReport.disabled = false;
  }
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

function renderChart() {
  const width = 860;
  const height = 320;
  const margin = { left: 52, right: 20, top: 24, bottom: 38 };
  const visible = stream.slice(0, currentIndex + 1);
  const allValues = stream.map((point) => point[selectedMetric.key]);
  const threshold = selectedMetric.threshold;
  const min = Math.min(...allValues, threshold ?? Infinity);
  const max = Math.max(...allValues, threshold ?? -Infinity);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.12;
  const x1 = margin.left;
  const x2 = width - margin.right;
  const y1 = height - margin.bottom;
  const y2 = margin.top;
  const maxT = stream.at(-1).t;

  const points = visible
    .map((point) => {
      const x = scale(point.t, 0, maxT, x1, x2);
      const y = scale(point[selectedMetric.key], yMin, yMax, y1, y2);
      return x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");

  const selected = selectedIncident();
  const cursorX = scale(currentTime(), 0, maxT, x1, x2);
  const cursorY = scale(currentPoint()[selectedMetric.key], yMin, yMax, y1, y2);
  const thresholdY = threshold == null ? "" : '<line class="threshold" x1="' + x1 + '" x2="' + x2 + '" y1="' + scale(threshold, yMin, yMax, y1, y2) + '" y2="' + scale(threshold, yMin, yMax, y1, y2) + '"></line>';
  const selectedBand =
    selected == null
      ? ""
      : '<rect class="incident-band" x="' +
        scale(selected.window_start, 0, maxT, x1, x2) +
        '" y="' +
        y2 +
        '" width="' +
        Math.max(4, scale(selected.window_end, 0, maxT, x1, x2) - scale(selected.window_start, 0, maxT, x1, x2)) +
        '" height="' +
        (y1 - y2) +
        '"></rect>';

  const incidentMarkers = visibleIncidents()
    .map((incident, index) => {
      const x = scale(incident.detection_at, 0, maxT, x1, x2);
      const point = stream.find((candidate) => candidate.t === incident.detection_at) ?? currentPoint();
      const y = scale(point[selectedMetric.key], yMin, yMax, y1, y2);
      const active = selected?.id === incident.id ? " selected" : "";
      const labelY = y2 + 15 + (index % 3) * 15;
      return (
        '<g class="incident-marker' +
        active +
        '" data-incident-id="' +
        incident.id +
        '" tabindex="0" role="button" aria-label="' +
        incident.title +
        '">' +
        '<line class="anomaly-line" x1="' +
        x +
        '" x2="' +
        x +
        '" y1="' +
        y2 +
        '" y2="' +
        y1 +
        '"></line>' +
        '<circle class="anomaly-dot" cx="' +
        x +
        '" cy="' +
        y +
        '" r="7"></circle>' +
        '<circle class="anomaly-hit" cx="' +
        x +
        '" cy="' +
        y +
        '" r="18"></circle>' +
        '<text class="anomaly-label" x="' +
        Math.min(x + 9, x2 - 165) +
        '" y="' +
        labelY +
        '">' +
        incident.title +
        "</text></g>"
      );
    })
    .join("");

  chart.innerHTML =
    '<rect width="' +
    width +
    '" height="' +
    height +
    '" fill="#fff"></rect>' +
    selectedBand +
    '<line class="grid-line" x1="' +
    x1 +
    '" x2="' +
    x2 +
    '" y1="' +
    y2 +
    '" y2="' +
    y2 +
    '"></line>' +
    '<line class="grid-line" x1="' +
    x1 +
    '" x2="' +
    x2 +
    '" y1="' +
    (y1 + y2) / 2 +
    '" y2="' +
    (y1 + y2) / 2 +
    '"></line>' +
    '<line class="axis" x1="' +
    x1 +
    '" x2="' +
    x2 +
    '" y1="' +
    y1 +
    '" y2="' +
    y1 +
    '"></line>' +
    '<line class="axis" x1="' +
    x1 +
    '" x2="' +
    x1 +
    '" y1="' +
    y1 +
    '" y2="' +
    y2 +
    '"></line>' +
    thresholdY +
    '<polyline class="series" points="' +
    points +
    '"></polyline>' +
    incidentMarkers +
    '<line class="cursor" x1="' +
    cursorX +
    '" x2="' +
    cursorX +
    '" y1="' +
    y2 +
    '" y2="' +
    y1 +
    '"></line>' +
    '<circle class="cursor-dot" cx="' +
    cursorX +
    '" cy="' +
    cursorY +
    '" r="5"></circle>' +
    '<text x="' +
    x1 +
    '" y="18" fill="#17202a" font-size="13" font-weight="700">' +
    selectedMetric.label +
    ": " +
    formatValue(currentPoint()[selectedMetric.key]) +
    " " +
    selectedMetric.unit +
    '</text>' +
    '<text x="8" y="' +
    (y2 + 4) +
    '" fill="#607080" font-size="12">' +
    formatValue(yMax) +
    '</text>' +
    '<text x="8" y="' +
    y1 +
    '" fill="#607080" font-size="12">' +
    formatValue(yMin) +
    '</text>' +
    '<text x="' +
    x1 +
    '" y="' +
    (height - 10) +
    '" fill="#607080" font-size="12">00:00</text>' +
    '<text x="' +
    (x2 - 45) +
    '" y="' +
    (height - 10) +
    '" fill="#607080" font-size="12">120:00</text>';

  chart.querySelectorAll(".incident-marker").forEach((marker) => {
    marker.addEventListener("click", () => selectIncident(marker.dataset.incidentId, true));
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIncident(marker.dataset.incidentId, true);
      }
    });
  });
}

function renderCausalChain() {
  const incident = selectedIncident();
  causalChain.innerHTML = "";
  if (!incident) {
    const empty = document.createElement("div");
    empty.className = "chain-empty";
    empty.textContent = "No causal chain yet. The cockpit starts from a detected impact anomaly, then searches upstream signals.";
    causalChain.appendChild(empty);
    return;
  }

  const hypothesis = selectedHypothesis(incident);
  const chain = chainForHypothesis(incident, hypothesis);
  chain.forEach((item) => {
    const div = document.createElement("div");
    div.className = "chain-step done" + (hypothesis.cause !== incident.probable_cause ? " preview" : "");
    div.innerHTML =
      "<span>" +
      item.role +
      "</span>" +
      "<strong>" +
      item.label +
      "</strong>" +
      "<small>" +
      formatTime(item.time) +
      " - " +
      item.metric +
      "</small>";
    causalChain.appendChild(div);
  });
}

function renderDetectionSteps() {
  detectionSteps.innerHTML = "";
  const detected = visibleIncidents().slice().sort((left, right) => right.detection_at - left.detection_at);
  if (!detected.length) {
    const empty = document.createElement("li");
    empty.className = "step empty";
    empty.innerHTML = "<strong>No detections yet</strong><span>Impact anomalies will appear here as the stream crosses detection thresholds.</span>";
    detectionSteps.appendChild(empty);
    return;
  }
  detected.forEach((incident) => {
    const selected = selectedIncidentId === incident.id;
    const li = document.createElement("li");
    li.className = "step done" + (selected ? " selected" : "");
    li.setAttribute("role", "button");
    li.setAttribute("tabindex", "0");
    li.innerHTML =
      "<strong>" +
      incident.title +
      "</strong><span>" +
      "detected at " +
      formatTime(incident.detection_at) +
      " - " +
      incident.probable_cause +
      "</span>";
    li.addEventListener("click", () => selectIncident(incident.id, true));
    li.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIncident(incident.id, true);
      }
    });
    detectionSteps.appendChild(li);
  });
}

function renderMetricsStrip() {
  const primary = ["payments_p95_ms", "storage_read_latency_p95_ms", "short_query_wait_p95_ms", "network_loss_pct"];
  const point = currentPoint();
  metricsStrip.innerHTML = "";
  primary.forEach((key) => {
    const def = metricDefs.find((metric) => metric.key === key);
    const card = document.createElement("div");
    const alert = def.threshold != null && point[key] >= def.threshold;
    card.className = "metric-card" + (alert ? " alert" : "");
    card.innerHTML = "<span>" + def.label + "</span><strong>" + formatValue(point[key]) + " " + def.unit + "</strong>";
    metricsStrip.appendChild(card);
  });
}

function renderReport() {
  const incident = selectedIncident();
  if (!incident) return;
  document.getElementById("reportTitle").textContent = incident.title;
  const hypothesis = selectedHypothesis(incident);
  document.getElementById("tab-diagnosis").innerHTML =
    '<div class="report-block"><strong>Detected anomaly</strong><p>' +
    incident.impact_metric +
    " at " +
    formatTime(incident.detection_at) +
    '</p></div>' +
    '<div class="report-block"><strong>Probable cause</strong><p>' +
    incident.probable_cause +
    '</p></div>' +
    '<div class="report-block"><strong>Selected hypothesis preview</strong><p>' +
    hypothesis.cause +
    " (" +
    Math.round(hypothesis.confidence * 100) +
    "%)</p></div>" +
    '<div class="report-block"><strong>Mechanism</strong><p>' +
    hypothesis.mechanism +
    '</p></div>' +
    '<div class="report-block"><strong>Recommended action</strong><p>' +
    incident.recommended_action +
    "</p></div>";

  document.getElementById("tab-hypotheses").innerHTML =
    '<div class="hypothesis-list">' +
    incident.hypotheses
      .map((item, index) => {
        const selected = item.cause === hypothesis.cause ? " selected" : "";
        const primary = item.cause === incident.probable_cause ? " primary" : "";
        return (
          '<div class="hypothesis' +
          selected +
          primary +
          '" data-hypothesis-cause="' +
          item.cause +
          '" role="button" tabindex="0"><div class="hypothesis-head"><strong>' +
          (index + 1) +
          ". " +
          item.cause +
          "</strong><span>" +
          Math.round(item.confidence * 100) +
          "%</span></div><p>" +
          item.reason +
          "</p></div>"
        );
      })
      .join("") +
    "</div>";
  document.querySelectorAll(".hypothesis").forEach((item) => {
    item.addEventListener("click", () => selectHypothesis(incident.id, item.dataset.hypothesisCause));
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectHypothesis(incident.id, item.dataset.hypothesisCause);
      }
    });
  });

  const chain = chainForHypothesis(incident, hypothesis);
  document.getElementById("tab-evidence").innerHTML =
    '<table class="report-table"><thead><tr><th>Direction</th><th>Signal</th><th>Time</th><th>Evidence</th></tr></thead><tbody>' +
    chain
      .map((item) => "<tr><td>" + item.role + "</td><td>" + item.metric + "</td><td>" + formatTime(item.time) + "</td><td>" + item.label + "</td></tr>")
      .join("") +
    "</tbody></table>";

  document.getElementById("tab-rejected").innerHTML = incident.rejected_causes
    .map((item) => '<div class="report-block"><strong>' + item.cause + '</strong><p>' + item.reason + '</p></div>')
    .join("");
}

function selectIncident(id, open) {
  selectedIncidentId = id;
  const incident = selectedIncident();
  selectedHypothesisByIncident[incident.id] = selectedHypothesisByIncident[incident.id] ?? incident.probable_cause;
  selectedMetric = metricDefs.find((metric) => metric.key === incident.impact_metric) ?? selectedMetric;
  metricPicker.value = selectedMetric.key;
  render();
  if (open) openDrawer();
}

function selectHypothesis(incidentId, cause) {
  selectedHypothesisByIncident[incidentId] = cause;
  render();
}

function render() {
  updateStatus();
  renderChart();
  renderCausalChain();
  renderDetectionSteps();
  renderMetricsStrip();
  renderReport();
}

function schedule() {
  clearInterval(timer);
  if (!playing) return;
  timer = setInterval(() => {
    currentIndex = Math.min(currentIndex + 1, stream.length - 1);
    if (currentIndex === stream.length - 1) {
      playing = false;
      playPause.textContent = "Play";
      clearInterval(timer);
    }
    render();
  }, Number(speed.value));
}

function openDrawer() {
  renderReport();
  backdrop.hidden = false;
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  backdrop.hidden = true;
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
}

metricPicker.addEventListener("change", () => {
  selectedMetric = metricDefs.find((metric) => metric.key === metricPicker.value);
  renderChart();
});

playPause.addEventListener("click", () => {
  playing = !playing;
  playPause.textContent = playing ? "Pause" : "Play";
  schedule();
});

resetStream.addEventListener("click", () => {
  currentIndex = 0;
  selectedIncidentId = null;
  selectedHypothesisByIncident = {};
  playing = true;
  playPause.textContent = "Pause";
  render();
  schedule();
});

speed.addEventListener("change", schedule);
openReport.addEventListener("click", openDrawer);
closeReport.addEventListener("click", closeDrawer);
backdrop.addEventListener("click", closeDrawer);

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
  });
});

if (!stream.length) {
  statusLabel.textContent = "No telemetry data";
  statusSubtitle.textContent = "Run python run.py to generate web_cockpit/data.js.";
  playPause.disabled = true;
  resetStream.disabled = true;
  openReport.disabled = true;
} else {
  renderMetricPicker();
  render();
  schedule();
}

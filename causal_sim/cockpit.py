from __future__ import annotations

from dataclasses import asdict
from html import escape
import json
from pathlib import Path
from string import Template

from causal_sim.models import CausalEpisode, TelemetryPoint


def render_cockpit(episode: CausalEpisode, path: str | Path, telemetry: list[TelemetryPoint] | None = None) -> None:
    evidence = "\n".join(
        f"<tr><td>{escape(item['metric'])}</td><td>{item['started_at']}s</td><td>{item['baseline']}</td><td>{item['observed']}</td><td>{escape(item['statement'])}</td></tr>"
        for item in episode.evidence
    )
    rejected = "\n".join(
        f"<li><span>{escape(item['cause'])}</span><small>{escape(item['reason'])}</small></li>" for item in episode.rejected_causes
    )
    telemetry_payload = json.dumps(
        [{"t": point.t, **point.metrics} for point in telemetry or []],
        separators=(",", ":"),
    )
    episode_payload = json.dumps(asdict(episode), separators=(",", ":"))
    body = Template("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Cockpit Mock</title>
  <style>
    :root { color-scheme: light; --bg: #f3f5f8; --panel: #ffffff; --line: #d8dee8; --ink: #17202a; --muted: #607080; --danger: #a12a2a; --blue: #2364aa; --green: #18705f; --amber: #9a6100; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: var(--bg); color: var(--ink); }
    main { max-width: 1280px; margin: 0 auto; padding: 24px; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }
    h1 { margin: 0 0 6px; font-size: 28px; line-height: 1.15; }
    h2 { margin: 0 0 12px; font-size: 16px; }
    p { margin: 0; color: var(--muted); line-height: 1.45; }
    section, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
    .grid { display: grid; grid-template-columns: 1.1fr .9fr; gap: 16px; margin-bottom: 16px; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
    .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 92px; }
    .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    .value { margin-top: 8px; font-size: 21px; font-weight: 700; overflow-wrap: anywhere; }
    .danger { color: var(--danger); }
    .confidence { color: var(--green); }
    code { background: #eef2f7; padding: 2px 5px; border-radius: 4px; }
    .chain { display: grid; grid-template-columns: repeat(5, minmax(110px, 1fr)); gap: 8px; align-items: stretch; }
    .chain div { border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 8px; padding: 10px; background: #fbfcfe; }
    .chain small { display: block; color: var(--muted); margin-bottom: 5px; }
    .chart-wrap { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; align-items: stretch; }
    .metric-list { display: grid; gap: 8px; align-content: start; }
    button.metric { width: 100%; text-align: left; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 10px; color: var(--ink); cursor: pointer; }
    button.metric.active { border-color: var(--blue); box-shadow: inset 3px 0 0 var(--blue); background: #f7fbff; }
    .chart-panel { min-height: 380px; position: relative; }
    svg { width: 100%; height: 330px; display: block; }
    .axis { stroke: #c7d0dc; stroke-width: 1; }
    .series { fill: none; stroke: var(--blue); stroke-width: 3; }
    .threshold { stroke: var(--amber); stroke-width: 1.5; stroke-dasharray: 5 5; }
    .point { fill: var(--blue); opacity: 0; }
    .hover-line { stroke: #596a7d; stroke-width: 1; stroke-dasharray: 3 4; opacity: 0; }
    .tooltip { position: absolute; pointer-events: none; background: #17202a; color: #fff; border-radius: 6px; padding: 8px 10px; font-size: 12px; transform: translate(10px, -100%); opacity: 0; min-width: 145px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 9px 8px; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    ul.rejected { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; }
    ul.rejected li { border: 1px solid var(--line); border-radius: 8px; padding: 10px; }
    ul.rejected span { display: block; font-weight: 700; margin-bottom: 5px; }
    ul.rejected small { color: var(--muted); line-height: 1.35; }
    .stack { display: grid; gap: 16px; }
    @media (max-width: 900px) { main { padding: 16px; } header, .grid, .chart-wrap { grid-template-columns: 1fr; display: grid; } .stats, ul.rejected { grid-template-columns: 1fr; } .chain { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>AI Cockpit</h1>
      <p>Causal episode view for PostgreSQL operational telemetry.</p>
    </div>
    <p><code>heavy_reporting_on_primary</code></p>
  </header>

  <div class="stats">
    <div class="stat"><div class="label">Business Health</div><div class="value danger">$business_status</div></div>
    <div class="stat"><div class="label">Impacted Flow</div><div class="value">$impacted_flow</div></div>
    <div class="stat"><div class="label">Diagnosis</div><div class="value">$probable_cause</div></div>
    <div class="stat"><div class="label">Confidence</div><div class="value confidence">$confidence</div></div>
  </div>

  <div class="grid">
    <section>
      <h2>Causal Chain</h2>
      <div class="chain">
        <div><small>Cause</small>$probable_cause</div>
        <div><small>Mechanism</small>$mechanism</div>
        <div><small>State</small>storage latency up</div>
        <div><small>Symptom</small>query wait up</div>
        <div><small>Impact</small>$business_status</div>
      </div>
    </section>
    <section>
      <h2>Recommended Action</h2>
      <p>$recommended_action</p>
      <p><strong>Cost:</strong> $action_cost</p>
    </section>
  </div>

  <section class="stack">
    <div>
      <h2>Telemetry Explorer</h2>
      <p>Hover the plot to inspect values. Select a metric to switch the chart.</p>
    </div>
    <div class="chart-wrap">
      <div class="metric-list" id="metricList"></div>
      <div class="chart-panel">
        <svg id="chart" viewBox="0 0 900 330" role="img" aria-label="Telemetry chart"></svg>
        <div class="tooltip" id="tooltip"></div>
      </div>
    </div>
  </section>

  <div class="grid">
    <section>
      <h2>Evidence</h2>
      <table>
        <thead><tr><th>Metric</th><th>Start</th><th>Baseline</th><th>Observed</th><th>Statement</th></tr></thead>
        <tbody>$evidence</tbody>
      </table>
    </section>
    <section>
      <h2>Rejected Causes</h2>
      <ul class="rejected">$rejected</ul>
    </section>
  </div>
</main>
<script>
const telemetry = $telemetry_payload;
const episode = $episode_payload;
const metrics = [
  { key: "payments_p95_ms", label: "Payments p95", unit: "ms", threshold: 500 },
  { key: "storage_read_latency_p95_ms", label: "Storage read latency p95", unit: "ms" },
  { key: "short_query_wait_p95_ms", label: "Short query wait p95", unit: "ms" },
  { key: "reporting_concurrency", label: "Reporting concurrency", unit: "sessions" },
  { key: "cpu_utilization_pct", label: "CPU utilization", unit: "%" },
  { key: "network_loss_pct", label: "Network loss", unit: "%" },
  { key: "replication_lag_sec", label: "Replication lag", unit: "s" }
];
let selectedMetric = metrics[0];
const chart = document.getElementById("chart");
const tooltip = document.getElementById("tooltip");
const metricList = document.getElementById("metricList");

function fmt(value) {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function scale(value, min, max, outMin, outMax) {
  if (max === min) return (outMin + outMax) / 2;
  return outMin + ((value - min) * (outMax - outMin)) / (max - min);
}

function renderButtons() {
  metricList.innerHTML = "";
  metrics.forEach(metric => {
    const button = document.createElement("button");
    button.className = "metric" + (metric.key === selectedMetric.key ? " active" : "");
    button.type = "button";
    const latest = telemetry[telemetry.length - 1][metric.key];
    button.innerHTML = `<strong>$${metric.label}</strong><br><small>$${fmt(latest)} $${metric.unit}</small>`;
    button.addEventListener("click", () => {
      selectedMetric = metric;
      renderButtons();
      renderChart();
    });
    metricList.appendChild(button);
  });
}

function renderChart() {
  const width = 900;
  const height = 330;
  const margin = { left: 54, right: 24, top: 24, bottom: 42 };
  const values = telemetry.map(point => point[selectedMetric.key]);
  const times = telemetry.map(point => point.t);
  const min = Math.min(...values, selectedMetric.threshold ?? Infinity);
  const max = Math.max(...values, selectedMetric.threshold ?? -Infinity);
  const yMin = min - (max - min || 1) * 0.08;
  const yMax = max + (max - min || 1) * 0.12;
  const x1 = margin.left;
  const x2 = width - margin.right;
  const y1 = height - margin.bottom;
  const y2 = margin.top;
  const points = telemetry.map(point => {
    const x = scale(point.t, times[0], times[times.length - 1], x1, x2);
    const y = scale(point[selectedMetric.key], yMin, yMax, y1, y2);
    return `$${x.toFixed(1)},$${y.toFixed(1)}`;
  }).join(" ");
  const thresholdY = selectedMetric.threshold == null ? "" : `<line class="threshold" x1="$${x1}" x2="$${x2}" y1="$${scale(selectedMetric.threshold, yMin, yMax, y1, y2)}" y2="$${scale(selectedMetric.threshold, yMin, yMax, y1, y2)}"></line><text x="$${x2 - 90}" y="$${scale(selectedMetric.threshold, yMin, yMax, y1, y2) - 7}" fill="#9a6100" font-size="12">SLO $${selectedMetric.threshold}</text>`;
  chart.innerHTML = `
    <rect x="0" y="0" width="$${width}" height="$${height}" fill="#fff"></rect>
    <line class="axis" x1="$${x1}" x2="$${x2}" y1="$${y1}" y2="$${y1}"></line>
    <line class="axis" x1="$${x1}" x2="$${x1}" y1="$${y1}" y2="$${y2}"></line>
    $${thresholdY}
    <polyline class="series" points="$${points}"></polyline>
    <line class="hover-line" id="hoverLine" x1="$${x1}" x2="$${x1}" y1="$${y2}" y2="$${y1}"></line>
    <circle class="point" id="hoverPoint" cx="$${x1}" cy="$${y1}" r="5"></circle>
    <text x="$${x1}" y="18" fill="#17202a" font-size="14" font-weight="700">$${selectedMetric.label}</text>
    <text x="$${x1}" y="$${height - 10}" fill="#607080" font-size="12">0 min</text>
    <text x="$${x2 - 44}" y="$${height - 10}" fill="#607080" font-size="12">30 min</text>
    <text x="8" y="$${y2 + 4}" fill="#607080" font-size="12">$${fmt(yMax)}</text>
    <text x="8" y="$${y1}" fill="#607080" font-size="12">$${fmt(yMin)}</text>
    <rect id="hitArea" x="$${x1}" y="$${y2}" width="$${x2 - x1}" height="$${y1 - y2}" fill="transparent"></rect>
  `;
  const line = document.getElementById("hoverLine");
  const dot = document.getElementById("hoverPoint");
  const hitArea = document.getElementById("hitArea");
  hitArea.addEventListener("mousemove", event => {
    const rect = chart.getBoundingClientRect();
    const cursorX = (event.clientX - rect.left) * (width / rect.width);
    const ratio = Math.max(0, Math.min(1, (cursorX - x1) / (x2 - x1)));
    const idx = Math.round(ratio * (telemetry.length - 1));
    const point = telemetry[idx];
    const x = scale(point.t, times[0], times[times.length - 1], x1, x2);
    const y = scale(point[selectedMetric.key], yMin, yMax, y1, y2);
    line.setAttribute("x1", x);
    line.setAttribute("x2", x);
    line.style.opacity = "1";
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", y);
    dot.style.opacity = "1";
    tooltip.style.opacity = "1";
    tooltip.style.left = `$${event.offsetX}px`;
    tooltip.style.top = `$${event.offsetY}px`;
    tooltip.innerHTML = `<strong>$${Math.round(point.t / 60)}:$${String(point.t % 60).padStart(2, "0")}</strong><br>$${selectedMetric.label}: $${fmt(point[selectedMetric.key])} $${selectedMetric.unit}`;
  });
  hitArea.addEventListener("mouseleave", () => {
    line.style.opacity = "0";
    dot.style.opacity = "0";
    tooltip.style.opacity = "0";
  });
}

renderButtons();
renderChart();
</script>
</body>
</html>
""").substitute(
        business_status=escape(episode.business_status),
        impacted_flow=escape(episode.impacted_flow),
        probable_cause=escape(episode.probable_cause),
        confidence=f"{episode.confidence:.0%}",
        mechanism=escape(episode.mechanism),
        recommended_action=escape(episode.recommended_action),
        action_cost=escape(episode.action_cost),
        evidence=evidence,
        rejected=rejected,
        telemetry_payload=telemetry_payload,
        episode_payload=episode_payload,
    )
    Path(path).write_text(body, encoding="utf-8")

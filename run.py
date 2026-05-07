from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from causal_sim.anomaly import detect_anomalies, negative_evidence
from causal_sim.causal_graph import build_causal_graph
from causal_sim.cockpit import render_cockpit
from causal_sim.episode import build_episode
from causal_sim.plotting import save_line_chart
from causal_sim.propagation import propagate
from causal_sim.scenario import load_scenario
from causal_sim.telemetry import generate_telemetry
from causal_sim.validation import validate_episode
from causal_sim.web_cockpit import export_web_cockpit_data


ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    template = load_scenario(ROOT / "scenarios" / "heavy_reporting_on_primary.yaml")
    graph = build_causal_graph(template)
    telemetry = generate_telemetry(propagate(template, graph))
    anomalies = detect_anomalies(telemetry)
    episode = build_episode(template, anomalies, negative_evidence(telemetry))
    validation = validate_episode(template, episode)

    fieldnames = ["t", *telemetry[0].metrics.keys()]
    with (OUTPUT / "timeseries.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for point in telemetry:
            writer.writerow({"t": point.t, **point.metrics})

    (OUTPUT / "episode.json").write_text(json.dumps(asdict(episode), indent=2), encoding="utf-8")
    (OUTPUT / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    render_cockpit(episode, OUTPUT / "cockpit_mock.html", telemetry)
    export_web_cockpit_data(telemetry, anomalies, episode, validation, ROOT / "web_cockpit" / "data.js")

    chart_map = {
        "payments_p95_ms": "timeseries_payments_p95.png",
        "storage_read_latency_p95_ms": "timeseries_storage_latency.png",
        "short_query_wait_p95_ms": "timeseries_short_query_wait.png",
        "reporting_concurrency": "timeseries_reporting_concurrency.png",
    }
    for metric, filename in chart_map.items():
        save_line_chart(telemetry, metric, OUTPUT / filename)

    print(f"MVP run complete. validation_passed={validation['passed']} output={OUTPUT} web={ROOT / 'web_cockpit' / 'index.html'}")


if __name__ == "__main__":
    main()

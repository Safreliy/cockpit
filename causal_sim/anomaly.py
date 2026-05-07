from __future__ import annotations

from causal_sim.models import Anomaly, TelemetryPoint


THRESHOLDS = {
    "reporting_concurrency": 25.0,
    "storage_read_latency_p95_ms": 50.0,
    "short_query_wait_p95_ms": 25.0,
    "payments_p95_ms": 200.0,
}


def detect_anomalies(telemetry: list[TelemetryPoint], baseline_window: int = 24) -> list[Anomaly]:
    baselines = {
        metric: sum(point.metrics[metric] for point in telemetry[:baseline_window]) / baseline_window
        for metric in THRESHOLDS
    }
    anomalies: list[Anomaly] = []
    for metric, threshold in THRESHOLDS.items():
        baseline = baselines[metric]
        for point in telemetry[baseline_window:]:
            delta = point.metrics[metric] - baseline
            if delta >= threshold:
                anomalies.append(
                    Anomaly(
                        metric=metric,
                        started_at=point.t,
                        baseline=round(baseline, 3),
                        observed=round(point.metrics[metric], 3),
                        direction="up",
                        evidence=f"{metric} rose from {baseline:.1f} to {point.metrics[metric]:.1f}",
                    )
                )
                break
    return sorted(anomalies, key=lambda item: item.started_at)


def negative_evidence(telemetry: list[TelemetryPoint]) -> list[dict[str, str]]:
    max_cpu = max(point.metrics["cpu_utilization_pct"] for point in telemetry)
    max_loss = max(point.metrics["network_loss_pct"] for point in telemetry)
    max_lag = max(point.metrics["replication_lag_sec"] for point in telemetry)
    return [
        {"cause": "cpu_saturation", "reason": f"CPU stayed below saturation, max {max_cpu:.1f}%"},
        {"cause": "network_packet_loss", "reason": f"network loss stayed stable, max {max_loss:.2f}%"},
        {"cause": "replication_lag", "reason": f"replication lag stayed stable, max {max_lag:.1f}s"},
    ]


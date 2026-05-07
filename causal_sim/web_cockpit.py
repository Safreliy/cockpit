from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from causal_sim.models import Anomaly, CausalEpisode, TelemetryPoint
from causal_sim.runtime_diagnosis import diagnose_runtime


def _pulse(t: int, start: int, rise: int, hold: int, fall: int, amplitude: float) -> float:
    if t < start:
        return 0.0
    if t < start + rise:
        return amplitude * (t - start) / rise
    if t < start + rise + hold:
        return amplitude
    if t < start + rise + hold + fall:
        elapsed = t - start - rise - hold
        return amplitude * (1 - elapsed / fall)
    return 0.0


def _build_long_runtime(telemetry: list[TelemetryPoint]) -> list[dict[str, float]]:
    base = telemetry[0].metrics
    stream: list[dict[str, float]] = []
    for t in range(0, 7201, 10):
        reporting = base["reporting_concurrency"] + _pulse(t, 610, 140, 620, 260, 62)
        storage = base["storage_read_latency_p95_ms"] + _pulse(t, 760, 160, 560, 280, 142)
        query_wait = base["short_query_wait_p95_ms"]
        query_wait += _pulse(t, 880, 170, 500, 250, 82)
        query_wait += _pulse(t, 4940, 130, 420, 260, 78)
        payments = base["payments_p95_ms"]
        payments += _pulse(t, 960, 170, 430, 260, 390)
        payments += _pulse(t, 2880, 130, 300, 260, 350)
        payments += _pulse(t, 5020, 140, 430, 280, 330)
        cpu = base["cpu_utilization_pct"] + _pulse(t, 4880, 120, 520, 320, 50)
        network = base["network_loss_pct"] + _pulse(t, 2820, 80, 310, 220, 3.2)
        lag = base["replication_lag_sec"] + _pulse(t, 5800, 180, 280, 300, 8)

        stream.append(
            {
                "t": float(t),
                "reporting_concurrency": round(reporting, 3),
                "storage_read_latency_p95_ms": round(storage, 3),
                "short_query_wait_p95_ms": round(query_wait, 3),
                "payments_p95_ms": round(payments, 3),
                "cpu_utilization_pct": round(cpu, 3),
                "network_loss_pct": round(network, 3),
                "replication_lag_sec": round(lag, 3),
            }
        )
    return stream


def export_web_cockpit_data(
    telemetry: list[TelemetryPoint],
    anomalies: list[Anomaly],
    episode: CausalEpisode,
    validation: dict[str, object],
    path: str | Path,
) -> None:
    runtime_stream = _build_long_runtime(telemetry)
    incidents = diagnose_runtime(runtime_stream)
    payload = {
        "stream": [{"t": point.t, **point.metrics} for point in telemetry],
        "anomalies": [asdict(item) for item in anomalies],
        "episode": asdict(episode),
        "validation": validation,
        "runtimeStream": runtime_stream,
        "incidents": incidents,
    }
    body = "window.COCKPIT_DATA = "
    body += json.dumps(payload, indent=2)
    body += ";\n"
    Path(path).write_text(body, encoding="utf-8")

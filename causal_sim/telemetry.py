from __future__ import annotations

from causal_sim.models import TelemetryPoint


def generate_telemetry(states: list[dict[str, float]]) -> list[TelemetryPoint]:
    telemetry: list[TelemetryPoint] = []
    for state in states:
        t = int(state["t"])
        metrics = {key: value for key, value in state.items() if key != "t"}
        events: list[str] = []
        logs: list[str] = []
        if t == 300:
            events.append("reporting_workload_started_on_primary")
            logs.append("analytics job opened high read concurrency on primary")
        if state["payments_p95_ms"] > 500:
            events.append("payments_slo_violation")
        telemetry.append(TelemetryPoint(t=t, metrics=metrics, events=events, logs=logs))
    return telemetry


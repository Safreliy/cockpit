from __future__ import annotations

from causal_sim.models import CausalGraph, CauseTemplate

METRIC_AMPLITUDES = {
    "reporting_concurrency": 60.0,
    "storage_read_latency_p95_ms": 145.0,
    "short_query_wait_p95_ms": 82.0,
    "payments_p95_ms": 380.0,
}

METRIC_RAMP_SECONDS = {
    "reporting_concurrency": 120,
    "storage_read_latency_p95_ms": 180,
    "short_query_wait_p95_ms": 180,
    "payments_p95_ms": 180,
}


def _ramp(elapsed: int, ramp_seconds: int = 180) -> float:
    if elapsed <= 0:
        return 0.0
    return min(1.0, elapsed / ramp_seconds)


def activation_times(graph: CausalGraph, cause_start_seconds: int = 300) -> dict[str, int]:
    starts: dict[str, int] = {"cause": cause_start_seconds}
    unresolved = list(graph.edges)
    while unresolved:
        progressed = False
        remaining = []
        for edge in unresolved:
            if edge.source not in starts:
                remaining.append(edge)
                continue
            candidate = starts[edge.source] + edge.delay_seconds
            starts[edge.target] = min(starts.get(edge.target, candidate), candidate)
            progressed = True
        if not progressed:
            raise ValueError("causal graph contains unreachable or cyclic edges")
        unresolved = remaining
    return starts


def metric_activation_times(graph: CausalGraph, cause_start_seconds: int = 300) -> dict[str, int]:
    starts = activation_times(graph, cause_start_seconds)
    return {node.metric: starts[node.id] for node in graph.nodes if node.metric and node.id in starts}


def propagate(template: CauseTemplate, graph: CausalGraph, duration_seconds: int = 1800, step_seconds: int = 10) -> list[dict[str, float]]:
    base = template.metrics
    starts = metric_activation_times(graph)

    states: list[dict[str, float]] = []
    for t in range(0, duration_seconds + step_seconds, step_seconds):
        metrics = dict(base)
        for metric, amplitude in METRIC_AMPLITUDES.items():
            started_at = starts.get(metric)
            if started_at is None:
                continue
            metrics[metric] = base[metric] + amplitude * _ramp(t - started_at, METRIC_RAMP_SECONDS.get(metric, 180))

        states.append(
            {
                "t": float(t),
                "reporting_concurrency": round(metrics["reporting_concurrency"], 3),
                "storage_read_latency_p95_ms": round(metrics["storage_read_latency_p95_ms"], 3),
                "short_query_wait_p95_ms": round(metrics["short_query_wait_p95_ms"], 3),
                "payments_p95_ms": round(metrics["payments_p95_ms"], 3),
                "cpu_utilization_pct": round(base["cpu_utilization_pct"] + 2.0 * _ramp(t - starts.get("reporting_concurrency", 300)), 3),
                "network_loss_pct": metrics["network_loss_pct"],
                "replication_lag_sec": metrics["replication_lag_sec"],
            }
        )
    return states

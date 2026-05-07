from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SignalChange:
    metric: str
    started_at: int
    baseline: float
    observed: float
    delta: float


CAUSES: dict[str, dict[str, Any]] = {
    "heavy_reporting_on_primary": {
        "title": "Payments latency degradation",
        "mechanism": "storage_read_contention",
        "signals": ["reporting_concurrency", "storage_read_latency_p95_ms", "short_query_wait_p95_ms"],
        "summary": "Payments p95 crossed SLO after correlated growth in reporting concurrency, storage latency, and query wait.",
        "action": "Move reporting workload to a read replica or throttle it until payments p95 returns below SLO.",
    },
    "client_db_packet_loss": {
        "title": "Payments transport instability",
        "mechanism": "transport_retries",
        "signals": ["network_loss_pct"],
        "summary": "Payments p95 degraded while network loss increased before the impact.",
        "action": "Route payment traffic away from the impaired client network segment and verify packet loss recovery.",
    },
    "cpu_saturation_on_primary": {
        "title": "CPU-bound query latency",
        "mechanism": "executor_cpu_queueing",
        "signals": ["cpu_utilization_pct", "short_query_wait_p95_ms"],
        "summary": "Payments p95 degraded after CPU utilization and query wait rose.",
        "action": "Reduce expensive query concurrency or scale CPU capacity on the primary node.",
    },
    "replication_lag": {
        "title": "Replication lag impact",
        "mechanism": "stale_read_or_failover_pressure",
        "signals": ["replication_lag_sec"],
        "summary": "Payments p95 degraded while replication lag increased.",
        "action": "Inspect replica health and replication apply throughput before routing reads back.",
    },
}

METRIC_LABELS = {
    "payments_p95_ms": "payments p95 exceeded SLO",
    "reporting_concurrency": "reporting workload increased",
    "storage_read_latency_p95_ms": "storage read latency increased",
    "short_query_wait_p95_ms": "short query wait increased",
    "network_loss_pct": "packet loss increased",
    "cpu_utilization_pct": "CPU utilization increased",
    "replication_lag_sec": "replication lag increased",
}

CHANGE_THRESHOLDS = {
    "reporting_concurrency": 20.0,
    "storage_read_latency_p95_ms": 45.0,
    "short_query_wait_p95_ms": 25.0,
    "network_loss_pct": 0.6,
    "cpu_utilization_pct": 25.0,
    "replication_lag_sec": 4.0,
}


def diagnose_runtime(stream: list[dict[str, float]], slo_ms: float = 500.0) -> list[dict[str, Any]]:
    detections = _impact_detections(stream, slo_ms)
    incidents: list[dict[str, Any]] = []
    for index, detected_at in enumerate(detections, start=1):
        window_start = max(0, detected_at - 420)
        window_end = min(int(stream[-1]["t"]), detected_at + 300)
        changes = _signal_changes(stream, window_start, detected_at)
        hypotheses = _rank_hypotheses(changes)
        selected = hypotheses[0]
        selected_cause = selected["cause"]
        cause_def = CAUSES[selected_cause]
        chain = _build_chain(selected_cause, changes, detected_at)
        rejected = [
            {"cause": item["cause"], "reason": item["reason"]}
            for item in hypotheses[1:]
            if item["score"] < selected["score"]
        ]
        incidents.append(
            {
                "id": _incident_id(selected_cause, index),
                "title": cause_def["title"],
                "summary": cause_def["summary"],
                "detection_at": detected_at,
                "window_start": window_start,
                "window_end": window_end,
                "impact_metric": "payments_p95_ms",
                "probable_cause": selected_cause,
                "mechanism": cause_def["mechanism"],
                "confidence": selected["confidence"],
                "recommended_action": cause_def["action"],
                "chain": chain,
                "hypotheses": hypotheses,
                "rejected_causes": rejected,
            }
        )
    return incidents


def _impact_detections(stream: list[dict[str, float]], slo_ms: float) -> list[int]:
    detections: list[int] = []
    in_incident = False
    last_detection = -10_000
    for point in stream:
        t = int(point["t"])
        value = point["payments_p95_ms"]
        if value >= slo_ms and not in_incident and t - last_detection > 360:
            detections.append(t)
            last_detection = t
            in_incident = True
        elif value < slo_ms * 0.9:
            in_incident = False
    return detections


def _points_between(stream: list[dict[str, float]], start: int, end: int) -> list[dict[str, float]]:
    return [point for point in stream if start <= point["t"] <= end]


def _avg(points: list[dict[str, float]], metric: str) -> float:
    if not points:
        return 0.0
    return sum(point[metric] for point in points) / len(points)


def _signal_changes(stream: list[dict[str, float]], window_start: int, detected_at: int) -> dict[str, SignalChange]:
    baseline_start = max(0, window_start - 420)
    baseline_end = max(0, window_start - 10)
    baseline_points = _points_between(stream, baseline_start, baseline_end)
    window_points = _points_between(stream, window_start, detected_at)
    changes: dict[str, SignalChange] = {}
    for metric, threshold in CHANGE_THRESHOLDS.items():
        baseline = _avg(baseline_points, metric)
        observed = max((point[metric] for point in window_points), default=baseline)
        delta = observed - baseline
        if delta < threshold:
            continue
        started_at = _first_change_time(window_points, metric, baseline, threshold * 0.55)
        changes[metric] = SignalChange(
            metric=metric,
            started_at=started_at,
            baseline=round(baseline, 3),
            observed=round(observed, 3),
            delta=round(delta, 3),
        )
    return changes


def _first_change_time(points: list[dict[str, float]], metric: str, baseline: float, threshold: float) -> int:
    for point in points:
        if point[metric] - baseline >= threshold:
            return int(point["t"])
    return int(points[0]["t"]) if points else 0


def _rank_hypotheses(changes: dict[str, SignalChange]) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    for cause, definition in CAUSES.items():
        expected = definition["signals"]
        present = [metric for metric in expected if metric in changes]
        missing = [metric for metric in expected if metric not in changes]
        competing = _competing_signal_penalty(cause, changes)
        order_bonus = _time_order_bonus(present, changes)
        score = len(present) * 25 - len(missing) * 10 - competing + order_bonus
        score = max(0, score)
        confidence = min(0.96, round(0.35 + score / 100, 2))
        reason = _hypothesis_reason(cause, present, missing, competing)
        hypotheses.append(
            {
                "cause": cause,
                "mechanism": definition["mechanism"],
                "score": score,
                "confidence": confidence,
                "matched_signals": present,
                "missing_signals": missing,
                "reason": reason,
            }
        )
    return sorted(hypotheses, key=lambda item: item["score"], reverse=True)


def _competing_signal_penalty(cause: str, changes: dict[str, SignalChange]) -> int:
    penalty = 0
    if cause != "client_db_packet_loss" and "network_loss_pct" in changes:
        penalty += 28
    if cause != "cpu_saturation_on_primary" and "cpu_utilization_pct" in changes:
        penalty += 24
    if cause != "heavy_reporting_on_primary" and "reporting_concurrency" in changes and "storage_read_latency_p95_ms" in changes:
        penalty += 24
    if cause != "replication_lag" and "replication_lag_sec" in changes:
        penalty += 14
    return penalty


def _time_order_bonus(metrics: list[str], changes: dict[str, SignalChange]) -> int:
    if len(metrics) < 2:
        return 4 if metrics else 0
    times = [changes[metric].started_at for metric in metrics]
    return 8 if times == sorted(times) else -8


def _hypothesis_reason(cause: str, present: list[str], missing: list[str], competing: int) -> str:
    if not present:
        return f"Rejected: no expected signals for {cause} moved before impact."
    reason = "Matched " + ", ".join(present)
    if missing:
        reason += "; missing " + ", ".join(missing)
    if competing:
        reason += f"; competing evidence penalty {competing}"
    return reason + "."


def _build_chain(cause: str, changes: dict[str, SignalChange], detected_at: int) -> list[dict[str, Any]]:
    chain = [
        {"role": "Impact", "metric": "payments_p95_ms", "label": METRIC_LABELS["payments_p95_ms"], "time": detected_at}
    ]
    for metric in reversed(CAUSES[cause]["signals"]):
        change = changes.get(metric)
        if change is None:
            continue
        role = _role_for_metric(metric)
        chain.append(
            {
                "role": role,
                "metric": metric,
                "label": METRIC_LABELS[metric],
                "time": change.started_at,
                "baseline": change.baseline,
                "observed": change.observed,
            }
        )
    chain.append(
        {
            "role": "Probable cause",
            "metric": cause,
            "label": cause,
            "time": min((item["time"] for item in chain[1:]), default=detected_at),
        }
    )
    return chain


def _role_for_metric(metric: str) -> str:
    if metric in {"short_query_wait_p95_ms", "network_loss_pct"}:
        return "Symptom"
    if metric in {"storage_read_latency_p95_ms", "cpu_utilization_pct", "replication_lag_sec"}:
        return "State"
    return "Signal"


def _incident_id(cause: str, index: int) -> str:
    suffix = {
        "heavy_reporting_on_primary": "reporting-payments",
        "client_db_packet_loss": "network-payments",
        "cpu_saturation_on_primary": "cpu-checkout",
        "replication_lag": "replication-payments",
    }[cause]
    return f"inc-{suffix}-{index:03d}"

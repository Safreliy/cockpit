from __future__ import annotations

from typing import Any


HYPOTHESIS_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "high_concurrency": [
        {
            "cause": "pgbench_or_application_load_spike",
            "base_score": 0.32,
            "why": "Active sessions crossed the concurrency threshold while workload throughput is elevated.",
            "factors": [
                {"metric": "active_connections", "threshold": 24, "weight": 0.28, "direction": ">="},
                {"metric": "xact_rate", "threshold": 50, "weight": 0.18, "direction": ">="},
                {"metric": "waiting_connections", "threshold": 2, "weight": 0.08, "direction": ">="},
            ],
        },
        {
            "cause": "connection_pool_misconfiguration",
            "base_score": 0.24,
            "why": "High active count can come from missing pool limits or bursty client pools.",
            "factors": [
                {"metric": "active_connections", "threshold": 32, "weight": 0.28, "direction": ">="},
                {"metric": "waiting_connections", "threshold": 1, "weight": 0.12, "direction": ">="},
            ],
        },
    ],
    "wait_contention": [
        {
            "cause": "lock_contention_or_slow_queries",
            "base_score": 0.34,
            "why": "Waiting sessions appeared; lock waits and slow query pressure are the first checks.",
            "factors": [
                {"metric": "waiting_connections", "threshold": 2, "weight": 0.34, "direction": ">="},
                {"metric": "active_connections", "threshold": 16, "weight": 0.12, "direction": ">="},
                {"metric": "xact_rate", "threshold": 50, "weight": 0.08, "direction": ">="},
            ],
        },
        {
            "cause": "downstream_resource_saturation",
            "base_score": 0.22,
            "why": "Waits can be amplified by IO pressure or saturated database workers.",
            "factors": [
                {"metric": "waiting_connections", "threshold": 2, "weight": 0.24, "direction": ">="},
                {"metric": "blk_read_time_ms_rate", "threshold": 50, "weight": 0.24, "direction": ">="},
                {"metric": "vacuum_max_elapsed_seconds", "threshold": 30, "weight": 0.12, "direction": ">="},
            ],
        },
    ],
    "read_io_pressure": [
        {
            "cause": "storage_or_cache_pressure",
            "base_score": 0.3,
            "why": "Read timing rose together with database IO counters.",
            "factors": [
                {"metric": "blk_read_time_ms_rate", "threshold": 50, "weight": 0.34, "direction": ">="},
                {"metric": "read_blocks_rate", "threshold": 20, "weight": 0.18, "direction": ">="},
                {"metric": "cache_hit_rate", "threshold": 100, "weight": 0.08, "direction": "<="},
            ],
        },
        {
            "cause": "working_set_shift",
            "base_score": 0.2,
            "why": "A larger working set can reduce cache locality and increase physical reads.",
            "factors": [
                {"metric": "read_blocks_rate", "threshold": 20, "weight": 0.28, "direction": ">="},
                {"metric": "blk_read_time_ms_rate", "threshold": 50, "weight": 0.18, "direction": ">="},
            ],
        },
    ],
    "vacuum_pressure": [
        {
            "cause": "manual_vacuum_or_autovacuum_overlap",
            "base_score": 0.32,
            "why": "VACUUM is active during the incident window and can compete for IO, locks, and buffer cache.",
            "factors": [
                {"metric": "vacuum_max_elapsed_seconds", "threshold": 30, "weight": 0.34, "direction": ">="},
                {"metric": "active_vacuum_sessions", "threshold": 1, "weight": 0.12, "direction": ">="},
                {"metric": "active_autovacuum_sessions", "threshold": 1, "weight": 0.12, "direction": ">="},
            ],
        },
        {
            "cause": "maintenance_window_misconfiguration",
            "base_score": 0.22,
            "why": "Maintenance work appears during foreground workload; check DBA operations and autovacuum settings.",
            "factors": [
                {"metric": "vacuum_max_elapsed_seconds", "threshold": 30, "weight": 0.22, "direction": ">="},
                {"metric": "active_connections", "threshold": 16, "weight": 0.14, "direction": ">="},
                {"metric": "xact_rate", "threshold": 50, "weight": 0.12, "direction": ">="},
            ],
        },
    ],
    "throughput_rise": [
        {
            "cause": "workload_start_or_traffic_surge",
            "base_score": 0.34,
            "why": "Transaction throughput rose sharply compared with the recent baseline.",
            "factors": [
                {"metric": "xact_rate", "threshold": 50, "weight": 0.26, "direction": ">="},
                {"metric": "active_connections", "threshold": 8, "weight": 0.16, "direction": ">="},
                {"metric": "waiting_connections", "threshold": 2, "weight": 0.06, "direction": ">="},
            ],
        },
        {
            "cause": "batch_job_or_benchmark_started",
            "base_score": 0.24,
            "why": "A sudden throughput rise often maps to a benchmark, batch job, or application traffic burst.",
            "factors": [
                {"metric": "xact_rate", "threshold": 80, "weight": 0.24, "direction": ">="},
                {"metric": "active_connections", "threshold": 8, "weight": 0.16, "direction": ">="},
            ],
        },
    ],
    "throughput_drop": [
        {
            "cause": "workload_stopped_or_client_backoff",
            "base_score": 0.36,
            "why": "Transaction throughput fell sharply compared with the recent baseline.",
            "factors": [
                {"metric": "xact_rate", "threshold": 10, "weight": 0.24, "direction": "<="},
                {"metric": "active_connections", "threshold": 4, "weight": 0.12, "direction": "<="},
            ],
        },
        {
            "cause": "resource_contention_or_blocking",
            "base_score": 0.24,
            "why": "A throughput drop can also be caused by waits, IO pressure, locks, or maintenance work.",
            "factors": [
                {"metric": "waiting_connections", "threshold": 2, "weight": 0.22, "direction": ">="},
                {"metric": "blk_read_time_ms_rate", "threshold": 50, "weight": 0.18, "direction": ">="},
                {"metric": "vacuum_max_elapsed_seconds", "threshold": 30, "weight": 0.16, "direction": ">="},
            ],
        },
    ],
    "ml_suspicious_activity": [
        {
            "cause": "compound_workload_or_resource_shift",
            "base_score": 0.2,
            "why": "Several weak signals jointly look suspicious even when a single threshold is not decisive.",
            "factors": [
                {"metric": "ml_anomaly_score", "threshold": 0.6, "weight": 0.3, "direction": ">="},
                {"metric": "workload_transition", "threshold": 0.6, "weight": 0.2, "direction": ">="},
                {"metric": "throughput_drop", "threshold": 0.5, "weight": 0.12, "direction": ">="},
                {"metric": "throughput_rise", "threshold": 0.5, "weight": 0.12, "direction": ">="},
            ],
        },
        {
            "cause": "dba_or_maintenance_induced_degradation",
            "base_score": 0.16,
            "why": "Maintenance and IO features contribute to the anomaly score when they move with workload signals.",
            "factors": [
                {"metric": "vacuum_pressure", "threshold": 0.6, "weight": 0.22, "direction": ">="},
                {"metric": "io_pressure", "threshold": 0.6, "weight": 0.22, "direction": ">="},
                {"metric": "wait_pressure", "threshold": 0.6, "weight": 0.14, "direction": ">="},
            ],
        },
    ],
}


DEFAULT_HYPOTHESES = HYPOTHESIS_TEMPLATES["read_io_pressure"]


def clamp(value: float, low: float = 0.0, high: float = 0.98) -> float:
    return max(low, min(high, value))


def metric_value(metric: str, signal: dict[str, Any], point: dict[str, float]) -> float:
    if metric == signal.get("metric"):
        return float(signal.get("value", 0) or 0)
    if metric == "ml_anomaly_score" and signal.get("metric") == "ml_anomaly_score":
        return float(signal.get("value", 0) or 0)
    if metric in point:
        return float(point.get(metric, 0) or 0)
    for item in signal.get("evidence", []):
        if item.get("metric") == metric:
            return float(item.get("value", 0) or 0)
    return 0.0


def factor_strength(value: float, threshold: float, direction: str) -> float:
    if threshold <= 0:
        return 0.0
    if direction == "<=":
        if value > threshold:
            return 0.0
        return clamp(1 - value / threshold)
    if value < threshold:
        return 0.0
    return clamp(value / threshold, high=1.0)


def score_hypothesis(template: dict[str, Any], signal: dict[str, Any], point: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
    score = float(template["base_score"])
    contributions: list[dict[str, Any]] = []
    for factor in template.get("factors", []):
        value = metric_value(str(factor["metric"]), signal, point)
        threshold = float(factor["threshold"])
        direction = str(factor.get("direction", ">="))
        strength = factor_strength(value, threshold, direction)
        weight = float(factor["weight"])
        contribution = round(weight * strength, 3)
        score += contribution
        contributions.append(
            {
                "metric": factor["metric"],
                "value": round(value, 3),
                "threshold": threshold,
                "direction": direction,
                "weight": weight,
                "contribution": contribution,
            }
        )
    return round(clamp(score), 2), contributions


def build_hypotheses(signal: dict[str, Any], point: dict[str, float]) -> list[dict[str, Any]]:
    templates = HYPOTHESIS_TEMPLATES.get(str(signal.get("type")), DEFAULT_HYPOTHESES)
    hypotheses = []
    for template in templates:
        score, factors = score_hypothesis(template, signal, point)
        hypotheses.append(
            {
                "cause": template["cause"],
                "score": score,
                "why": template["why"],
                "score_basis": {
                    "base_score": template["base_score"],
                    "factors": factors,
                },
            }
        )
    return sorted(hypotheses, key=lambda item: item["score"], reverse=True)

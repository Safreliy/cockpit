from __future__ import annotations

from typing import Any, Protocol


SIGNAL_CONTRACT = "SuspiciousSignal.v1"


RULE_DETECTORS: list[dict[str, Any]] = [
    {
        "id": "rules.postgres.high_concurrency.v1",
        "name": "High concurrency detector",
        "type": "high_concurrency",
        "metric": "active_connections",
        "operator": ">=",
        "threshold": 24,
        "recover_threshold": 18,
        "confirmations": 2,
        "recovery_samples": 3,
        "cooldown_seconds": 120,
        "severity": "warning",
        "summary": "Active database concurrency is elevated.",
        "candidate_root": "workload_concurrency_spike",
    },
    {
        "id": "rules.postgres.wait_contention.v1",
        "name": "Wait contention detector",
        "type": "wait_contention",
        "metric": "waiting_connections",
        "operator": ">=",
        "threshold": 2,
        "recover_threshold": 0,
        "confirmations": 2,
        "recovery_samples": 3,
        "cooldown_seconds": 120,
        "severity": "warning",
        "summary": "Postgres sessions are waiting; inspect locks, IO, and concurrent workload.",
        "candidate_root": "lock_or_resource_contention",
    },
    {
        "id": "rules.postgres.read_io_pressure.v1",
        "name": "Read IO pressure detector",
        "type": "read_io_pressure",
        "metric": "blk_read_time_ms_rate",
        "operator": ">=",
        "threshold": 50,
        "recover_threshold": 20,
        "confirmations": 2,
        "recovery_samples": 3,
        "cooldown_seconds": 180,
        "severity": "critical",
        "summary": "Block read time is rising; possible storage pressure.",
        "candidate_root": "storage_read_pressure",
    },
    {
        "id": "rules.postgres.vacuum_pressure.v1",
        "name": "Vacuum pressure detector",
        "type": "vacuum_pressure",
        "metric": "vacuum_max_elapsed_seconds",
        "operator": ">=",
        "threshold": 30,
        "recover_threshold": 5,
        "confirmations": 1,
        "recovery_samples": 3,
        "cooldown_seconds": 120,
        "severity": "warning",
        "summary": "A long-running VACUUM is active and may be competing for IO or locks.",
        "candidate_root": "manual_or_autovacuum_resource_pressure",
    },
]


class SignalDetector(Protocol):
    def describe(self) -> dict[str, Any]:
        ...

    def detect(self, point: dict[str, float], history: list[dict[str, float]]) -> list[dict[str, Any]]:
        ...


def detection_confidence(value: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.5
    ratio = value / threshold
    return round(min(0.98, max(0.55, 0.55 + (ratio - 1) * 0.22)), 2)


def signal_score(value: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.5
    return round(min(1.0, max(0.1, value / threshold)), 2)


def signal_fingerprint(signal_type: str, entity: str = "postgres:cockpit") -> str:
    return f"{entity}:{signal_type}"


def detector_meta(detector_id: str, name: str, engine: str, detector_type: str) -> dict[str, Any]:
    return {
        "id": detector_id,
        "name": name,
        "engine": engine,
        "type": detector_type,
        "signal_contract": SIGNAL_CONTRACT,
    }


def build_hypotheses(signal: dict[str, Any], point: dict[str, float]) -> list[dict[str, Any]]:
    kind = signal["type"]
    active = point.get("active_connections", 0)
    waiting = point.get("waiting_connections", 0)
    read_time = point.get("blk_read_time_ms_rate", 0)
    read_blocks = point.get("read_blocks_rate", 0)
    vacuum_elapsed = point.get("vacuum_max_elapsed_seconds", 0)
    vacuum_sessions = point.get("active_vacuum_sessions", 0) + point.get("active_autovacuum_sessions", 0)
    if kind == "high_concurrency":
        return [
            {"cause": "pgbench_or_application_load_spike", "score": 0.72 if active >= 24 else 0.45, "why": "Active sessions crossed the concurrency threshold while the load generator may be running."},
            {"cause": "connection_pool_misconfiguration", "score": 0.43, "why": "High active count can also come from missing pool limits or bursty client pools."},
        ]
    if kind == "wait_contention":
        return [
            {"cause": "lock_contention_or_slow_queries", "score": 0.76 if waiting >= 2 else 0.4, "why": "Waiting sessions appeared; lock waits and slow query pressure are the first checks."},
            {"cause": "downstream_resource_saturation", "score": 0.58 if read_time >= 50 else 0.34, "why": "Waits can be amplified by IO pressure or saturated database workers."},
        ]
    if kind == "vacuum_pressure":
        return [
            {"cause": "manual_vacuum_or_autovacuum_overlap", "score": 0.8 if vacuum_elapsed >= 30 else 0.42, "why": "VACUUM is active during the incident window and can compete for IO, locks, and buffer cache."},
            {"cause": "maintenance_window_misconfiguration", "score": 0.58 if vacuum_sessions > 0 else 0.25, "why": "Maintenance work appears during foreground workload; check DBA operations and autovacuum settings."},
        ]
    return [
        {"cause": "storage_or_cache_pressure", "score": 0.78 if read_time >= 50 else 0.4, "why": "Read timing rose together with database IO counters."},
        {"cause": "working_set_shift", "score": 0.49 if read_blocks > 0 else 0.28, "why": "A larger working set can reduce cache locality and increase physical reads."},
    ]


def build_causal_chain(signal: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"stage": "symptom", "label": signal["metric"], "detail": f"{signal['value']} >= {signal['threshold']}"},
        {"stage": "candidate cause", "label": signal["candidate_root"], "detail": "ranked from current evidence"},
        {"stage": "impact", "label": signal["type"], "detail": signal["summary"]},
    ]


def build_investigation(signal: dict[str, Any], sample_count: int = 1) -> dict[str, Any]:
    progress = min(88, 18 + sample_count * 12)
    if sample_count <= 1:
        phase = "collecting_evidence"
        summary = "Collecting telemetry around the anomaly window."
    elif sample_count <= 3:
        phase = "ranking_hypotheses"
        summary = "Ranking competing root-cause hypotheses from current evidence."
    else:
        phase = "awaiting_feedback"
        summary = "Causal explanation is ready for operator review."
    return {
        "state": "running" if phase != "awaiting_feedback" else "needs_review",
        "phase": phase,
        "progress": progress,
        "engine": {"mode": "hybrid inference", "current": "rules, graph scoring, and ML suspicious-activity scoring"},
        "summary": summary,
        "started_at": signal["t"],
        "updated_at": signal["t"],
        "steps": [
            {"id": "capture_window", "label": "Capture anomaly window", "status": "done", "detail": f"{signal['metric']} crossed {signal['threshold']}."},
            {"id": "collect_evidence", "label": "Collect supporting and negative evidence", "status": "running" if sample_count <= 1 else "done", "detail": "Read active sessions, waits, IO timing, throughput, and contextual counters."},
            {"id": "rank_hypotheses", "label": "Run causal inference", "status": "pending" if sample_count <= 1 else "running" if sample_count <= 3 else "done", "detail": "Rank hypotheses from detector signals, graph context, and current evidence."},
            {"id": "operator_review", "label": "Wait for operator review", "status": "pending" if sample_count <= 3 else "running", "detail": "Confirm, reject, or enrich the proposed explanation."},
        ],
        "next_actions": [
            "Open related query fingerprints.",
            "Compare baseline versus incident window.",
            "Collect lock/wait-event breakdown before final root-cause confirmation.",
        ],
    }


def enrich_signal(signal: dict[str, Any], point: dict[str, float]) -> dict[str, Any]:
    signal["hypotheses"] = signal.get("hypotheses") or build_hypotheses(signal, point)
    signal["causal_chain"] = signal.get("causal_chain") or build_causal_chain(signal)
    return signal


class RuleThresholdDetector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def describe(self) -> dict[str, Any]:
        return detector_meta(self.config["id"], self.config["name"], "rules", self.config["type"])

    def detect(self, point: dict[str, float], history: list[dict[str, float]]) -> list[dict[str, Any]]:
        detector = self.config
        value = point.get(detector["metric"], 0)
        threshold = detector["threshold"]
        if value < threshold:
            return []
        signal = {
            "id": f"sig-{detector['type']}-{int(point['t'])}",
            "t": int(point["t"]),
            "type": detector["type"],
            "fingerprint": signal_fingerprint(detector["type"]),
            "severity": detector["severity"],
            "metric": detector["metric"],
            "value": value,
            "threshold": threshold,
            "recover_threshold": detector["recover_threshold"],
            "confirmations": detector["confirmations"],
            "recovery_samples": detector["recovery_samples"],
            "cooldown_seconds": detector["cooldown_seconds"],
            "summary": detector["summary"],
            "candidate_root": detector["candidate_root"],
            "confidence": detection_confidence(value, threshold),
            "score": signal_score(value, threshold),
            "source": "threshold_detector",
            "detector": self.describe(),
            "evidence": [
                {"metric": detector["metric"], "value": value, "threshold": threshold, "direction": detector["operator"]},
                {"metric": "active_connections", "value": point.get("active_connections", 0), "role": "context"},
                {"metric": "waiting_connections", "value": point.get("waiting_connections", 0), "role": "context"},
                {"metric": "blk_read_time_ms_rate", "value": point.get("blk_read_time_ms_rate", 0), "role": "context"},
                {"metric": "active_vacuum_sessions", "value": point.get("active_vacuum_sessions", 0), "role": "operational_context"},
                {"metric": "active_autovacuum_sessions", "value": point.get("active_autovacuum_sessions", 0), "role": "operational_context"},
                {"metric": "vacuum_max_elapsed_seconds", "value": point.get("vacuum_max_elapsed_seconds", 0), "role": "operational_context"},
                {"metric": "config_reload_time", "value": point.get("config_reload_time", 0), "role": "operational_context"},
            ],
        }
        return [enrich_signal(signal, point)]


class StatisticalBaselineDetector:
    def describe(self) -> dict[str, Any]:
        return detector_meta("stats.postgres.throughput_drop.v1", "Throughput baseline detector", "statistical", "throughput_drop")

    def detect(self, point: dict[str, float], history: list[dict[str, float]]) -> list[dict[str, Any]]:
        if len(history) < 12:
            return []
        avg_xact = sum(item.get("xact_rate", 0) for item in history[-30:]) / len(history[-30:])
        current = point.get("xact_rate", 0)
        if avg_xact <= 10 or current >= avg_xact * 0.45:
            return []
        signal = {
            "id": f"sig-throughput_drop-{int(point['t'])}",
            "t": int(point["t"]),
            "type": "throughput_drop",
            "fingerprint": signal_fingerprint("throughput_drop"),
            "severity": "warning",
            "metric": "xact_rate",
            "value": current,
            "threshold": round(avg_xact * 0.45, 3),
            "recover_threshold": round(avg_xact * 0.75, 3),
            "confirmations": 2,
            "recovery_samples": 4,
            "cooldown_seconds": 180,
            "summary": "Transaction throughput dropped significantly versus the recent baseline.",
            "candidate_root": "workload_stall_or_resource_contention",
            "confidence": 0.68,
            "score": round(1 - (current / avg_xact), 2),
            "source": "baseline_deviation_detector",
            "detector": self.describe(),
            "evidence": [
                {"metric": "xact_rate", "value": current, "baseline": round(avg_xact, 3), "role": "baseline_deviation"},
                {"metric": "active_connections", "value": point.get("active_connections", 0), "role": "context"},
                {"metric": "waiting_connections", "value": point.get("waiting_connections", 0), "role": "context"},
                {"metric": "vacuum_max_elapsed_seconds", "value": point.get("vacuum_max_elapsed_seconds", 0), "role": "operational_context"},
            ],
            "hypotheses": [
                {"cause": "resource_contention_or_blocking", "score": 0.65, "why": "Throughput fell compared with a recent baseline; waits, IO, VACUUM, and config changes should be checked."},
                {"cause": "workload_shape_change", "score": 0.42, "why": "A workload transition can reduce transaction rate without a direct database fault."},
            ],
        }
        return [enrich_signal(signal, point)]


class MLBasedSuspicionDetector:
    def describe(self) -> dict[str, Any]:
        return detector_meta("ml.postgres.suspicious_activity.v0", "ML suspicious activity detector", "ml", "ml_suspicious_activity")

    def detect(self, point: dict[str, float], history: list[dict[str, float]]) -> list[dict[str, Any]]:
        if len(history) < 15:
            return []
        features = self.features(point, history[-45:])
        score = round(min(1.0, features["active_pressure"] * 0.22 + features["wait_pressure"] * 0.22 + features["io_pressure"] * 0.2 + features["vacuum_pressure"] * 0.16 + features["throughput_drop"] * 0.2), 2)
        if score < 0.72:
            return []
        signal = {
            "id": f"sig-ml_suspicious_activity-{int(point['t'])}",
            "t": int(point["t"]),
            "type": "ml_suspicious_activity",
            "fingerprint": signal_fingerprint("ml_suspicious_activity"),
            "severity": "critical" if score >= 0.9 else "warning",
            "metric": "ml_anomaly_score",
            "value": score,
            "threshold": 0.72,
            "recover_threshold": 0.45,
            "confirmations": 2,
            "recovery_samples": 4,
            "cooldown_seconds": 180,
            "summary": "ML detector found a suspicious multi-metric pattern.",
            "candidate_root": "multi_signal_resource_contention",
            "confidence": round(min(0.95, 0.5 + score * 0.45), 2),
            "score": score,
            "source": "ml_like_detector",
            "detector": self.describe(),
            "model": {"kind": "hybrid_anomaly_model", "version": "0", "signal_contract": SIGNAL_CONTRACT},
            "evidence": [{"metric": name, "value": value, "role": "ml_feature"} for name, value in features.items()],
            "hypotheses": [
                {"cause": "compound_resource_contention", "score": score, "why": "Several weak signals jointly look suspicious even when a single threshold is not decisive."},
                {"cause": "dba_or_maintenance_induced_degradation", "score": round(max(features["vacuum_pressure"], features["io_pressure"]), 2), "why": "Maintenance and IO features contribute to the anomaly score."},
            ],
        }
        return [enrich_signal(signal, point)]

    def features(self, point: dict[str, float], baseline: list[dict[str, float]]) -> dict[str, float]:
        avg_xact = sum(item.get("xact_rate", 0) for item in baseline) / len(baseline)
        current_xact = point.get("xact_rate", 0)
        throughput_drop = 0.0 if avg_xact <= 10 else max(0.0, min(1.0, 1 - current_xact / avg_xact))
        return {
            "active_pressure": min(1.0, point.get("active_connections", 0) / 24),
            "wait_pressure": min(1.0, point.get("waiting_connections", 0) / 2),
            "io_pressure": min(1.0, point.get("blk_read_time_ms_rate", 0) / 50),
            "vacuum_pressure": min(1.0, point.get("vacuum_max_elapsed_seconds", 0) / 30),
            "throughput_drop": round(throughput_drop, 2),
        }


DETECTOR_PIPELINE: list[SignalDetector] = [
    *(RuleThresholdDetector(config) for config in RULE_DETECTORS),
    StatisticalBaselineDetector(),
    MLBasedSuspicionDetector(),
]


def detector_catalog(enabled_detector_ids: set[str] | None = None) -> list[dict[str, Any]]:
    catalog = []
    for detector in DETECTOR_PIPELINE:
        meta = detector.describe()
        meta["enabled"] = enabled_detector_ids is None or meta["id"] in enabled_detector_ids
        catalog.append(meta)
    return catalog


def evaluate_detectors(
    point: dict[str, float],
    history: list[dict[str, float]] | None = None,
    enabled_detector_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for detector in DETECTOR_PIPELINE:
        meta = detector.describe()
        if enabled_detector_ids is not None and meta["id"] not in enabled_detector_ids:
            continue
        signals.extend(detector.detect(point, history or []))
    return signals

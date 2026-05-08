import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit.hypotheses import build_hypotheses


def test_hypothesis_scores_include_explainable_basis():
    signal = {
        "type": "wait_contention",
        "metric": "waiting_connections",
        "value": 3.0,
        "evidence": [{"metric": "active_connections", "value": 30.0}],
    }
    point = {
        "waiting_connections": 3.0,
        "active_connections": 30.0,
        "xact_rate": 120.0,
        "blk_read_time_ms_rate": 0.0,
    }
    hypotheses = build_hypotheses(signal, point)
    assert hypotheses[0]["cause"] == "lock_contention_or_slow_queries"
    assert hypotheses[0]["score"] > hypotheses[1]["score"]
    assert hypotheses[0]["score_basis"]["base_score"] == 0.34
    assert {item["metric"] for item in hypotheses[0]["score_basis"]["factors"]} >= {"waiting_connections", "active_connections"}


def test_ml_hypotheses_use_detector_features_from_evidence():
    signal = {
        "type": "ml_suspicious_activity",
        "metric": "ml_anomaly_score",
        "value": 0.86,
        "evidence": [
            {"metric": "workload_transition", "value": 0.9},
            {"metric": "throughput_drop", "value": 0.8},
            {"metric": "vacuum_pressure", "value": 0.1},
            {"metric": "io_pressure", "value": 0.0},
        ],
    }
    hypotheses = build_hypotheses(signal, {})
    assert hypotheses[0]["cause"] == "compound_workload_or_resource_shift"
    assert hypotheses[0]["score"] >= 0.7
    assert all("score_basis" in item for item in hypotheses)

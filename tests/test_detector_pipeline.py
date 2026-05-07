import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit.detectors import MLBasedSuspicionDetector, detector_catalog, evaluate_detectors


def test_detector_catalog_exposes_replaceable_engines():
    catalog = detector_catalog()
    engines = {item["engine"] for item in catalog}
    assert "rules" in engines
    assert "statistical" in engines
    assert "ml" in engines
    assert all(item["signal_contract"] == "SuspiciousSignal.v1" for item in catalog)
    assert all({"id", "name", "engine", "type", "signal_contract", "enabled"} <= set(item) for item in catalog)


def test_ml_detector_uses_signal_contract():
    detector = MLBasedSuspicionDetector()
    history = [
        {
            "t": float(index),
            "xact_rate": 1000.0,
            "active_connections": 2.0,
            "waiting_connections": 0.0,
            "blk_read_time_ms_rate": 0.0,
            "vacuum_max_elapsed_seconds": 0.0,
        }
        for index in range(20)
    ]
    point = {
        "t": 30.0,
        "xact_rate": 100.0,
        "active_connections": 30.0,
        "waiting_connections": 3.0,
        "blk_read_time_ms_rate": 80.0,
        "vacuum_max_elapsed_seconds": 45.0,
    }
    signals = detector.detect(point, history)
    assert len(signals) == 1
    signal = signals[0]
    for key in [
        "id",
        "type",
        "fingerprint",
        "severity",
        "metric",
        "value",
        "threshold",
        "recover_threshold",
        "confidence",
        "score",
        "detector",
        "evidence",
        "hypotheses",
        "causal_chain",
    ]:
        assert key in signal
    assert signal["detector"]["engine"] == "ml"


def test_detector_pipeline_can_be_filtered_by_detector_id():
    point = {
        "t": 30.0,
        "xact_rate": 100.0,
        "active_connections": 30.0,
        "waiting_connections": 3.0,
        "blk_read_time_ms_rate": 80.0,
        "vacuum_max_elapsed_seconds": 45.0,
    }
    all_signals = evaluate_detectors(point, [])
    filtered_signals = evaluate_detectors(point, [], {"rules.postgres.high_concurrency.v1"})
    assert {signal["type"] for signal in all_signals} >= {"high_concurrency", "wait_contention", "read_io_pressure", "vacuum_pressure"}
    assert [signal["type"] for signal in filtered_signals] == ["high_concurrency"]

from causal_sim.anomaly import detect_anomalies, negative_evidence
from causal_sim.causal_graph import build_causal_graph
from causal_sim.propagation import propagate
from causal_sim.scenario import load_scenario
from causal_sim.telemetry import generate_telemetry


def test_anomaly_layer_recovers_ordered_signal_without_ground_truth():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    telemetry = generate_telemetry(propagate(template, build_causal_graph(template)))
    anomalies = detect_anomalies(telemetry)

    assert [item.metric for item in anomalies] == [
        "reporting_concurrency",
        "storage_read_latency_p95_ms",
        "short_query_wait_p95_ms",
        "payments_p95_ms",
    ]
    assert [item.started_at for item in anomalies] == sorted(item.started_at for item in anomalies)
    assert {item["cause"] for item in negative_evidence(telemetry)} == {
        "cpu_saturation",
        "network_packet_loss",
        "replication_lag",
    }


from causal_sim.causal_graph import build_causal_graph
from causal_sim.propagation import metric_activation_times, propagate
from causal_sim.scenario import load_scenario


def test_cause_propagates_in_time_order_and_negative_evidence_stays_stable():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    states = propagate(template, build_causal_graph(template))

    def first_change(metric: str, threshold: float) -> int:
        baseline = states[0][metric]
        for state in states:
            if state[metric] - baseline >= threshold:
                return int(state["t"])
        raise AssertionError(metric)

    assert first_change("reporting_concurrency", 25) < first_change("storage_read_latency_p95_ms", 50)
    assert first_change("storage_read_latency_p95_ms", 50) < first_change("short_query_wait_p95_ms", 25)
    assert first_change("short_query_wait_p95_ms", 25) < first_change("payments_p95_ms", 200)
    assert max(state["cpu_utilization_pct"] for state in states) < 80
    assert len({state["network_loss_pct"] for state in states}) == 1
    assert len({state["replication_lag_sec"] for state in states}) == 1


def test_metric_activation_times_are_derived_from_causal_graph_edges():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    graph = build_causal_graph(template)

    starts = metric_activation_times(graph)

    assert starts["reporting_concurrency"] < starts["storage_read_latency_p95_ms"]
    assert starts["storage_read_latency_p95_ms"] < starts["short_query_wait_p95_ms"]
    assert starts["short_query_wait_p95_ms"] < starts["payments_p95_ms"]

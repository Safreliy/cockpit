from causal_sim.causal_graph import build_causal_graph
from causal_sim.scenario import load_scenario


def test_graph_preserves_expected_mvp_chain():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    graph = build_causal_graph(template)

    assert [node.id for node in graph.nodes] == ["cause", "mechanism", "storage", "query_wait", "payments", "business"]
    assert [(edge.source, edge.target) for edge in graph.edges] == [
        ("cause", "mechanism"),
        ("mechanism", "storage"),
        ("storage", "query_wait"),
        ("query_wait", "payments"),
        ("payments", "business"),
    ]
    assert all(edge.delay_seconds > 0 for edge in graph.edges)


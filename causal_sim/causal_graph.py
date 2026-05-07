from __future__ import annotations

from causal_sim.models import CausalEdge, CausalGraph, CausalNode, CauseTemplate


def build_causal_graph(template: CauseTemplate) -> CausalGraph:
    nodes = [CausalNode(**node) for node in template.graph_nodes]
    known = {node.id for node in nodes}
    edges = [CausalEdge(**edge) for edge in template.graph_edges]
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError(f"edge references unknown node: {edge.source}->{edge.target}")
        if edge.delay_seconds <= 0:
            raise ValueError("edge delays must be positive")
    return CausalGraph(nodes=nodes, edges=edges)


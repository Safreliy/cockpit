from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CauseTemplate:
    id: str
    title: str
    location: str
    mechanism: str
    business_flow: str
    impact_metric: str
    slo_ms: float
    rejected_causes: list[str]
    recommended_action: str
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    metrics: dict[str, float]
    ground_truth: dict[str, Any]


@dataclass(frozen=True)
class CausalNode:
    id: str
    kind: str
    label: str
    metric: str | None = None


@dataclass(frozen=True)
class CausalEdge:
    source: str
    target: str
    delay_seconds: int
    strength: float = 1.0


@dataclass(frozen=True)
class CausalGraph:
    nodes: list[CausalNode]
    edges: list[CausalEdge]

    def node(self, node_id: str) -> CausalNode:
        for item in self.nodes:
            if item.id == node_id:
                return item
        raise KeyError(node_id)


@dataclass(frozen=True)
class TelemetryPoint:
    t: int
    metrics: dict[str, float]
    events: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Anomaly:
    metric: str
    started_at: int
    baseline: float
    observed: float
    direction: str
    evidence: str


@dataclass(frozen=True)
class CausalEpisode:
    business_status: str
    impacted_flow: str
    probable_cause: str
    mechanism: str
    confidence: float
    evidence: list[dict[str, Any]]
    rejected_causes: list[dict[str, str]]
    recommended_action: str
    action_cost: str


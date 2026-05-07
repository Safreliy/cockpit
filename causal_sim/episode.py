from __future__ import annotations

from causal_sim.models import Anomaly, CausalEpisode, CauseTemplate


EXPECTED_CHAIN = [
    "reporting_concurrency",
    "storage_read_latency_p95_ms",
    "short_query_wait_p95_ms",
    "payments_p95_ms",
]


def build_episode(template: CauseTemplate, anomalies: list[Anomaly], rejected: list[dict[str, str]]) -> CausalEpisode:
    by_metric = {item.metric: item for item in anomalies}
    evidence = []
    matched = 0
    previous_started_at = -1
    for metric in EXPECTED_CHAIN:
        anomaly = by_metric.get(metric)
        if anomaly is None:
            continue
        if anomaly.started_at > previous_started_at:
            matched += 1
        previous_started_at = anomaly.started_at
        evidence.append(
            {
                "metric": metric,
                "started_at": anomaly.started_at,
                "baseline": anomaly.baseline,
                "observed": anomaly.observed,
                "statement": anomaly.evidence,
            }
        )

    confidence = round(0.45 + 0.12 * matched + 0.02 * len(rejected), 2)
    return CausalEpisode(
        business_status="payments degraded",
        impacted_flow=template.business_flow,
        probable_cause=template.id,
        mechanism=template.mechanism,
        confidence=min(confidence, 0.97),
        evidence=evidence,
        rejected_causes=rejected,
        recommended_action=template.recommended_action,
        action_cost="temporarily reduced reporting freshness; no payment traffic interruption expected",
    )


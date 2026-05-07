from __future__ import annotations

from dataclasses import asdict

from causal_sim.models import CausalEpisode, CauseTemplate


def validate_episode(template: CauseTemplate, episode: CausalEpisode) -> dict[str, object]:
    truth = template.ground_truth
    rejected = {item["cause"] for item in episode.rejected_causes}
    checks = {
        "root_cause_detected": episode.probable_cause == truth["root_cause"],
        "mechanism_detected": episode.mechanism == truth["mechanism"],
        "business_impact_detected": episode.impacted_flow == truth["business_flow"],
        "false_cpu_cause_avoided": "cpu_saturation" in rejected,
        "false_network_cause_avoided": "network_packet_loss" in rejected,
        "false_replication_cause_avoided": "replication_lag" in rejected,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "episode": asdict(episode),
    }


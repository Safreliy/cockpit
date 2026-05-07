from causal_sim.anomaly import detect_anomalies, negative_evidence
from causal_sim.causal_graph import build_causal_graph
from causal_sim.episode import build_episode
from causal_sim.propagation import propagate
from causal_sim.scenario import load_scenario
from causal_sim.telemetry import generate_telemetry


def test_episode_names_cause_mechanism_impact_and_action():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    telemetry = generate_telemetry(propagate(template, build_causal_graph(template)))
    episode = build_episode(template, detect_anomalies(telemetry), negative_evidence(telemetry))

    assert episode.probable_cause == "heavy_reporting_on_primary"
    assert episode.mechanism == "storage_read_contention"
    assert episode.impacted_flow == "payments"
    assert episode.business_status == "payments degraded"
    assert episode.recommended_action
    assert len(episode.evidence) == 4
    assert {item["cause"] for item in episode.rejected_causes} == set(template.rejected_causes)


from causal_sim.anomaly import detect_anomalies, negative_evidence
from causal_sim.causal_graph import build_causal_graph
from causal_sim.episode import build_episode
from causal_sim.propagation import propagate
from causal_sim.scenario import load_scenario
from causal_sim.telemetry import generate_telemetry
from causal_sim.validation import validate_episode


def test_validation_report_passes_all_mvp_checks():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    telemetry = generate_telemetry(propagate(template, build_causal_graph(template)))
    episode = build_episode(template, detect_anomalies(telemetry), negative_evidence(telemetry))
    report = validate_episode(template, episode)

    assert report["passed"] is True
    assert all(report["checks"].values())


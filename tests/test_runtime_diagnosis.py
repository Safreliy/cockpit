from causal_sim.causal_graph import build_causal_graph
from causal_sim.propagation import propagate
from causal_sim.scenario import load_scenario
from causal_sim.telemetry import generate_telemetry
from causal_sim.runtime_diagnosis import diagnose_runtime
from causal_sim.web_cockpit import _build_long_runtime


def test_runtime_diagnosis_builds_incidents_from_telemetry_without_manual_chains():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    telemetry = generate_telemetry(propagate(template, build_causal_graph(template)))
    runtime = _build_long_runtime(telemetry)

    incidents = diagnose_runtime(runtime)

    assert [item["probable_cause"] for item in incidents] == [
        "heavy_reporting_on_primary",
        "client_db_packet_loss",
        "cpu_saturation_on_primary",
    ]
    assert all(item["chain"][0]["role"] == "Impact" for item in incidents)
    assert all("hypotheses" in item and len(item["hypotheses"]) >= 3 for item in incidents)
    assert all(item["hypotheses"][0]["cause"] == item["probable_cause"] for item in incidents)

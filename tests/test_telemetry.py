from causal_sim.causal_graph import build_causal_graph
from causal_sim.propagation import propagate
from causal_sim.scenario import load_scenario
from causal_sim.telemetry import generate_telemetry


def test_telemetry_has_30_minutes_at_10_second_step_and_events():
    template = load_scenario("scenarios/heavy_reporting_on_primary.yaml")
    telemetry = generate_telemetry(propagate(template, build_causal_graph(template)))

    assert len(telemetry) == 181
    assert telemetry[0].t == 0
    assert telemetry[-1].t == 1800
    assert all((right.t - left.t) == 10 for left, right in zip(telemetry, telemetry[1:]))
    assert any("reporting_workload_started_on_primary" in point.events for point in telemetry)
    assert any("payments_slo_violation" in point.events for point in telemetry)


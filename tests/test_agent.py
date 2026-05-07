import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit.agent import CausalAgent, IncidentVerdictTool, JsonMemoryStore, OperationalContextTool, SnapshotTool


class FailingLLM:
    model = "test-llm"

    def complete_json(self, messages, schema_hint):
        raise RuntimeError("disabled")


class VerdictSink:
    def __init__(self):
        self.verdict = None

    def submit_verdict(self, incident_id, verdict):
        self.verdict = verdict
        return {"ok": True, "incident_id": incident_id}


def test_causal_agent_submits_fallback_verdict(tmp_path):
    incident = {
        "id": "inc-1",
        "type": "throughput_drop",
        "metric": "xact_rate",
        "value": 0,
        "confidence": 0.7,
        "created_at": 100,
        "last_seen_at": 120,
        "causal_chain": [
            {"stage": "symptom", "label": "xact_rate", "detail": "0 <= 10"},
            {"stage": "candidate cause", "label": "workload_stopped", "detail": "ranked"},
        ],
        "investigation": {"next_actions": ["Compare baseline versus incident window."]},
    }
    snapshot = {
        "generated_at": 120,
        "stream": [{"t": 120, "xact_rate": 0}],
        "incidents": [incident],
        "signals": [],
        "settings": {},
        "load": None,
        "operational_events": [{"t": 118, "type": "postgres_config_changed"}],
        "experiments": [],
    }
    sink = VerdictSink()
    agent = CausalAgent(
        llm=FailingLLM(),
        tools=[SnapshotTool(lambda: snapshot), OperationalContextTool(lambda: snapshot), IncidentVerdictTool(sink)],
        memory=JsonMemoryStore(tmp_path / "memory.json"),
    )
    result = agent.investigate(incident)
    assert result["submit_result"]["ok"] is True
    assert sink.verdict["root_cause"] == "postgres_config_changed"
    assert sink.verdict["engine"] == "fallback"
    assert (tmp_path / "memory.json").exists()

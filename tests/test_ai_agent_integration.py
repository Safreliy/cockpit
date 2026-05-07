import sys
import time
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit.ai_agent import (
    WhatareyatalkinaboutClient,
    build_investigation_prompt,
    compact_incident_context,
    parse_agent_verdict,
    run_ai_investigation,
)
from cockpit_backend import TelemetryStore


class FakeAgentClient:
    def __init__(self):
        self.created_chat = None
        self.prompt = ""

    def ensure_model(self):
        return "model-1"

    def ensure_mcp_ids(self):
        return ["mcp-1"]

    def create_chat(self, incident_id, model_id, mcp_ids):
        self.created_chat = {
            "incident_id": incident_id,
            "model_id": model_id,
            "mcp_ids": mcp_ids,
        }
        return "chat-1"

    def complete(self, chat_id, prompt):
        self.prompt = prompt
        return (
            '{"verdict":"lock contention from workload","confidence":0.82,'
            '"root_cause":"blocked updates","causal_chain":[{"stage":"cause","detail":"row lock waits"}],'
            '"supporting_evidence":["waiting_connections increased"],'
            '"negative_evidence":["no long vacuum"],'
            '"recommended_actions":["inspect pg_locks"],'
            '"needs_more_data":["query fingerprints"]}',
            {"tokens_in": 100, "tokens_out": 80},
        )


class FakeWhatareyClient(WhatareyatalkinaboutClient):
    def __init__(self):
        super().__init__(base_url="http://agent.local")
        self.requests = []

    def _request(self, method, path, payload=None, admin=False):
        self.requests.append({"method": method, "path": path, "payload": payload})
        if method == "GET" and path == "/api/v1/models":
            return {"data": []}
        if method == "POST" and path == "/api/v1/models":
            return {"data": {"id": "model-created"}}
        raise AssertionError((method, path, payload))


def sample_incident():
    return {
        "id": "inc-wait-1",
        "type": "wait_contention",
        "status": "active",
        "severity": "warning",
        "summary": "Postgres sessions are waiting.",
        "metric": "waiting_connections",
        "value": 3,
        "threshold": 2,
        "confidence": 0.8,
        "started_at": 100,
        "last_seen_at": 110,
        "fingerprint": "postgres:cockpit:wait_contention",
        "detector": {"name": "Wait contention detector", "engine": "rules"},
        "evidence": [{"metric": "waiting_connections", "value": 3}],
        "hypotheses": [{"cause": "lock_contention", "score": 0.7}],
        "causal_chain": [{"stage": "symptom", "detail": "waiting_connections >= 2"}],
        "timeline": [{"t": 100, "type": "wait_contention", "metric": "waiting_connections", "value": 3}],
        "operational_events": [],
        "investigation": {"state": "running", "phase": "ranking", "progress": 50},
    }


def test_ai_prompt_contains_compact_incident_context():
    context = compact_incident_context(
        sample_incident(),
        [{"t": 90.0, "waiting_connections": 0.0}, {"t": 101.0, "waiting_connections": 3.0}],
        {"work_mem": {"setting": "4096", "unit": "kB"}},
    )
    prompt = build_investigation_prompt(context)
    assert "PostgreSQL observability cockpit" in prompt
    assert "inc-wait-1" in prompt
    assert "waiting_connections" in prompt
    assert "Return ONLY valid JSON" in prompt


def test_parse_agent_verdict_accepts_json_fenced_response():
    verdict = parse_agent_verdict(
        '```json\n{"verdict":"DBA setting changed","confidence":0.71,"recommended_actions":["rollback"]}\n```'
    )
    assert verdict["verdict"] == "DBA setting changed"
    assert verdict["confidence"] == 0.71
    assert verdict["recommended_actions"] == ["rollback"]
    assert verdict["supporting_evidence"] == []


def test_whatarey_client_can_create_model_using_agent_backend_global_llm(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "Qwen-test")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AI_AGENT_MODEL_ID", raising=False)
    client = FakeWhatareyClient()
    assert client.ensure_model() == "model-created"
    create_request = client.requests[-1]
    assert create_request["path"] == "/api/v1/models"
    assert create_request["payload"]["name"] == "Qwen-test"
    assert create_request["payload"]["base_url"] is None


def test_run_ai_investigation_creates_session_and_returns_verdict():
    fake = FakeAgentClient()
    result = run_ai_investigation(sample_incident(), [{"t": 100.0, "waiting_connections": 3.0}], {}, client=fake)
    assert result["status"] == "complete"
    assert result["chat_id"] == "chat-1"
    assert result["model_id"] == "model-1"
    assert result["mcp_ids"] == ["mcp-1"]
    assert result["verdict"]["root_cause"] == "blocked updates"
    assert fake.created_chat["incident_id"] == "inc-wait-1"
    assert "Incident context JSON" in fake.prompt


def test_backend_ai_investigation_updates_incident_verdict():
    store = TelemetryStore()
    point = {
        "t": 100.0,
        "active_connections": 1.0,
        "waiting_connections": 3.0,
        "blk_read_time_ms_rate": 0.0,
        "vacuum_max_elapsed_seconds": 0.0,
        "xact_rate": 10.0,
    }
    store.add_point(point)
    incident_id = store.incidents[0]["id"]

    def fake_run(incident, stream, settings, existing_session=None):
        return {
            "status": "complete",
            "chat_id": "chat-1",
            "model_id": "model-1",
            "mcp_ids": ["mcp-1"],
            "updated_at": int(time.time()),
            "usage": {"tokens_in": 1, "tokens_out": 1},
            "verdict": {
                "verdict": "Lock contention",
                "confidence": 0.9,
                "root_cause": "blocked row updates",
                "supporting_evidence": ["waiting sessions"],
                "recommended_actions": ["inspect pg_locks"],
            },
        }

    with patch("cockpit_backend.run_ai_investigation", side_effect=fake_run):
        ok, message, incident = store.start_ai_investigation(incident_id)
        assert ok is True
        assert message == "started"
        assert incident["ai_investigation"]["status"] in {"running", "complete"}
        deadline = time.time() + 2
        while time.time() < deadline:
            updated = store.get_incident(incident_id)
            if updated and updated.get("ai_investigation", {}).get("status") == "complete":
                break
            time.sleep(0.02)
    updated = store.get_incident(incident_id)
    assert updated["ai_verdict"]["verdict"] == "Lock contention"
    assert updated["investigation"]["phase"] == "ai_verdict_ready"

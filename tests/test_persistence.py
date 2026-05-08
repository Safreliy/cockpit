import sys
import time
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit.persistence import epoch_expr, json_literal, sql_literal
from cockpit_backend import TelemetryStore


class FakePersistence:
    def __init__(self):
        self.signals = []
        self.incidents = []

    def ensure_schema(self):
        return

    def load_recent(self, limit):
        return {
            "signals": list(self.signals)[-limit:],
            "incidents": list(self.incidents)[-limit:],
        }

    def save_signal(self, signal):
        self.signals.append(dict(signal))

    def save_incident(self, incident):
        self.incidents.append(dict(incident))

    def save_ai_verdict(self, incident):
        self.save_incident(incident)


def incident_point(t=100.0):
    return {
        "t": t,
        "active_connections": 1.0,
        "waiting_connections": 3.0,
        "blk_read_time_ms_rate": 0.0,
        "vacuum_max_elapsed_seconds": 0.0,
        "xact_rate": 10.0,
    }


def test_store_persists_signals_and_incidents():
    persistence = FakePersistence()
    store = TelemetryStore(persistence=persistence)
    store.add_point(incident_point())
    assert persistence.signals
    assert persistence.signals[-1]["type"] == "wait_contention"
    assert persistence.incidents
    assert persistence.incidents[-1]["status"] == "candidate"


def test_store_hydrates_recent_persisted_state():
    persistence = FakePersistence()
    source = TelemetryStore(persistence=persistence)
    source.add_point(incident_point())

    restored = TelemetryStore(persistence=persistence)
    restored.hydrate_from_persistence(10)
    assert restored.signals
    assert restored.incidents
    assert restored.get_incident(restored.incidents[0]["id"])["type"] == "wait_contention"


def test_store_persists_ai_verdict_updates():
    persistence = FakePersistence()
    store = TelemetryStore(persistence=persistence)
    store.add_point(incident_point())
    incident_id = store.incidents[0]["id"]

    def fake_run(incident, stream, settings, existing_session=None):
        return {
            "status": "complete",
            "chat_id": "chat-1",
            "model_id": "model-1",
            "mcp_ids": ["mcp-1"],
            "updated_at": int(time.time()),
            "verdict": {"verdict": "Wait contention", "confidence": 0.8},
        }

    with patch("cockpit_backend.run_ai_investigation", side_effect=fake_run):
        ok, _, _ = store.start_ai_investigation(incident_id)
        assert ok
        deadline = time.time() + 2
        while time.time() < deadline:
            if persistence.incidents[-1].get("ai_verdict"):
                break
            time.sleep(0.02)
    assert persistence.incidents[-1]["ai_verdict"]["verdict"] == "Wait contention"


def test_sql_literal_helpers_escape_payloads():
    assert sql_literal("a'b") == "'a''b'"
    assert json_literal({"message": "can't"}) == '\'{"message": "can\'\'t"}\''
    assert epoch_expr(100) == "to_timestamp(100.0)"
    assert epoch_expr(None) == "NULL"

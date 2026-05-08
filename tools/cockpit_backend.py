from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cockpit.ai_agent import AIAgentError, WhatareyatalkinaboutClient, ai_agent_enabled, run_ai_investigation
from cockpit.detectors import build_investigation, detector_catalog, evaluate_detectors
from cockpit.experiments import EXPERIMENT_SETTINGS
from cockpit.persistence import NoopPersistence, Persistence, PostgresPersistence
from live_pg_monitor import QUERIES, query_prometheus, query_settings


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web_cockpit"
COMPOSE_FILE = ROOT / "infra" / "docker-compose.yml"


PGBENCH_CUSTOM_SCRIPTS = {
    "planner_range": """
\\set range_start random(1, 900000)
SELECT count(*) FROM pgbench_accounts WHERE aid BETWEEN :range_start AND :range_start + 100000;
""",
    "sort_spill": """
SELECT aid, abalance FROM pgbench_accounts ORDER BY abalance, aid LIMIT 5000;
""",
    "aggregate_scan": """
SELECT bid, sum(abalance), avg(abalance) FROM pgbench_accounts GROUP BY bid ORDER BY bid;
""",
}


class TelemetryStore:
    def __init__(
        self,
        max_points: int = 720,
        max_detections: int = 200,
        persistence: Persistence | None = None,
    ) -> None:
        self.points: deque[dict[str, float]] = deque(maxlen=max_points)
        self.detections: deque[dict[str, Any]] = deque(maxlen=max_detections)
        self.signals: deque[dict[str, Any]] = deque(maxlen=max_detections)
        self.incidents: deque[dict[str, Any]] = deque(maxlen=max_detections)
        self.operational_events: deque[dict[str, Any]] = deque(maxlen=300)
        self.settings: dict[str, dict[str, str]] = {}
        self.experiments: deque[dict[str, Any]] = deque(maxlen=100)
        self.last_config_reload_time: float | None = None
        self.active_by_type: dict[str, str] = {}
        self.active_by_fingerprint: dict[str, str] = {}
        self.cooldown_until: dict[str, int] = {}
        self.clients: list[queue.Queue[dict[str, Any]]] = []
        self.lock = threading.Lock()
        self.load_process: subprocess.Popen[str] | None = None
        self.load_started_at: int | None = None
        self.load_config: dict[str, Any] | None = None
        self.load_output: deque[str] = deque(maxlen=40)
        self.load_script_path: str | None = None
        self.enabled_detector_ids: set[str] | None = None
        self.persistence = persistence or NoopPersistence()

    def add_point(self, point: dict[str, float]) -> None:
        events: list[dict[str, Any]] = [{"type": "telemetry", "point": point}]
        persist_signals: list[dict[str, Any]] = []
        persist_incidents: list[dict[str, Any]] = []
        with self.lock:
            history = list(self.points)
            signals = evaluate_detectors(point, history, self.enabled_detector_ids)
            seen_fingerprints = {signal["fingerprint"] for signal in signals}
            self.points.append(point)
            for signal in signals:
                self.signals.append(signal)
                self.detections.append(signal)
                persist_signals.append(dict(signal))
                incident = self.upsert_incident_locked(signal)
                if incident:
                    persist_incidents.append(dict(incident))
                    events.append({"type": "detection", "detection": signal})
                    events.append({"type": "signal", "signal": signal})
                    events.append({"type": "incident", "incident": incident})
            for incident in self.incidents:
                if incident["status"] in {"resolved", "false_positive"}:
                    continue
                if incident["fingerprint"] not in seen_fingerprints:
                    updated = self.advance_incident_without_signal_locked(incident, int(point["t"]))
                    if updated:
                        persist_incidents.append(dict(incident))
                        events.append({"type": "incident", "incident": incident})
            for event in events:
                self._publish_locked(event)
        self.persist_many(persist_signals, persist_incidents)

    def hydrate_from_persistence(self, limit: int) -> None:
        try:
            data = self.persistence.load_recent(limit)
        except Exception as error:
            print(f"persistence load failed: {error}", flush=True)
            return
        with self.lock:
            for signal in data.get("signals", []):
                self.signals.append(signal)
                self.detections.append(signal)
            self.incidents.clear()
            self.active_by_type.clear()
            self.active_by_fingerprint.clear()
            now = int(time.time())
            for incident in data.get("incidents", []):
                self.incidents.append(incident)
                if incident.get("status") not in {"resolved", "false_positive"}:
                    self.active_by_type[str(incident.get("type"))] = str(incident.get("id"))
                    self.active_by_fingerprint[str(incident.get("fingerprint"))] = str(incident.get("id"))
                if incident.get("status") in {"resolved", "false_positive"}:
                    self.cooldown_until[str(incident.get("fingerprint"))] = now

    def persist_many(self, signals: list[dict[str, Any]], incidents: list[dict[str, Any]]) -> None:
        for signal in signals:
            try:
                self.persistence.save_signal(signal)
            except Exception as error:
                print(f"signal persistence failed: {error}", flush=True)
        seen_incidents: set[str] = set()
        for incident in incidents:
            incident_id = str(incident.get("id", ""))
            if incident_id in seen_incidents:
                continue
            seen_incidents.add(incident_id)
            try:
                self.persistence.save_incident(incident)
            except Exception as error:
                print(f"incident persistence failed: {error}", flush=True)

    def persist_incident(self, incident: dict[str, Any]) -> None:
        try:
            self.persistence.save_incident(dict(incident))
        except Exception as error:
            print(f"incident persistence failed: {error}", flush=True)

    def collect_query_fingerprint_snapshot(self, observed_at: int) -> None:
        try:
            self.persistence.collect_query_fingerprint_snapshot(observed_at)
        except Exception as error:
            print(f"query fingerprint snapshot failed: {error}", flush=True)

    def advance_incident_without_signal_locked(self, incident: dict[str, Any], now: int) -> bool:
        incident["quiet_samples"] = int(incident.get("quiet_samples", 0)) + 1
        recovery_samples = int(incident.get("recovery_samples", 3))
        if incident["status"] in {"candidate", "active", "open", "acknowledged"} and incident["quiet_samples"] >= 1:
            incident["status"] = "recovering"
            incident["recovering_at"] = incident.get("recovering_at") or now
            incident["updated_at"] = now
            incident["consecutive_signal_count"] = 0
            return True
        if incident["status"] == "recovering" and incident["quiet_samples"] >= recovery_samples:
            incident["status"] = "resolved"
            incident["resolved_at"] = now
            incident["updated_at"] = now
            self.active_by_fingerprint.pop(incident["fingerprint"], None)
            self.active_by_type.pop(incident["type"], None)
            self.cooldown_until[incident["fingerprint"]] = now + int(incident.get("cooldown_seconds", 120))
            if incident.get("investigation"):
                incident["investigation"]["state"] = "complete"
                incident["investigation"]["phase"] = "resolved"
                incident["investigation"]["progress"] = 100
                incident["investigation"]["updated_at"] = now
            return True
        return False

    def add_settings_snapshot(self, settings: dict[str, dict[str, str]], observed_at: int) -> None:
        events: list[dict[str, Any]] = []
        with self.lock:
            if not self.settings:
                self.settings = settings
                return
            for name, current in settings.items():
                previous = self.settings.get(name)
                if previous and previous.get("setting") != current.get("setting"):
                    event = {
                        "id": f"op-config-{name}-{observed_at}",
                        "t": observed_at,
                        "type": "postgres_config_changed",
                        "severity": "info",
                        "summary": f"PostgreSQL setting {name} changed from {previous.get('setting')} to {current.get('setting')}.",
                        "setting": name,
                        "previous": previous,
                        "current": current,
                    }
                    self.operational_events.append(event)
                    events.append({"type": "operational_event", "event": event})
            self.settings = settings
            for event in events:
                self._publish_locked(event)

    def add_operational_events_from_point(self, point: dict[str, float]) -> None:
        observed_at = int(point["t"])
        events: list[dict[str, Any]] = []
        reload_time = point.get("config_reload_time", 0)
        with self.lock:
            if reload_time and self.last_config_reload_time and reload_time != self.last_config_reload_time:
                event = {
                    "id": f"op-config-reload-{observed_at}",
                    "t": observed_at,
                    "type": "postgres_config_reloaded",
                    "severity": "info",
                    "summary": "PostgreSQL configuration was reloaded.",
                    "value": reload_time,
                }
                self.operational_events.append(event)
                events.append({"type": "operational_event", "event": event})
            if reload_time:
                self.last_config_reload_time = reload_time
            if point.get("vacuum_max_elapsed_seconds", 0) >= 30:
                event = {
                    "id": f"op-vacuum-{observed_at}",
                    "t": observed_at,
                    "type": "postgres_vacuum_active",
                    "severity": "warning",
                    "summary": "Long-running VACUUM activity is visible during telemetry polling.",
                    "active_vacuum_sessions": point.get("active_vacuum_sessions", 0),
                    "active_autovacuum_sessions": point.get("active_autovacuum_sessions", 0),
                    "vacuum_max_elapsed_seconds": point.get("vacuum_max_elapsed_seconds", 0),
                }
                if not self.operational_events or self.operational_events[-1].get("type") != event["type"]:
                    self.operational_events.append(event)
                    events.append({"type": "operational_event", "event": event})
            for event in events:
                self._publish_locked(event)

    def run_psql(self, sql: str) -> tuple[bool, str]:
        psql = shutil.which("psql")
        if not psql:
            return False, "psql is not available in backend runtime"
        env = os.environ.copy()
        if os.environ.get("PGPASSWORD"):
            env["PGPASSWORD"] = os.environ["PGPASSWORD"]
        args = [
            psql,
            "-h",
            os.environ.get("PGHOST", "127.0.0.1"),
            "-p",
            os.environ.get("PGPORT", "55432"),
            "-U",
            os.environ.get("PGUSER", "cockpit"),
            "-d",
            os.environ.get("PGDATABASE", "cockpit"),
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-c",
            sql,
        ]
        process = subprocess.run(args, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        return process.returncode == 0, process.stdout.strip()

    def run_psql_scalar(self, sql: str) -> tuple[bool, str]:
        psql = shutil.which("psql")
        if not psql:
            return False, "psql is not available in backend runtime"
        env = os.environ.copy()
        if os.environ.get("PGPASSWORD"):
            env["PGPASSWORD"] = os.environ["PGPASSWORD"]
        args = [
            psql,
            "-h",
            os.environ.get("PGHOST", "127.0.0.1"),
            "-p",
            os.environ.get("PGPORT", "55432"),
            "-U",
            os.environ.get("PGUSER", "cockpit"),
            "-d",
            os.environ.get("PGDATABASE", "cockpit"),
            "-v",
            "ON_ERROR_STOP=1",
            "-qAt",
            "-c",
            sql,
        ]
        process = subprocess.run(args, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        return process.returncode == 0, process.stdout.strip()

    def run_psql_many(self, statements: list[str]) -> tuple[bool, str]:
        output: list[str] = []
        for statement in statements:
            ok, message = self.run_psql(statement)
            if message:
                output.append(message)
            if not ok:
                return False, "\n".join(output)
        return True, "\n".join(output)

    def apply_setting_experiment(self, name: str, value: str) -> tuple[bool, str, dict[str, Any] | None]:
        if name not in EXPERIMENT_SETTINGS:
            return False, "setting is not allowed for cockpit experiments", None
        if not self.is_safe_setting_value(value):
            return False, "setting value contains unsupported characters", None
        if EXPERIMENT_SETTINGS[name].get("kind") == "table_storage":
            return self.apply_table_storage_experiment(name, value)
        with self.lock:
            previous = dict(self.settings.get(name, {"setting": EXPERIMENT_SETTINGS[name]["default"], "unit": ""}))
        ok, output = self.run_psql_many([f"ALTER SYSTEM SET {name} = '{value}'", "SELECT pg_reload_conf()"])
        if not ok:
            return False, output or "failed to apply setting", None
        experiment = {
            "id": f"exp-{name}-{int(time.time())}",
            "t": int(time.time()),
            "type": "postgres_setting_experiment",
            "status": "applied",
            "setting": name,
            "value": value,
            "previous": previous,
            "summary": f"Applied experiment: {name} = {value}.",
        }
        event = {
            "id": f"op-experiment-{name}-{experiment['t']}",
            "t": experiment["t"],
            "type": "postgres_setting_experiment",
            "severity": "warning",
            "summary": experiment["summary"],
            "setting": name,
            "previous": previous,
            "current": {"setting": value},
        }
        with self.lock:
            self.experiments.append(experiment)
            self.operational_events.append(event)
            self._publish_locked({"type": "operational_event", "event": event})
            self._publish_locked({"type": "experiment", "experiment": experiment})
        return True, "applied", experiment

    def apply_table_storage_experiment(self, name: str, value: str) -> tuple[bool, str, dict[str, Any] | None]:
        meta = EXPERIMENT_SETTINGS[name]
        table = str(meta["table"])
        parameter = str(meta["storage_parameter"])
        if parameter != "fillfactor" or table not in {"pgbench_accounts", "pgbench_branches", "pgbench_tellers"}:
            return False, "table storage experiment is not allowed", None
        try:
            numeric_value = int(value)
        except ValueError:
            return False, "fillfactor must be an integer", None
        if not 10 <= numeric_value <= 100:
            return False, "fillfactor must be between 10 and 100", None
        ok, previous_value = self.run_psql_scalar(
            f"SELECT coalesce((SELECT split_part(option, '=', 2) FROM unnest(coalesce(reloptions, ARRAY[]::text[])) AS option WHERE option LIKE '{parameter}=%'), '100') FROM pg_class WHERE oid = 'public.{table}'::regclass"
        )
        if not ok:
            return False, previous_value or "failed to read current table storage option", None
        ok, output = self.run_psql(f"ALTER TABLE public.{table} SET ({parameter} = {numeric_value})")
        if not ok:
            return False, output or "failed to apply table storage option", None
        experiment = {
            "id": f"exp-{name}-{int(time.time())}",
            "t": int(time.time()),
            "type": "postgres_table_storage_experiment",
            "status": "applied",
            "setting": name,
            "value": value,
            "previous": {"setting": previous_value or meta["default"], "unit": "", "kind": "table_storage"},
            "summary": f"Applied storage experiment: {table}.{parameter} = {value}.",
        }
        event = {
            "id": f"op-experiment-{name}-{experiment['t']}",
            "t": experiment["t"],
            "type": "postgres_table_storage_experiment",
            "severity": "warning",
            "summary": experiment["summary"],
            "setting": name,
            "previous": experiment["previous"],
            "current": {"setting": value, "kind": "table_storage"},
        }
        with self.lock:
            self.experiments.append(experiment)
            self.operational_events.append(event)
            self._publish_locked({"type": "operational_event", "event": event})
            self._publish_locked({"type": "experiment", "experiment": experiment})
        return True, "applied", experiment

    def rollback_setting_experiment(self, experiment_id: str) -> tuple[bool, str, dict[str, Any] | None]:
        with self.lock:
            experiment = next((item for item in self.experiments if item["id"] == experiment_id), None)
        if not experiment:
            return False, "experiment not found", None
        if experiment.get("status") == "rolled_back":
            return False, "experiment is already rolled back", experiment
        name = str(experiment["setting"])
        if EXPERIMENT_SETTINGS[name].get("kind") == "table_storage":
            return self.rollback_table_storage_experiment(experiment)
        previous_value = str(experiment.get("previous", {}).get("setting", EXPERIMENT_SETTINGS[name]["default"]))
        if not self.is_safe_setting_value(previous_value):
            return False, "previous setting value is unsupported", None
        ok, output = self.run_psql_many([f"ALTER SYSTEM SET {name} = '{previous_value}'", "SELECT pg_reload_conf()"])
        if not ok:
            return False, output or "failed to roll back setting", None
        with self.lock:
            experiment["status"] = "rolled_back"
            experiment["rolled_back_at"] = int(time.time())
            event = {
                "id": f"op-experiment-rollback-{name}-{experiment['rolled_back_at']}",
                "t": experiment["rolled_back_at"],
                "type": "postgres_setting_rollback",
                "severity": "info",
                "summary": f"Rolled back experiment: {name} = {previous_value}.",
                "setting": name,
                "current": {"setting": previous_value},
            }
            self.operational_events.append(event)
            self._publish_locked({"type": "operational_event", "event": event})
            self._publish_locked({"type": "experiment", "experiment": experiment})
            return True, "rolled back", experiment

    def rollback_table_storage_experiment(self, experiment: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
        name = str(experiment["setting"])
        meta = EXPERIMENT_SETTINGS[name]
        table = str(meta["table"])
        parameter = str(meta["storage_parameter"])
        previous_value = str(experiment.get("previous", {}).get("setting", meta["default"]))
        try:
            numeric_value = int(previous_value)
        except ValueError:
            return False, "previous fillfactor is unsupported", None
        if not 10 <= numeric_value <= 100:
            return False, "previous fillfactor is outside the supported range", None
        ok, output = self.run_psql(f"ALTER TABLE public.{table} SET ({parameter} = {numeric_value})")
        if not ok:
            return False, output or "failed to roll back table storage option", None
        with self.lock:
            experiment["status"] = "rolled_back"
            experiment["rolled_back_at"] = int(time.time())
            event = {
                "id": f"op-experiment-rollback-{name}-{experiment['rolled_back_at']}",
                "t": experiment["rolled_back_at"],
                "type": "postgres_table_storage_rollback",
                "severity": "info",
                "summary": f"Rolled back storage experiment: {table}.{parameter} = {previous_value}.",
                "setting": name,
                "current": {"setting": previous_value, "kind": "table_storage"},
            }
            self.operational_events.append(event)
            self._publish_locked({"type": "operational_event", "event": event})
            self._publish_locked({"type": "experiment", "experiment": experiment})
            return True, "rolled back", experiment

    def is_safe_setting_value(self, value: str) -> bool:
        if not value or len(value) > 32:
            return False
        return all(char.isalnum() or char in "._-" for char in value)

    def upsert_incident_locked(self, detection: dict[str, Any]) -> dict[str, Any] | None:
        fingerprint = detection["fingerprint"]
        now = int(detection["t"])
        incident_id = self.active_by_fingerprint.get(fingerprint)
        incident = next((item for item in self.incidents if item["id"] == incident_id), None)
        if incident is None and self.cooldown_until.get(fingerprint, 0) > now:
            return None
        related_events = self.related_operational_events_locked(detection["t"])
        if incident is None:
            investigation = build_investigation(detection, 1)
            confirmations = int(detection.get("confirmations", 2))
            status = "active" if confirmations <= 1 else "candidate"
            incident = {
                "id": f"inc-{detection['type']}-{detection['t']}",
                "fingerprint": fingerprint,
                "type": detection["type"],
                "severity": detection["severity"],
                "status": status,
                "created_at": detection["t"],
                "started_at": detection["t"],
                "activated_at": detection["t"] if status == "active" else None,
                "last_seen_at": detection["t"],
                "quiet_samples": 0,
                "consecutive_signal_count": 1,
                "signal_count": 1,
                "sample_count": 1,
                "confirmations": confirmations,
                "recovery_samples": int(detection.get("recovery_samples", 3)),
                "cooldown_seconds": int(detection.get("cooldown_seconds", 120)),
                "summary": detection["summary"],
                "metric": detection["metric"],
                "value": detection["value"],
                "threshold": detection["threshold"],
                "recover_threshold": detection.get("recover_threshold"),
                "confidence": detection["confidence"],
                "detector": detection["detector"],
                "evidence": detection["evidence"],
                "operational_events": related_events,
                "investigation": investigation,
                "timeline": [self.signal_timeline_entry(detection)],
                "notes": [],
            }
            self.incidents.append(incident)
            self.active_by_type[detection["type"]] = incident["id"]
            self.active_by_fingerprint[fingerprint] = incident["id"]
            return incident
        sample_count = int(incident.get("sample_count", 0)) + 1
        signal_count = int(incident.get("signal_count", 0)) + 1
        consecutive_count = int(incident.get("consecutive_signal_count", 0)) + 1
        status = incident["status"]
        if status in {"candidate", "recovering"} and consecutive_count >= int(incident.get("confirmations", 2)):
            status = "active"
            incident["activated_at"] = incident.get("activated_at") or detection["t"]
        if status == "resolved":
            status = "active"
        investigation = build_investigation(detection, sample_count)
        investigation["started_at"] = incident.get("investigation", {}).get("started_at", incident["created_at"])
        timeline = list(incident.get("timeline", []))
        timeline.append(self.signal_timeline_entry(detection))
        incident.update(
            {
                "severity": detection["severity"],
                "status": status,
                "last_seen_at": detection["t"],
                "quiet_samples": 0,
                "consecutive_signal_count": consecutive_count,
                "signal_count": signal_count,
                "sample_count": sample_count,
                "summary": detection["summary"],
                "metric": detection["metric"],
                "value": detection["value"],
                "threshold": detection["threshold"],
                "recover_threshold": detection.get("recover_threshold"),
                "confidence": detection["confidence"],
                "detector": detection["detector"],
                "evidence": detection["evidence"],
                "operational_events": related_events,
                "investigation": investigation,
                "timeline": timeline[-80:],
            }
        )
        return incident

    def signal_timeline_entry(self, signal: dict[str, Any]) -> dict[str, Any]:
        return {
            "t": signal["t"],
            "type": signal["type"],
            "source": signal.get("source", "detector"),
            "metric": signal["metric"],
            "value": signal["value"],
            "score": signal.get("score", 0),
            "confidence": signal.get("confidence", 0),
            "summary": signal["summary"],
        }

    def related_operational_events_locked(self, incident_time: int, window_seconds: int = 900) -> list[dict[str, Any]]:
        return [
            event
            for event in self.operational_events
            if abs(int(event.get("t", 0)) - incident_time) <= window_seconds
        ][-20:]

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self.lock:
            incident = next((item for item in self.incidents if item["id"] == incident_id), None)
            return dict(incident) if incident else None

    def update_incident_status(self, incident_id: str, status: str, note: str = "") -> tuple[bool, str, dict[str, Any] | None]:
        allowed = {"open", "acknowledged", "resolved", "false_positive"}
        if status not in allowed:
            return False, "unsupported incident status", None
        with self.lock:
            incident = next((item for item in self.incidents if item["id"] == incident_id), None)
            if incident is None:
                return False, "incident not found", None
            incident["status"] = status
            incident["updated_at"] = int(time.time())
            if status in {"resolved", "false_positive"} and incident.get("investigation"):
                incident["investigation"]["state"] = "complete"
                incident["investigation"]["phase"] = status
                incident["investigation"]["progress"] = 100
                incident["investigation"]["updated_at"] = incident["updated_at"]
            if status == "acknowledged" and incident.get("investigation"):
                incident["investigation"]["state"] = "operator_review"
                incident["investigation"]["updated_at"] = incident["updated_at"]
            if note:
                incident.setdefault("notes", []).append({"t": incident["updated_at"], "text": note})
            if status in {"resolved", "false_positive"}:
                self.active_by_type.pop(incident["type"], None)
                self.active_by_fingerprint.pop(incident.get("fingerprint", ""), None)
                self.cooldown_until[incident.get("fingerprint", "")] = incident["updated_at"] + int(incident.get("cooldown_seconds", 120))
            elif status == "open":
                self.active_by_type[incident["type"]] = incident["id"]
                self.active_by_fingerprint[incident.get("fingerprint", incident["type"])] = incident["id"]
            self._publish_locked({"type": "incident", "incident": incident})
            self.persist_incident(incident)
            return True, "updated", incident

    @staticmethod
    def sanitize_image_attachments(image_attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        for item in image_attachments or []:
            url = str(item.get("image_url", ""))
            if not url.startswith("data:image/"):
                continue
            detail = str(item.get("detail") or "high")
            if detail not in {"auto", "low", "high"}:
                detail = "high"
            attachments.append(
                {
                    "type": "image_url",
                    "image_url": url,
                    "detail": detail,
                    "captured_at": int(item.get("captured_at") or time.time()),
                    "source": str(item.get("source") or "dashboard_chart"),
                }
            )
            if len(attachments) >= 2:
                break
        return attachments

    def start_ai_investigation(self, incident_id: str, image_attachments: list[dict[str, Any]] | None = None) -> tuple[bool, str, dict[str, Any] | None]:
        requested_attachment_count = len(image_attachments or [])
        attachments = self.sanitize_image_attachments(image_attachments)
        with self.lock:
            incident = next((item for item in self.incidents if item["id"] == incident_id), None)
            if incident is None:
                return False, "incident not found", None
            if incident.get("ai_investigation", {}).get("status") == "running":
                return False, "AI investigation is already running", incident
            incident["ai_investigation"] = {
                **incident.get("ai_investigation", {}),
                "status": "running",
                "started_at": int(time.time()),
                "updated_at": int(time.time()),
            }
            if incident.get("investigation"):
                incident["investigation"]["state"] = "ai_inference"
                incident["investigation"]["phase"] = "ai_root_cause_analysis"
                incident["investigation"]["progress"] = max(int(incident["investigation"].get("progress", 0)), 70)
                incident["investigation"]["updated_at"] = incident["ai_investigation"]["updated_at"]
            if attachments:
                incident["image_attachments"] = attachments
                incident["dashboard_visual_context"] = self.dashboard_visual_context_locked(
                    int(time.time()),
                    has_image=True,
                )
            incident["visual_input_status"] = {
                "requested": requested_attachment_count,
                "accepted": len(attachments),
                "attached_to_agent_request": bool(attachments),
                "updated_at": int(time.time()),
            }
            stream = list(self.points)
            settings = dict(self.settings)
            incident_copy = dict(incident)
            self._publish_locked({"type": "incident", "incident": incident})
            self.persist_incident(incident)

        threading.Thread(
            target=self._run_ai_investigation_thread,
            args=(incident_id, incident_copy, stream, settings),
            daemon=True,
        ).start()
        return True, "started", incident

    def start_ai_healthcheck(self, image_attachments: list[dict[str, Any]] | None = None) -> tuple[bool, str, dict[str, Any] | None]:
        now = int(time.time())
        requested_attachment_count = len(image_attachments or [])
        attachments = self.sanitize_image_attachments(image_attachments)
        with self.lock:
            latest = dict(self.points[-1]) if self.points else {"t": float(now)}
            stream = list(self.points)
            settings = dict(self.settings)
            incident = {
                "id": f"inc-ai_healthcheck-{now}",
                "fingerprint": "cockpit:ai_healthcheck",
                "type": "ai_healthcheck",
                "severity": "info",
                "status": "active",
                "created_at": now,
                "started_at": now,
                "activated_at": now,
                "last_seen_at": now,
                "quiet_samples": 0,
                "consecutive_signal_count": 1,
                "signal_count": 1,
                "sample_count": len(stream),
                "confirmations": 1,
                "recovery_samples": 1,
                "cooldown_seconds": 0,
                "summary": "Operator requested an AI healthcheck of the current PostgreSQL cockpit state.",
                "metric": "ai_healthcheck",
                "value": 1,
                "threshold": 1,
                "confidence": 0,
                "detector": {
                    "id": "manual.ai_healthcheck.v1",
                    "name": "AI healthcheck",
                    "engine": "ai",
                    "type": "ai_healthcheck",
                    "signal_contract": "SuspiciousSignal.v1",
                },
                "evidence": [
                    {"metric": key, "value": value, "role": "latest_telemetry"}
                    for key, value in latest.items()
                    if key != "t"
                ],
                "operational_events": list(self.operational_events)[-20:],
                "investigation": {
                    "state": "ai_inference",
                    "phase": "ai_healthcheck",
                    "progress": 70,
                    "summary": "AI agent is checking the current telemetry, incidents, DBA context, and MCP tools.",
                    "started_at": now,
                    "updated_at": now,
                    "steps": [
                        {"id": "capture_snapshot", "label": "Capture current cockpit state", "status": "done", "detail": "Current telemetry, incidents, operational events, and settings were captured."},
                        {"id": "summarize_dashboard", "label": "Capture dashboard window", "status": "done", "detail": "The last 15 minutes of visible metrics were summarized and the current chart screenshot was attached when available."},
                        {"id": "ai_healthcheck", "label": "Run AI healthcheck", "status": "running", "detail": "The AI agent can inspect MCP tools and return a health verdict."},
                    ],
                },
                "timeline": [
                    {
                        "t": now,
                        "type": "ai_healthcheck",
                        "source": "operator",
                        "metric": "ai_healthcheck",
                        "value": 1,
                        "score": 0,
                        "confidence": 0,
                        "summary": "AI healthcheck requested.",
                    }
                ],
                "notes": [],
                "dashboard_visual_context": self.dashboard_visual_context_locked(now, has_image=bool(attachments)),
                "image_attachments": attachments,
                "visual_input_status": {
                    "requested": requested_attachment_count,
                    "accepted": len(attachments),
                    "attached_to_agent_request": bool(attachments),
                    "updated_at": now,
                },
                "ai_investigation": {
                    "status": "running",
                    "started_at": now,
                    "updated_at": now,
                },
            }
            self.incidents.append(incident)
            self.active_by_type[incident["type"]] = incident["id"]
            self.active_by_fingerprint[incident["fingerprint"]] = incident["id"]
            incident_copy = dict(incident)
            self._publish_locked({"type": "incident", "incident": incident})
            self.persist_incident(incident)

        threading.Thread(
            target=self._run_ai_investigation_thread,
            args=(incident["id"], incident_copy, stream, settings),
            daemon=True,
        ).start()
        return True, "started", incident

    def ensure_ai_chat_session(self, incident_id: str) -> tuple[bool, str, dict[str, Any] | None]:
        with self.lock:
            incident = next((item for item in self.incidents if item["id"] == incident_id), None)
            if incident is None:
                return False, "incident not found", None
            existing = dict(incident.get("ai_investigation") or {})
            if existing.get("chat_id") and existing.get("model_id"):
                return True, "ready", dict(incident)

        try:
            agent = WhatareyatalkinaboutClient()
            model_id = existing.get("model_id") or agent.ensure_model()
            mcp_ids = existing.get("mcp_ids") or agent.ensure_mcp_ids()
            chat_id = existing.get("chat_id") or agent.create_chat(incident_id, model_id, mcp_ids)
        except AIAgentError as error:
            return False, str(error), None

        now = int(time.time())
        with self.lock:
            incident = next((item for item in self.incidents if item["id"] == incident_id), None)
            if incident is None:
                return False, "incident not found", None
            incident["ai_investigation"] = {
                **incident.get("ai_investigation", {}),
                "status": incident.get("ai_investigation", {}).get("status", "chat_ready"),
                "chat_id": chat_id,
                "model_id": model_id,
                "mcp_ids": mcp_ids,
                "updated_at": now,
            }
            if incident.get("investigation") and incident["investigation"].get("state") not in {"ai_inference", "ai_complete"}:
                incident["investigation"]["state"] = "ai_chat_ready"
                incident["investigation"]["updated_at"] = now
            self._publish_locked({"type": "incident", "incident": incident})
            self.persist_incident(incident)
            return True, "ready", dict(incident)

    def dashboard_visual_context_locked(self, now: int, window_seconds: int = 900, has_image: bool = False) -> dict[str, Any]:
        points = [point for point in self.points if int(point.get("t", 0)) >= now - window_seconds]
        series_summary: dict[str, dict[str, float]] = {}
        for metric in QUERIES:
            values = [float(point.get(metric, 0) or 0) for point in points if metric in point]
            if not values:
                continue
            series_summary[metric] = {
                "last": round(values[-1], 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "avg": round(sum(values) / len(values), 3),
            }
        return {
            "kind": "dashboard_textual_surrogate",
            "window_seconds": window_seconds,
            "points": len(points),
            "image_attached": has_image,
            "note": "Text summary of the dashboard chart; when image_attached=true the AI request also contains a PNG screenshot of the visible chart.",
            "series_summary": series_summary,
        }

    def _run_ai_investigation_thread(
        self,
        incident_id: str,
        incident: dict[str, Any],
        stream: list[dict[str, float]],
        settings: dict[str, Any],
    ) -> None:
        try:
            result = run_ai_investigation(
                incident,
                stream,
                settings,
                existing_session=incident.get("ai_investigation"),
            )
        except AIAgentError as error:
            result = {"status": "failed", "updated_at": int(time.time()), "error": str(error)}
        except Exception as error:
            result = {"status": "failed", "updated_at": int(time.time()), "error": f"unexpected AI investigation error: {error}"}
        with self.lock:
            current = next((item for item in self.incidents if item["id"] == incident_id), None)
            if current is None:
                return
            current["ai_investigation"] = {**current.get("ai_investigation", {}), **result}
            if result.get("status") == "complete":
                current["ai_verdict"] = result.get("verdict")
                if current.get("investigation"):
                    current["investigation"]["state"] = "ai_complete"
                    current["investigation"]["phase"] = "ai_verdict_ready"
                    current["investigation"]["progress"] = 100
                    current["investigation"]["summary"] = str(result.get("verdict", {}).get("verdict", "AI verdict is ready."))
                    current["investigation"]["updated_at"] = int(time.time())
            elif current.get("investigation"):
                current["investigation"]["state"] = "ai_failed"
                current["investigation"]["phase"] = "ai_unavailable"
                current["investigation"]["updated_at"] = int(time.time())
            self._publish_locked({"type": "incident", "incident": current})
            self.persist_incident(current)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "source": "prometheus-postgres",
                "generated_at": int(time.time()),
                "stream": list(self.points),
                "detections": list(self.detections),
                "signals": list(self.signals),
                "incidents": list(self.incidents),
                "operational_events": list(self.operational_events),
                "settings": self.settings,
                "experiments": list(self.experiments),
                "experiment_settings": EXPERIMENT_SETTINGS,
                "detectors": detector_catalog(self.enabled_detector_ids),
                "ai_agent": {
                    "enabled": ai_agent_enabled(),
                    "base_url": os.environ.get("AI_AGENT_BASE_URL", ""),
                    "model": os.environ.get("LLM_MODEL") or os.environ.get("AI_AGENT_MODEL_NAME", ""),
                    "mcp_url": os.environ.get("AI_AGENT_MCP_URL", ""),
                },
                "load": self.load_status_locked(),
                "retention": {
                    "telemetry_points": self.points.maxlen,
                    "detections": self.detections.maxlen,
                    "signals": self.signals.maxlen,
                    "incidents": self.incidents.maxlen,
                    "disk_policy": "backend keeps rolling memory only; Prometheus retention is configured in infra/docker-compose.yml",
                },
            }

    def set_enabled_detectors(self, detector_ids: list[str]) -> tuple[bool, str, list[dict[str, Any]]]:
        known_ids = {item["id"] for item in detector_catalog()}
        requested = {str(item) for item in detector_ids if str(item)}
        unknown = requested - known_ids
        if requested and unknown:
            return False, f"unknown detector ids: {', '.join(sorted(unknown))}", detector_catalog(self.enabled_detector_ids)
        with self.lock:
            self.enabled_detector_ids = requested or None
            catalog = detector_catalog(self.enabled_detector_ids)
            self._publish_locked({"type": "detectors", "detectors": catalog})
            return True, "updated", catalog

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        client: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self.lock:
            self.clients.append(client)
        return client

    def unsubscribe(self, client: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def _publish_locked(self, event: dict[str, Any]) -> None:
        alive = []
        for client in self.clients:
            try:
                client.put_nowait(event)
                alive.append(client)
            except queue.Full:
                pass
        self.clients = alive

    def start_load(self, config: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            if self.load_process and self.load_process.poll() is None:
                return False, "load is already running"
        args, workload = self.workload_args(config)
        env = os.environ.copy()
        if os.environ.get("PGPASSWORD"):
            env["PGPASSWORD"] = os.environ["PGPASSWORD"]
        process = subprocess.Popen(
            args,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        with self.lock:
            self.load_process = process
            self.load_started_at = int(time.time())
            self.load_config = workload
            self.load_script_path = workload.get("script_path")
            self.load_output.clear()
            self._publish_locked({"type": "load", "load": self.load_status_locked()})
        threading.Thread(target=self.capture_load_output, args=(process,), daemon=True).start()
        return True, "started"

    def capture_load_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            with self.lock:
                self.load_output.append(line.rstrip())
        process.wait()
        with self.lock:
            script_path = self.load_script_path
            self.load_script_path = None
        if script_path:
            try:
                Path(script_path).unlink(missing_ok=True)
            except OSError:
                pass
        with self.lock:
            self._publish_locked({"type": "load", "load": self.load_status_locked()})

    def workload_args(self, config: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        engine = str(config.get("engine", "pgbench"))
        if engine != "pgbench":
            raise ValueError(f"unsupported workload engine: {engine}")
        clients = max(1, min(512, int(config.get("clients", 32))))
        jobs = max(1, min(128, int(config.get("jobs", min(clients, 4)))))
        seconds = max(1, min(86400, int(config.get("seconds", 60))))
        mode = str(config.get("mode", "mixed"))
        rate = max(0, min(100000, int(config.get("rate", 0))))
        script = str(config.get("script", "default"))
        workload = {
            "engine": engine,
            "profile": str(config.get("profile", "custom")),
            "script": script,
            "clients": clients,
            "jobs": jobs,
            "seconds": seconds,
            "mode": mode,
            "rate": rate,
        }
        if script in PGBENCH_CUSTOM_SCRIPTS:
            script_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=f"-{script}.sql", encoding="utf-8")
            script_file.write(PGBENCH_CUSTOM_SCRIPTS[script].strip() + "\n")
            script_file.close()
            workload["script_path"] = script_file.name
        return self.pgbench_args(workload), workload

    def pgbench_args(self, workload: dict[str, Any]) -> list[str]:
        clients = int(workload["clients"])
        jobs = int(workload["jobs"])
        seconds = int(workload["seconds"])
        mode = str(workload["mode"])
        rate = int(workload.get("rate", 0))
        script = str(workload.get("script", "default"))
        script_path = str(workload.get("script_path", ""))
        pgbench = shutil.which("pgbench")
        if pgbench:
            args = [
                pgbench,
                "-h",
                os.environ.get("PGHOST", "127.0.0.1"),
                "-p",
                os.environ.get("PGPORT", "55432"),
                "-U",
                os.environ.get("PGUSER", "cockpit"),
                "-c",
                str(clients),
                "-j",
                str(jobs),
                "-T",
                str(seconds),
                "-P",
                "5",
            ]
            if rate > 0:
                args += ["-R", str(rate)]
            if script_path:
                args += ["-f", script_path]
            elif script == "simple_update":
                args += ["-b", "simple-update"]
            elif script == "select_only" or mode == "readonly":
                args.append("-S")
            args.append(os.environ.get("PGDATABASE", "cockpit"))
            return args
        args = [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "exec",
            "-T",
            "postgres",
            "pgbench",
        ]
        args += ["-c", str(clients), "-j", str(jobs), "-T", str(seconds), "-P", "5"]
        if rate > 0:
            args += ["-R", str(rate)]
        if script == "simple_update":
            args += ["-b", "simple-update"]
        elif script == "select_only" or mode == "readonly":
            args.append("-S")
        args += ["-U", "cockpit", "cockpit"]
        return args

    def stop_load(self) -> tuple[bool, str]:
        with self.lock:
            process = self.load_process
        if not process or process.poll() is not None:
            return False, "no running load"
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        with self.lock:
            script_path = self.load_script_path
            self.load_script_path = None
        if script_path:
            try:
                Path(script_path).unlink(missing_ok=True)
            except OSError:
                pass
        with self.lock:
            self._publish_locked({"type": "load", "load": self.load_status_locked()})
        return True, "stopped"

    def load_status_locked(self) -> dict[str, Any]:
        running = bool(self.load_process and self.load_process.poll() is None)
        config = dict(self.load_config or {})
        config.pop("script_path", None)
        return {
            "running": running,
            "started_at": self.load_started_at if running else None,
            "returncode": None if running or not self.load_process else self.load_process.returncode,
            "config": config or None,
            "output": list(self.load_output)[-10:],
        }


def poll_prometheus(store: TelemetryStore, interval: float, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            now = int(time.time())
            point: dict[str, float] = {"t": float(now)}
            for name, expr in QUERIES.items():
                point[name] = round(query_prometheus(expr), 3)
            store.add_point(point)
            store.add_operational_events_from_point(point)
            store.add_settings_snapshot(query_settings(), now)
            store.collect_query_fingerprint_snapshot(now)
        except Exception as error:
            print(f"telemetry poll failed: {error}", flush=True)
        stop.wait(interval)


class Handler(SimpleHTTPRequestHandler):
    store: TelemetryStore

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        request_path = parsed.path
        if request_path == "/":
            request_path = "/live.html"
        return str(WEB_ROOT / request_path.lstrip("/"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            self.write_json(self.store.snapshot())
            return
        if parsed.path == "/api/detectors":
            self.write_json({"ok": True, "detectors": self.store.snapshot()["detectors"]})
            return
        if parsed.path.startswith("/api/incidents/"):
            incident_id = parsed.path.removeprefix("/api/incidents/")
            incident = self.store.get_incident(incident_id)
            if incident is None:
                self.write_json({"ok": False, "message": "incident not found"}, status=404)
                return
            self.write_json({"ok": True, "incident": incident})
            return
        if parsed.path.startswith("/api/chats/") and parsed.path.endswith("/messages"):
            incident_id = parsed.path.removeprefix("/api/chats/").removesuffix("/messages")
            self.handle_chat_messages(incident_id)
            return
        if parsed.path == "/events":
            self.handle_events()
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/load/start":
            payload = self.read_json()
            try:
                ok, message = self.store.start_load(payload)
                status = 200 if ok else 409
            except (TypeError, ValueError) as error:
                ok, message, status = False, str(error), 400
            self.write_json({"ok": ok, "message": message, "load": self.store.snapshot()["load"]}, status=status)
            return
        if parsed.path == "/api/load/stop":
            ok, message = self.store.stop_load()
            self.write_json({"ok": ok, "message": message, "load": self.store.snapshot()["load"]}, status=200 if ok else 409)
            return
        if parsed.path == "/api/incidents/status":
            payload = self.read_json()
            ok, message, incident = self.store.update_incident_status(
                str(payload.get("id", "")),
                str(payload.get("status", "")),
                str(payload.get("note", "")),
            )
            self.write_json({"ok": ok, "message": message, "incident": incident}, status=200 if ok else 400)
            return
        if parsed.path == "/api/incidents/ai":
            payload = self.read_json()
            ok, message, incident = self.store.start_ai_investigation(
                str(payload.get("id", "")),
                list(payload.get("image_attachments", [])),
            )
            status = 200 if ok else 404 if message == "incident not found" else 409
            self.write_json({"ok": ok, "message": message, "incident": incident}, status=status)
            return
        if parsed.path == "/api/ai/healthcheck":
            payload = self.read_json()
            ok, message, incident = self.store.start_ai_healthcheck(list(payload.get("image_attachments", [])))
            self.write_json({"ok": ok, "message": message, "incident": incident}, status=200 if ok else 409)
            return
        if parsed.path == "/api/incidents/chat/stream":
            payload = self.read_json()
            self.handle_incident_chat_stream(
                str(payload.get("id", "")),
                str(payload.get("message", "")),
            )
            return
        if parsed.path == "/api/detectors":
            payload = self.read_json()
            ok, message, detectors = self.store.set_enabled_detectors(list(payload.get("enabled_detector_ids", [])))
            self.write_json({"ok": ok, "message": message, "detectors": detectors}, status=200 if ok else 400)
            return
        if parsed.path == "/api/experiments/apply":
            payload = self.read_json()
            ok, message, experiment = self.store.apply_setting_experiment(
                str(payload.get("setting", "")),
                str(payload.get("value", "")),
            )
            self.write_json({"ok": ok, "message": message, "experiment": experiment}, status=200 if ok else 400)
            return
        if parsed.path == "/api/experiments/rollback":
            payload = self.read_json()
            ok, message, experiment = self.store.rollback_setting_experiment(str(payload.get("id", "")))
            self.write_json({"ok": ok, "message": message, "experiment": experiment}, status=200 if ok else 400)
            return
        self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def write_sse_event(self, event: dict[str, Any]) -> None:
        self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def handle_incident_chat_stream(self, incident_id: str, message: str) -> None:
        if not message.strip():
            self.write_json({"ok": False, "message": "message is required"}, status=400)
            return
        if not ai_agent_enabled():
            self.write_json({"ok": False, "message": "AI agent backend is not configured"}, status=409)
            return
        ok, status_message, incident = self.store.ensure_ai_chat_session(incident_id)
        if not ok or not incident:
            self.write_json({"ok": False, "message": status_message}, status=404 if status_message == "incident not found" else 409)
            return
        chat_id = str(incident.get("ai_investigation", {}).get("chat_id", ""))
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.write_sse_event({"type": "cockpit_status", "status": "connected", "chat_id": chat_id, "incident_id": incident_id})
        try:
            agent = WhatareyatalkinaboutClient(timeout=float(os.environ.get("AI_AGENT_STREAM_TIMEOUT", "300")))
            for line in agent.stream_completion_lines(chat_id, message):
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
        except Exception as error:
            self.write_sse_event({"type": "error", "error": str(error)})

    def handle_chat_messages(self, incident_id: str) -> None:
        incident = self.store.get_incident(incident_id)
        if incident is None:
            self.write_json({"ok": False, "message": "incident not found"}, status=404)
            return
        chat_id = str(incident.get("ai_investigation", {}).get("chat_id") or "")
        if not chat_id:
            self.write_json({"ok": True, "messages": []})
            return
        try:
            messages = WhatareyatalkinaboutClient(timeout=30).get_messages(chat_id)
        except AIAgentError as error:
            self.write_json({"ok": False, "message": str(error)}, status=409)
            return
        mapped: list[dict[str, Any]] = []
        for item in messages:
            role = str(item.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            content_type = str(item.get("content_type") or "text")
            content = str(item.get("content") or "")
            if content_type == "multimodal":
                try:
                    parts = json.loads(content)
                    content = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict) and part.get("type") == "text")
                except json.JSONDecodeError:
                    pass
            if not content.strip():
                continue
            mapped.append(
                {
                    "role": role,
                    "content": content,
                    "meta": "history",
                    "t": int(time.time()),
                }
            )
        self.write_json({"ok": True, "messages": mapped[-80:]})

    def handle_events(self) -> None:
        client = self.store.subscribe()
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            snapshot = {"type": "snapshot", "snapshot": self.store.snapshot()}
            self.write_sse(snapshot)
            while True:
                try:
                    event = client.get(timeout=15)
                    self.write_sse(event)
                except queue.Empty:
                    self.write_sse({"type": "heartbeat", "t": int(time.time())})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.store.unsubscribe(client)

    def write_sse(self, payload: dict[str, Any]) -> None:
        self.wfile.write(b"data: ")
        self.wfile.write(json.dumps(payload).encode("utf-8"))
        self.wfile.write(b"\n\n")
        self.wfile.flush()

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args: Any) -> None:
        if self.path == "/events":
            return
        super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--max-points", type=int, default=720)
    parser.add_argument("--max-detections", type=int, default=200)
    parser.add_argument("--no-persistence", action="store_true")
    args = parser.parse_args()

    persistence: Persistence = NoopPersistence()
    if not args.no_persistence and os.environ.get("COCKPIT_PERSISTENCE", "postgres") != "off":
        try:
            persistence = PostgresPersistence()
            persistence.ensure_schema()
            print("Cockpit persistence: postgres incident/signal/verdict storage enabled.")
        except Exception as error:
            print(f"Cockpit persistence disabled: {error}", flush=True)
            persistence = NoopPersistence()

    store = TelemetryStore(max_points=args.max_points, max_detections=args.max_detections, persistence=persistence)
    store.hydrate_from_persistence(args.max_detections)
    Handler.store = store
    stop = threading.Event()
    poller = threading.Thread(target=poll_prometheus, args=(store, args.interval, stop), daemon=True)
    poller.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Cockpit backend: http://{args.host}:{args.port}")
    print("Telemetry retention: rolling memory window; incidents/signals/verdicts persist in Postgres when available.")
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()

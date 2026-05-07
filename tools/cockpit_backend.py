from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from live_pg_monitor import QUERIES, query_prometheus, query_settings


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web_cockpit"
COMPOSE_FILE = ROOT / "infra" / "docker-compose.yml"


DETECTORS: list[dict[str, Any]] = [
    {
        "id": "rules.postgres.high_concurrency.v1",
        "name": "High concurrency detector",
        "engine": "rules",
        "future_engine": "ml_ready",
        "type": "high_concurrency",
        "metric": "active_connections",
        "operator": ">=",
        "threshold": 24,
        "severity": "warning",
        "summary": "Active database concurrency is elevated.",
        "candidate_root": "workload_concurrency_spike",
    },
    {
        "id": "rules.postgres.wait_contention.v1",
        "name": "Wait contention detector",
        "engine": "rules",
        "future_engine": "ml_ready",
        "type": "wait_contention",
        "metric": "waiting_connections",
        "operator": ">=",
        "threshold": 2,
        "severity": "warning",
        "summary": "Postgres sessions are waiting; inspect locks, IO, and concurrent workload.",
        "candidate_root": "lock_or_resource_contention",
    },
    {
        "id": "rules.postgres.read_io_pressure.v1",
        "name": "Read IO pressure detector",
        "engine": "rules",
        "future_engine": "ml_ready",
        "type": "read_io_pressure",
        "metric": "blk_read_time_ms_rate",
        "operator": ">=",
        "threshold": 50,
        "severity": "critical",
        "summary": "Block read time is rising; possible storage pressure.",
        "candidate_root": "storage_read_pressure",
    },
    {
        "id": "rules.postgres.vacuum_pressure.v1",
        "name": "Vacuum pressure detector",
        "engine": "rules",
        "future_engine": "ml_ready",
        "type": "vacuum_pressure",
        "metric": "vacuum_max_elapsed_seconds",
        "operator": ">=",
        "threshold": 30,
        "severity": "warning",
        "summary": "A long-running VACUUM is active and may be competing for IO or locks.",
        "candidate_root": "manual_or_autovacuum_resource_pressure",
    },
]


def detection_confidence(value: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.5
    ratio = value / threshold
    return round(min(0.98, max(0.55, 0.55 + (ratio - 1) * 0.22)), 2)


def build_hypotheses(detection: dict[str, Any], point: dict[str, float]) -> list[dict[str, Any]]:
    kind = detection["type"]
    active = point.get("active_connections", 0)
    waiting = point.get("waiting_connections", 0)
    read_time = point.get("blk_read_time_ms_rate", 0)
    read_blocks = point.get("read_blocks_rate", 0)
    vacuum_elapsed = point.get("vacuum_max_elapsed_seconds", 0)
    vacuum_sessions = point.get("active_vacuum_sessions", 0) + point.get("active_autovacuum_sessions", 0)
    if kind == "high_concurrency":
        return [
            {
                "cause": "pgbench_or_application_load_spike",
                "score": 0.72 if active >= 24 else 0.45,
                "why": "Active sessions crossed the concurrency threshold while the load generator may be running.",
            },
            {
                "cause": "connection_pool_misconfiguration",
                "score": 0.43,
                "why": "High active count can also come from missing pool limits or bursty client pools.",
            },
        ]
    if kind == "wait_contention":
        return [
            {
                "cause": "lock_contention_or_slow_queries",
                "score": 0.76 if waiting >= 2 else 0.4,
                "why": "Waiting sessions appeared; lock waits and slow query pressure are the first checks.",
            },
            {
                "cause": "downstream_resource_saturation",
                "score": 0.58 if read_time >= 50 else 0.34,
                "why": "Waits can be amplified by IO pressure or saturated database workers.",
            },
        ]
    if kind == "vacuum_pressure":
        return [
            {
                "cause": "manual_vacuum_or_autovacuum_overlap",
                "score": 0.8 if vacuum_elapsed >= 30 else 0.42,
                "why": "VACUUM is active during the incident window and can compete for IO, locks, and buffer cache.",
            },
            {
                "cause": "maintenance_window_misconfiguration",
                "score": 0.58 if vacuum_sessions > 0 else 0.25,
                "why": "Maintenance work appears during foreground workload; check DBA operations and autovacuum settings.",
            },
        ]
    return [
        {
            "cause": "storage_or_cache_pressure",
            "score": 0.78 if read_time >= 50 else 0.4,
            "why": "Read timing rose together with database IO counters.",
        },
        {
            "cause": "working_set_shift",
            "score": 0.49 if read_blocks > 0 else 0.28,
            "why": "A larger working set can reduce cache locality and increase physical reads.",
        },
    ]


def build_causal_chain(detection: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"stage": "symptom", "label": detection["metric"], "detail": f"{detection['value']} >= {detection['threshold']}"},
        {"stage": "candidate cause", "label": detection["candidate_root"], "detail": "ranked from current evidence"},
        {"stage": "impact", "label": detection["type"], "detail": detection["summary"]},
    ]


def build_investigation(detection: dict[str, Any], sample_count: int = 1) -> dict[str, Any]:
    progress = min(88, 18 + sample_count * 12)
    if sample_count <= 1:
        phase = "collecting_evidence"
        summary = "Collecting telemetry around the anomaly window."
    elif sample_count <= 3:
        phase = "ranking_hypotheses"
        summary = "Ranking competing root-cause hypotheses from current evidence."
    else:
        phase = "awaiting_feedback"
        summary = "Draft explanation is ready; operator feedback or richer telemetry can improve confidence."
    steps = [
        {
            "id": "capture_window",
            "label": "Capture anomaly window",
            "status": "done",
            "detail": f"{detection['metric']} crossed {detection['threshold']}.",
        },
        {
            "id": "collect_evidence",
            "label": "Collect supporting and negative evidence",
            "status": "running" if sample_count <= 1 else "done",
            "detail": "Read active sessions, waits, IO timing, throughput, and contextual counters.",
        },
        {
            "id": "rank_hypotheses",
            "label": "Run causal inference",
            "status": "pending" if sample_count <= 1 else "running" if sample_count <= 3 else "done",
            "detail": "Score hypotheses with rule constraints now; later this slot can be ML/AI-ranked.",
        },
        {
            "id": "operator_review",
            "label": "Wait for operator review",
            "status": "pending" if sample_count <= 3 else "running",
            "detail": "Confirm, reject, or enrich the proposed explanation.",
        },
    ]
    return {
        "state": "running" if phase != "awaiting_feedback" else "needs_review",
        "phase": phase,
        "progress": progress,
        "engine": {
            "mode": "hybrid_inference",
            "current": "rules_and_graph_scoring_stub",
            "future": "ml_model_or_ai_agent",
        },
        "summary": summary,
        "started_at": detection["t"],
        "updated_at": detection["t"],
        "steps": steps,
        "next_actions": [
            "Open related query fingerprints.",
            "Compare baseline versus incident window.",
            "Collect lock/wait-event breakdown before final root-cause confirmation.",
        ],
    }


def evaluate_detectors(point: dict[str, float]) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    for detector in DETECTORS:
        value = point.get(detector["metric"], 0)
        threshold = detector["threshold"]
        if value < threshold:
            continue
        detection = {
            "t": int(point["t"]),
            "type": detector["type"],
            "severity": detector["severity"],
            "metric": detector["metric"],
            "value": value,
            "threshold": threshold,
            "summary": detector["summary"],
            "candidate_root": detector["candidate_root"],
            "confidence": detection_confidence(value, threshold),
            "detector": {
                "id": detector["id"],
                "name": detector["name"],
                "engine": detector["engine"],
                "future_engine": detector["future_engine"],
            },
            "evidence": [
                {"metric": detector["metric"], "value": value, "threshold": threshold, "direction": detector["operator"]},
                {"metric": "active_connections", "value": point.get("active_connections", 0), "role": "context"},
                {"metric": "waiting_connections", "value": point.get("waiting_connections", 0), "role": "context"},
                {"metric": "blk_read_time_ms_rate", "value": point.get("blk_read_time_ms_rate", 0), "role": "context"},
                {"metric": "active_vacuum_sessions", "value": point.get("active_vacuum_sessions", 0), "role": "operational_context"},
                {"metric": "active_autovacuum_sessions", "value": point.get("active_autovacuum_sessions", 0), "role": "operational_context"},
                {"metric": "vacuum_max_elapsed_seconds", "value": point.get("vacuum_max_elapsed_seconds", 0), "role": "operational_context"},
                {"metric": "config_reload_time", "value": point.get("config_reload_time", 0), "role": "operational_context"},
            ],
        }
        detection["hypotheses"] = build_hypotheses(detection, point)
        detection["causal_chain"] = build_causal_chain(detection)
        detections.append(detection)
    return detections


class TelemetryStore:
    def __init__(self, max_points: int = 720, max_detections: int = 200) -> None:
        self.points: deque[dict[str, float]] = deque(maxlen=max_points)
        self.detections: deque[dict[str, Any]] = deque(maxlen=max_detections)
        self.incidents: deque[dict[str, Any]] = deque(maxlen=max_detections)
        self.operational_events: deque[dict[str, Any]] = deque(maxlen=300)
        self.settings: dict[str, dict[str, str]] = {}
        self.last_config_reload_time: float | None = None
        self.active_by_type: dict[str, str] = {}
        self.clients: list[queue.Queue[dict[str, Any]]] = []
        self.lock = threading.Lock()
        self.load_process: subprocess.Popen[str] | None = None
        self.load_started_at: int | None = None
        self.load_output: deque[str] = deque(maxlen=40)

    def add_point(self, point: dict[str, float]) -> None:
        events: list[dict[str, Any]] = [{"type": "telemetry", "point": point}]
        detections = evaluate_detectors(point)
        seen_types = {detection["type"] for detection in detections}
        with self.lock:
            self.points.append(point)
            for detection in detections:
                self.detections.append(detection)
                incident = self.upsert_incident_locked(detection)
                events.append({"type": "detection", "detection": detection})
                events.append({"type": "incident", "incident": incident})
            for incident in self.incidents:
                if incident["status"] == "open" and incident["type"] not in seen_types:
                    incident["quiet_samples"] = int(incident.get("quiet_samples", 0)) + 1
                    if incident["quiet_samples"] >= 3:
                        incident["status"] = "resolved"
                        incident["resolved_at"] = int(point["t"])
                        self.active_by_type.pop(incident["type"], None)
                        events.append({"type": "incident", "incident": incident})
            for event in events:
                self._publish_locked(event)

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

    def upsert_incident_locked(self, detection: dict[str, Any]) -> dict[str, Any]:
        incident_id = self.active_by_type.get(detection["type"])
        incident = next((item for item in self.incidents if item["id"] == incident_id), None)
        related_events = self.related_operational_events_locked(detection["t"])
        if incident is None:
            investigation = build_investigation(detection, 1)
            incident = {
                "id": f"inc-{detection['type']}-{detection['t']}",
                "type": detection["type"],
                "severity": detection["severity"],
                "status": "open",
                "created_at": detection["t"],
                "last_seen_at": detection["t"],
                "quiet_samples": 0,
                "sample_count": 1,
                "summary": detection["summary"],
                "metric": detection["metric"],
                "value": detection["value"],
                "threshold": detection["threshold"],
                "confidence": detection["confidence"],
                "detector": detection["detector"],
                "evidence": detection["evidence"],
                "operational_events": related_events,
                "hypotheses": detection["hypotheses"],
                "causal_chain": detection["causal_chain"],
                "investigation": investigation,
                "notes": [],
            }
            self.incidents.append(incident)
            self.active_by_type[detection["type"]] = incident["id"]
            return incident
        sample_count = int(incident.get("sample_count", 0)) + 1
        investigation = build_investigation(detection, sample_count)
        investigation["started_at"] = incident.get("investigation", {}).get("started_at", incident["created_at"])
        incident.update(
            {
                "severity": detection["severity"],
                "status": "open",
                "last_seen_at": detection["t"],
                "quiet_samples": 0,
                "sample_count": sample_count,
                "summary": detection["summary"],
                "metric": detection["metric"],
                "value": detection["value"],
                "threshold": detection["threshold"],
                "confidence": detection["confidence"],
                "detector": detection["detector"],
                "evidence": detection["evidence"],
                "operational_events": related_events,
                "hypotheses": detection["hypotheses"],
                "causal_chain": detection["causal_chain"],
                "investigation": investigation,
            }
        )
        return incident

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
            elif status == "open":
                self.active_by_type[incident["type"]] = incident["id"]
            self._publish_locked({"type": "incident", "incident": incident})
            return True, "updated", incident

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "source": "prometheus-postgres",
                "generated_at": int(time.time()),
                "stream": list(self.points),
                "detections": list(self.detections),
                "incidents": list(self.incidents),
                "operational_events": list(self.operational_events),
                "settings": self.settings,
                "detectors": DETECTORS,
                "load": self.load_status_locked(),
                "retention": {
                    "telemetry_points": self.points.maxlen,
                    "detections": self.detections.maxlen,
                    "incidents": self.incidents.maxlen,
                    "disk_policy": "backend keeps rolling memory only; Prometheus retention is configured in infra/docker-compose.yml",
                },
            }

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

    def start_load(self, clients: int, jobs: int, seconds: int, mode: str) -> tuple[bool, str]:
        with self.lock:
            if self.load_process and self.load_process.poll() is None:
                return False, "load is already running"
        args = self.pgbench_args(clients, jobs, seconds, mode)
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
            self._publish_locked({"type": "load", "load": self.load_status_locked()})

    def pgbench_args(self, clients: int, jobs: int, seconds: int, mode: str) -> list[str]:
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
            if mode == "readonly":
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
        if mode == "readonly":
            args.append("-S")
        args += ["-c", str(clients), "-j", str(jobs), "-T", str(seconds), "-P", "5", "-U", "cockpit", "cockpit"]
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
            self._publish_locked({"type": "load", "load": self.load_status_locked()})
        return True, "stopped"

    def load_status_locked(self) -> dict[str, Any]:
        running = bool(self.load_process and self.load_process.poll() is None)
        return {
            "running": running,
            "started_at": self.load_started_at if running else None,
            "returncode": None if running or not self.load_process else self.load_process.returncode,
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
        if parsed.path.startswith("/api/incidents/"):
            incident_id = parsed.path.removeprefix("/api/incidents/")
            incident = self.store.get_incident(incident_id)
            if incident is None:
                self.write_json({"ok": False, "message": "incident not found"}, status=404)
                return
            self.write_json({"ok": True, "incident": incident})
            return
        if parsed.path == "/events":
            self.handle_events()
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/load/start":
            payload = self.read_json()
            clients = int(payload.get("clients", 32))
            jobs = int(payload.get("jobs", 4))
            seconds = int(payload.get("seconds", 60))
            mode = str(payload.get("mode", "mixed"))
            ok, message = self.store.start_load(clients, jobs, seconds, mode)
            self.write_json({"ok": ok, "message": message, "load": self.store.snapshot()["load"]}, status=200 if ok else 409)
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
    args = parser.parse_args()

    store = TelemetryStore(max_points=args.max_points, max_detections=args.max_detections)
    Handler.store = store
    stop = threading.Event()
    poller = threading.Thread(target=poll_prometheus, args=(store, args.interval, stop), daemon=True)
    poller.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Cockpit backend: http://{args.host}:{args.port}")
    print("Telemetry retention: rolling memory window only; Prometheus keeps its own 2d TSDB retention.")
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()

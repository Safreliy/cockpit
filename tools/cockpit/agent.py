from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol


class LLMClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any]) -> dict[str, Any]:
        ...


class AgentTool(Protocol):
    name: str
    description: str

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class VerdictSink(Protocol):
    def submit_verdict(self, incident_id: str, verdict: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL") or "Qwen3.5-122B-A10B-AWQ-8bit"
        self.timeout = timeout

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"LLM request failed: {error}") from error
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise RuntimeError("LLM returned non-JSON content") from error


class JsonMemoryStore:
    def __init__(self, path: Path, max_facts: int = 80) -> None:
        self.path = path
        self.max_facts = max_facts

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        facts = payload.get("facts", [])
        return facts if isinstance(facts, list) else []

    def append(self, fact: dict[str, Any]) -> None:
        facts = self.load()
        facts.append({"t": int(time.time()), **fact})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"facts": facts[-self.max_facts :]}, indent=2), encoding="utf-8")


class SnapshotTool:
    name = "monitoring.snapshot"
    description = "Read compact cockpit snapshot, including current and historical incidents."

    def __init__(self, snapshot_provider: Any) -> None:
        self.snapshot_provider = snapshot_provider

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.snapshot_provider()
        limit = int(arguments.get("limit", 80))
        return {
            "stream": snapshot.get("stream", [])[-limit:],
            "incidents": snapshot.get("incidents", [])[-30:],
            "signals": snapshot.get("signals", [])[-80:],
            "settings": snapshot.get("settings", {}),
            "load": snapshot.get("load"),
        }


class OperationalContextTool:
    name = "monitoring.operational_context"
    description = "Read DBA changes, config reloads, experiments, and maintenance events around an incident window."

    def __init__(self, snapshot_provider: Any) -> None:
        self.snapshot_provider = snapshot_provider

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.snapshot_provider()
        center = int(arguments.get("t", snapshot.get("generated_at", 0)))
        window = int(arguments.get("window_seconds", 900))
        def near(item: dict[str, Any]) -> bool:
            return abs(int(item.get("t", 0)) - center) <= window
        return {
            "operational_events": [item for item in snapshot.get("operational_events", []) if near(item)][-30:],
            "experiments": [item for item in snapshot.get("experiments", []) if near(item)][-30:],
        }


class IncidentVerdictTool:
    name = "incident.submit_causal_verdict"
    description = "Submit causal-chain verdict for an incident with evidence and confidence."

    def __init__(self, sink: VerdictSink) -> None:
        self.sink = sink

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.sink.submit_verdict(str(arguments["incident_id"]), arguments["verdict"])


class CausalAgent:
    def __init__(
        self,
        llm: LLMClient,
        tools: list[AgentTool],
        memory: JsonMemoryStore,
        max_context_chars: int = 18000,
    ) -> None:
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}
        self.memory = memory
        self.max_context_chars = max_context_chars

    def investigate(self, incident: dict[str, Any]) -> dict[str, Any]:
        started_at = int(time.time())
        trace: list[dict[str, Any]] = []
        snapshot_context = self.tools["monitoring.snapshot"].call({"limit": 120})
        trace.append({"tool": "monitoring.snapshot", "status": "ok"})
        operational_context = self.tools["monitoring.operational_context"].call(
            {"t": incident.get("last_seen_at") or incident.get("created_at"), "window_seconds": 1800}
        )
        trace.append({"tool": "monitoring.operational_context", "status": "ok"})
        memory_facts = self.memory.load()[-20:]
        context = {
            "incident": incident,
            "snapshot_context": snapshot_context,
            "operational_context": operational_context,
            "long_term_memory": memory_facts,
        }
        compacted = self.compact_context(context)
        verdict = self.ask_llm_or_fallback(compacted, incident, operational_context)
        verdict.setdefault("incident_id", incident["id"])
        verdict.setdefault("generated_at", int(time.time()))
        verdict.setdefault("engine", self.engine_name())
        verdict.setdefault("trace", trace)
        verdict["duration_ms"] = int((time.time() - started_at) * 1000)
        submit_result = self.tools["incident.submit_causal_verdict"].call(
            {"incident_id": incident["id"], "verdict": verdict}
        )
        trace.append({"tool": "incident.submit_causal_verdict", "status": "ok"})
        self.memory.append(
            {
                "kind": "causal_verdict",
                "incident_type": incident.get("type"),
                "root_cause": verdict.get("root_cause"),
                "confidence": verdict.get("confidence"),
            }
        )
        return {"verdict": verdict, "submit_result": submit_result}

    def compact_context(self, context: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(context, ensure_ascii=False)
        if len(encoded) <= self.max_context_chars:
            return context
        incident = context["incident"]
        snapshot = context["snapshot_context"]
        return {
            "incident": incident,
            "snapshot_context": {
                "stream": snapshot.get("stream", [])[-40:],
                "incidents": snapshot.get("incidents", [])[-12:],
                "signals": snapshot.get("signals", [])[-30:],
                "settings": snapshot.get("settings", {}),
                "load": snapshot.get("load"),
                "compacted": True,
            },
            "operational_context": context["operational_context"],
            "long_term_memory": context.get("long_term_memory", [])[-10:],
        }

    def ask_llm_or_fallback(
        self,
        context: dict[str, Any],
        incident: dict[str, Any],
        operational_context: dict[str, Any],
    ) -> dict[str, Any]:
        schema_hint = {
            "root_cause": "string",
            "confidence": "number 0..1",
            "causal_chain": [{"stage": "string", "label": "string", "detail": "string"}],
            "supporting_evidence": ["string"],
            "counter_evidence": ["string"],
            "recommended_actions": ["string"],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a PostgreSQL incident investigation agent. "
                    "Return only JSON. Prefer causal chains grounded in telemetry, DBA changes, workload state, and prior incidents."
                ),
            },
            {"role": "user", "content": json.dumps({"schema": schema_hint, "context": context}, ensure_ascii=False)},
        ]
        try:
            verdict = self.llm.complete_json(messages, schema_hint)
            if isinstance(verdict, dict) and verdict.get("root_cause"):
                verdict["engine"] = self.engine_name()
                return verdict
        except RuntimeError as error:
            return self.fallback_verdict(incident, operational_context, str(error))
        return self.fallback_verdict(incident, operational_context, "LLM returned incomplete verdict")

    def fallback_verdict(self, incident: dict[str, Any], operational_context: dict[str, Any], reason: str) -> dict[str, Any]:
        ops = operational_context.get("operational_events", [])
        root_cause = incident.get("causal_chain", [{}])[1].get("label") if incident.get("causal_chain") else incident.get("type")
        if ops:
            root_cause = ops[-1].get("type", root_cause)
        return {
            "root_cause": root_cause,
            "confidence": incident.get("confidence", 0.55),
            "causal_chain": incident.get("causal_chain", []),
            "supporting_evidence": [
                f"Incident metric {incident.get('metric')}={incident.get('value')}",
                f"Related operational events: {len(ops)}",
            ],
            "counter_evidence": ["LLM inference unavailable; fallback verdict used."],
            "recommended_actions": incident.get("investigation", {}).get("next_actions", []),
            "engine": "fallback",
            "fallback_reason": reason,
        }

    def engine_name(self) -> str:
        return getattr(self.llm, "model", "llm")

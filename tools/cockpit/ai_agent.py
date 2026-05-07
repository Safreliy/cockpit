from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any
from uuid import UUID


DEFAULT_AGENT_USER_ID = "00000000-0000-4000-8000-000000000001"


class AIAgentError(RuntimeError):
    pass


def ai_agent_enabled() -> bool:
    return bool(os.environ.get("AI_AGENT_BASE_URL"))


def compact_incident_context(incident: dict[str, Any], stream: list[dict[str, float]], settings: dict[str, Any]) -> dict[str, Any]:
    started = int(incident.get("started_at") or incident.get("created_at") or 0)
    ended = int(incident.get("resolved_at") or incident.get("last_seen_at") or started)
    left = started - 180
    right = ended + 180
    window = [point for point in stream if left <= int(point.get("t", 0)) <= right][-120:]
    return {
        "incident": {
            "id": incident.get("id"),
            "type": incident.get("type"),
            "status": incident.get("status"),
            "severity": incident.get("severity"),
            "summary": incident.get("summary"),
            "metric": incident.get("metric"),
            "value": incident.get("value"),
            "threshold": incident.get("threshold"),
            "confidence": incident.get("confidence"),
            "started_at": incident.get("started_at"),
            "last_seen_at": incident.get("last_seen_at"),
            "resolved_at": incident.get("resolved_at"),
            "fingerprint": incident.get("fingerprint"),
        },
        "detector": incident.get("detector"),
        "evidence": incident.get("evidence", [])[-20:],
        "hypotheses": incident.get("hypotheses", [])[:8],
        "causal_chain": incident.get("causal_chain", []),
        "signal_timeline": incident.get("timeline", [])[-30:],
        "operational_events": incident.get("operational_events", [])[-20:],
        "settings": settings,
        "telemetry_window": window,
    }


def build_investigation_prompt(context: dict[str, Any]) -> str:
    return (
        "You are an AI incident investigator for a PostgreSQL observability cockpit.\n"
        "Investigate the incident using the supplied detector evidence, telemetry window, DBA events, and available MCP tools.\n"
        "If MCP tools are available, use them to inspect the incident context before the final answer.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "verdict": "short root-cause verdict",\n'
        '  "confidence": 0.0,\n'
        '  "root_cause": "specific suspected root cause",\n'
        '  "causal_chain": [{"stage": "symptom|cause|impact|evidence", "detail": "..."}],\n'
        '  "supporting_evidence": ["..."],\n'
        '  "negative_evidence": ["..."],\n'
        '  "recommended_actions": ["..."],\n'
        '  "needs_more_data": ["..."]\n'
        "}\n\n"
        "Incident context JSON:\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )


def parse_agent_verdict(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise AIAgentError("AI agent did not return JSON verdict")
        verdict = json.loads(match.group(0))
    if not isinstance(verdict, dict):
        raise AIAgentError("AI agent verdict must be a JSON object")
    verdict.setdefault("verdict", "No verdict")
    verdict.setdefault("confidence", 0)
    verdict.setdefault("supporting_evidence", [])
    verdict.setdefault("negative_evidence", [])
    verdict.setdefault("recommended_actions", [])
    verdict.setdefault("needs_more_data", [])
    return verdict


class WhatareyatalkinaboutClient:
    def __init__(
        self,
        base_url: str | None = None,
        user_id: str | None = None,
        source: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("AI_AGENT_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.user_id = user_id or os.environ.get("AI_AGENT_USER_ID") or DEFAULT_AGENT_USER_ID
        self.source = source or os.environ.get("AI_AGENT_SOURCE") or "cockpit"
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, admin: bool = False) -> dict[str, Any]:
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        headers = {
            "Content-Type": "application/json",
            "X-User-ID": self.user_id,
            "X-Source": self.source,
        }
        if admin and os.environ.get("AI_AGENT_ADMIN_TOKEN"):
            headers["X-Admin-Token"] = os.environ["AI_AGENT_ADMIN_TOKEN"]
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise AIAgentError(f"AI agent HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AIAgentError(f"AI agent unavailable: {error}") from error
        return json.loads(raw) if raw else {}

    def ensure_model(self) -> str:
        configured = os.environ.get("AI_AGENT_MODEL_ID")
        if configured:
            UUID(configured)
            return configured
        model_name = os.environ.get("LLM_MODEL") or os.environ.get("AI_AGENT_MODEL_NAME")
        if not model_name:
            raise AIAgentError("AI model is not configured: set AI_AGENT_MODEL_ID or LLM_MODEL")
        models = self._request("GET", "/api/v1/models").get("data", [])
        for model in models:
            if model.get("name") == model_name:
                return str(model["id"])
        base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("AI_AGENT_LLM_BASE_URL")
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("AI_AGENT_LLM_API_KEY")
        payload = {
            "name": model_name,
            "base_url": base_url,
            "api_key": api_key,
            "token_limit": int(os.environ.get("AI_AGENT_TOKEN_LIMIT", "128000")),
        }
        return str(self._request("POST", "/api/v1/models", payload).get("data", {})["id"])

    def ensure_mcp_ids(self) -> list[str]:
        configured_ids = [item.strip() for item in os.environ.get("AI_AGENT_MCP_IDS", "").split(",") if item.strip()]
        if configured_ids:
            return configured_ids
        mcp_url = os.environ.get("AI_AGENT_MCP_URL")
        if not mcp_url:
            return []
        name = os.environ.get("AI_AGENT_MCP_NAME", "cockpit-telemetry")
        mcps = self._request("GET", "/api/v1/mcps/user").get("data", [])
        for mcp in mcps:
            if mcp.get("name") == name and mcp.get("url") == mcp_url:
                return [str(mcp["id"])]
        payload = {"name": name, "url": mcp_url, "headers": None}
        return [str(self._request("POST", "/api/v1/mcps/user", payload).get("data", {})["id"])]

    def create_chat(self, incident_id: str, model_id: str, mcp_ids: list[str]) -> str:
        payload = {
            "short_name": f"cockpit {incident_id}",
            "system_prompt": (
                "You are a production PostgreSQL incident investigator. "
                "Use telemetry evidence and MCP tools when available. "
                "Prefer concrete root-cause chains over generic monitoring advice."
            ),
            "model_id": model_id,
            "mcp_ids": mcp_ids,
            "context_engine": "ctxEngV2",
            "temperature": float(os.environ.get("AI_AGENT_TEMPERATURE", "0.2")),
            "max_tokens": int(os.environ.get("AI_AGENT_MAX_TOKENS", "4000")),
        }
        return str(self._request("POST", "/api/v1/chats", payload).get("data", {})["id"])

    def complete(self, chat_id: str, prompt: str) -> tuple[str, dict[str, Any]]:
        response = self._request("POST", f"/api/v1/chats/{chat_id}/completion", {"message": prompt})
        data = response.get("data", {})
        return str(data.get("message", {}).get("content", "")), data.get("usage", {})


def run_ai_investigation(
    incident: dict[str, Any],
    stream: list[dict[str, float]],
    settings: dict[str, Any],
    existing_session: dict[str, Any] | None = None,
    client: WhatareyatalkinaboutClient | None = None,
) -> dict[str, Any]:
    agent = client or WhatareyatalkinaboutClient()
    session = dict(existing_session or {})
    model_id = session.get("model_id") or agent.ensure_model()
    mcp_ids = session.get("mcp_ids") or agent.ensure_mcp_ids()
    chat_id = session.get("chat_id") or agent.create_chat(str(incident["id"]), model_id, mcp_ids)
    context = compact_incident_context(incident, stream, settings)
    content, usage = agent.complete(chat_id, build_investigation_prompt(context))
    verdict = parse_agent_verdict(content)
    now = int(time.time())
    return {
        "status": "complete",
        "chat_id": chat_id,
        "model_id": model_id,
        "mcp_ids": mcp_ids,
        "updated_at": now,
        "usage": usage,
        "verdict": verdict,
    }

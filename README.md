# Cockpit

Incident-centric observability cockpit prototype for PostgreSQL telemetry and causal investigation.

The project started as a causal load simulator and now includes a local live stack: PostgreSQL, postgres_exporter, Prometheus, a Python SSE backend, a cockpit MCP server, and a browser UI that turns detector signals into incidents with lifecycle, investigation progress, hypotheses, evidence, and causal-chain drafts.

## What It Does

- Streams real PostgreSQL telemetry from Prometheus.
- Starts configurable benchmark workloads from the web UI, including pgbench clients, jobs, duration, mode, target TPS, and planner/sort/update profiles.
- Detects suspicious activity through a pluggable detector pipeline: rule-based, statistical, and ML detectors.
- Aggregates detector signals into incident periods by fingerprint.
- Shows incident lifecycle: candidate, active, recovering, resolved, acknowledged, false positive.
- Displays an investigation process and can delegate root-cause analysis to a separate AI agent backend with MCP tools for live metrics, waits, locks, settings, and query fingerprints.
- Provides a sandbox-only DBA experiment lab for controlled PostgreSQL setting changes and rollback.
- Supports storage experiments such as pgbench table `fillfactor` changes, tracked as DBA context for incidents.
- Keeps telemetry bounded: backend uses rolling memory buffers, Prometheus has TSDB retention, and incidents/signals/AI verdicts are persisted as compact records in PostgreSQL.

## Quick Start

```powershell
docker compose -f infra/docker-compose.yml up -d --build
```

Open:

```text
http://127.0.0.1:8088
```

Initialize pgbench data if needed:

```powershell
.\infra\scripts\init_pgbench.ps1 -Scale 10
```

Then open `Benchmark lab`, start a workload, and watch incidents, investigation state, and metric movement.

## AI Agent Integration

Cockpit can call a separately running `whatareyatalkinabout` backend for AI root-cause verdicts. Configure it with environment variables; do not commit real API keys.

```powershell
$env:AI_AGENT_BASE_URL="http://host.docker.internal:8000"
$env:AI_AGENT_MCP_URL="http://host.docker.internal:8090/mcp"
$env:LLM_MODEL="your-model-name"
$env:LLM_BASE_URL="https://your-openai-compatible-endpoint/v1"
$env:LLM_API_KEY="..."
docker compose -f infra/docker-compose.yml up -d --build cockpit_mcp cockpit_backend
```

For the local Docker sandbox, `whatareyatalkinabout` must allow private MCP URLs:

```text
URL_SSRF_PROTECTION=False
```

Keep SSRF protection enabled in production and expose the cockpit MCP through an approved internal/public endpoint instead.

Optional:

- `AI_AGENT_MODEL_ID` - reuse an existing model in the agent backend.
- `AI_AGENT_MCP_URL` or `AI_AGENT_MCP_IDS` - attach MCP tools to the per-incident agent session. The local default is `http://host.docker.internal:8090/mcp`.
- `AI_AGENT_USER_ID` - stable user id used by cockpit when creating agent chats.

## Simulator MVP

The original simulator still generates static artifacts:

```powershell
python run.py
```

Artifacts are written to `output/`, and the replay UI lives in:

```text
web_cockpit/index.html
```

## Test

```powershell
python -m pytest
```

## Main Paths

- `tools/cockpit_backend.py` - live backend, SSE, incidents, load control.
- `tools/cockpit/detectors.py` - detector interface and signal pipeline.
- `tools/cockpit/hypotheses.py` - explainable hypothesis ranking rules and score factors.
- `tools/cockpit/persistence.py` - PostgreSQL persistence for signals, incidents, and AI verdicts.
- `tools/cockpit_mcp_server.py` - MCP tools for AI incident investigation.
- `tools/cockpit/experiments.py` - DBA experiment allowlist.
- `tools/live_pg_monitor.py` - Prometheus query helpers.
- `web_cockpit/live.html` - live incident cockpit UI.
- `web_cockpit/index.html` - static simulator replay UI.
- `infra/docker-compose.yml` - local observability stack.
- `causal_sim/` - simulator and causal episode generation.
- `ROADMAP.md` - product and architecture roadmap.

## Current Status

This is an MVP/prototype. The next valuable step is richer evidence collection: PostgreSQL wait events, locks, query fingerprints, before/during comparison, topology graph, and persistent incident storage.

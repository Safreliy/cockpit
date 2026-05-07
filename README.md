# Cockpit

Incident-centric observability cockpit prototype for PostgreSQL telemetry and causal investigation.

The project started as a causal load simulator and now includes a local live stack: PostgreSQL, postgres_exporter, Prometheus, a Python SSE backend, and a browser UI that turns detector signals into incidents with lifecycle, investigation progress, hypotheses, evidence, and causal-chain drafts.

## What It Does

- Streams real PostgreSQL telemetry from Prometheus.
- Starts configurable benchmark workloads from the web UI, including pgbench clients, jobs, duration, mode, target TPS, and planner/sort/update profiles.
- Detects suspicious activity through a pluggable detector pipeline: rule-based, statistical, and ML detectors.
- Aggregates detector signals into incident periods by fingerprint.
- Shows incident lifecycle: candidate, active, recovering, resolved, acknowledged, false positive.
- Displays an investigation process that can later be driven by ML/AI inference.
- Provides a sandbox-only DBA experiment lab for controlled PostgreSQL setting changes and rollback.
- Keeps telemetry bounded: backend uses rolling memory buffers, Prometheus has TSDB retention.

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
- `tools/cockpit/experiments.py` - DBA experiment allowlist.
- `tools/live_pg_monitor.py` - Prometheus query helpers.
- `web_cockpit/live.html` - live incident cockpit UI.
- `web_cockpit/index.html` - static simulator replay UI.
- `infra/docker-compose.yml` - local observability stack.
- `causal_sim/` - simulator and causal episode generation.
- `ROADMAP.md` - product and architecture roadmap.

## Current Status

This is an MVP/prototype. The next valuable step is richer evidence collection: PostgreSQL wait events, locks, query fingerprints, before/during comparison, topology graph, and persistent incident storage.

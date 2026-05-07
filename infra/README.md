# Local Postgres Observability Sandbox

This stack is the first step from simulation toward real telemetry.

## Services

- PostgreSQL on `localhost:55432`
- postgres_exporter on `localhost:9187`
- Prometheus on `localhost:9090`
- Cockpit backend and live UI on `localhost:8088`

## Start

```powershell
docker compose -f infra/docker-compose.yml up -d
```

This now starts the full local cockpit stack, including the Python backend. After a reboot, the same command should bring the UI API back without starting `python tools/cockpit_backend.py` manually.

## Initialize pgbench

```powershell
.\infra\scripts\init_pgbench.ps1 -Scale 20
```

## Run Load

```powershell
.\infra\scripts\run_pgbench.ps1 -Clients 32 -Jobs 4 -Seconds 180 -Mode mixed
```

Read-only load:

```powershell
.\infra\scripts\run_pgbench.ps1 -Clients 48 -Jobs 4 -Seconds 180 -Mode readonly
```

## Live Monitor

```powershell
python tools/live_pg_monitor.py
```

The monitor polls Prometheus and writes `web_cockpit/live_data.js`. This gives us a bridge from real Postgres telemetry to the cockpit data model. A dedicated live cockpit page can consume this next.

## Live Backend + Web UI

```powershell
docker compose -f infra/docker-compose.yml up -d --build cockpit_backend
```

Open:

```text
http://127.0.0.1:8088
```

The backend:

- polls Prometheus every 2 seconds;
- streams telemetry and detections to the browser over Server-Sent Events;
- exposes `POST /api/load/start` and `POST /api/load/stop`;
- starts `pgbench` from the backend container against the Postgres service;
- keeps only a rolling in-memory telemetry window.

Manual host mode is still available for debugging:

```powershell
python tools/cockpit_backend.py
```

## Retention Policy

For local development we use bounded retention at two layers:

- Prometheus TSDB retention is set to `2d` in `docker-compose.yml`.
- The cockpit backend keeps a rolling in-memory buffer: 720 telemetry points and 200 detections by default.

At the default 2 second polling interval, 720 points is about 24 minutes of UI history. The backend does not append telemetry to disk. If we later persist incidents, we should store compact episode records, not raw high-cardinality telemetry.

## Stop

```powershell
docker compose -f infra/docker-compose.yml down
```

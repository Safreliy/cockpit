# Web Cockpit

This folder contains two browser UIs:

- `live.html` - the current live incident cockpit served by `tools/cockpit_backend.py`.
- `index.html` - the original static simulator replay UI that reads generated `data.js`.

## Live UI

Start the full sandbox stack:

```powershell
docker compose -f infra/docker-compose.yml up -d --build
```

Open:

```text
http://127.0.0.1:8088
```

The live UI consumes:

- `/api/snapshot`
- `/api/incidents/:id`
- `/api/load/start`
- `/api/load/stop`
- `/api/detectors`
- `/api/experiments/apply`
- `/api/experiments/rollback`
- `/events` over Server-Sent Events

`Benchmark lab` currently runs pgbench workloads with configurable clients, jobs, duration, mode, and target TPS. The UI keeps the workload engine explicit so additional generators can be added behind the same controls.

## Replay UI

Generate simulator data:

```powershell
python run.py
```

Then open:

```text
web_cockpit/index.html
```

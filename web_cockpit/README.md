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
- `/api/incidents/ai`
- `/api/load/start`
- `/api/load/stop`
- `/api/detectors`
- `/api/experiments/apply`
- `/api/experiments/rollback`
- `/events` over Server-Sent Events

`Benchmark lab` currently runs pgbench workloads with configurable clients, jobs, duration, mode, target TPS, and profiles for default TPS, read-only, planner range scans, sort pressure, aggregate scans, and write-path pressure. The UI keeps the workload engine explicit so additional generators can be added behind the same controls.

AI verdicts are produced by a separately running `whatareyatalkinabout` backend. Set `AI_AGENT_BASE_URL` and either `AI_AGENT_MODEL_ID` or `LLM_MODEL`/`LLM_BASE_URL`/`LLM_API_KEY` before starting `cockpit_backend`.

## Replay UI

Generate simulator data:

```powershell
python run.py
```

Then open:

```text
web_cockpit/index.html
```

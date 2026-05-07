# Roadmap: From MVP to Real AI Cockpit

## 1. Stabilize the Simulator Core

- Keep expanding scenario coverage beyond `heavy_reporting_on_primary`.
- Add scenario composition: single cause, additive pairs, amplifying pairs, masking pairs, cascades, and false correlations.
- Make the propagation engine graph-driven instead of scenario-specific.
- Add explicit topology: services, databases, replicas, jobs, network zones, business flows.
- Keep ground truth separate from diagnosis code.

## 2. Build Real Telemetry Interfaces

- Define ingestion interfaces for metrics, logs, events, traces, topology, deploy history, and incident annotations.
- Start with file and HTTP ingestion, then add adapters for Prometheus, OpenTelemetry, PostgreSQL stats, cloud metrics, and business KPIs.
- Normalize all incoming signals into one time-indexed telemetry model.
- Track signal provenance so cockpit explanations can show where each piece of evidence came from.
- Add retention, replay, and backfill modes for incident analysis.

## 3. Move From Mock HTML to Cockpit Application

- Replace static HTML with a small web app and API.
- Add views for business health, active causal episodes, evidence, rejected causes, topology, timelines, and drill-downs.
- Support interactive charts, synchronized cursors, anomaly overlays, causal-chain overlays, and later live chart updates.
- Add operator actions: acknowledge, mark false positive, attach notes, export episode, and compare with previous incidents.
- Keep the episode as the central object, not individual alerts.

## 4. Improve Causal Search

- Phase 1: deterministic rule-based matching for known scenarios.
- Phase 2: graph search over candidate causes, mechanisms, symptoms, and impacts.
- Phase 3: scoring model with positive evidence, negative evidence, time ordering, topology distance, and business impact.
- Phase 4: probabilistic causal inference with confidence intervals and competing hypotheses.
- Phase 5: ML/AI-like diagnosis that learns patterns from historical telemetry, validated incidents, operator feedback, and simulated ground truth.
- Phase 6: hybrid AI cockpit where deterministic constraints prevent impossible causal chains, while learned ranking proposes the most plausible explanations.

## 5. Validation and Evaluation

- Build a benchmark suite of simulated incidents with known ground truth.
- Measure root cause accuracy, mechanism accuracy, impact accuracy, false-cause rejection, time-to-diagnosis, and explanation quality.
- Add regression tests for every new scenario and every known false positive.
- Compare diagnosis output against ground truth only in validation, never inside runtime diagnosis.
- Track how often the cockpit says "unknown" when evidence is insufficient.

## 6. Production Architecture

- Split into simulator, ingestion service, diagnosis engine, storage, API, and UI.
- Store telemetry and episodes in PostgreSQL.
- Add background workers for anomaly compression and causal search.
- Add streaming ingestion for near-real-time operation.
- Add auth, workspace/project separation, audit log, and role-based access.
- Package local development with one command and production with containers.

## 7. Operator Feedback Loop

- Let users confirm or reject proposed causal episodes.
- Capture remediation outcomes and whether business metrics recovered.
- Feed validated outcomes back into scoring and later ML training.
- Keep explanations inspectable: evidence, rejected causes, confidence, missing data, and alternative hypotheses.

## 8. Near-Term Implementation Order

1. Make propagation fully graph-driven so causal-chain UI is generated from graph metadata, not hardcoded labels.
2. Add anomaly marker metadata: severity, confidence, source signal, detection rule, and linked causal node.
3. Add two more scenarios with negative evidence and validation.
4. Add a local API layer for telemetry stream, active episodes, episode reports, and validation reports.
5. Replace playback with true online delivery through Server-Sent Events or WebSocket.
6. Add operator feedback in the report drawer: confirm, reject, mark insufficient evidence, and attach remediation outcome.
7. Introduce a candidate-cause scorer before moving toward ML/AI-like diagnosis.

## 9. Live Cockpit Next Steps

1. Treat raw detector output as signal, not as the operator-facing object. The UI should primarily show incidents/episodes with status, confidence, evidence, and drill-down reports.
2. Keep the detector interface engine-neutral. Current detectors can be rule-based, but every detector result must expose detector id, engine type, confidence, evidence, competing hypotheses, and causal-chain candidates so ML/AI engines can later plug into the same contract.
3. Add incident lifecycle: open, acknowledged, resolved, false positive, notes, and operator feedback. These fields become future training labels and evaluation data.
4. Expand Postgres telemetry from basic counters to query fingerprints, lock waits, wait events, replication, IO, vacuum, WAL, pooler state, deploy markers, and application/business KPIs.
5. Move causal search from single-threshold explanation to graph-driven propagation: symptom -> candidate mechanisms -> candidate root causes -> business impact, with positive and negative evidence for every edge.
6. Add persistent storage for incidents and compacted telemetry windows. Keep raw high-cardinality telemetry in Prometheus/OpenTelemetry storage with retention policies; store only incident windows, summaries, and operator labels in cockpit storage.
7. Add detector evaluation: false positive rate, missed incidents, time-to-detect, time-to-explain, root-cause accuracy, and operator override rate.

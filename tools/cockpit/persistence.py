from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Protocol


class Persistence(Protocol):
    def ensure_schema(self) -> None:
        ...

    def load_recent(self, limit: int) -> dict[str, list[dict[str, Any]]]:
        ...

    def save_signal(self, signal: dict[str, Any]) -> None:
        ...

    def save_incident(self, incident: dict[str, Any]) -> None:
        ...

    def save_ai_verdict(self, incident: dict[str, Any]) -> None:
        ...

    def collect_query_fingerprint_snapshot(self, observed_at: int) -> None:
        ...


class NoopPersistence:
    def ensure_schema(self) -> None:
        return

    def load_recent(self, limit: int) -> dict[str, list[dict[str, Any]]]:
        return {"signals": [], "incidents": []}

    def save_signal(self, signal: dict[str, Any]) -> None:
        return

    def save_incident(self, incident: dict[str, Any]) -> None:
        return

    def save_ai_verdict(self, incident: dict[str, Any]) -> None:
        return

    def collect_query_fingerprint_snapshot(self, observed_at: int) -> None:
        return


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def json_literal(value: Any) -> str:
    return sql_literal(json.dumps(value, ensure_ascii=False, default=str))


def epoch_expr(value: Any) -> str:
    if value in (None, ""):
        return "NULL"
    try:
        return f"to_timestamp({float(value)})"
    except (TypeError, ValueError):
        return "NULL"


class PostgresPersistence:
    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.psql = shutil.which("psql")
        if not self.psql:
            raise RuntimeError("psql is not available for cockpit persistence")

    def psql_args(self) -> list[str]:
        return [
            self.psql or "psql",
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
        ]

    def run_sql(self, sql: str, quiet: bool = True) -> str:
        env = os.environ.copy()
        if os.environ.get("PGPASSWORD"):
            env["PGPASSWORD"] = os.environ["PGPASSWORD"]
        args = self.psql_args()
        if quiet:
            args.append("-qAt")
        process = subprocess.run(
            args,
            input=sql,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=self.timeout,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stdout.strip() or "psql command failed")
        return process.stdout

    def ensure_schema(self) -> None:
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS cockpit_signals (
              id text PRIMARY KEY,
              t timestamptz NOT NULL,
              fingerprint text NOT NULL,
              type text NOT NULL,
              severity text NOT NULL,
              metric text NOT NULL,
              value double precision,
              payload jsonb NOT NULL,
              updated_at timestamptz NOT NULL DEFAULT now()
            );

            CREATE INDEX IF NOT EXISTS cockpit_signals_t_idx ON cockpit_signals(t DESC);
            CREATE INDEX IF NOT EXISTS cockpit_signals_fingerprint_idx ON cockpit_signals(fingerprint);

            CREATE TABLE IF NOT EXISTS cockpit_incidents (
              id text PRIMARY KEY,
              fingerprint text NOT NULL,
              type text NOT NULL,
              severity text NOT NULL,
              status text NOT NULL,
              created_at timestamptz NOT NULL,
              started_at timestamptz NOT NULL,
              last_seen_at timestamptz NOT NULL,
              resolved_at timestamptz,
              payload jsonb NOT NULL,
              updated_at timestamptz NOT NULL DEFAULT now()
            );

            CREATE INDEX IF NOT EXISTS cockpit_incidents_started_idx ON cockpit_incidents(started_at DESC);
            CREATE INDEX IF NOT EXISTS cockpit_incidents_status_idx ON cockpit_incidents(status);
            CREATE INDEX IF NOT EXISTS cockpit_incidents_fingerprint_idx ON cockpit_incidents(fingerprint);

            CREATE TABLE IF NOT EXISTS cockpit_ai_verdicts (
              incident_id text PRIMARY KEY REFERENCES cockpit_incidents(id) ON DELETE CASCADE,
              status text NOT NULL,
              chat_id text,
              model_id text,
              verdict jsonb,
              payload jsonb NOT NULL,
              updated_at timestamptz NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS cockpit_query_fingerprint_snapshots (
              observed_at timestamptz NOT NULL,
              userid oid NOT NULL,
              dbid oid NOT NULL,
              queryid bigint NOT NULL,
              calls bigint NOT NULL,
              total_plan_time double precision NOT NULL,
              total_exec_time double precision NOT NULL,
              rows bigint NOT NULL,
              shared_blks_hit bigint NOT NULL,
              shared_blks_read bigint NOT NULL,
              shared_blks_dirtied bigint NOT NULL,
              shared_blks_written bigint NOT NULL,
              local_blks_hit bigint NOT NULL,
              local_blks_read bigint NOT NULL,
              local_blks_dirtied bigint NOT NULL,
              local_blks_written bigint NOT NULL,
              temp_blks_read bigint NOT NULL,
              temp_blks_written bigint NOT NULL,
              blk_read_time double precision NOT NULL,
              blk_write_time double precision NOT NULL,
              wal_records bigint NOT NULL,
              wal_fpi bigint NOT NULL,
              wal_bytes numeric NOT NULL,
              query text NOT NULL,
              PRIMARY KEY (observed_at, userid, dbid, queryid)
            );

            CREATE INDEX IF NOT EXISTS cockpit_query_fingerprint_snapshots_observed_idx
              ON cockpit_query_fingerprint_snapshots(observed_at DESC);
            CREATE INDEX IF NOT EXISTS cockpit_query_fingerprint_snapshots_queryid_idx
              ON cockpit_query_fingerprint_snapshots(queryid, observed_at DESC);
            """,
            quiet=False,
        )

    def load_recent(self, limit: int) -> dict[str, list[dict[str, Any]]]:
        limited = max(1, min(limit, 1000))
        signals = self._load_payloads(
            f"SELECT payload::text FROM cockpit_signals ORDER BY t DESC LIMIT {limited}"
        )
        incidents = self._load_payloads(
            f"SELECT payload::text FROM cockpit_incidents ORDER BY started_at DESC LIMIT {limited}"
        )
        return {"signals": list(reversed(signals)), "incidents": list(reversed(incidents))}

    def _load_payloads(self, sql: str) -> list[dict[str, Any]]:
        output = self.run_sql(sql)
        items: list[dict[str, Any]] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                items.append(payload)
        return items

    def save_signal(self, signal: dict[str, Any]) -> None:
        sql = f"""
        INSERT INTO cockpit_signals(id, t, fingerprint, type, severity, metric, value, payload, updated_at)
        VALUES (
          {sql_literal(signal.get('id'))},
          {epoch_expr(signal.get('t'))},
          {sql_literal(signal.get('fingerprint'))},
          {sql_literal(signal.get('type'))},
          {sql_literal(signal.get('severity'))},
          {sql_literal(signal.get('metric'))},
          {float(signal.get('value', 0) or 0)},
          {json_literal(signal)}::jsonb,
          now()
        )
        ON CONFLICT (id) DO UPDATE SET
          t = EXCLUDED.t,
          fingerprint = EXCLUDED.fingerprint,
          type = EXCLUDED.type,
          severity = EXCLUDED.severity,
          metric = EXCLUDED.metric,
          value = EXCLUDED.value,
          payload = EXCLUDED.payload,
          updated_at = now();
        """
        self.run_sql(sql)

    def save_incident(self, incident: dict[str, Any]) -> None:
        sql = f"""
        INSERT INTO cockpit_incidents(
          id, fingerprint, type, severity, status, created_at, started_at, last_seen_at,
          resolved_at, payload, updated_at
        )
        VALUES (
          {sql_literal(incident.get('id'))},
          {sql_literal(incident.get('fingerprint'))},
          {sql_literal(incident.get('type'))},
          {sql_literal(incident.get('severity'))},
          {sql_literal(incident.get('status'))},
          {epoch_expr(incident.get('created_at'))},
          {epoch_expr(incident.get('started_at'))},
          {epoch_expr(incident.get('last_seen_at'))},
          {epoch_expr(incident.get('resolved_at'))},
          {json_literal(incident)}::jsonb,
          now()
        )
        ON CONFLICT (id) DO UPDATE SET
          fingerprint = EXCLUDED.fingerprint,
          type = EXCLUDED.type,
          severity = EXCLUDED.severity,
          status = EXCLUDED.status,
          last_seen_at = EXCLUDED.last_seen_at,
          resolved_at = EXCLUDED.resolved_at,
          payload = EXCLUDED.payload,
          updated_at = now();
        """
        self.run_sql(sql)
        self.save_ai_verdict(incident)

    def save_ai_verdict(self, incident: dict[str, Any]) -> None:
        ai = incident.get("ai_investigation")
        if not ai:
            return
        sql = f"""
        INSERT INTO cockpit_ai_verdicts(incident_id, status, chat_id, model_id, verdict, payload, updated_at)
        VALUES (
          {sql_literal(incident.get('id'))},
          {sql_literal(ai.get('status', 'unknown'))},
          {sql_literal(ai.get('chat_id'))},
          {sql_literal(ai.get('model_id'))},
          {json_literal(incident.get('ai_verdict'))}::jsonb,
          {json_literal(ai)}::jsonb,
          now()
        )
        ON CONFLICT (incident_id) DO UPDATE SET
          status = EXCLUDED.status,
          chat_id = EXCLUDED.chat_id,
          model_id = EXCLUDED.model_id,
          verdict = EXCLUDED.verdict,
          payload = EXCLUDED.payload,
          updated_at = now();
        """
        self.run_sql(sql)

    def collect_query_fingerprint_snapshot(self, observed_at: int) -> None:
        sql = f"""
        INSERT INTO cockpit_query_fingerprint_snapshots(
          observed_at, userid, dbid, queryid, calls, total_plan_time, total_exec_time, rows,
          shared_blks_hit, shared_blks_read, shared_blks_dirtied, shared_blks_written,
          local_blks_hit, local_blks_read, local_blks_dirtied, local_blks_written,
          temp_blks_read, temp_blks_written, blk_read_time, blk_write_time,
          wal_records, wal_fpi, wal_bytes, query
        )
        SELECT
          {epoch_expr(observed_at)} AS observed_at,
          userid,
          dbid,
          queryid,
          calls,
          total_plan_time,
          total_exec_time,
          rows,
          shared_blks_hit,
          shared_blks_read,
          shared_blks_dirtied,
          shared_blks_written,
          local_blks_hit,
          local_blks_read,
          local_blks_dirtied,
          local_blks_written,
          temp_blks_read,
          temp_blks_written,
          blk_read_time,
          blk_write_time,
          wal_records,
          wal_fpi,
          wal_bytes,
          left(query, 2000)
        FROM pg_stat_statements
        WHERE queryid IS NOT NULL
          AND dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        ON CONFLICT (observed_at, userid, dbid, queryid) DO UPDATE SET
          calls = EXCLUDED.calls,
          total_plan_time = EXCLUDED.total_plan_time,
          total_exec_time = EXCLUDED.total_exec_time,
          rows = EXCLUDED.rows,
          shared_blks_hit = EXCLUDED.shared_blks_hit,
          shared_blks_read = EXCLUDED.shared_blks_read,
          shared_blks_dirtied = EXCLUDED.shared_blks_dirtied,
          shared_blks_written = EXCLUDED.shared_blks_written,
          local_blks_hit = EXCLUDED.local_blks_hit,
          local_blks_read = EXCLUDED.local_blks_read,
          local_blks_dirtied = EXCLUDED.local_blks_dirtied,
          local_blks_written = EXCLUDED.local_blks_written,
          temp_blks_read = EXCLUDED.temp_blks_read,
          temp_blks_written = EXCLUDED.temp_blks_written,
          blk_read_time = EXCLUDED.blk_read_time,
          blk_write_time = EXCLUDED.blk_write_time,
          wal_records = EXCLUDED.wal_records,
          wal_fpi = EXCLUDED.wal_fpi,
          wal_bytes = EXCLUDED.wal_bytes,
          query = EXCLUDED.query;

        DELETE FROM cockpit_query_fingerprint_snapshots
        WHERE observed_at < now() - interval '2 days';
        """
        self.run_sql(sql)

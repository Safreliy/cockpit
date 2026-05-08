from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
COCKPIT_BACKEND_URL = os.environ.get("COCKPIT_BACKEND_URL", "http://127.0.0.1:8088").rstrip("/")

DEFAULT_METRICS = {
    "connections": 'pg_stat_activity_cockpit_connections{datname="cockpit"}',
    "active_connections": 'pg_stat_activity_cockpit_active_connections{datname="cockpit"}',
    "waiting_connections": 'pg_stat_activity_cockpit_waiting_connections{datname="cockpit"}',
    "xact_rate": 'rate(pg_stat_database_xact_commit{datname="cockpit"}[1m]) + rate(pg_stat_database_xact_rollback{datname="cockpit"}[1m])',
    "read_blocks_rate": 'rate(pg_database_io_cockpit_blks_read{datname="cockpit"}[1m])',
    "cache_hit_rate": 'rate(pg_database_io_cockpit_blks_hit{datname="cockpit"}[1m])',
    "blk_read_time_ms_rate": 'rate(pg_database_io_cockpit_blk_read_time_ms{datname="cockpit"}[1m])',
    "active_vacuum_sessions": 'pg_vacuum_activity_cockpit_active_vacuum_sessions{datname="cockpit"}',
    "active_autovacuum_sessions": 'pg_vacuum_activity_cockpit_active_autovacuum_sessions{datname="cockpit"}',
    "vacuum_max_elapsed_seconds": 'pg_vacuum_activity_cockpit_vacuum_max_elapsed_seconds{datname="cockpit"}',
}

READONLY_SQL_RE = re.compile(r"^\s*(select|with|show|explain)\b", re.IGNORECASE | re.DOTALL)
BLOCKED_SQL_RE = re.compile(
    r"\b(insert|update|delete|alter|drop|create|truncate|grant|revoke|copy|vacuum|analyze|call|do|execute)\b",
    re.IGNORECASE,
)


def fetch_json(url: str, timeout: float = 4.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_backend(path: str) -> dict[str, Any]:
    return fetch_json(COCKPIT_BACKEND_URL + path)


def prometheus_query(expr: str) -> list[dict[str, Any]]:
    url = PROMETHEUS_URL + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    payload = fetch_json(url)
    return payload.get("data", {}).get("result", [])


def prometheus_query_range(expr: str, minutes: int = 15, step_seconds: int = 10) -> list[dict[str, Any]]:
    end = int(time.time())
    start = end - max(1, min(minutes, 360)) * 60
    params = {
        "query": expr,
        "start": start,
        "end": end,
        "step": max(1, min(step_seconds, 60)),
    }
    url = PROMETHEUS_URL + "/api/v1/query_range?" + urllib.parse.urlencode(params)
    payload = fetch_json(url)
    return payload.get("data", {}).get("result", [])


def pg_dsn() -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE", "cockpit")
    user = os.environ.get("PGUSER", "cockpit")
    password = os.environ.get("PGPASSWORD", "cockpit")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def query_postgres(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(pg_dsn(), row_factory=dict_row, connect_timeout=4) as connection:
        connection.execute("SET statement_timeout = '4s'")
        connection.execute("SET default_transaction_read_only = on")
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]


def readonly_sql_allowed(sql: str) -> tuple[bool, str]:
    stripped = sql.strip()
    if not stripped:
        return False, "empty query"
    if ";" in stripped.rstrip(";"):
        return False, "multiple statements are not allowed"
    if not READONLY_SQL_RE.search(stripped):
        return False, "only SELECT, WITH, SHOW, and EXPLAIN are allowed"
    if BLOCKED_SQL_RE.search(stripped):
        return False, "query contains a blocked write or maintenance command"
    return True, "ok"


def compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": snapshot.get("generated_at"),
        "latest_point": (snapshot.get("stream") or [{}])[-1],
        "active_incidents": [
            incident
            for incident in snapshot.get("incidents", [])
            if incident.get("status") not in {"resolved", "false_positive"}
        ][-10:],
        "recent_operational_events": snapshot.get("operational_events", [])[-10:],
        "recent_experiments": snapshot.get("experiments", [])[-10:],
        "detectors": snapshot.get("detectors", []),
    }


def get_snapshot() -> dict[str, Any]:
    """Return compact live cockpit state: latest telemetry, active incidents, DBA events, experiments, detectors."""
    return compact_snapshot(fetch_backend("/api/snapshot"))


def get_incident(incident_id: str) -> dict[str, Any]:
    """Return the full cockpit incident object by id."""
    return fetch_backend("/api/incidents/" + urllib.parse.quote(incident_id))


def get_metric_window(metric: str, minutes: int = 15, step_seconds: int = 10) -> dict[str, Any]:
    """Return a Prometheus range window for a known cockpit metric."""
    if metric not in DEFAULT_METRICS:
        return {"error": f"unknown metric {metric}", "known_metrics": sorted(DEFAULT_METRICS)}
    return {
        "metric": metric,
        "minutes": minutes,
        "series": prometheus_query_range(DEFAULT_METRICS[metric], minutes, step_seconds),
    }


def get_postgres_settings(names: list[str] | None = None) -> list[dict[str, Any]]:
    """Return selected PostgreSQL settings from pg_settings."""
    if names:
        return query_postgres(
            """
            SELECT name, setting, unit, context, pending_restart, source
            FROM pg_settings
            WHERE name = ANY(%s)
            ORDER BY name
            """,
            (names,),
        )
    return query_postgres(
        """
        SELECT name, setting, unit, context, pending_restart, source
        FROM pg_settings
        WHERE name IN (
          'max_connections',
          'shared_buffers',
          'work_mem',
          'maintenance_work_mem',
          'effective_cache_size',
          'random_page_cost',
          'seq_page_cost',
          'cpu_tuple_cost',
          'max_parallel_workers',
          'max_parallel_workers_per_gather',
          'enable_seqscan',
          'enable_indexscan',
          'enable_bitmapscan',
          'enable_tidscan',
          'enable_hashjoin',
          'enable_mergejoin',
          'enable_nestloop',
          'enable_hashagg',
          'enable_sort',
          'enable_material',
          'jit',
          'jit_above_cost',
          'synchronous_commit',
          'commit_delay',
          'commit_siblings',
          'effective_io_concurrency',
          'vacuum_cost_delay',
          'vacuum_cost_limit',
          'autovacuum',
          'autovacuum_max_workers',
          'autovacuum_vacuum_cost_delay',
          'autovacuum_vacuum_cost_limit',
          'statement_timeout',
          'idle_in_transaction_session_timeout',
          'lock_timeout',
          'track_io_timing'
        )
        ORDER BY name
        """
    )


def get_wait_event_breakdown() -> list[dict[str, Any]]:
    """Return current session counts grouped by wait event."""
    return query_postgres(
        """
        SELECT
          coalesce(wait_event_type, 'none') AS wait_event_type,
          coalesce(wait_event, 'none') AS wait_event,
          state,
          count(*)::int AS sessions
        FROM pg_stat_activity
        WHERE datname = current_database()
        GROUP BY wait_event_type, wait_event, state
        ORDER BY sessions DESC, wait_event_type, wait_event
        LIMIT 30
        """
    )


def get_locks() -> list[dict[str, Any]]:
    """Return current lock holders/waiters with truncated query text."""
    return query_postgres(
        """
        SELECT
          a.pid,
          a.state,
          a.wait_event_type,
          a.wait_event,
          l.locktype,
          l.mode,
          l.granted,
          now() - coalesce(a.query_start, a.backend_start) AS age,
          left(a.query, 240) AS query
        FROM pg_locks l
        JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE a.datname = current_database()
        ORDER BY l.granted ASC, age DESC
        LIMIT 50
        """
    )


def get_activity() -> list[dict[str, Any]]:
    """Return current PostgreSQL activity with wait state and truncated query text."""
    return query_postgres(
        """
        SELECT
          pid,
          usename,
          state,
          wait_event_type,
          wait_event,
          now() - coalesce(query_start, backend_start) AS age,
          left(query, 300) AS query
        FROM pg_stat_activity
        WHERE datname = current_database()
        ORDER BY age DESC
        LIMIT 50
        """
    )


PG_STAT_STATEMENTS_SORTS = {
    "total_exec_time": "total_exec_time DESC",
    "mean_exec_time": "mean_exec_time DESC",
    "calls": "calls DESC",
    "rows": "rows DESC",
    "shared_blks_read": "shared_blks_read DESC",
    "shared_blks_hit": "shared_blks_hit DESC",
    "temp_blks_written": "temp_blks_written DESC",
    "wal_bytes": "wal_bytes DESC",
}

QUERY_WINDOW_SORTS = {
    "total_exec_time": "total_exec_time_ms_delta DESC",
    "calls": "calls_delta DESC",
    "rows": "rows_delta DESC",
    "shared_blks_read": "shared_blks_read_delta DESC",
    "shared_blks_hit": "shared_blks_hit_delta DESC",
    "temp_blks_written": "temp_blks_written_delta DESC",
    "wal_bytes": "wal_bytes_delta DESC",
}


def pg_stat_statements_order_by(sort_by: str) -> str:
    return PG_STAT_STATEMENTS_SORTS.get(sort_by, PG_STAT_STATEMENTS_SORTS["total_exec_time"])


def query_window_order_by(sort_by: str) -> str:
    return QUERY_WINDOW_SORTS.get(sort_by, QUERY_WINDOW_SORTS["total_exec_time"])


def get_pg_stat_statements_status() -> dict[str, Any]:
    """Return pg_stat_statements availability, reset time, and tracking settings."""
    extension = query_postgres(
        """
        SELECT extname, extversion
        FROM pg_extension
        WHERE extname = 'pg_stat_statements'
        """
    )
    settings = get_postgres_settings(["shared_preload_libraries", "pg_stat_statements.track", "pg_stat_statements.max"])
    info = []
    if extension:
        info = query_postgres(
            """
            SELECT stats_reset
            FROM pg_stat_statements_info
            """
        )
    return {
        "available": bool(extension),
        "extension": extension[0] if extension else None,
        "info": info[0] if info else None,
        "settings": settings,
        "scope_note": "pg_stat_statements is cumulative since stats_reset; use cockpit incident timestamps to interpret the rows for a specific incident window.",
    }


def get_query_fingerprints(limit: int = 10, sort_by: str = "total_exec_time") -> list[dict[str, Any]]:
    """Return top pg_stat_statements query fingerprints sorted by time, calls, IO, temp IO, rows, or WAL."""
    order_by = pg_stat_statements_order_by(sort_by)
    return query_postgres(
        f"""
        SELECT
          queryid,
          calls,
          round(total_plan_time::numeric, 2) AS total_plan_time_ms,
          round(total_exec_time::numeric, 2) AS total_exec_time_ms,
          round(mean_exec_time::numeric, 2) AS mean_exec_time_ms,
          round(max_exec_time::numeric, 2) AS max_exec_time_ms,
          rows,
          shared_blks_read,
          shared_blks_hit,
          shared_blks_dirtied,
          shared_blks_written,
          local_blks_read,
          local_blks_written,
          temp_blks_read,
          temp_blks_written,
          round(blk_read_time::numeric, 2) AS blk_read_time_ms,
          round(blk_write_time::numeric, 2) AS blk_write_time_ms,
          wal_records,
          wal_fpi,
          wal_bytes,
          left(query, 320) AS query
        FROM pg_stat_statements
        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        ORDER BY {order_by}
        LIMIT %s
        """,
        (max(1, min(limit, 50)),),
    )


def get_query_fingerprint_detail(queryid: int) -> list[dict[str, Any]]:
    """Return detailed pg_stat_statements data for a specific queryid."""
    return query_postgres(
        """
        SELECT
          r.rolname AS user_name,
          d.datname AS database_name,
          queryid,
          calls,
          round(total_plan_time::numeric, 2) AS total_plan_time_ms,
          round(total_exec_time::numeric, 2) AS total_exec_time_ms,
          round(mean_exec_time::numeric, 2) AS mean_exec_time_ms,
          round(min_exec_time::numeric, 2) AS min_exec_time_ms,
          round(max_exec_time::numeric, 2) AS max_exec_time_ms,
          round(stddev_exec_time::numeric, 2) AS stddev_exec_time_ms,
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
          round(blk_read_time::numeric, 2) AS blk_read_time_ms,
          round(blk_write_time::numeric, 2) AS blk_write_time_ms,
          wal_records,
          wal_fpi,
          wal_bytes,
          query
        FROM pg_stat_statements s
        LEFT JOIN pg_roles r ON r.oid = s.userid
        LEFT JOIN pg_database d ON d.oid = s.dbid
        WHERE queryid = %s
          AND dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        ORDER BY total_exec_time DESC
        LIMIT 10
        """,
        (queryid,),
    )


def get_query_fingerprint_window(
    start_epoch: int,
    end_epoch: int,
    limit: int = 10,
    sort_by: str = "total_exec_time",
) -> dict[str, Any]:
    """Return pg_stat_statements deltas between persisted snapshots around an incident window."""
    if end_epoch <= start_epoch:
        return {"error": "end_epoch must be greater than start_epoch"}
    order_by = query_window_order_by(sort_by)
    rows = query_postgres(
        f"""
        WITH bounds AS (
          SELECT to_timestamp(%s) AS start_ts, to_timestamp(%s) AS end_ts
        ),
        start_rows AS (
          SELECT DISTINCT ON (userid, dbid, queryid)
            userid, dbid, queryid, observed_at,
            calls, total_plan_time, total_exec_time, rows,
            shared_blks_hit, shared_blks_read, shared_blks_dirtied, shared_blks_written,
            local_blks_hit, local_blks_read, local_blks_dirtied, local_blks_written,
            temp_blks_read, temp_blks_written, blk_read_time, blk_write_time,
            wal_records, wal_fpi, wal_bytes
          FROM cockpit_query_fingerprint_snapshots, bounds
          WHERE observed_at <= bounds.start_ts
          ORDER BY userid, dbid, queryid, observed_at DESC
        ),
        end_rows AS (
          SELECT DISTINCT ON (userid, dbid, queryid)
            userid, dbid, queryid, observed_at, query,
            calls, total_plan_time, total_exec_time, rows,
            shared_blks_hit, shared_blks_read, shared_blks_dirtied, shared_blks_written,
            local_blks_hit, local_blks_read, local_blks_dirtied, local_blks_written,
            temp_blks_read, temp_blks_written, blk_read_time, blk_write_time,
            wal_records, wal_fpi, wal_bytes
          FROM cockpit_query_fingerprint_snapshots, bounds
          WHERE observed_at <= bounds.end_ts
          ORDER BY userid, dbid, queryid, observed_at DESC
        ),
        deltas AS (
          SELECT
            e.queryid,
            e.observed_at AS end_snapshot_at,
            s.observed_at AS start_snapshot_at,
            greatest(e.calls - coalesce(s.calls, 0), 0) AS calls_delta,
            round(greatest(e.total_plan_time - coalesce(s.total_plan_time, 0), 0)::numeric, 2) AS total_plan_time_ms_delta,
            round(greatest(e.total_exec_time - coalesce(s.total_exec_time, 0), 0)::numeric, 2) AS total_exec_time_ms_delta,
            greatest(e.rows - coalesce(s.rows, 0), 0) AS rows_delta,
            greatest(e.shared_blks_hit - coalesce(s.shared_blks_hit, 0), 0) AS shared_blks_hit_delta,
            greatest(e.shared_blks_read - coalesce(s.shared_blks_read, 0), 0) AS shared_blks_read_delta,
            greatest(e.shared_blks_dirtied - coalesce(s.shared_blks_dirtied, 0), 0) AS shared_blks_dirtied_delta,
            greatest(e.shared_blks_written - coalesce(s.shared_blks_written, 0), 0) AS shared_blks_written_delta,
            greatest(e.temp_blks_read - coalesce(s.temp_blks_read, 0), 0) AS temp_blks_read_delta,
            greatest(e.temp_blks_written - coalesce(s.temp_blks_written, 0), 0) AS temp_blks_written_delta,
            round(greatest(e.blk_read_time - coalesce(s.blk_read_time, 0), 0)::numeric, 2) AS blk_read_time_ms_delta,
            round(greatest(e.blk_write_time - coalesce(s.blk_write_time, 0), 0)::numeric, 2) AS blk_write_time_ms_delta,
            greatest(e.wal_records - coalesce(s.wal_records, 0), 0) AS wal_records_delta,
            greatest(e.wal_fpi - coalesce(s.wal_fpi, 0), 0) AS wal_fpi_delta,
            greatest(e.wal_bytes - coalesce(s.wal_bytes, 0), 0) AS wal_bytes_delta,
            left(e.query, 600) AS query
          FROM end_rows e
          LEFT JOIN start_rows s USING (userid, dbid, queryid)
        )
        SELECT *
        FROM deltas
        WHERE calls_delta > 0
           OR total_exec_time_ms_delta > 0
           OR shared_blks_read_delta > 0
           OR temp_blks_written_delta > 0
           OR wal_bytes_delta > 0
        ORDER BY {order_by}
        LIMIT %s
        """,
        (start_epoch, end_epoch, max(1, min(limit, 50))),
    )
    return {
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "sort_by": sort_by,
        "scope_note": "Deltas are computed from cockpit_query_fingerprint_snapshots. Snapshot cadence follows telemetry polling, so start/end snapshots may be nearest earlier samples.",
        "rows": rows,
    }


def get_table_storage_options() -> list[dict[str, Any]]:
    """Return storage parameters and size for pgbench tables."""
    return query_postgres(
        """
        SELECT
          n.nspname AS schema,
          c.relname AS table,
          c.reloptions,
          pg_total_relation_size(c.oid) AS total_bytes,
          pg_relation_size(c.oid) AS heap_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname IN ('pgbench_accounts', 'pgbench_branches', 'pgbench_tellers', 'pgbench_history')
        ORDER BY c.relname
        """
    )


def run_readonly_query(sql: str) -> dict[str, Any]:
    """Run a bounded read-only SQL query for incident investigation."""
    ok, reason = readonly_sql_allowed(sql)
    if not ok:
        return {"error": reason}
    try:
        return {"rows": query_postgres(sql.rstrip(";"))[:100]}
    except Exception as error:
        return {"error": str(error)}


def build_mcp() -> Any:
    from fastmcp import FastMCP
    from starlette.responses import JSONResponse

    mcp = FastMCP("cockpit-telemetry")
    for tool in [
        get_snapshot,
        get_incident,
        get_metric_window,
        get_postgres_settings,
        get_wait_event_breakdown,
        get_locks,
        get_activity,
        get_pg_stat_statements_status,
        get_query_fingerprints,
        get_query_fingerprint_detail,
        get_query_fingerprint_window,
        get_table_storage_options,
        run_readonly_query,
    ]:
        mcp.tool(tool)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Any) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "cockpit-mcp"})

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    build_mcp().run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

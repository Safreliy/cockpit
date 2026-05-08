import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit_mcp_server import compact_snapshot, pg_stat_statements_order_by, query_window_order_by, readonly_sql_allowed


def test_readonly_sql_guard_accepts_safe_queries():
    assert readonly_sql_allowed("select * from pg_stat_activity limit 1")[0]
    assert readonly_sql_allowed("WITH x AS (SELECT 1) SELECT * FROM x")[0]
    assert readonly_sql_allowed("show work_mem")[0]


def test_readonly_sql_guard_blocks_writes_and_multi_statements():
    assert not readonly_sql_allowed("alter system set work_mem = '64MB'")[0]
    assert not readonly_sql_allowed("select 1; drop table cockpit_marker")[0]
    assert not readonly_sql_allowed("vacuum verbose")[0]


def test_compact_snapshot_keeps_investigation_relevant_state():
    snapshot = {
        "generated_at": 123,
        "stream": [{"t": 1}, {"t": 2}],
        "incidents": [
            {"id": "old", "status": "resolved"},
            {"id": "active", "status": "active"},
        ],
        "operational_events": [{"id": str(index)} for index in range(12)],
        "experiments": [{"id": str(index)} for index in range(12)],
        "detectors": [{"id": "rules.postgres.wait_contention.v1"}],
    }
    compact = compact_snapshot(snapshot)
    assert compact["latest_point"] == {"t": 2}
    assert [item["id"] for item in compact["active_incidents"]] == ["active"]
    assert len(compact["recent_operational_events"]) == 10
    assert len(compact["recent_experiments"]) == 10


def test_pg_stat_statements_sort_allowlist():
    assert pg_stat_statements_order_by("shared_blks_read") == "shared_blks_read DESC"
    assert pg_stat_statements_order_by("temp_blks_written") == "temp_blks_written DESC"
    assert pg_stat_statements_order_by("not_a_column") == "total_exec_time DESC"
    assert query_window_order_by("wal_bytes") == "wal_bytes_delta DESC"
    assert query_window_order_by("not_a_column") == "total_exec_time_ms_delta DESC"

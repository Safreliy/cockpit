from __future__ import annotations


EXPERIMENT_SETTINGS: dict[str, dict[str, str]] = {
    "work_mem": {
        "default": "4MB",
        "risky": "64kB",
        "description": "Per-operation memory; low values can force temp files.",
    },
    "maintenance_work_mem": {
        "default": "64MB",
        "risky": "1MB",
        "description": "Maintenance memory; low values can slow VACUUM/CREATE INDEX.",
    },
    "random_page_cost": {
        "default": "4",
        "risky": "10",
        "description": "Planner IO cost; high values can change query plans.",
    },
    "max_parallel_workers_per_gather": {
        "default": "2",
        "risky": "0",
        "description": "Disables parallel query for foreground workload.",
    },
    "autovacuum_vacuum_cost_delay": {
        "default": "2ms",
        "risky": "0",
        "description": "Lower delay makes autovacuum more aggressive.",
    },
    "autovacuum_vacuum_cost_limit": {
        "default": "-1",
        "risky": "10000",
        "description": "Higher limit can make autovacuum consume more IO.",
    },
    "log_min_duration_statement": {
        "default": "-1",
        "risky": "0",
        "description": "Logs every statement; useful but noisy.",
    },
}

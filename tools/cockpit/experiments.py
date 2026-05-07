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
    "seq_page_cost": {
        "default": "1",
        "risky": "10",
        "description": "Sequential scan cost; can push the planner away from scan-heavy plans.",
    },
    "cpu_tuple_cost": {
        "default": "0.01",
        "risky": "1",
        "description": "Planner CPU cost per row; high values can change join, scan, and aggregate choices.",
    },
    "effective_cache_size": {
        "default": "4GB",
        "risky": "128MB",
        "description": "Planner cache estimate; low values make index access look less attractive.",
    },
    "max_parallel_workers_per_gather": {
        "default": "2",
        "risky": "0",
        "description": "Disables parallel query for foreground workload.",
    },
    "enable_seqscan": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for sequential scans; useful for visible plan-change experiments.",
    },
    "enable_indexscan": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for index scans; can force inefficient alternatives.",
    },
    "enable_hashagg": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for hash aggregation; affects aggregate-heavy workloads.",
    },
    "jit": {
        "default": "on",
        "risky": "off",
        "description": "Disables JIT compilation; useful for CPU-heavy queries.",
    },
    "synchronous_commit": {
        "default": "on",
        "risky": "off",
        "description": "Commit durability tradeoff; can visibly change write-heavy benchmark TPS.",
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

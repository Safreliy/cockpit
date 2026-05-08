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
    "enable_bitmapscan": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for bitmap scans; can make selective read workloads choose worse paths.",
    },
    "enable_tidscan": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for TID scans; useful as a controlled plan-shape perturbation.",
    },
    "enable_hashjoin": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for hash joins; can degrade join-heavy ad hoc workloads.",
    },
    "enable_mergejoin": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for merge joins; can change plans for ordered joins and range workloads.",
    },
    "enable_nestloop": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for nested loops; can degrade highly selective indexed joins.",
    },
    "enable_hashagg": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for hash aggregation; affects aggregate-heavy workloads.",
    },
    "enable_sort": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for explicit sorts; useful for visible plan-change experiments.",
    },
    "enable_material": {
        "default": "on",
        "risky": "off",
        "description": "Planner switch for materialization nodes; can change complex query plans.",
    },
    "jit": {
        "default": "on",
        "risky": "off",
        "description": "Disables JIT compilation; useful for CPU-heavy queries.",
    },
    "jit_above_cost": {
        "default": "100000",
        "risky": "0",
        "description": "Forces JIT on cheaper queries; can add visible CPU overhead on short statements.",
    },
    "synchronous_commit": {
        "default": "on",
        "risky": "off",
        "description": "Commit durability tradeoff; can visibly change write-heavy benchmark TPS.",
    },
    "commit_delay": {
        "default": "0",
        "risky": "100000",
        "description": "Adds commit delay in microseconds when enough transactions are committing together.",
    },
    "commit_siblings": {
        "default": "5",
        "risky": "1",
        "description": "Makes commit_delay easier to trigger under concurrent write load.",
    },
    "effective_io_concurrency": {
        "default": "1",
        "risky": "0",
        "description": "Planner/runtime IO concurrency hint; lowering can reduce async prefetch benefits.",
    },
    "vacuum_cost_delay": {
        "default": "0",
        "risky": "20ms",
        "description": "Throttles manual VACUUM; useful with a concurrent VACUUM experiment.",
    },
    "vacuum_cost_limit": {
        "default": "200",
        "risky": "10",
        "description": "Very low manual VACUUM cost limit can stretch maintenance windows.",
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
    "statement_timeout": {
        "default": "0",
        "risky": "50ms",
        "description": "Cancels slow statements; can turn latency degradation into visible workload errors.",
    },
    "idle_in_transaction_session_timeout": {
        "default": "0",
        "risky": "5s",
        "description": "Kills idle-in-transaction sessions; useful for testing operator-change correlation.",
    },
    "lock_timeout": {
        "default": "0",
        "risky": "100ms",
        "description": "Fails lock waits quickly; useful for lock-contention incident experiments.",
    },
    "pgbench_accounts.fillfactor": {
        "default": "100",
        "risky": "50",
        "description": "Table storage parameter for pgbench_accounts; lower values reserve page space for future updates.",
        "kind": "table_storage",
        "table": "pgbench_accounts",
        "storage_parameter": "fillfactor",
    },
    "pgbench_branches.fillfactor": {
        "default": "100",
        "risky": "50",
        "description": "Table storage parameter for pgbench_branches; useful for storage-option correlation experiments.",
        "kind": "table_storage",
        "table": "pgbench_branches",
        "storage_parameter": "fillfactor",
    },
}

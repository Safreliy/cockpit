import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit_backend import TelemetryStore


def test_pgbench_workload_config_supports_rate_and_builtin_script():
    store = TelemetryStore()
    args, workload = store.workload_args(
        {
            "engine": "pgbench",
            "profile": "update",
            "script": "simple_update",
            "clients": 32,
            "jobs": 4,
            "seconds": 600,
            "rate": 200,
            "mode": "mixed",
        }
    )
    assert workload["rate"] == 200
    assert workload["script"] == "simple_update"
    assert "-R" in args
    assert "200" in args
    assert "-b" in args
    assert "simple-update" in args


def test_pgbench_workload_config_supports_custom_script_file():
    store = TelemetryStore()
    args, workload = store.workload_args(
        {
            "engine": "pgbench",
            "profile": "planner",
            "script": "planner_range",
            "clients": 8,
            "jobs": 2,
            "seconds": 60,
            "rate": 20,
            "mode": "readonly",
        }
    )
    script_path = Path(workload["script_path"])
    try:
        assert workload["script"] == "planner_range"
        assert "-f" in args
        assert str(script_path) in args
        assert "pgbench_accounts" in script_path.read_text(encoding="utf-8")
    finally:
        script_path.unlink(missing_ok=True)

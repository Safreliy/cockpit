import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cockpit.experiments import EXPERIMENT_SETTINGS
from cockpit_backend import TelemetryStore


def test_experiment_controls_include_plan_io_timeout_and_storage_cases():
    expected = {
        "enable_bitmapscan",
        "enable_hashjoin",
        "jit_above_cost",
        "commit_delay",
        "vacuum_cost_delay",
        "statement_timeout",
        "lock_timeout",
        "pgbench_accounts.fillfactor",
    }
    assert expected <= set(EXPERIMENT_SETTINGS)
    assert EXPERIMENT_SETTINGS["pgbench_accounts.fillfactor"]["kind"] == "table_storage"


def test_fillfactor_experiment_validates_range_before_psql():
    store = TelemetryStore()
    ok, message, experiment = store.apply_setting_experiment("pgbench_accounts.fillfactor", "0")
    assert not ok
    assert "between 10 and 100" in message
    assert experiment is None

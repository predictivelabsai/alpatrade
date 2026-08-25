"""DB-free contracts for stale paper-run recovery ("zombie" run cleanup).

Paper runs are inserted as 'running' and only finalized when the process ends
cleanly; a redeploy/kill orphans the row forever. These tests pin the heartbeat +
sweep mechanism that finalizes such orphans without touching a live DB.
"""
import inspect
from pathlib import Path


def test_migration_adds_heartbeat_and_cleans_orphans():
    sql = Path("sql/24_runs_heartbeat.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS heartbeat_at" in sql
    # One-time cleanup finalizes existing orphaned paper runs.
    assert "mode = 'paper'" in sql
    assert "status = 'running'" in sql
    assert "status = 'stale'" in sql
    # Idempotent + scoped: never creates the schema, only alters runs.
    assert "CREATE SCHEMA" not in sql.upper()
    assert "alpatrade.runs" in sql


def test_agent_storage_exposes_heartbeat_and_sweep():
    from utils import agent_storage

    assert hasattr(agent_storage, "heartbeat_run")
    assert hasattr(agent_storage, "sweep_stale_paper_runs")

    hb = inspect.getsource(agent_storage.heartbeat_run)
    # Only ever stamps a still-running row; safe no-op otherwise.
    assert "status = 'running'" in hb
    assert "heartbeat_at" in hb

    sweep = inspect.getsource(agent_storage.sweep_stale_paper_runs)
    # Finalizes only stale paper runs, falling back to started_at/created_at for
    # pre-heartbeat rows, and returns the count.
    assert "mode = 'paper'" in sweep
    assert "status = 'stale'" in sweep
    assert "COALESCE(heartbeat_at, started_at, created_at)" in sweep


def test_paper_loop_heartbeats_each_cycle():
    from agents.paper_trade_agent import PaperTradeAgent

    source = inspect.getsource(PaperTradeAgent.run)
    assert "heartbeat_run(self.session_id)" in source


def test_worker_sweeps_stale_paper_runs():
    from engine.autonomy import worker

    source = inspect.getsource(worker.loop)
    assert "sweep_stale_paper_runs(RUNS_STALE_SECONDS)" in source


def test_default_stale_window_exceeds_default_poll_interval():
    """The sweep must not kill a live session between heartbeats."""
    from engine.autonomy import worker

    # Default paper poll is 300s; the stale window must be comfortably larger so a
    # legitimately long-running (but heart-beating) session is never swept.
    assert worker.RUNS_STALE_SECONDS >= 600


def test_dedup_guard_is_scoped_to_owner_and_config():
    """Replacing duplicate paper runs must never touch another user's or a
    different config's runs."""
    import inspect
    from utils import agent_storage

    assert hasattr(agent_storage, "stop_duplicate_paper_runs")
    src = inspect.getsource(agent_storage.stop_duplicate_paper_runs)
    # Strictly scoped: same user, same account, same slug, same symbol-set, and
    # never the run we are about to create.
    assert "user_id = :uid" in src
    assert "account_id = :aid" in src
    assert "strategy_slug = :slug" in src
    assert "run_id <> :keep" in src
    assert "jsonb_array_elements_text(config->'symbols')" in src
    # Only ever stops 'running' paper rows, to 'stopped' (deliberate replacement).
    assert "mode = 'paper'" in src and "status = 'running'" in src
    assert "status = 'stopped'" in src


def test_dedup_guard_noop_without_owner():
    """Unattributed runs (no user/account) are left completely alone."""
    from utils.agent_storage import stop_duplicate_paper_runs
    assert stop_duplicate_paper_runs("r", "btd-3dp", ["AAPL"], None, None) == 0
    assert stop_duplicate_paper_runs("r", "btd-3dp", ["AAPL"], "u", None) == 0
    assert stop_duplicate_paper_runs("r", "btd-3dp", ["AAPL"], None, "a") == 0


def test_orchestrator_replaces_own_duplicate_paper_runs():
    import inspect
    from agents.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator.run_paper_trade)
    assert "stop_duplicate_paper_runs(" in src
    # called before store_run so the fresh run is the only survivor
    assert src.index("stop_duplicate_paper_runs(") < src.index("store_run(")

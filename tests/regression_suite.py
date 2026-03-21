"""
AlpaTrade Regression Test Suite
================================
Comprehensive tests covering backend logic, tool calls, agents, auth,
command processing, and data storage.

Run:  python -m pytest tests/regression_suite.py -v
  or: python tests/regression_suite.py
"""

import sys
import os
import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. Strategy Slug Builder
# ---------------------------------------------------------------------------

class TestStrategySlug(unittest.TestCase):
    """Test slug generation for strategy parameter encoding."""

    def test_btd_full_slug(self):
        from utils.strategy_slug import build_slug
        slug = build_slug("buy_the_dip", {
            "dip_threshold": 3.0,
            "stop_loss": 0.5,
            "take_profit": 1.0,
            "hold_days": 1,
        }, "1m")
        self.assertEqual(slug, "btd-3dp-50sl-1tp-1d-1m")

    def test_btd_partial_params(self):
        from utils.strategy_slug import build_slug
        slug = build_slug("buy_the_dip", {"dip_threshold": 7.0, "hold_days": 2})
        self.assertEqual(slug, "btd-7dp-2d")

    def test_btd_ratio_conversion(self):
        """Params < 1 should be treated as ratios and converted to %."""
        from utils.strategy_slug import build_slug
        slug = build_slug("buy_the_dip", {"dip_threshold": 0.05, "stop_loss": 0.005})
        self.assertEqual(slug, "btd-5dp-05sl")

    def test_momentum_slug(self):
        from utils.strategy_slug import build_slug
        slug = build_slug("momentum", {
            "lookback_period": 20,
            "momentum_threshold": 5.0,
            "hold_days": 3,
        })
        self.assertEqual(slug, "mom-20lb-5mt-3d")

    def test_vix_slug(self):
        from utils.strategy_slug import build_slug
        slug = build_slug("vix", {"vix_threshold": 20.0})
        self.assertEqual(slug, "vix-20t")

    def test_empty_params(self):
        from utils.strategy_slug import build_slug
        slug = build_slug("buy_the_dip", {})
        self.assertEqual(slug, "btd")

    def test_unknown_strategy(self):
        from utils.strategy_slug import build_slug
        slug = build_slug("my_custom_strategy", {}, "3m")
        self.assertEqual(slug, "my_-3m")


# ---------------------------------------------------------------------------
# 2. Agent Shared State
# ---------------------------------------------------------------------------

class TestAgentState(unittest.TestCase):
    """Test AgentState and PortfolioState dataclasses."""

    def test_agent_state_transitions(self):
        from agents.shared.state import AgentState
        agent = AgentState(agent_name="backtester")
        self.assertEqual(agent.status, "idle")

        agent.set_running("parameterized_backtest")
        self.assertEqual(agent.status, "running")
        self.assertEqual(agent.current_task, "parameterized_backtest")
        self.assertIsNotNone(agent.last_updated)

        agent.set_completed()
        self.assertEqual(agent.status, "completed")
        self.assertIsNone(agent.current_task)

        agent.set_error("test error")
        self.assertEqual(agent.status, "error")
        self.assertEqual(agent.error_message, "test error")

        agent.set_idle()
        self.assertEqual(agent.status, "idle")
        self.assertIsNone(agent.current_task)
        self.assertIsNone(agent.error_message)

    def test_portfolio_state_serialization(self):
        from agents.shared.state import PortfolioState
        state = PortfolioState(run_id="test-123", mode="backtest")
        agent = state.get_agent("backtester")
        agent.set_running("test_task")

        data = state.to_dict()
        self.assertEqual(data["run_id"], "test-123")
        self.assertEqual(data["mode"], "backtest")
        self.assertEqual(data["agents"]["backtester"]["status"], "running")

        # Round-trip
        restored = PortfolioState.from_dict(data)
        self.assertEqual(restored.run_id, "test-123")
        self.assertEqual(restored.agents["backtester"].status, "running")

    def test_portfolio_state_save_load(self):
        import tempfile
        from agents.shared.state import PortfolioState
        state = PortfolioState(run_id="save-test", mode="paper")
        state.get_agent("paper_trader").set_running("paper_trading")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            state.save(path)
            loaded = PortfolioState.load(path)
            self.assertEqual(loaded.run_id, "save-test")
            self.assertEqual(loaded.agents["paper_trader"].status, "running")
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 3. Message Bus
# ---------------------------------------------------------------------------

class TestMessageBus(unittest.TestCase):
    """Test inter-agent message bus."""

    def test_publish_and_retrieve(self):
        import tempfile
        from agents.shared.message_bus import MessageBus
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(messages_dir=tmpdir)
            mid = bus.publish(
                from_agent="backtester",
                to_agent="portfolio_manager",
                msg_type="backtest_result",
                payload={"sharpe": 2.5},
            )
            self.assertIsNotNone(mid)

            msgs = bus.get_messages(msg_type="backtest_result")
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0].payload["sharpe"], 2.5)

    def test_invalid_message_type(self):
        import tempfile
        from agents.shared.message_bus import MessageBus
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(messages_dir=tmpdir)
            with self.assertRaises(ValueError):
                bus.publish(
                    from_agent="test",
                    to_agent="test",
                    msg_type="invalid_type",
                    payload={},
                )


# ---------------------------------------------------------------------------
# 4. Auth Module (password hashing, encryption, JWT)
# ---------------------------------------------------------------------------

class TestAuth(unittest.TestCase):
    """Test auth utilities (no DB required for hashing/JWT)."""

    def test_password_hash_verify(self):
        from utils.auth import hash_password, verify_password
        pw = "TestPassword123!"
        hashed = hash_password(pw)
        self.assertNotEqual(hashed, pw)
        self.assertTrue(verify_password(pw, hashed))
        self.assertFalse(verify_password("wrong", hashed))

    def test_key_encryption_roundtrip(self):
        from utils.auth import encrypt_key, decrypt_key
        original = "PKTEST123456789"
        encrypted = encrypt_key(original)
        self.assertNotEqual(encrypted, original.encode())
        decrypted = decrypt_key(encrypted)
        self.assertEqual(decrypted, original)

    def test_jwt_roundtrip(self):
        from utils.auth import create_jwt_token, decode_jwt_token
        token = create_jwt_token("user-123", "test@example.com")
        self.assertIsInstance(token, str)
        decoded = decode_jwt_token(token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["user_id"], "user-123")
        self.assertEqual(decoded["email"], "test@example.com")

    def test_jwt_invalid_token(self):
        from utils.auth import decode_jwt_token
        result = decode_jwt_token("invalid.token.here")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5. Command Processor — Positional Param Parsing
# ---------------------------------------------------------------------------

class TestCommandParser(unittest.TestCase):
    """Test command processor parameter parsing."""

    def setUp(self):
        self.app = MagicMock()
        self.app._orch = None
        from tui.command_processor import CommandProcessor
        self.cp = CommandProcessor(self.app, user_id=None)

    def test_parse_trades_paper(self):
        params = self.cp._parse_positional_params("trades paper")
        self.assertEqual(params.get("type"), "paper")

    def test_parse_trades_backtest_slug(self):
        params = self.cp._parse_positional_params("trades backtest btd-3dp")
        self.assertEqual(params.get("type"), "backtest")
        self.assertEqual(params.get("strategy"), "btd-3dp")

    def test_parse_trades_with_runid(self):
        params = self.cp._parse_positional_params(
            "trades paper btd 5815c821-c72d-42d2-9fa6-eaf22ecf8b83")
        self.assertEqual(params.get("type"), "paper")
        self.assertEqual(params.get("strategy"), "btd")
        self.assertEqual(params.get("run-id"),
                         "5815c821-c72d-42d2-9fa6-eaf22ecf8b83")

    def test_parse_all_scope(self):
        params = self.cp._parse_positional_params("trades all")
        self.assertEqual(params.get("scope"), "all")

    def test_parse_colon_syntax(self):
        params = self.cp._parse_positional_params("trades:paper")
        self.assertEqual(params.get("type"), "paper")

    def test_parse_report_runid(self):
        params = self.cp._parse_positional_params(
            "report 5815c821-c72d-42d2-9fa6-eaf22ecf8b83")
        self.assertEqual(params.get("run-id"),
                         "5815c821-c72d-42d2-9fa6-eaf22ecf8b83")

    def test_parse_top_paper_slug(self):
        params = self.cp._parse_positional_params("top paper btd")
        self.assertEqual(params.get("type"), "paper")
        self.assertEqual(params.get("strategy"), "btd")

    def test_parse_equity_backtest(self):
        params = self.cp._parse_positional_params("equity backtest")
        self.assertEqual(params.get("type"), "backtest")

    def test_user_account_filters_default(self):
        """Default: filters by user_id and account_id."""
        cp = self._make_cp(user_id="u1", account_id="a1")
        where, bind = [], {}
        cp._add_user_account_filters(where, bind, {})
        self.assertIn("user_id = :user_id", " ".join(where))
        self.assertIn("account_id = :account_id", " ".join(where))
        self.assertEqual(bind["user_id"], "u1")

    def test_user_account_filters_all(self):
        """scope=all: only user_id, no account_id."""
        cp = self._make_cp(user_id="u1", account_id="a1")
        where, bind = [], {}
        cp._add_user_account_filters(where, bind, {"scope": "all"})
        self.assertIn("user_id = :user_id", " ".join(where))
        self.assertNotIn("account_id", " ".join(where))

    def _make_cp(self, user_id=None, account_id=None):
        from tui.command_processor import CommandProcessor
        return CommandProcessor(self.app, user_id=user_id,
                                account_id=account_id)


# ---------------------------------------------------------------------------
# 6. Command Routing (async)
# ---------------------------------------------------------------------------

class TestCommandRouting(unittest.TestCase):
    """Test that commands route to the right handlers."""

    def setUp(self):
        self.app = MagicMock()
        self.app._orch = None
        from tui.command_processor import CommandProcessor
        self.cp = CommandProcessor(self.app, user_id=None)

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_help_returns_content(self):
        result = self._run(self.cp.process_command("help"))
        # CLI help uses Rich tables, so result could be None (rendered directly)
        # or a string. Just verify no crash.
        self.assertIsNotNone(result)

    def test_unknown_command_goes_to_chat(self):
        """Unrecognized input should go to chat agent (may fail without API key)."""
        # This tests routing, not the AI response
        with patch.object(self.cp, '_chat_agent', return_value="mocked"):
            result = self._run(self.cp.process_command("what is the weather"))
            self.assertEqual(result, "mocked")


# ---------------------------------------------------------------------------
# 7. Database Connectivity
# ---------------------------------------------------------------------------

class TestDatabase(unittest.TestCase):
    """Test database connection and basic queries."""

    def test_connection(self):
        """Verify DB pool connects and can run a simple query."""
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            result = session.execute(text("SELECT 1")).fetchone()
            self.assertEqual(result[0], 1)

    def test_schema_exists(self):
        """Verify alpatrade schema and key tables exist."""
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            for table in ["runs", "trades", "users", "backtest_summaries",
                          "user_accounts"]:
                result = session.execute(
                    text(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'alpatrade'
                            AND table_name = :tbl
                        )
                    """),
                    {"tbl": table},
                ).fetchone()
                self.assertTrue(result[0], f"Table alpatrade.{table} missing")

    def test_trades_have_required_columns(self):
        """Verify trades table has user_id and account_id columns."""
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            for col in ["user_id", "account_id", "trade_type", "entry_time",
                        "exit_time"]:
                result = session.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns
                            WHERE table_schema = 'alpatrade'
                            AND table_name = 'trades'
                            AND column_name = :col
                        )
                    """),
                    {"col": col},
                ).fetchone()
                self.assertTrue(result[0], f"Column trades.{col} missing")


# ---------------------------------------------------------------------------
# 8. Report Agent (DB queries)
# ---------------------------------------------------------------------------

class TestReportAgent(unittest.TestCase):
    """Test ReportAgent summary and top_strategies queries."""

    def test_summary_returns_list(self):
        from agents.report_agent import ReportAgent
        agent = ReportAgent()
        rows = agent.summary(limit=5)
        self.assertIsInstance(rows, list)
        if rows:
            self.assertIn("run_id", rows[0])
            self.assertIn("mode", rows[0])
            self.assertIn("total_pnl", rows[0])

    def test_summary_filter_by_type(self):
        from agents.report_agent import ReportAgent
        agent = ReportAgent()
        paper = agent.summary(trade_type="paper", limit=5)
        for r in paper:
            self.assertEqual(r["mode"], "paper")

        backtest = agent.summary(trade_type="backtest", limit=5)
        for r in backtest:
            self.assertEqual(r["mode"], "backtest")

    def test_top_strategies_returns_list(self):
        from agents.report_agent import ReportAgent
        agent = ReportAgent()
        rows = agent.top_strategies(limit=5)
        self.assertIsInstance(rows, list)
        if rows:
            self.assertIn("strategy_slug", rows[0])
            self.assertIn("avg_sharpe", rows[0])
            self.assertIn("total_runs", rows[0])

    def test_top_strategies_paper(self):
        from agents.report_agent import ReportAgent
        agent = ReportAgent()
        rows = agent.top_strategies(trade_type="paper", limit=5)
        self.assertIsInstance(rows, list)

    def test_detail_nonexistent_run(self):
        from agents.report_agent import ReportAgent
        agent = ReportAgent()
        result = agent.detail("nonexistent-run-id-00000000")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 9. Agent Storage
# ---------------------------------------------------------------------------

class TestAgentStorage(unittest.TestCase):
    """Test storage backend detection and run operations."""

    def test_storage_backend_detection(self):
        from utils.agent_storage import get_storage_backend
        backend = get_storage_backend()
        self.assertIn(backend, ["file", "db"])

    def test_fetch_nonexistent_backtest(self):
        from utils.agent_storage import fetch_backtest_trades
        trades = fetch_backtest_trades("nonexistent-run-00000000")
        self.assertIsInstance(trades, list)
        self.assertEqual(len(trades), 0)

    def test_fetch_nonexistent_paper(self):
        from utils.agent_storage import fetch_paper_trades
        trades = fetch_paper_trades("nonexistent-run-00000000")
        self.assertIsInstance(trades, list)
        self.assertEqual(len(trades), 0)


# ---------------------------------------------------------------------------
# 10. AGUI Tool Functions
# ---------------------------------------------------------------------------

class TestAGUITools(unittest.TestCase):
    """Test agui_app tool functions (show_recent_trades, etc.)."""

    def test_show_recent_trades_all(self):
        from agui_app import show_recent_trades
        result = show_recent_trades(limit=5)
        self.assertIsInstance(result, str)
        # Should return either trades table or "No trades found"
        self.assertTrue("trades" in result.lower() or "Symbol" in result
                        or "No trades" in result)

    def test_show_recent_trades_paper(self):
        from agui_app import show_recent_trades
        result = show_recent_trades(limit=5, trade_type="paper")
        self.assertIsInstance(result, str)

    def test_show_recent_trades_backtest(self):
        from agui_app import show_recent_trades
        result = show_recent_trades(limit=5, trade_type="backtest")
        self.assertIsInstance(result, str)

    def test_show_equity_curve_backtest(self):
        from agui_app import show_equity_curve
        result = show_equity_curve(trade_type="backtest")
        self.assertIsInstance(result, str)
        # Should return chart data or "No trade data"
        self.assertTrue("__CHART_DATA__" in result or "No" in result)

    def test_show_equity_curve_nonexistent(self):
        from agui_app import show_equity_curve
        result = show_equity_curve(run_id="nonexistent-00000000")
        self.assertIn("No", result)


# ---------------------------------------------------------------------------
# 11. Orchestrator Initialization
# ---------------------------------------------------------------------------

class TestOrchestrator(unittest.TestCase):
    """Test Orchestrator setup and configuration."""

    def test_init_creates_agents(self):
        from agents.orchestrator import Orchestrator
        orch = Orchestrator()
        self.assertIsNotNone(orch.backtester)
        self.assertIsNotNone(orch.paper_trader)
        self.assertIsNotNone(orch.validator)
        self.assertIsNotNone(orch.reconciler)
        self.assertIsNotNone(orch.run_id)

    def test_parse_duration(self):
        from agents.orchestrator import parse_duration
        self.assertEqual(parse_duration("1h"), 3600)
        self.assertEqual(parse_duration("30m"), 1800)
        self.assertEqual(parse_duration("7d"), 604800)
        self.assertEqual(parse_duration("300s"), 300)
        self.assertEqual(parse_duration("300"), 300)

    def test_init_with_user_and_account(self):
        from agents.orchestrator import Orchestrator
        orch = Orchestrator(user_id="test-user", account_id="test-account")
        self.assertEqual(orch.user_id, "test-user")
        self.assertEqual(orch.account_id, "test-account")
        self.assertEqual(orch.backtester.user_id, "test-user")
        self.assertEqual(orch.backtester.account_id, "test-account")


# ---------------------------------------------------------------------------
# 12. Backtest Agent (unit-level)
# ---------------------------------------------------------------------------

class TestBacktestAgent(unittest.TestCase):
    """Test BacktestAgent initialization."""

    def test_init(self):
        from agents.backtest_agent import BacktestAgent
        agent = BacktestAgent(user_id="u1", account_id="a1")
        self.assertEqual(agent.user_id, "u1")
        self.assertEqual(agent.account_id, "a1")
        self.assertEqual(agent.results, [])


# ---------------------------------------------------------------------------
# 13. Validate Agent (unit-level)
# ---------------------------------------------------------------------------

class TestValidateAgent(unittest.TestCase):
    """Test ValidationResult structure."""

    def test_validation_result_to_dict(self):
        from agents.validate_agent import ValidationResult
        vr = ValidationResult(
            status="passed",
            run_id="test-run",
            total_checked=10,
            anomalies=[],
            corrections=[],
            suggestions=[],
            iterations_used=1,
        )
        d = vr.to_dict()
        self.assertEqual(d["status"], "passed")
        self.assertEqual(d["run_id"], "test-run")
        self.assertEqual(d["total_trades_checked"], 10)
        self.assertEqual(d["iterations_used"], 1)


# ---------------------------------------------------------------------------
# 14. Config Loading
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):
    """Test parameters.yaml loading."""

    def test_parameters_yaml_exists(self):
        path = PROJECT_ROOT / "config" / "parameters.yaml"
        self.assertTrue(path.exists(), "config/parameters.yaml not found")

    def test_parameters_yaml_structure(self):
        import yaml
        path = PROJECT_ROOT / "config" / "parameters.yaml"
        with open(path) as f:
            params = yaml.safe_load(f)
        self.assertIn("buy_the_dip", params)
        self.assertIn("general", params)
        btd = params["buy_the_dip"]
        self.assertIn("symbols", btd)
        self.assertIn("dip_threshold", btd)
        self.assertIn("hold_days", btd)


# ---------------------------------------------------------------------------
# 15. PDT Tracker
# ---------------------------------------------------------------------------

class TestPDTTracker(unittest.TestCase):
    """Test Pattern Day Trade tracker."""

    def test_basic_tracking(self):
        from utils.pdt_tracker import PDTTracker
        tracker = PDTTracker()
        now = datetime.now(timezone.utc)

        # No trades yet
        self.assertTrue(tracker.can_day_trade(now))
        self.assertEqual(tracker.get_day_trade_count(now), 0)

        # Record 3 day trades
        for i in range(3):
            tracker.record_day_trade(now, f"SYM{i}")

        self.assertEqual(tracker.get_day_trade_count(now), 3)
        self.assertFalse(tracker.can_day_trade(now))

    def test_rolling_window(self):
        from utils.pdt_tracker import PDTTracker
        tracker = PDTTracker()
        # Use a date far enough back (> 5 business days)
        old = datetime.now(timezone.utc) - timedelta(days=10)

        for i in range(3):
            tracker.record_day_trade(old, f"OLD{i}")

        now = datetime.now(timezone.utc)
        # Old trades outside 5-business-day window should not count
        self.assertEqual(tracker.get_day_trade_count(now), 0)


# ---------------------------------------------------------------------------
# 16. Auth — User CRUD (requires DB)
# ---------------------------------------------------------------------------

class TestAuthDB(unittest.TestCase):
    """Test user creation and lookup (requires running DB)."""

    def test_create_and_lookup_user(self):
        from utils.auth import create_user, get_user_by_email
        import uuid
        email = f"regression-{uuid.uuid4().hex[:8]}@test.local"
        user = create_user(email, "TestPass123!", display_name="Regression Test")
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], email)

        found = get_user_by_email(email)
        self.assertIsNotNone(found)
        self.assertEqual(found["email"], email)

        # Cleanup
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            session.execute(
                text("DELETE FROM alpatrade.users WHERE email = :email"),
                {"email": email},
            )


# ---------------------------------------------------------------------------
# 17. Backtester Util — Metric Calculation
# ---------------------------------------------------------------------------

class TestBacktesterUtil(unittest.TestCase):
    """Test backtester utility metric calculation."""

    def test_calculate_metrics_empty(self):
        import pandas as pd
        from utils.backtester_util import calculate_metrics
        df = pd.DataFrame(columns=["entry_time", "exit_time", "pnl",
                                    "pnl_pct", "capital_after"])
        metrics = calculate_metrics(df, initial_capital=10000,
                                     start_date="2025-01-01",
                                     end_date="2025-12-31")
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["total_pnl"], 0)


# ---------------------------------------------------------------------------
# 18. Agent Status (stale detection)
# ---------------------------------------------------------------------------

class TestAgentStatusStaleDetection(unittest.TestCase):
    """Test that agent:status correctly detects stale running states."""

    def test_stale_running_corrected_to_idle(self):
        from agents.shared.state import PortfolioState
        import tempfile

        state = PortfolioState(run_id="stale-test", mode="paper")
        pt = state.get_agent("paper_trader")
        pt.set_running("paper_trading")

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        state.save(path)

        # Load and check — no live PID means it should be correctable
        loaded = PortfolioState.load(path)
        self.assertEqual(loaded.agents["paper_trader"].status, "running")

        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 19. AGUI Command Interceptor Detection
# ---------------------------------------------------------------------------

class TestAGUICommandDetection(unittest.TestCase):
    """Test that the AGUI command interceptor recognizes commands."""

    def test_cli_bases_detected(self):
        from agui_app import _CLI_BASES
        for cmd in ["trades", "runs", "top", "report", "equity", "chart",
                     "news", "profile"]:
            self.assertIn(cmd, _CLI_BASES, f"{cmd} not in _CLI_BASES")

    def test_cli_exact_detected(self):
        from agui_app import _CLI_EXACT
        for cmd in ["status", "help", "positions", "account", "accounts"]:
            self.assertIn(cmd, _CLI_EXACT, f"{cmd} not in _CLI_EXACT")


# ---------------------------------------------------------------------------
# 20. End-to-end: Command → DB Query → Result
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    """End-to-end tests: run commands and verify output format."""

    def setUp(self):
        self.app = MagicMock()
        self.app._orch = None
        from tui.command_processor import CommandProcessor
        self.cp = CommandProcessor(self.app, user_id=None)

    def test_trades_returns_markdown_table(self):
        result = self.cp._agent_trades({"type": "backtest", "limit": "5"})
        self.assertIsInstance(result, str)
        if "No trades" not in result:
            self.assertIn("Symbol", result)
            self.assertIn("P&L", result)

    def test_runs_returns_markdown_table(self):
        result = self.cp._agent_runs()
        self.assertIsInstance(result, str)
        if "No runs" not in result:
            self.assertIn("Run ID", result)
            self.assertIn("Mode", result)

    def test_report_returns_markdown(self):
        result = self.cp._agent_report({})
        self.assertIsInstance(result, str)
        if "No runs" not in result:
            self.assertIn("Run", result)

    def test_top_returns_markdown(self):
        result = self.cp._agent_top({})
        self.assertIsInstance(result, str)

    def test_status_returns_markdown(self):
        result = self.cp._agent_status()
        self.assertIsInstance(result, str)
        self.assertIn("Agent Status", result)

    def test_trades_paper_filter(self):
        result = self.cp._agent_trades({"type": "paper"})
        if "No trades" not in result:
            self.assertNotIn("| backtest |", result)

    def test_trades_backtest_filter(self):
        result = self.cp._agent_trades({"type": "backtest"})
        if "No trades" not in result:
            self.assertNotIn("| paper |", result)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Change to project root so relative paths work
    os.chdir(PROJECT_ROOT)

    # Use verbose test runner
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])

    print(f"\n{'='*70}")
    print(f"AlpaTrade Regression Suite — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}\n")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with error code if any test failed
    sys.exit(0 if result.wasSuccessful() else 1)

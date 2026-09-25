"""Offline tests for the live BTD recorder (mock DB) and the Live runs page."""
import json
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.live_btd_store import LiveRecorder, STRATEGY_NAME  # noqa: E402

UID = "b00535af-1a2e-4dc5-8b4b-eaaedf01077d"


class _Res:
    def __init__(self, row=None, rowcount=1):
        self._row, self.rowcount = row, rowcount

    def first(self):
        return self._row


class FakeEngine:
    def __init__(self, fail_on=None, user_row=(UID,), rowcount=1):
        self.calls, self.fail_on, self.user_row, self.rowcount = [], fail_on, user_row, rowcount

    @contextmanager
    def begin(self):
        yield self

    def execute(self, clause, params):
        sql = " ".join(str(clause).split())
        self.calls.append((sql, params))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("connection refused")
        if "FROM alpatrade.users" in sql:
            return _Res(self.user_row)
        if "COUNT(*) FILTER" in sql:
            return _Res((1, 1, 0, 8.0, 8.0, 8.0, 8.0, 8.0))
        return _Res(None, self.rowcount)


def test_no_database_url_disables_recording():
    assert not LiveRecorder(None, "x@y.z").enabled


def test_unknown_email_disables_and_never_creates_user():
    eng = FakeEngine(user_row=None)
    rec = LiveRecorder(None, "nobody@example.com", engine=eng)
    assert not rec.enabled
    assert rec.ensure_run(None, {}) is None
    assert not any("INSERT INTO alpatrade.users" in s for s, _ in eng.calls)


def test_ensure_run_is_live_and_owned_by_user():
    eng = FakeEngine()
    rec = LiveRecorder(None, "kaljuvee@gmail.com", engine=eng)
    rid = rec.ensure_run(None, {"account_number": "885504372", "dip_threshold": 3.0})
    assert rid and rec.user_id == UID
    sql, params = eng.calls[-1]
    assert "INSERT INTO alpatrade.runs" in sql and "'live'" in sql
    assert params["uid"] == UID and params["strategy"] == STRATEGY_NAME
    assert json.loads(params["config"])["account_number"] == "885504372"


def test_trade_lifecycle_uses_live_trade_type_and_client_order_id():
    eng = FakeEngine()
    rec = LiveRecorder(None, "kaljuvee@gmail.com", engine=eng)
    assert rec.entry_submitted("r1", "NVDA", "btd-NVDA-20260925", 389.39, 4.7, 234.75)
    assert rec.entry_filled("r1", "btd-NVDA-20260925", 1.74, 223.7, "2026-09-25T19:50:00Z", 8, 1.5)
    assert rec.exit_filled("r1", "btd-NVDA-20260925", 1.74, 241.6, None, "TP 8.01%")
    ins, upd_fill, upd_exit = [c for c in eng.calls if "alpatrade.trades" in c[0]]
    assert "'live'" in ins[0] and ins[1]["cid"] == "btd-NVDA-20260925" and ins[1]["uid"] == UID
    assert abs(upd_fill[1]["tp"] - 223.7 * 1.08) < 1e-9 and abs(upd_fill[1]["sl"] - 223.7 * 0.985) < 1e-9
    assert upd_exit[1]["tp"] is True and upd_exit[1]["sl"] is False


def test_db_failure_is_swallowed_and_disables_for_the_pass(caplog):
    eng = FakeEngine(fail_on="INSERT INTO alpatrade.trades")
    rec = LiveRecorder(None, "kaljuvee@gmail.com", engine=eng, log=logging.getLogger("t"))
    with caplog.at_level(logging.WARNING):
        assert rec.entry_submitted("r1", "AMZN", "c1", 100, 3, 1) is None   # no exception
    assert not rec.enabled
    assert "failed" in caplog.text
    n = len(eng.calls)
    assert rec.record_performance("r1", {}) is None and len(eng.calls) == n  # short-circuits


def test_positions_and_performance_upserts():
    eng = FakeEngine(rowcount=0)   # force the INSERT branches
    rec = LiveRecorder(None, "kaljuvee@gmail.com", engine=eng)
    pos = {"symbol": "GOOGL", "qty": "1.1", "avg_entry_price": "342", "current_price": "345",
           "market_value": "379.5", "unrealized_pl": "3.3", "unrealized_plpc": "0.0087", "cost_basis": "376.2"}
    assert rec.sync_positions("r1", [pos], {"GOOGL": "2026-09-25"})
    assert any("INSERT INTO alpatrade.positions" in s for s, _ in eng.calls)
    closed = rec.realized("r1")
    assert closed["trade_count"] == 1 and closed["total_pnl"] == 8.0
    assert rec.record_performance("r1", {"strategy_return_pct": 0.3}, daily_key="2026-09-25", closed=closed)
    sqls = [s for s, _ in eng.calls]
    assert any("ARRAY['daily', :k]" in s for s in sqls)
    assert any("INSERT INTO alpatrade.pnl_summary" in s for s in sqls)


def test_live_runs_page_renders_performance():
    from engine.web.ph_runs import _render
    row = {"run_id": "abcdef1234", "strategy": STRATEGY_NAME, "status": "running",
           "started_at": "2026-09-25T13:00", "completed_at": None,
           "run_config": json.dumps({"account_number": "885504372", "dip_threshold": 3.0,
                                     "take_profit": 8.0, "stop_loss": 1.5, "min_hold_days": 3,
                                     "hold_days": 3, "position_size": 0.142857}),
           "run_results": {"latest": {"total_pnl": 12.5, "strategy_return_pct": 0.46,
                                      "spy_return_pct": -0.2, "open_positions": 3,
                                      "closed_trades": 1, "as_of": "2026-09-25T15:55"}}}
    html = _render("live", [row])
    assert "Live runs" in html and "885504372" in html and "+0.46%" in html
    assert "dip 3.0% / TP 8.0% / SL 1.5% / hold 3-3d / size 14.3%" in html
    assert "No live runs yet" in _render("live", [])
    assert "href='/live'" in _render("paper", [])

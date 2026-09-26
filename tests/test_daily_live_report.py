"""Daily LIVE report: GET-only reads, fills/FIFO P&L, owner-only recipient,
trading-day scheduling and rendering. Offline — Alpaca, DB and Postmark mocked."""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest

from engine.brokers import alpaca_live_readonly as ro
from scripts import daily_live_report as rep

ACCOUNT = {"account_number": "885504372", "equity": "10200.00", "last_equity": "10000.00",
           "cash": "3000.00", "buying_power": "3000.00", "long_market_value": "7200.00"}
POSITIONS = [{"symbol": "GOOGL", "qty": "4.5", "avg_entry_price": "200", "current_price": "204",
              "market_value": "918", "unrealized_pl": "18", "unrealized_plpc": "0.02"}]
OPEN_ORDERS = [{"symbol": "AAPL", "side": "buy", "type": "limit", "qty": "1", "notional": None,
                "limit_price": "150", "time_in_force": "day", "status": "new",
                "submitted_at": "2026-09-25T14:00:00Z"}]
HISTORY_FILLS = [
    {"id": "1", "order_id": "o-old", "symbol": "AFRM", "side": "buy", "qty": "2.593",
     "price": "50", "transaction_time": "2026-08-01T14:00:00Z"},
    {"id": "2", "order_id": "o-afrm", "symbol": "AFRM", "side": "sell", "qty": "2.593",
     "price": "60", "transaction_time": "2026-09-25T13:31:00Z"},
    {"id": "3", "order_id": "o-crcl", "symbol": "CRCL", "side": "sell", "qty": "1",
     "price": "92.49", "transaction_time": "2026-09-25T03:31:00Z"},  # no prior buy
    {"id": "4", "order_id": "o-goog", "symbol": "GOOGL", "side": "buy", "qty": "2.5",
     "price": "200", "transaction_time": "2026-09-25T19:50:00Z"},
    {"id": "5", "order_id": "o-goog", "symbol": "GOOGL", "side": "buy", "qty": "2.0",
     "price": "200", "transaction_time": "2026-09-25T19:50:01Z"},
]
CLOSED = [{"id": "o-goog", "client_order_id": "btd-GOOGL-20260925"},
          {"id": "o-afrm", "client_order_id": "manual-1"}]
CAL = [{"date": "2026-09-24", "open": "09:30", "close": "16:00"},
       {"date": "2026-09-25", "open": "09:30", "close": "16:00"}]
HIST = {"timestamp": [int(datetime(2026, 9, 24, 4, tzinfo=timezone.utc).timestamp()),
                      int(datetime(2026, 9, 25, 4, tzinfo=timezone.utc).timestamp())],
        "equity": [10000.0, 10150.0]}


class FakeHTTP:
    """GET-only fake of the live API; filters calendar and fills like Alpaca does."""

    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        path = url.replace(ro.LIVE_BASE_URL, "")
        params = params or {}
        self.calls.append((path, params))
        if path == "/v2/account":
            body = ACCOUNT
        elif path == "/v2/positions":
            body = POSITIONS
        elif path == "/v2/orders":
            body = OPEN_ORDERS if params.get("status") == "open" else CLOSED
        elif path == "/v2/calendar":
            body = [c for c in CAL if params["start"] <= c["date"] <= params["end"]]
        elif path == "/v2/account/portfolio/history":
            body = HIST
        elif path == "/v2/account/activities/FILL":
            lo, hi = params.get("after", ""), params.get("until", "9999")
            body = [f for f in HISTORY_FILLS if lo < f["transaction_time"] <= hi]
        else:  # pragma: no cover
            raise AssertionError(path)
        return SimpleNamespace(status_code=200, json=lambda: body)


def _client(http=None):
    return ro.LiveReadOnlyClient("AKTESTKEY123456", "SECRETVALUE987654321",
                                 expected_account_number="885504372", http=http or FakeHTTP())


TARGET = {"user_id": "u-1", "email": "kaljuvee@gmail.com", "account_number": "885504372",
          "label": "Alpaca live"}
RUN = {"run_id": "abced9a9-ad0c-4c0b-a850-2ab49a45808a", "strategy": "Mag-7 BTD min-hold 3d",
       "status": "running",
       "config": {"symbols": ["GOOGL", "AMZN"], "dip_threshold": 3.0, "take_profit": 8.0,
                  "stop_loss": 1.5, "min_hold_days": 3, "hold_days": 3, "position_size": 0.142857,
                  "start_equity": 10000.0, "start_spy": 600.0, "started": "2026-09-24"},
       "results": {"latest": {"realized_pnl": 0, "closed_trades": 0, "spy": 606.0}},
       "heartbeat_at": datetime(2026, 9, 25, 19, 55, tzinfo=timezone.utc)}
RTRADES = [{"symbol": "GOOGL", "shares": 4.5, "entry_price": 200.0, "exit_price": None,
            "pnl": None, "reason": "open", "order_id": "btd-GOOGL-20260925", "dip_pct": 3.4,
            "entry_time": datetime(2026, 9, 25, 19, 50, 1, tzinfo=timezone.utc),
            "exit_time": None, "target_price": 216.0, "stop_price": 197.0,
            "created_at": datetime(2026, 9, 25, 19, 47, tzinfo=timezone.utc)}]


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(rep, "live_run", lambda uid, acct=None: RUN)
    monkeypatch.setattr(rep, "runner_trades", lambda rid: RTRADES)
    monkeypatch.setattr(rep, "_db_ok", lambda: True)
    monkeypatch.setattr(rep, "spy_close", lambda day, run: 612.0)
    monkeypatch.setattr(rep, "dip_signals", lambda syms, day, thr: [
        {"symbol": "GOOGL", "close": 204, "high20": 212, "dip": 3.8, "status": "signal"},
        {"symbol": "AMZN", "close": 220, "high20": 225, "dip": 2.2, "status": "near"}])


SAT = datetime(2026, 9, 26, 7, 50, tzinfo=timezone.utc)  # Sat 10:50 Tallinn


# ---- read-only client extensions ---------------------------------------------

def test_new_reads_are_get_only_and_allowlisted():
    http = FakeHTTP()
    c = _client(http)
    c.get_calendar("2026-09-25", "2026-09-25")
    c.get_fills(after="2026-09-24T00:00:00Z", until="2026-09-26T00:00:00Z")
    c.get_order_history("2026-09-18T00:00:00Z", "2026-09-26T00:00:00Z")
    c.get_portfolio_history("2026-09-15", "2026-09-25", "1D")
    assert {p for p, _ in http.calls} == {"/v2/calendar", "/v2/account/activities/FILL",
                                          "/v2/orders", "/v2/account/portfolio/history"}


@pytest.mark.parametrize("path,params", [
    ("/v2/orders", {"status": "all"}),
    ("/v2/orders", {"after": "2026-09-01"}),                     # status is mandatory
    ("/v2/orders", {"status": "closed", "symbols": "AAPL"}),     # unknown key
    ("/v2/account/activities/FILL", {"date": "2026-09-25; DROP"}),
    ("/v2/account/activities", {}),
    ("/v2/account/activities/TRANS", {}),
    ("/v2/calendar", {"start": "x"}),
    ("/v2/assets", {}),
])
def test_extended_queries_still_refused_before_network(path, params):
    http = FakeHTTP()
    with pytest.raises(ro.LiveReadOnlyError):
        _client(http)._get(path, params)
    assert http.calls == []


# ---- trading days -------------------------------------------------------------

def test_session_helpers_use_the_calendar():
    c = _client()
    assert rep.session_for(c, date(2026, 9, 26)) is None  # Saturday
    s = rep.latest_completed_session(c, SAT)
    assert s["date"] == date(2026, 9, 25)
    assert s["close"].hour == 16
    assert rep.previous_session(c, date(2026, 9, 25))["date"] == date(2026, 9, 24)


# ---- P&L ------------------------------------------------------------------------

def test_aggregate_and_fifo_realized():
    orders = rep.aggregate_fills(HISTORY_FILLS[1:])
    goog = next(o for o in orders if o["order_id"] == "o-goog")
    assert goog["qty"] == pytest.approx(4.5) and goog["price"] == pytest.approx(200)
    pnl = rep.fifo_realized(HISTORY_FILLS, orders)
    assert pnl["o-afrm"] == pytest.approx(2.593 * 10)
    assert pnl["o-crcl"] is None  # no cost basis in history -> unknown, not $0
    assert "o-goog" not in pnl


def test_gather_friday_from_saturday(db):
    d = rep.gather(_client(), TARGET, now=SAT)
    assert d["day"] == "2026-09-25" and d["backdated"]
    assert d["equity"] == pytest.approx(10150) and d["day_pnl"] == pytest.approx(150)
    assert d["equity_now"] == pytest.approx(10200)
    syms = [(o["symbol"], o["side"], o["source"]) for o in d["fills"]]
    # the overnight CRCL fill (Thu 23:31 ET) belongs to Friday's session window
    assert ("CRCL", "sell", "other") in syms and ("GOOGL", "buy", "runner") in syms
    assert ("AFRM", "sell", "other") in syms
    assert d["runner_open"][0]["symbol"] == "GOOGL"
    assert d["runner_open"][0]["max_hold_exit"] == date(2026, 9, 28)
    assert d["perf"]["account_return_pct"] == pytest.approx(1.5)
    assert d["perf"]["spy_return_pct"] == pytest.approx(2.0)
    assert d["perf"]["excess_pct"] == pytest.approx(-0.5)
    assert d["warnings"] == []


def test_missed_runner_pass_is_flagged(db, monkeypatch):
    stale = {**RUN, "heartbeat_at": datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(rep, "live_run", lambda uid, acct=None: stale)
    d = rep.gather(_client(), TARGET, now=SAT)
    assert any("entry window" in w for w in d["warnings"])


def test_non_trading_day_short_circuits(db):
    d = rep.gather(_client(), TARGET, day=date(2026, 9, 26), now=SAT)
    assert d["no_trading_day"]
    assert "No trading day" in rep.render(d)


def test_render_contains_all_sections_and_no_secrets(db):
    d = rep.gather(_client(), TARGET, now=SAT)
    html = rep.render(d)
    for needle in ("Daily LIVE report", "885504372", "+$150.00", "Fills this session",
                   "CRCL", "AFRM", "+$25.93", "n/a", "Current positions", "GOOGL",
                   "Open orders", "AAPL", "Live runner", "Mon Sep 28", "SIGNAL", "near",
                   "SPY since start", "+2.00%", "-0.50%", "REAL MONEY"):
        assert needle in html, needle
    assert "AKTESTKEY" not in html and "SECRETVALUE" not in html
    assert rep.subject_for(d).startswith("AlpaTrade LIVE PnL — Sep 25, 2026 (+$150")


# ---- sending: owner only ----------------------------------------------------------

def test_send_report_goes_only_to_owner_and_returns_message_id(db, monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr("utils.email_util.send_email_to_result",
                        lambda to, subj, body: sent.append((to, subj)) or
                        {"ok": True, "message_id": "pm-123", "error": None})
    claims, finishes = [], []
    monkeypatch.setattr(rep, "claim_live_delivery",
                        lambda uid, acct, day, force=False: claims.append(day) or True)
    monkeypatch.setattr(rep, "finish_live_delivery",
                        lambda uid, acct, day, ok, mid=None: finishes.append((ok, mid)))
    out = tmp_path / "r.html"
    res = rep.send_report(TARGET, client=_client(), html_out=str(out),
                          day=date(2026, 9, 25))
    assert res["sent"] and res["message_id"] == "pm-123"
    assert [to for to, _ in sent] == ["kaljuvee@gmail.com"]
    assert claims == ["2026-09-25"] and finishes == [(True, "pm-123")]
    assert "Daily LIVE report" in out.read_text()


def test_already_delivered_is_not_resent(db, monkeypatch):
    send = mock.Mock()
    monkeypatch.setattr("utils.email_util.send_email_to_result", send)
    monkeypatch.setattr(rep, "claim_live_delivery", lambda *a, **k: False)
    res = rep.send_report(TARGET, client=_client(), day=date(2026, 9, 25))
    assert not res["sent"] and "already" in res["error"]
    send.assert_not_called()


def test_cli_has_no_recipient_override():
    import inspect
    src = inspect.getsource(rep.main)
    assert '"--to"' not in src and "'--to'" not in src


def test_report_targets_query_joins_owner_email(monkeypatch):
    seen = {}

    class Sess:
        def execute(self, sql, params=None):
            seen["sql"] = str(sql)
            return SimpleNamespace(fetchall=lambda: [("u-1", "kaljuvee@gmail.com",
                                                      "885504372", "Alpaca live")])
    from contextlib import contextmanager

    @contextmanager
    def gs():
        yield Sess()
    monkeypatch.setattr(rep, "_pool", lambda: SimpleNamespace(get_session=gs))
    t = rep.report_targets()
    assert t == [TARGET]
    assert "user_live_broker_accounts" in seen["sql"] and "l.read_only" in seen["sql"]
    assert "u.email" in seen["sql"] and "user_accounts ua" not in seen["sql"]


# ---- email sender ----------------------------------------------------------------

def test_send_email_to_result_returns_postmark_message_id(monkeypatch):
    from utils import email_util
    monkeypatch.setenv("POSTMARK_API_KEY", "pm-token")
    monkeypatch.setenv("FROM_EMAIL", "bot@alpatrade.chat")
    resp = SimpleNamespace(raise_for_status=lambda: None, content=b"{}",
                           json=lambda: {"MessageID": "abc-1", "ErrorCode": 0})
    with mock.patch.object(email_util.requests, "post", return_value=resp) as post:
        out = email_util.send_email_to_result("kaljuvee@gmail.com", "s", "<p>x</p>")
    assert out == {"ok": True, "message_id": "abc-1", "error": None}
    assert post.call_args.kwargs["json"]["To"] == "kaljuvee@gmail.com"
    monkeypatch.delenv("POSTMARK_API_KEY")
    assert email_util.send_email_to_result("a@b", "s", "x")["ok"] is False


# ---- scheduler ------------------------------------------------------------------

@pytest.fixture
def sched(monkeypatch):
    from engine.autonomy import schedule
    schedule._live_done.clear()
    schedule._live_closes.clear()
    monkeypatch.setenv("LIVE_REPORT_ENABLED", "true")
    monkeypatch.setattr(rep, "report_targets", lambda email=None: [TARGET])
    monkeypatch.setattr(rep, "client_for", lambda t: _client())
    calls = []
    monkeypatch.setattr(rep, "send_report",
                        lambda t, day=None, client=None, **k: calls.append((t["email"], day))
                        or {"sent": True, "message_id": "m"})
    return schedule, calls


def test_scheduler_waits_for_close_plus_delay_then_sends_once(sched):
    schedule, calls = sched
    before = datetime(2026, 9, 25, 20, 10, tzinfo=timezone.utc)  # 16:10 ET
    after = datetime(2026, 9, 25, 20, 21, tzinfo=timezone.utc)   # 16:21 ET = 23:21 Tallinn
    assert schedule.run_due_live_reports(before) == [] and calls == []
    schedule.run_due_live_reports(after)
    schedule.run_due_live_reports(after)
    assert calls == [("kaljuvee@gmail.com", date(2026, 9, 25))]


def test_scheduler_skips_weekends(sched):
    schedule, calls = sched
    schedule.run_due_live_reports(datetime(2026, 9, 26, 21, 0, tzinfo=timezone.utc))
    assert calls == []


def test_scheduler_can_be_disabled(sched, monkeypatch):
    schedule, calls = sched
    monkeypatch.setenv("LIVE_REPORT_ENABLED", "false")
    assert schedule.run_due_live_reports(datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)) == []
    assert calls == []


def test_paper_report_remains_paper_only():
    import inspect
    from scripts import daily_pnl_report as paper
    assert "trade_type = 'paper'" in inspect.getsource(paper.gather_trades)
    assert "user_accounts" in inspect.getsource(paper.report_targets)
    assert "live" not in inspect.getsource(paper.report_targets).lower()

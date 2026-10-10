"""Synthetic reproductions of the Semi 7 backtest bugs; each must FAIL the audit."""
from utils.backtest_audit import (FAIL, PASS, WARN, AuditInput, assert_publishable, audit,
                                  from_leaderboard_metrics)
import pytest

LIVE = {"dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3}
TESTED_LIVE = {"dip_threshold": 0.03, "take_profit": 0.08, "stop_loss": 0.015, "hold_days": 3, "min_hold_days": 3}


def _trade(sym, d_in, d_out, pnl, cap_after, *, shares=10, entry=100.0, fees=0.05, **kw):
    return {"ticker": sym, "signal_time": f"{d_in}T15:50", "entry_time": f"{d_in}T15:55",
            "exit_time": f"{d_out}T16:00", "shares": shares, "entry_price": entry,
            "exit_price": entry + (pnl + fees) / shares, "pnl": pnl, "capital_after": cap_after,
            "total_fees": fees, "target_price": entry * 1.08, "stop_price": entry * 0.985, **kw}


def _good_trades(n=40):
    out, cap = [], 10_000.0
    for i in range(n):
        d1, d2 = f"2026-01-{1 + i % 27:02d}", f"2026-01-{1 + i % 27:02d}"
        pnl = 12.0 if i % 3 else -8.0
        cap += pnl
        t = _trade("AAA", d1, d2, pnl, cap)
        t["entry_time"], t["exit_time"] = f"2026-{1 + i // 27:02d}-{1 + i % 27:02d}T15:55", f"2026-{1 + i // 27:02d}-{1 + i % 27:02d}T16:00"
        t["signal_time"] = t["entry_time"][:11] + "15:50"
        out.append(t)
    return out, cap


def _base(**kw):
    trades, final = _good_trades()
    a = dict(trades=trades, initial_capital=10_000.0, final_equity=final,
             reported_return_pct=(final / 10_000 - 1) * 100, slippage_bps=5.0, same_bar_policy="stop_first",
             label="live", params=TESTED_LIVE, live_params=LIVE, fill_rule="close",
             universe=["AAA"], universe_as_of="2025-12-31", period_start="2026-01-01",
             annualised_pct=25.0, sharpe=1.4, max_drawdown_pct=-4.0, is_return_pct=10.0, oos_return_pct=7.0,
             engine_stamp={"engine": "buy_the_dip", "engine_version": "0.33.6", "git_sha": "b47e6de"})
    a.update(kw)
    return AuditInput(**a)


def _status(rep, name):
    return next(c for c in rep.checks if c.name == name).status


def test_clean_backtest_passes():
    rep = audit(_base())
    assert rep.status == PASS, rep.reasons


def test_same_bar_multi_exit_double_count_fails():
    # two positions of $1,000 each close on the same bar for +$20 each; the engine re-adds the
    # released capital on the second exit -> capital_after $11,040 instead of $10,040
    trades = [_trade("AAA", "2026-02-02", "2026-02-05", 20.0, 11_020.0),
              _trade("BBB", "2026-02-02", "2026-02-05", 20.0, 11_040.0)]
    rep = audit(_base(trades=trades, final_equity=11_040.0, reported_return_pct=10.4, n_trades=40))
    assert _status(rep, "same_bar_exits") == FAIL
    assert _status(rep, "reconciliation") == FAIL
    assert rep.status == FAIL


def test_tp_and_sl_on_same_bar_booked_as_target_fails():
    trades, final = _good_trades()
    trades[5].update(bar_high=trades[5]["target_price"] + 1, bar_low=trades[5]["stop_price"] - 1, hit_target=True)
    rep = audit(_base(trades=trades))
    assert _status(rep, "tp_sl_same_bar") == FAIL and rep.status == FAIL
    assert _status(audit(_base(same_bar_policy="target_first")), "tp_sl_same_bar") == FAIL
    assert _status(audit(_base(same_bar_policy=None)), "tp_sl_same_bar") == WARN


def test_zero_slippage_or_fees_fails():
    assert _status(audit(_base(slippage_bps=0.0)), "costs") == FAIL
    trades, _ = _good_trades()
    for t in trades:
        t["total_fees"] = 0.0
    assert _status(audit(_base(trades=trades)), "costs") == FAIL


def test_param_mismatch_labelled_live_fails_but_research_passes():
    semi7_tested = {"dip_threshold": 0.03, "take_profit": 0.015, "stop_loss": 0.005, "hold_days": 1}
    rep = audit(_base(params=semi7_tested))
    c = next(c for c in rep.checks if c.name == "params")
    assert c.status == FAIL and "tp 1.5 vs live 8" in c.reason and "max_hold 1 vs live 3" in c.reason
    assert _status(audit(_base(params=semi7_tested, label="research")), "params") == PASS


def test_negative_cash_and_lookahead_fail():
    trades = [_trade("AAA", "2026-03-02", "2026-03-05", 5.0, 10_005.0, shares=80),
              _trade("BBB", "2026-03-02", "2026-03-05", 5.0, 10_010.0, shares=80)]
    assert _status(audit(_base(trades=trades)), "cash") == FAIL           # 2 × $8,000 on $10k
    look = [dict(t) for t in _good_trades()[0]]
    look[0]["signal_time"] = "2026-01-01T16:30"                            # signal after the fill
    assert _status(audit(_base(trades=look)), "lookahead") == FAIL
    assert _status(audit(_base(fill_rule="next_open")), "lookahead") == FAIL  # filled on signal bar


def test_plausibility_gates_and_override():
    assert _status(audit(_base(annualised_pct=250.0)), "plausibility") == WARN
    assert _status(audit(_base(sharpe=5.0)), "plausibility") == WARN
    assert _status(audit(_base(max_drawdown_pct=0.0)), "plausibility") == WARN   # 0 DD, 40 trades
    assert _status(audit(_base(annualised_pct=1629.7)), "plausibility") == FAIL
    assert _status(audit(_base(sharpe=9.0)), "plausibility") == FAIL
    over = audit(_base(annualised_pct=1629.7, override_note="JK 2026-10-10: tiny sample, reviewed"))
    assert _status(over, "plausibility") == WARN


def test_min_trades_universe_and_oos():
    assert _status(audit(_base(n_trades=5)), "min_trades") == FAIL
    assert _status(audit(_base(n_trades=25)), "min_trades") == WARN
    assert _status(audit(_base(universe_as_of="2026-10-09")), "universe") == WARN
    c = next(c for c in audit(_base(is_return_pct=20.0, oos_return_pct=4.0)).checks if c.name == "oos_degradation")
    assert c.status == WARN and "IS +20.00% vs OOS +4.00%" in c.reason


def test_publish_gate_refuses_failures():
    with pytest.raises(PermissionError):
        assert_publishable(audit(_base(slippage_bps=0)))
    assert_publishable(audit(_base(annualised_pct=250.0)))   # warn is publishable


def test_semi7_leaderboard_entry_fails():
    from engine.leaderboard.semi7 import audit_input
    bm = {"annualised_pct": 1629.7, "sharpe": 7.67, "max_drawdown_pct": 0.0, "trades": 742,
          "period_start": "2026-02-11", "universe": "Semi 7", "audit_input": audit_input()}
    rep = audit(from_leaderboard_metrics(bm))
    assert rep.status == FAIL
    names = {c.name for c in rep.checks if c.status == FAIL}
    assert {"costs", "params", "known_issue"} <= names


def test_btd_results_before_b47e6de_or_unstamped_are_invalid():
    old = audit(_base(engine_stamp={"engine": "buy_the_dip", "engine_version": "0.32.1"}))
    assert _status(old, "engine_version") == FAIL and "b47e6de" in old.reasons[0]
    assert _status(audit(_base(engine_stamp=None, engine="buy_the_dip")), "engine_version") == FAIL
    assert _status(audit(_base(engine_stamp={"engine": "buy_the_dip", "engine_version": "0.34.0"})),
                   "engine_version") == PASS
    assert _status(audit(_base(engine_stamp=None, engine="breakout")), "engine_version") == WARN


def test_every_run_gets_an_engine_stamp():
    from utils.agent_storage import _stamped
    from utils.engine_stamp import app_version
    cfg = _stamped({"params": {}}, "buy_the_dip")
    assert cfg["engine_stamp"]["engine"] == "buy_the_dip" and cfg["engine_stamp"]["engine_version"] == app_version()
    assert _stamped({"engine_stamp": {"x": 1}}, "btd")["engine_stamp"] == {"x": 1}


def test_leaderboard_badge_and_audit_section_for_failing_entry():
    from engine.leaderboard import semi7
    from engine.web import ph_leaderboard as lb
    wf = {"rows": [{"test_period": "2026-02-11→2026-03-13", "oos_pnl": 4094, "oos_ret": 0.41, "oos_trades": 108,
                    "params": {"dip_threshold": 0.03, "take_profit": 0.015, "stop_loss": 0.005, "hold_days": 1}}],
          "metrics": {"btd_sharpe": 7.67, "trade_win_rate": 60.6}, "total_is": 30000, "total_oos": 25000}
    bm = semi7.build_metrics(wf, {"2026-02-11": 100.0, "2026-03-13": 101.0})
    row = {"id": 17, "kind": "backtest", "backtest_metrics": bm, "skill_md": "", "name": "Semi 7"}
    row["user_id"] = "owner"
    # public / other users: no audit badge or section at all (no PASS / WARN / FAILED)
    for viewer in (None, {"user_id": "someone"}):
        badge = lb._bt_badge(row, viewer)
        assert "Backtest" in badge and "Audit" not in badge and "#audit" not in badge and "Failed" not in badge
        assert lb.audit_html(row, viewer) == ""
    assert lb._audit(row).status == "fail"            # the gate still evaluates it
    own = {"user_id": "owner"}
    assert "Failed checks" in lb._bt_badge(row, own)
    sec = lb.audit_html(row, own)
    assert "Failed backtest checks" in sec and "engine_version" in sec and "Audit" not in sec


def test_publish_gate_blocks_failing_and_stamps_passing():
    from engine.leaderboard.audit_gate import gate
    good_md = "## Parameters\n```json\n{\"execution\": {\"slippage_bps_per_side\": 10}, \"params\": {}}\n```\n"
    bm = {"annualised_pct": 12.0, "sharpe": 0.9, "max_drawdown_pct": -20.0, "trades": 400,
          "template": "breakout", "period_start": "2016-01-04"}
    out = gate(bm, good_md)
    assert out["audit"]["status"] in ("pass", "warn") and out["engine_stamp"]["engine_version"]
    with pytest.raises(PermissionError):
        gate({**bm, "annualised_pct": 1629.7}, good_md)


def test_open_positions_at_end_is_warn_but_big_residual_still_fails():
    trades, final = _good_trades()
    rep = audit(_base(final_equity=final - 30, reported_return_pct=None, open_at_end_possible=True,
                      period_end="2026-02-14"))
    assert _status(rep, "reconciliation") == WARN
    rep = audit(_base(final_equity=final + 3000, reported_return_pct=None, open_at_end_possible=True,
                      period_end="2026-02-14"))
    assert _status(rep, "reconciliation") == FAIL

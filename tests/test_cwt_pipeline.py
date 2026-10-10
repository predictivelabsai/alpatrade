"""Chat With Traders pipeline + backtest strategies on the Leaderboard — DB-free tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.leaderboard import perf, skill, store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cwt_pipeline as cwt  # noqa: E402

BM = {"period_start": "2016-01-04", "period_end": "2026-10-09", "trading_days": 2708,
      "total_return_pct": -17.4, "annualised_pct": -1.77, "spy_return_pct": 356.2,
      "spy_annualised_pct": 15.17, "alpha_pct": -373.6, "alpha_annualised_pct": -16.9,
      "sharpe": -0.2, "max_drawdown_pct": -30.2, "win_rate_pct": 27.0, "trades": 334,
      "test": {"period_start": "2022-01-03", "period_end": "2026-10-09", "annualised_pct": -3.2,
               "spy_annualised_pct": 12.3, "sharpe": -0.42, "max_drawdown_pct": -26.5,
               "trades": 124}, "universe": "S&P 500 current members"}


def _bt(**kw):
    s = {"id": 9, "user_id": "u-julian", "name": "Kristjan Kullamägi · Momentum breakout (backtest)",
         "author": "Kristjan Kullamägi", "description": "Daily-bar backtest", "is_public": True,
         "skill_md": "---\ntitle: X\nkind: backtest\nauthor: Kristjan Kullamägi\n---\n# X\n",
         "kind": "backtest", "source": "chatwithtraders.com",
         "source_url": "https://chatwithtraders.com/episode/212-kristjan-kullamagi",
         "backtest_metrics": dict(BM), "live_strategy_slug": None, "cloned_from_id": None}
    s.update(kw)
    return s


def test_backtest_metrics_come_from_stored_json_not_live_run():
    m = perf.strategy_metrics(_bt())
    assert m["is_backtest"] and m["has_data"]
    # simple ×252/trading days (v0.33.4): -17.4% × 252 / 2708; alpha = simple − SPY simple
    assert abs(m["annualised_pct"] - (-17.4 * 252 / 2708)) < 1e-9
    assert abs(m["alpha_pct"] - (-17.4 - 356.2) * 252 / 2708) < 1e-9
    assert abs(m["alpha_total_pct"] - (-373.6)) < 1e-9
    assert m["start_date"] == "2016-01-04" and m["as_of"] == "2026-10-09"
    empty = perf.strategy_metrics(_bt(backtest_metrics=None))
    assert empty["is_backtest"] and empty["annualised_pct"] is None
    assert "never traded live" in perf.annualised_tip(m)


def test_backtests_rank_after_live_strategies():
    live_none = dict(perf.EMPTY)
    live = {**perf.EMPTY, "annualised_pct": 5.0}
    bt_hi = {**perf.EMPTY, "annualised_pct": 99.0, "is_backtest": True}
    rows = sorted([bt_hi, live_none, live], key=perf.rank_key)
    assert rows == [live, live_none, bt_hi]


def test_leaderboard_row_shows_backtest_badge_period_and_source():
    from engine.web import ph_leaderboard as lb
    html = lb.leaderboard_html([(_bt(), perf.strategy_metrics(_bt()))], None)
    assert "lb-badge bt" in html and ">Backtest<" in html
    assert "href='https://chatwithtraders.com/episode/212-kristjan-kullamagi'" in html
    assert "Kristjan Kullamägi" in html and "4 Jan 2016 – 9 Oct 2026" in html
    assert "Backtest period" in html and perf.pct(-17.4 * 252 / 2708) in html


def test_strategy_page_backtest_kpis_and_disclaimer():
    from engine.web import ph_leaderboard as lb
    s = _bt()
    page = lb.strategy_html(s, perf.strategy_metrics(s), None)
    assert ">Backtest<" in page and "not a live" in page
    assert "Out-of-sample test window" in page and "Sharpe" in page
    assert "chatwithtraders.com ↗" in page
    live = lb.strategy_html({**s, "kind": "live", "backtest_metrics": None}, dict(perf.EMPTY), None)
    assert ">Backtest<" not in live


def test_source_link_rejects_non_http_urls():
    from engine.web import ph_leaderboard as lb
    assert lb._source(_bt(source_url="javascript:alert(1)")) == ""
    assert "&lt;" in lb._source(_bt(source="<b>x</b>"))


def test_live_strategy_unchanged_predictive_labs():
    seed = Path("engine/leaderboard/seeds/mag7-btd-live.md").read_text(encoding="utf-8")
    assert skill.front_matter(seed)["author"] == "Predictive Labs Ltd"
    assert not store.is_backtest({"kind": "live"}) and store.is_backtest({"kind": "backtest"})


def test_guest_and_caption_parsing():
    assert cwt._guest("212: Kristjan Kullamägi – Breakouts, Home Runs") == "Kristjan Kullamägi"
    assert cwt._guest("318 · Dave Mabe - The Shift") == "Dave Mabe"
    j = {"events": [{"tStartMs": 0, "segs": [{"utf8": "i buy"}]},
                    {"tStartMs": 31000, "segs": [{"utf8": "opening range highs"}]},
                    {"tStartMs": 65000, "segs": [{"utf8": "low of day"}]}]}
    txt = cwt.captions_to_text(j)
    assert txt.splitlines()[0].startswith("[00:00:00] i buy opening range highs")
    assert "[00:01:05] low of day" in txt


def _bars(n=260, seed=0, jump_at=None):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    c = 50 * np.cumprod(1 + rng.normal(0.003, 0.01, n))
    if jump_at:
        c[jump_at:] *= 1.5  # a future jump the strategy must not see in advance
    df = pd.DataFrame({"o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1e6}, index=idx)
    return df


def test_breakout_has_no_look_ahead():
    """Changing bars AFTER day k must not change anything up to day k."""
    from engine.backtest.breakout import BreakoutParams, run
    p = BreakoutParams(mom_days=40, mom_min=0.05, cons_days=10, cons_max_range=0.2,
                       market_filter=False)
    spy = _bars(seed=99)
    a = {"A": _bars(seed=1), "B": _bars(seed=2)}
    b = {"A": _bars(seed=1, jump_at=200), "B": _bars(seed=2, jump_at=200)}
    ra = run(a, spy, "2020-03-01", "2020-12-31", p)
    rb = run(b, spy, "2020-03-01", "2020-12-31", p)
    k = a["A"].index[199]
    assert ra["equity"].loc[:k].equals(rb["equity"].loc[:k])
    assert ra["trades"] > 0


def test_breakout_cash_only_and_costs():
    from engine.backtest.breakout import BreakoutParams, run
    p = BreakoutParams(mom_days=40, mom_min=0.05, cons_days=10, cons_max_range=0.2,
                       market_filter=False, max_pos_pct=0.5, risk_pct=0.05)
    spy = _bars(seed=99)
    bars = {s: _bars(seed=i) for i, s in enumerate("ABCDEF")}
    r = run(bars, spy, "2020-03-01", "2020-12-31", p, capital=10_000)
    assert r["fees_paid"] > 0
    assert sum(t["pnl"] for t in r["trips"]) == pytest.approx(r["equity"].iloc[-1] - 10_000, rel=1e-6)
    assert (r["equity"] > 0).all()


def test_skill_md_round_trips_params_and_front_matter():
    import json
    d = Path("data/cwt/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns")
    if not (d / "skill.md").exists():
        pytest.skip("pilot artefacts not present")
    md = (d / "skill.md").read_text(encoding="utf-8")
    fm = skill.front_matter(md)
    assert fm["kind"] == "backtest" and fm["source"] == "chatwithtraders.com"
    assert fm["author"] == "Kristjan Kullamägi"
    block = skill.extract_params(md)
    assert block["kind"] == "backtest" and block["params"]["slippage_bps"] >= 5
    assert json.loads((d / "backtest.json").read_text())["full"]["trades"] > 0


def test_leaderboard_filters_and_pagination():
    from engine.web import ph_leaderboard as lb
    live = {"id": 1, "user_id": "u", "name": "Mag-7 BTD", "author": "Predictive Labs Ltd",
            "description": "", "kind": "live", "skill_md": "", "is_public": True}
    rows = [(live, dict(perf.EMPTY))] + [
        (_bt(id=100 + i, name=f"Trader {i} · Dip", author=f"Trader {i}"), perf.strategy_metrics(_bt()))
        for i in range(60)]
    html = lb.leaderboard_html(rows, None)
    assert "page 1 of 3" in html and "Next →" in html and "Predictive Labs Ltd" in html
    assert html.count("class='lb-row' id='strategy-") == lb.PAGE_SIZE
    bt = lb.leaderboard_html(rows, None, kind="backtest", page=3)
    assert "Predictive Labs Ltd" not in bt.split("lb-note")[0] and "page 3 of 3" in bt
    assert bt.count("class='lb-row' id='strategy-") == 10
    lv = lb.leaderboard_html(rows, None, kind="live")
    assert "Mag-7 BTD" in lv and "Trader 1 · Dip" not in lv
    q = lb.leaderboard_html(rows, None, q="trader 42")
    assert "Trader 42" in q and "1 strategy" in q
    src = lb.leaderboard_html(rows, None, source="AlpaTrade")
    assert "Mag-7 BTD" in src and "Trader 3 ·" not in src
    assert "<script>" not in lb.leaderboard_html(rows, None, q="<script>").split("LB_JS")[0].split("<script>\n(function")[0]
    assert "(hover: none)" in lb.LB_JS and "min-height:44px" in lb.LB_CSS


def test_multi_episode_sources_listed():
    from engine.web import ph_leaderboard as lb
    bm = {**BM, "episodes": [{"episode": "64", "url": "https://chatwithtraders.com/episode/64-x", "title": "a"},
                             {"episode": "4", "url": "https://chatwithtraders.com/episode/4-y", "title": "b"},
                             {"episode": "9", "url": "javascript:alert(1)", "title": "c"}]}
    s = _bt(backtest_metrics=bm)
    assert "2 episodes" in lb._source(s)
    page = lb.strategy_html(s, perf.strategy_metrics(s), None)
    assert "ep. 64 ↗" in page and "ep. 4 ↗" in page and "javascript:" not in page


def test_templates_no_look_ahead_and_reconcile():
    from engine.backtest import templates as T
    spy = _bars(seed=99)
    for tpl, extra in (("dip", {"dip": 0.01, "target": 0.03, "stop": 0.03, "max_hold": 5, "trend_ma": 0}),
                       ("trend_ma", {"fast": 5, "slow": 20, "exit_ma": 20}),
                       ("gap", {"gap_min": 0.01, "stop": 0.03, "max_hold": 5}),
                       ("relative_strength", {"lookback": 20, "top_n": 2, "rebalance_days": 5, "trend_ma": 0})):
        p = T.RuleParams.from_dict({"template": tpl, "market_filter": False, **extra})
        a = {s: _bars(n=400, seed=i) for i, s in enumerate("ABCD")}
        b = {s: _bars(n=400, seed=i, jump_at=300) for i, s in enumerate("ABCD")}
        a = {s: df.assign(o=df["c"].shift(1).fillna(df["c"]) * (1.02 if tpl == "gap" else 1.0)) for s, df in a.items()}
        b = {s: df.assign(o=df["c"].shift(1).fillna(df["c"]) * (1.02 if tpl == "gap" else 1.0)) for s, df in b.items()}
        ra = T.run(a, spy.reindex(a["A"].index).ffill(), "2020-03-01", "2021-07-01", p, capital=10_000)
        rb = T.run(b, spy.reindex(b["A"].index).ffill(), "2020-03-01", "2021-07-01", p, capital=10_000)
        k = a["A"].index[298]
        assert ra["equity"].loc[:k].equals(rb["equity"].loc[:k]), tpl
        assert sum(t["pnl"] for t in ra["trips"]) == pytest.approx(ra["equity"].iloc[-1] - 10_000, rel=1e-6, abs=1e-6), tpl


def test_rule_params_clamp_and_percent_fix():
    from engine.backtest.templates import RuleParams
    p = RuleParams.from_dict({"template": "dip", "dip": 0.9, "pos_pct": 3, "max_positions": 500, "junk": 1})
    assert p.dip == 0.5 and p.pos_pct == 0.25 and p.max_positions == 50
    g = {"template": "dip", "members": [{"spec": {"params": {"dip": 5, "target": 8, "pos_pct": 10}}}]}
    q = cwt.group_params(g)
    assert q.dip == 0.05 and q.target == 0.08 and q.pos_pct == 0.10


def test_spec_params_zero_means_default_and_windows_are_feasible():
    # LLM zeros ("not stated") used to clamp to the lower bound (5% range, 2-day 10% partial)
    p = cwt.spec_params({"params": {"momentum_lookback_days": 20, "momentum_min_pct": 0,
                                    "consolidation_days": 20, "consolidation_max_range_pct": 0,
                                    "partial_after_days": 0, "partial_frac": 0,
                                    "max_position_pct": 0, "max_positions": 0}})
    assert p.mom_min == 0.30 and p.cons_max_range == 0.15
    assert p.partial_days == 4 and p.partial_frac == 0.33 and p.max_pos_pct == 0.20
    assert p.max_positions == 10
    # momentum must be measured over >= 20 sessions before the consolidation
    assert p.mom_days >= p.cons_days + 20
    # fractions given for percent fields
    q = cwt.spec_params({"params": {"momentum_min_pct": 0.05, "consolidation_max_range_pct": 0.1,
                                    "partial_frac": 33}})
    assert q.mom_min == 0.10 and q.cons_max_range == 0.10 and q.partial_frac == 0.33


def test_group_params_zero_size_fields_use_defaults():
    g = {"template": "dip", "members": [{"spec": {"params": {"dip": 0.03, "pos_pct": 0,
                                                            "max_positions": 0, "trend_ma": 0}}}]}
    q = cwt.group_params(g)
    assert q.pos_pct == 0.10 and q.max_positions == 10 and q.trend_ma == 0  # 0 = no trend filter kept
    rs = cwt.group_params({"template": "relative_strength",
                           "members": [{"spec": {"params": {"rebalance_days": 1, "top_n": 10}}}]})
    assert rs.rebalance_days == 5 and rs.hold_buffer == 2.0


def test_rotation_hysteresis_cuts_churn():
    from engine.backtest import templates as T
    spy = _bars(n=500, seed=99)
    bars = {s: _bars(n=500, seed=i) for i, s in enumerate("ABCDEFGHIJ")}
    base = {"template": "relative_strength", "lookback": 20, "top_n": 3, "rebalance_days": 5,
            "trend_ma": 0, "market_filter": False}
    tight = T.run(bars, spy, "2020-03-01", "2021-10-01", T.RuleParams.from_dict({**base, "hold_buffer": 1.0}))
    loose = T.run(bars, spy, "2020-03-01", "2021-10-01", T.RuleParams.from_dict(base))
    assert 0 < loose["trades"] < tight["trades"]
    assert sum(t["pnl"] for t in loose["trips"]) == pytest.approx(loose["equity"].iloc[-1] - 100_000, rel=1e-6)


def test_classification_override_stan_gluzman_intraday():
    ep = {"episode_number": "211", "slug": "211-stan-gluzman-one-bias-one-objective-make-money"}
    if not (cwt.DATA / ep["slug"] / "spec.json").exists():
        pytest.skip("episode artefacts not present")
    s = cwt.load_spec(ep)
    assert s["category"] == "intraday_only" and not s["testable"] and s["_override"]

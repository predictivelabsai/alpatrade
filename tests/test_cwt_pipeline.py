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
    assert m["annualised_pct"] == -1.77 and m["alpha_pct"] == -16.9  # annualised alpha
    assert m["alpha_total_pct"] == -373.6
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
    assert "Backtest period" in html and perf.pct(-1.77) in html


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

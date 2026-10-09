"""Strategy Leaderboard (/leaderboard) + user strategies — DB-free unit tests."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from engine.leaderboard import perf, skill, store

SEED_MD = Path("engine/leaderboard/seeds/mag7-btd-live.md")

RUN = {
    "run_id": "r1",
    "config": {"started": "2026-09-24", "start_equity": 2725.59, "start_spy": 767.29},
    "results": {"daily": {
        "2026-09-24": {"equity": 2725.59, "spy": 767.29},
        "2026-10-07": {"equity": 2800.00, "spy": 770.00},
        "2026-10-08": {"equity": 2809.13, "spy": 774.30},
    }},
}


def test_metrics_from_live_run_snapshot():
    m = perf.metrics_from_run(RUN, today=date(2026, 10, 9))
    assert m["has_data"] is True
    assert m["as_of"] == "2026-10-08"
    assert m["start_date"] == "2026-09-24"
    assert m["days_running"] == 15
    assert m["trading_days"] == 11  # NYSE sessions 24 Sep..8 Oct inclusive
    assert m["return_pct"] == pytest.approx((2809.13 / 2725.59 - 1) * 100)
    assert m["spy_return_pct"] == pytest.approx((774.30 / 767.29 - 1) * 100)
    assert m["alpha_pct"] == pytest.approx(m["return_pct"] - m["spy_return_pct"])
    assert m["annualised_pct"] == pytest.approx(m["return_pct"] * 252 / 11)
    r = m["return_pct"] / 100
    assert m["annualised_compound_pct"] == pytest.approx(((1 + r) ** (252 / 11) - 1) * 100)


def test_metrics_never_invent_numbers():
    for run in (None, {}, {"config": {"started": "2026-09-24"}, "results": {}},
                {"config": {"started": "2026-09-24", "start_equity": 100},  # no start SPY
                 "results": {"daily": {"2026-10-01": {"equity": 101, "spy": 1}}}}):
        m = perf.metrics_from_run(run, today=date(2026, 10, 9))
        assert m["annualised_pct"] is None and m["alpha_pct"] is None
    assert perf.pct(None) == "—"
    assert perf.strategy_metrics({"id": 1, "user_id": "u", "live_strategy_slug": None}) == perf.EMPTY


def test_rank_puts_strategies_without_data_last():
    rows = [{"annualised_pct": None}, {"annualised_pct": 10.0}, {"annualised_pct": 50.0}]
    assert [r["annualised_pct"] for r in sorted(rows, key=perf.rank_key)] == [50.0, 10.0, None]


def test_seed_skill_params_match_live_config_v2():
    md = SEED_MD.read_text(encoding="utf-8")
    fm = skill.front_matter(md)
    assert fm["title"].startswith("Mag-7 Buy-the-Dip") and fm["author"] == "Julian Kaljuvee"
    block = skill.extract_params(md)
    assert block["name"] == "buy_the_dip_mag7_minhold_live" and block["config_version"] == 2
    assert block["params"] == {
        "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"], "dip": 3.0,
        "ref": "high20", "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
        "pos_frac": 0.142857, "max_exposure": 0.0, "entry_window": "15-5",
        "close_window": "15-2", "feed": "iex"}
    ext = block["execution"]["extended_hours_exit"]
    assert ext == {"enabled": True, "order_type": "limit", "limit_ref": "bid", "discount_bps": 15,
                   "reprice_after_min": 5, "max_reprices": 2,
                   "fallback": "market_day_at_regular_open"}
    assert block["live"]["started"] == "2026-09-24"
    assert block["live"]["start_equity_usd"] == 2725.59
    assert "FastSkills" not in md


def test_copy_text_is_the_skill_markdown_and_chat_prompt_uses_params():
    md = SEED_MD.read_text(encoding="utf-8")
    s = {"name": "Mag-7", "description": "d", "skill_md": md}
    assert skill.copy_text(s).strip() == md.strip()
    p = skill.chat_prompt(s)
    assert "AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA" in p and "3.0%" in p and "Paper only" in p
    assert skill.copy_text({"name": "X", "description": "y", "skill_md": ""}).startswith("# X")


def test_public_name_never_shows_email():
    assert store.public_name("kaljuvee@gmail.com") == "kaljuvee"
    assert store.public_name(None, "a.b@c.com") == "a.b"
    assert store.public_name("Julian Kaljuvee") == "Julian Kaljuvee"
    assert store.author_of({"author_name": "Julian Kaljuvee", "user_display_name": "x@y"}) \
        == "Julian Kaljuvee"


def _strategy(**kw):
    s = {"id": 7, "user_id": "owner-1", "name": "Mag-7 <BTD>", "author": "Julian Kaljuvee",
         "author_name": "Julian Kaljuvee", "description": "Buys dips", "is_public": True,
         "skill_md": SEED_MD.read_text(encoding="utf-8"), "live_strategy_slug": "x",
         "cloned_from_id": None}
    s.update(kw)
    return s


def test_leaderboard_html_has_fields_actions_and_mobile_hooks():
    from engine.web import ph_leaderboard as lb
    m = perf.metrics_from_run(RUN, today=date(2026, 10, 9))
    html = lb.leaderboard_html([(_strategy(), m), (_strategy(id=8, live_strategy_slug=None),
                                                   dict(perf.EMPTY))], None)
    assert "Mag-7 &lt;BTD&gt;" in html and "<BTD>" not in html.split("<script")[0]
    assert "Julian Kaljuvee" in html and "Buys dips" in html
    assert perf.pct(m["annualised_pct"]) in html and perf.pct(m["alpha_pct"]) in html
    assert "Since 24 Sep 2026" in html and "15 days running" in html
    assert "Copy for ChatGPT" in html and "Copy for Claude" in html
    assert "action='/strategies/7/clone'" in html and "Clone into AlpaTrade" in html
    assert "id='lb-md-7'" in html and "data-tip=" in html and "lb-sub m" in html
    assert "session close 8 Oct 2026" in html
    assert html.count("—") >= 3  # strategy without live data shows dashes
    # mobile: cards under 760px, 44px tap targets, tap-tooltip toast
    assert "@media(max-width:760px)" in lb.LB_CSS and "min-height:44px" in lb.LB_CSS
    assert "(hover: none)" in lb.LB_JS


def test_owner_sees_toggle_not_clone():
    from engine.web import ph_leaderboard as lb
    m = dict(perf.EMPTY)
    owner = {"user_id": "owner-1", "email": "o@x"}
    page = lb.strategy_html(_strategy(), m, owner)
    assert "Make private" in page and "/strategies/7/clone" not in page
    assert "Backtest in AlpaTrade chat" in page
    other = lb.strategy_html(_strategy(), m, {"user_id": "someone-else"})
    assert "/strategies/7/clone" in other and "Make private" not in other
    mine = lb.my_strategies_html([(_strategy(is_public=False), m)])
    assert "Make public" in mine and "Private" in mine and "/strategies/7/delete" in mine


def test_json_script_cannot_break_out():
    from engine.web import ph_leaderboard as lb
    out = lb._json_script("x", "</script><script>alert(1)</script>")
    assert out.count("</script>") == 1 and out.endswith("</script>")
    assert json.loads(re.search(r">(.*)</script>$", out).group(1)) == \
        "</script><script>alert(1)</script>"


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient
    import app as app_module
    from engine.web import ph_leaderboard as lb
    rows = {7: _strategy(), 9: _strategy(id=9, user_id="owner-2", is_public=False)}
    calls = {}
    monkeypatch.setattr(store, "list_public", lambda: [s for s in rows.values() if s["is_public"]])
    monkeypatch.setattr(store, "get", lambda sid: rows.get(int(sid)))
    monkeypatch.setattr(lb.lperf, "strategy_metrics",
                        lambda s, today=None: perf.metrics_from_run(RUN, today=date(2026, 10, 9)))
    monkeypatch.setattr(store, "clone", lambda sid, uid, author_name=None: calls.setdefault("clone", (sid, uid)) and 42)
    return TestClient(app_module.app), calls


def test_routes_public_leaderboard_and_privacy(client):
    c, calls = client
    r = c.get("/leaderboard")
    assert r.status_code == 200 and "Leaderboard" in r.text and "Julian Kaljuvee" in r.text
    assert 'href="/leaderboard"' in r.text  # main nav link
    j = c.get("/leaderboard.json").json()
    assert j["strategies"][0]["user"] == "Julian Kaljuvee"
    assert j["strategies"][0]["as_of"] == "2026-10-08"
    assert c.get("/strategies/7").status_code == 200
    assert c.get("/strategies/9").status_code == 404  # private, not the owner
    md = c.get("/strategies/7/skill.md")
    assert md.status_code == 200 and "Parameters (machine-readable)" in md.text
    r = c.post("/strategies/7/clone", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/signin")
    assert "clone" not in calls
    assert c.get("/strategies", follow_redirects=False).status_code == 303


def test_home_links_leaderboard():
    from fastcore.xml import to_xml
    from engine.web import ph_landing
    html = to_xml(ph_landing.home_page())
    assert html.count('href="/leaderboard"') >= 3  # desktop nav, mobile nav, hero (+footer)
    import app  # noqa: F401
    from engine.web import ph_layout
    assert ("Leaderboard", "/leaderboard", "leaderboard") in ph_layout.TRADE_PAGES

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
    # 11 sessions < 63 (~90 calendar days): not annualised
    # <90d rule reverted: always annualised, compounded on the TWR, with a short-period hint
    r = m["return_pct"] / 100
    assert m["annualised_pct"] == pytest.approx(((1 + r) ** (252 / 11) - 1) * 100)
    assert m["annualised_short"] is True and "Short period" in perf.annualised_tip(m)
    assert m["annualised_short"] is True


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
    assert fm["title"].startswith("Mag-7 Buy-the-Dip") and fm["author"] == "Predictive Labs Ltd"
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
    assert "n/a (&lt;90d)" not in html and perf.pct(m["annualised_pct"]) in html
    assert perf.pct(m["alpha_pct"]) in html
    assert "Since 24 Sep 2026" in html and "15 days running" in html
    assert "Open in Grok" in html and "Copy to clipboard" in html and "Copy for ChatGPT" not in html
    assert "href='/strategies/7/clone'" in html and "Clone strategy" in html
    assert "id='lb-md-7'" in html and "data-tip=" in html
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


# ── "Shown as" (public user name) ────────────────────────────────────────────
def test_clean_author_trims_strips_html_caps_and_falls_back():
    assert store.MAX_AUTHOR == 60
    assert store.clean_author("  Predictive   Labs Ltd \n") == "Predictive Labs Ltd"
    assert store.clean_author("<b>Acme</b><script>x</script>") == "Acmex"
    assert store.clean_author("&lt;i&gt;Bob&lt;/i&gt;") == "Bob"
    assert store.clean_author("A & B") == "A & B"
    assert len(store.clean_author("x" * 200)) == 60
    assert store.clean_author("   ", "kaljuvee") == "kaljuvee"
    assert store.clean_author("<br>", "kaljuvee") == "kaljuvee"
    assert store.clean_author("", None) is None
    assert store.default_author({"email": "kaljuvee@gmail.com", "display_name": "Julian"}) == "kaljuvee"
    assert store.default_author({"display_name": "Julian"}) == "Julian"


def test_with_author_rewrites_front_matter_only():
    md = SEED_MD.read_text(encoding="utf-8")
    out = skill.with_author(md, "New Name")
    assert skill.front_matter(out)["author"] == "New Name"
    assert out.replace("author: New Name", "author: Predictive Labs Ltd", 1) == md
    assert skill.with_author("# no front matter\nauthor: x\n", "Y") == "# no front matter\nauthor: x\n"
    assert skill.with_author(md, "") == md
    # skill.md / Copy-for text follow the strategy's current "Shown as" name
    assert "author: Shown Elsewhere" in skill.copy_text(
        {"skill_md": md, "author": "Shown Elsewhere"})
    assert skill.front_matter(skill.copy_text({"skill_md": md, "author": "Predictive Labs Ltd"}))[
        "author"] == "Predictive Labs Ltd"


def test_clean_syncs_skill_author_on_save():
    md = SEED_MD.read_text(encoding="utf-8")
    name, _, out_md, author = store._clean("N", "d", md, "  <i>Kalju</i> Labs ")
    assert author == "Kalju Labs" and skill.front_matter(out_md)["author"] == "Kalju Labs"


def test_form_prefills_shown_as_and_escapes():
    from engine.web import ph_leaderboard as lb
    edit = lb.form_html("/strategies/7/edit", _strategy(author="Predictive Labs Ltd",
                                                        author_name="Predictive Labs Ltd"),
                        default_author="kaljuvee")
    assert "name='author_name'" in edit and "value='Predictive Labs Ltd'" in edit
    assert "maxlength='60'" in edit and "disabled" not in edit and "readonly" not in edit
    new = lb.form_html("/strategies/new", default_author="kaljuvee")
    assert "value='kaljuvee'" in new
    xss = lb.form_html("/strategies/new", {"author_name": "'><script>x</script>"},
                       default_author="k")
    assert "<script>x" not in xss and "&#x27;&gt;&lt;script&gt;" in xss
    page = lb.strategy_html(_strategy(author="<b>Evil</b>"), dict(perf.EMPTY), None)
    assert "<b>Evil</b>" not in page and "&lt;b&gt;Evil&lt;/b&gt;" in page


@pytest.fixture
def owner_client(monkeypatch):
    from starlette.testclient import TestClient
    import app as app_module
    from engine.web import ph_leaderboard as lb
    owner = {"user_id": "owner-1", "email": "kaljuvee@gmail.com", "display_name": "Julian"}
    rows = {1: _strategy(id=1, author="Predictive Labs Ltd", author_name="Predictive Labs Ltd"),
            9: _strategy(id=9, user_id="owner-2", author="other", author_name="other")}
    calls = {}

    def fake_update(sid, uid, name, desc, md, author, pub):
        calls["update"] = (sid, uid, author)
        s = rows.get(int(sid))
        if not s or s["user_id"] != uid:
            return False
        s.update(name=name, author_name=author, author=author, skill_md=md, is_public=pub)
        return True

    monkeypatch.setattr(lb, "_user", lambda session: owner)
    monkeypatch.setattr(store, "get", lambda sid: rows.get(int(sid)))
    monkeypatch.setattr(store, "list_public", lambda: [s for s in rows.values() if s["is_public"]])
    monkeypatch.setattr(store, "update", fake_update)
    monkeypatch.setattr(store, "create", lambda uid, n, d, md, author, pub:
                        calls.setdefault("create", author) and 77)
    monkeypatch.setattr(store, "clone", lambda sid, uid, author_name=None:
                        calls.setdefault("clone", author_name) and 78)
    monkeypatch.setattr(lb.lperf, "strategy_metrics", lambda s, today=None: dict(perf.EMPTY))
    return TestClient(app_module.app), calls, rows


def test_owner_edits_shown_as_and_it_shows_everywhere(owner_client):
    c, calls, rows = owner_client
    r = c.get("/strategies/1/edit")
    assert r.status_code == 200 and "value='Predictive Labs Ltd'" in r.text
    assert c.get("/strategies/9/edit").status_code == 404  # not the owner
    form = {"name": rows[1]["name"], "description": "d", "skill_md": rows[1]["skill_md"],
            "is_public": "1", "author_name": "  Kalju <b>Capital</b> "}
    r = c.post("/strategies/1/edit", data=form, follow_redirects=False)
    assert r.status_code == 303 and calls["update"] == (1, "owner-1", "Kalju Capital")
    assert "Kalju Capital" in c.get("/leaderboard").text
    assert c.get("/leaderboard.json").json()["strategies"][0]["user"] == "Kalju Capital"
    assert "by <b>Kalju Capital</b>" in c.get("/strategies/1").text
    assert "author: Kalju Capital" in c.get("/strategies/1/skill.md").text
    # blank -> email local part; non-owner save is refused
    c.post("/strategies/1/edit", data={**form, "author_name": "   "}, follow_redirects=False)
    assert calls["update"][2] == "kaljuvee"
    assert c.post("/strategies/9/edit", data=form, follow_redirects=False).status_code == 404
    assert rows[9]["author"] == "other"


def test_new_and_clone_default_to_email_local_part(owner_client):
    c, calls, _ = owner_client
    r = c.get("/strategies/new")
    assert r.status_code == 200 and "value='kaljuvee'" in r.text
    c.post("/strategies/new", data={"name": "X", "author_name": ""}, follow_redirects=False)
    assert calls["create"] == "kaljuvee"
    from engine.leaderboard import clone_bt
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(clone_bt, "existing_clone", lambda sid, uid: None)
    mp.setattr(clone_bt, "_pool", lambda: _NoDB())
    mp.setattr(clone_bt, "get_config", lambda sid, uid: {"template": "buy_the_dip"})
    try:
        r = c.post("/strategies/9/clone", follow_redirects=False)
    finally:
        mp.undo()
    assert calls["clone"] == "kaljuvee" and "/app?new=1&autorun=" in r.headers["location"]


class _NoDB:
    def get_session(self):
        import contextlib

        class S:
            def execute(self, *a, **k):
                return None
        return contextlib.nullcontext(S())


# ---- View more detail, AI logo buttons, Semi 7 backtest entry -------------------------------

def test_index_series_removes_deposits_and_draws_down():
    from engine.leaderboard.detail import index_series
    from datetime import date
    flows = [{"date": date(2026, 10, 9), "amount": 2000.0}]
    s = index_series(["2026-10-07", "2026-10-08", "2026-10-09"], [10000, 9500, 11500], [100, 99, 100], flows)
    assert s["index"][0] == 100 and abs(s["index"][1] - 95) < 1e-9
    assert abs(s["index"][2] - 95) < 1e-9          # +$2k deposit is not a return
    assert abs(s["drawdown_pct"][2] + 5) < 1e-9 and s["max_drawdown_pct"] == s["drawdown_pct"][1]
    assert s["spy_index"] == [100.0, 99.0, 100.0] and s["daily_return_pct"][2] == 0


def _wf():
    return {"rows": [{"test_period": "2026-01-02→2026-02-02", "oos_pnl": 1000, "oos_ret": 0.10, "oos_trades": 4},
                     {"test_period": "2026-02-02→2026-03-02", "oos_pnl": -550, "oos_ret": -0.05, "oos_trades": 3}],
            "metrics": {"btd_sharpe": 1.2, "trade_win_rate": 55.0}}


def test_semi7_build_metrics_curve_alpha_and_live_switch():
    from engine.leaderboard import semi7
    bm = semi7.build_metrics(_wf(), {"2026-01-02": 100.0, "2026-01-30": 102.0, "2026-03-02": 104.0})
    assert bm["equity_curve"]["equity"] == [10000.0, 11000.0, 10450.0]
    assert bm["equity_curve"]["spy"] == [100.0, 102.0, 104.0]   # nearest prior close on 2026-02-02
    assert abs(bm["total_return_pct"] - 4.5) < 1e-9 and abs(bm["alpha_pct"] - 0.5) < 1e-9
    assert abs(bm["max_drawdown_pct"] + 5) < 1e-9 and bm["trades"] == 7
    assert bm["live_slug"] == "buy_the_dip_semi7_minhold_live"
    assert bm["annualised_pct"] > bm["total_return_pct"]


def test_backtest_entry_switches_to_live_when_live_record_exists(monkeypatch):
    from engine.leaderboard import perf, semi7
    bm = semi7.build_metrics(_wf(), {"2026-01-02": 100.0, "2026-03-02": 104.0})
    row = {"id": 17, "kind": "backtest", "user_id": "u1", "backtest_metrics": bm, "live_strategy_slug": None}
    real = perf.strategy_metrics
    monkeypatch.setattr(perf, "metrics_from_run", lambda *a, **k: {**perf.EMPTY, "has_data": False}, raising=False)
    monkeypatch.setattr(perf, "_live_run", lambda uid, slug: None)
    m = real(dict(row))
    assert m["is_backtest"] and m["annualised_pct"] is not None
    live = {**perf.EMPTY, "has_data": True, "annualised_pct": 12.0}
    calls = {}

    def fake(strategy, today=None, _real=real):
        if strategy.get("kind") == "live":
            calls["slug"] = strategy["live_strategy_slug"]; return live
        return _real(strategy, today)
    monkeypatch.setattr(perf, "strategy_metrics", fake)
    r2 = dict(row)
    assert real(r2) is live and r2["kind"] == "live" and calls["slug"] == semi7.LIVE_SLUG


def test_cards_have_view_more_and_ai_logo_buttons_including_grok():
    from engine.web import ph_leaderboard as lb
    s = {"id": 5, "name": "X", "description": "d", "skill_md": "---\ntitle: X\n---\nbody", "kind": "live",
         "author_name": "A", "user_id": "u"}
    html = lb._actions(s, None) if hasattr(lb, "_actions") else ""
    assert "/strategies/5#details" in html and "View more" in html
    assert "Open in Grok" in html and "Copy to clipboard" in html and "lbCopyClip(5)" in html
    assert "ChatGPT" not in html and "Claude" not in html and html.count("<svg") == 2
    assert "paste into Claude or ChatGPT" in lb.LB_JS and "chatgpt.com" not in lb.LB_JS
    assert "grok.com/?q=" in lb.LB_JS


def test_detail_html_backtest_has_plotly_charts_params_and_skill():
    from engine.leaderboard import semi7
    from engine.leaderboard.detail import backtest_detail
    from engine.web import ph_leaderboard as lb
    md = open("engine/leaderboard/seeds/semi7-btd-backtest.md").read()
    s = {"id": 17, "kind": "backtest", "description": "Semi 7 dip buyer", "skill_md": md, "name": "Semi 7",
         "backtest_metrics": semi7.build_metrics(_wf(), {"2026-01-02": 100.0, "2026-03-02": 104.0})}
    det = backtest_detail(s)
    assert det["series"]["dates"] and det["config"]["params"]["symbols"][0] == "TSM"
    html = lb.detail_html(s, {"is_backtest": True}, det)
    for want in ("id='details'", "lb-eq-17", "lb-dd-17", "plotly", "Parameters", "Strategy prompt",
                 "SKILL.md", "lbCopyRaw(17)"):
        assert want in html, want
    assert "id='lb-dr-17'" not in html       # no daily returns for a fold-level backtest curve
    none = lb.detail_html({**s, "backtest_metrics": {}}, {"is_backtest": True}, {"series": {}})
    assert "No equity curve stored" in none


def test_detail_has_single_compact_copy_not_repeated_skill():
    from engine.leaderboard.detail import backtest_detail
    from engine.web import ph_leaderboard as lb
    md = open("engine/leaderboard/seeds/semi7-btd-backtest.md").read()
    s = {"id": 17, "kind": "backtest", "description": "d", "skill_md": md, "name": "Semi 7", "backtest_metrics": {}}
    html = lb.detail_html(s, {"is_backtest": True}, backtest_detail(s))
    assert "lb-skill-17" not in html and "<pre id=" not in html
    assert html.count("lbCopyRaw(17)") == 1 and "<rect" in html and ">Copy<" in html
    assert "toast('Copied')" in lb.LB_JS


def test_prefill_urls_full_or_short_with_page_link():
    import json, shutil, subprocess
    from engine.web import ph_leaderboard as lb
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    js = lb.LB_JS.split("<script>")[1].split("</script>")[0]
    harness = ("var location={origin:'https://alpatrade.chat'};var window={matchMedia:function(){return{matches:false}}};"
               "var document={getElementById:function(){return null},addEventListener:function(){},"
               "querySelectorAll:function(){return []}};" + js +
               ";var o={};['grok'].forEach(function(p){o[p]=[window.lbPrefill(1,p,'short skill'),"
               "window.lbPrefill(1,p,'x'.repeat(9000))]});console.log(JSON.stringify(o))")
    out = json.loads(subprocess.run([node, "-e", harness], capture_output=True, text=True, check=True).stdout)
    bases = {"grok": "https://grok.com/?q="}
    for p, (short, long_) in out.items():
        assert short["full"] and short["url"] == bases[p] + "short%20skill"
        assert not long_["full"] and long_["url"].startswith(bases[p]) and len(long_["url"]) < 1000
        assert "alpatrade.chat%2Fstrategies%2F1" in long_["url"]

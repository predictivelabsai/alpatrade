"""Clone to Grok Bot: template JSON, slugs, share ids, login flag, routes — DB-free."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.leaderboard import grokbot as gb
from engine.leaderboard import grokbot_clicks as clicks

MD = Path("engine/leaderboard/seeds/mag7-btd-live.md").read_text()
S = {"id": 7, "name": "Mag-7 BTD (live)", "description": "Buy the dip", "skill_md": MD,
     "author": "julian", "is_public": True, "user_id": "u1"}


def test_slug_roundtrip():
    assert gb.slug_for(S) == "mag-7-btd-live-7"
    assert gb.id_from_slug("mag-7-btd-live-7.json") == 7
    assert gb.id_from_slug("nope") is None


def test_template_contents():
    t = gb.template(S)
    assert t["format"] == gb.FORMAT and t["name"] == "AlpaTrade Mag-7 BTD (live)"
    assert t["skills"][0]["content"].strip().startswith("---") or "params" in t["skills"][0]["content"]
    assert t["parameters"] and "params" in t["parameters"]
    ins = t["instructions"]
    for needle in ("secret request", "/v2/account", "CONFIRM LIVE TRADING", "Cash only", "at least", "Predictive Labs Ltd"):
        assert needle in ins
    names = {r["name"]: r for r in t["routines"]}
    assert names["Entry window"]["schedule"] == "45-55/5 15 * * 1-5"
    assert names["Open exit placement"]["schedule"] == "31 9 * * 1-5"
    assert all(r["timezone"] == "America/New_York" for r in t["routines"])
    assert {x["name"] for x in t["secrets"]} >= {"ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"}
    assert t["source"]["template_url"].endswith("/templates/grokbot/mag-7-btd-live-7.json")
    assert t["share_url"] is None
    json.dumps(t)


def test_share_ids(monkeypatch):
    monkeypatch.setenv("GROKBOT_SHARE_IDS", "mag-7-btd-live-7=yTeKCLayahHnMdHFG9GJg,bad=<x>")
    assert gb.share_url(S) == "https://x.ai/bot/yTeKCLayahHnMdHFG9GJg"
    monkeypatch.setenv("GROKBOT_SHARE_IDS", json.dumps({"7": "abcdefgh"}))
    assert gb.share_url(S) == "https://x.ai/bot/abcdefgh"


def test_login_flag_default_off(monkeypatch):
    monkeypatch.delenv("GROKBOT_CLONE_REQUIRES_LOGIN", raising=False)
    assert gb.requires_login() is False
    from engine.web.ph_grokbot import button
    assert "gbOpen(" in button(S, None)
    monkeypatch.setenv("GROKBOT_CLONE_REQUIRES_LOGIN", "1")
    assert "/signin" in button(S, None) and "gbOpen(" in button(S, {"user_id": "u"})


def test_click_actions_whitelist():
    assert clicks.record(7, "evil") is False


def test_routes(monkeypatch):
    from starlette.testclient import TestClient
    from fasthtml.common import fast_app
    from engine.web import ph_grokbot
    from engine.leaderboard import store
    monkeypatch.setattr(store, "get", lambda sid: S if sid == 7 else None)
    monkeypatch.setattr(store, "list_public", lambda: [S])
    seen = []
    monkeypatch.setattr(clicks, "record", lambda sid, a: seen.append((sid, a)) or True)
    monkeypatch.setattr(ph_grokbot, "_user", lambda session: None)
    app, rt = fast_app()
    ph_grokbot.register(app, rt)
    c = TestClient(app)
    r = c.get("/templates/grokbot/mag-7-btd-live-7.json")
    assert r.status_code == 200 and r.json()["name"].startswith("AlpaTrade")
    assert "max-age" in r.headers["cache-control"]
    assert c.get("/templates/grokbot/x-99.json").status_code == 404
    assert c.post("/templates/grokbot/7/click", content=b'{"action":"open"}').json()["ok"] is True
    assert (7, "open") in seen and (7, "json") in seen
    assert c.get("/admin/grokbot-clicks").status_code == 403

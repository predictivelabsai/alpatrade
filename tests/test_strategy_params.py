"""v0.51.0 user-editable strategy params: validation, version flow, live gate, walk-forward,
chat proposal confirmation (engine/leaderboard/params.py, utils/btd_rules.py)."""
import copy
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import btd_rules as R  # noqa: E402
from engine.leaderboard import params as SP  # noqa: E402
from engine.leaderboard import walkforward as WF  # noqa: E402

UID, OTHER, SID = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", 7


# ── validation ──────────────────────────────────────────────────────────────
def test_defaults_validate_and_match_old_behaviour():
    p = R.validate_params({})
    assert p["stop_mode"] == "pct" and p["stop_timing"] == "always" and p["vol_filter"] == "off"
    assert p["regime_filter"] == "" and p["max_exposure_pct"] == 0.0
    assert R.position_exit_pcts(p, [], 100.0, date(2026, 1, 5)) == (p["tp"], p["sl"])


def test_validation_normalises_and_collects_every_error():
    p = R.validate_params({"symbols": "nvda, amd;tsm nvda", "dip": "0.03", "sl": "2%", "regime_filter": "smh,spy",
                           "stop_mode": "ATR", "max_hold": "5"})
    assert p["symbols"] == ["NVDA", "AMD", "TSM"] and p["dip"] == 3.0 and p["sl"] == 2.0
    assert p["regime_filter"] == "SMH,SPY" and p["stop_mode"] == "atr" and p["max_hold"] == 5
    with pytest.raises(R.ParamError) as e:
        R.validate_params({"dip": 80, "pos_frac": 2, "stop_k": 0, "symbols": "", "regime_filter": "IWM",
                           "vol_filter": "vix", "min_hold": 2.5})
    assert set(e.value.errors) == {"dip", "pos_frac", "stop_k", "symbols", "regime_filter", "vol_filter", "min_hold"}
    with pytest.raises(R.ParamError) as e:
        R.validate_params({"min_hold": 5, "max_hold": 3})
    assert "max_hold" in e.value.errors
    with pytest.raises(R.ParamError):
        R.validate_params({"symbols": ["A" * 11]})
    with pytest.raises(R.ParamError):
        R.validate_params({"symbols": [f"S{i}" for i in range(26)]})
    with pytest.raises(R.ParamError):
        R.validate_params({"dip": float("nan")})


def test_rule_helpers():
    bars = [{"t": f"2026-01-{i + 1:02d}", "o": 100, "h": 102, "l": 98, "c": 100} for i in range(25)]
    assert R.atr(bars) == pytest.approx(4.0)
    tp, sl = R.position_exit_pcts({**R.validate_params({"stop_mode": "atr", "stop_k": 1.5, "tp_mult": 2})},
                                  bars, 100.0, date(2026, 2, 1))
    assert sl == pytest.approx(6.0) and tp == pytest.approx(12.0)
    assert R.position_exit_pcts({"stop_mode": "atr", "stop_k": 2, "tp": 8, "sl": 1}, bars[:5], 100, date(2026, 2, 1)) is None
    P = {"vol_filter": "atr", "vol_max": 3.0}
    assert R.vol_symbol_block(P, bars, date(2026, 2, 1))          # ATR 4% > 3%
    assert R.vol_symbol_block({**P, "vol_max": 5.0}, bars, date(2026, 2, 1)) is None
    assert R.vol_market_block({"vol_filter": "spy_atr", "vol_max": 3}, [], date(2026, 2, 1))   # fail closed
    up = [{"t": f"2026-01-{i + 1:02d}", "o": 1, "h": 1, "l": 1, "c": 100 + i} for i in range(25)]
    Ps = {"regime_mode": "sma", "regime_sma": 10}
    assert R.regime_check(Ps, {"SPY": up}, {"SPY": 130.0}, date(2026, 2, 1)) is None
    assert "SMA10" in R.regime_check(Ps, {"SPY": up}, {"SPY": 100.0}, date(2026, 2, 1))
    assert R.exposure_cap({"max_exposure": 5000, "max_exposure_pct": 30}, 10000) == 3000
    assert R.entry_block(1000, 2500, 9999, {"max_exposure_pct": 30}, base_value=10000)
    assert R.entry_block(400, 2500, 9999, {"max_exposure_pct": 30}, base_value=10000) is None
    e, d3, d4 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 8)
    assert R.stop_live(e, d3, {"stop_timing": "always", "min_hold": 3})
    assert not R.stop_live(e, d3, {"stop_timing": "exit_day", "min_hold": 3})
    assert R.stop_live(e, d4, {"stop_timing": "exit_day", "min_hold": 3})


# ── fake repo ───────────────────────────────────────────────────────────────
class FakeRepo:
    def __init__(self, cfg_params=None, live=None, paper=None):
        self.cfg = {"template": "buy_the_dip", "params": cfg_params or {"symbols": ["AAPL", "MSFT"], "dip": 3, "tp": 8,
                                                                         "sl": 1.5, "max_hold": 3, "pos_frac": 0.1},
                    "execution": {}, "mode": "paper"}
        self.vs, self.runs, self.events, self.props, self.writes = [], [], [], {}, []
        self.acts = {}
        if live:
            self.acts["live"] = {"id": 41, "mode": "live", "status": live, "account_ref": "L1", "allocation_usd": 5000,
                                 "cid_prefix": "uabc123", "params_version_id": None}
        if paper:
            self.acts["paper"] = {"id": 40, "mode": "paper", "status": paper, "params_version_id": None}

    def strategy(self, sid):
        return {"id": sid, "user_id": UID, "name": "Semis dip"} if sid == SID else None

    def config(self, sid, uid):
        return copy.deepcopy(self.cfg)

    def write_config_params(self, sid, uid, params):
        self.cfg["params"] = copy.deepcopy(params); self.writes.append(params)

    def versions(self, sid):
        return copy.deepcopy(self.vs)

    def insert_version(self, uid, sid, params, status, parent_id, source, note, diff):
        v = {"id": 100 + len(self.vs), "user_id": uid, "user_strategy_id": sid, "version": len(self.vs) + 1,
             "params": copy.deepcopy(params), "status": status, "parent_id": parent_id, "source": source,
             "note": note, "diff": diff, "created_at": "2026-10-16T18:00:00"}
        self.vs.append(v)
        return copy.deepcopy(v)

    def activations(self, sid, uid):
        return copy.deepcopy(self.acts)

    def set_activation_version(self, aid, vid):
        for a in self.acts.values():
            if a["id"] == aid:
                a["params_version_id"] = vid

    def wf_runs(self, vid):
        return [copy.deepcopy(r) for r in reversed(self.runs) if r["version_id"] == vid]

    def wf_run(self, rid):
        return next((copy.deepcopy(r) for r in self.runs if r["id"] == rid), None)

    def wf_done_by_key(self, key):
        return next((copy.deepcopy(r) for r in reversed(self.runs) if r["cache_key"] == key and r["status"] == "done"), None)

    def wf_insert(self, uid, sid, vid, key, status, result=None, cached=False, progress=""):
        import datetime as dt
        self.runs.append({"id": len(self.runs) + 1, "user_id": uid, "user_strategy_id": sid, "version_id": vid,
                          "cache_key": key, "status": status, "result": result, "cached": cached, "progress": progress,
                          "error": None, "created_at": dt.datetime.now(dt.timezone.utc)})
        return len(self.runs)

    def wf_update(self, rid, **kw):
        self.runs[rid - 1].update(kw)

    def log_event(self, uid, event, meta):
        self.events.append((event, meta))

    def insert_proposal(self, code, uid, sid, base_id, changes, note):
        self.props[code] = {"code": code, "user_id": uid, "user_strategy_id": sid, "base_version_id": base_id,
                            "changes": changes, "note": note, "used_at": None, "age_s": 5}

    def proposal(self, code):
        return copy.deepcopy(self.props.get(code))

    def use_proposal(self, code, vid):
        if self.props[code]["used_at"]:
            return False
        self.props[code]["used_at"] = "now"; return True


@pytest.fixture
def repo(monkeypatch):
    r = FakeRepo(live="active", paper="active")
    monkeypatch.setattr(SP, "repo", r)
    return r


def fake_wf(params, live_params, bars, progress, asof):
    progress("fold 1", {"folds": []})
    return {"asof": asof, "segments": {}, "folds": [], "oos": {"cand": {"total_pct": 12.0, "sharpe": 1.1, "max_dd_pct": -8.0}},
            "params": params}


# ── version flow ────────────────────────────────────────────────────────────
def test_baseline_then_draft_versions_never_touch_activations(repo):
    vs = SP.ensure_baseline(SID, UID)
    assert len(vs) == 1 and vs[0]["status"] == "baseline" and vs[0]["params"]["sl"] == 1.5
    res = SP.create_version(SID, UID, {"stop_mode": "atr", "stop_k": 2.0}, source="ui", note="semis wider stop")
    assert res["ok"] and res["version"]["version"] == 2 and res["version"]["status"] == "draft"
    assert [k for k, _a, _b in res["diff"]] == ["stop_mode", "stop_k"] or {k for k, _a, _b in res["diff"]} == {"stop_mode"}
    assert repo.writes == [] and all(a["params_version_id"] is None for a in repo.acts.values())
    assert repo.events[-1][0] == f"params_edit_{res['version']['id']}"
    again = SP.create_version(SID, UID, {"stop_mode": "atr", "stop_k": 2.0})
    assert again["unchanged"] and len(repo.vs) == 2
    bad = SP.create_version(SID, UID, {"dip": 99})
    assert not bad["ok"] and "dip" in bad["errors"] and len(repo.vs) == 2
    unknown = SP.propose(SID, UID, {"leverage": 3})
    assert not unknown["ok"] and "leverage" in unknown["errors"]


def test_not_owner_or_not_btd(repo):
    with pytest.raises(SP.ParamsError):
        SP.ensure_baseline(SID, OTHER)
    repo.cfg["template"] = "momentum"
    with pytest.raises(SP.ParamsError):
        SP.ensure_baseline(SID, UID)


def test_paper_applies_immediately_but_keeps_live_config(repo):
    SP.ensure_baseline(SID, UID)
    v = SP.create_version(SID, UID, {"regime_filter": "SPY"})["version"]
    res = SP.apply_version(SID, UID, v["id"], "paper")
    assert res["ok"] and repo.acts["paper"]["params_version_id"] == v["id"]
    assert repo.writes == [], "live runs another version: the config row (read by old runners) must not change"
    assert repo.acts["live"]["params_version_id"] is None
    assert repo.events[-1][0] == f"params_apply_{v['id']}_paper"


def test_paper_apply_without_live_updates_config(monkeypatch):
    r = FakeRepo(paper="active")
    monkeypatch.setattr(SP, "repo", r)
    SP.ensure_baseline(SID, UID)
    v = SP.create_version(SID, UID, {"dip": 4})["version"]
    assert SP.apply_version(SID, UID, v["id"], "paper")["ok"]
    assert r.cfg["params"]["dip"] == 4.0


def test_live_apply_needs_walkforward_and_typed_live(repo):
    SP.ensure_baseline(SID, UID)
    v = SP.create_version(SID, UID, {"stop_mode": "atr", "stop_k": 2.0, "tp_mult": 3})["version"]
    res = SP.apply_version(SID, UID, v["id"], "live", "LIVE")
    assert not res["ok"] and any("walk-forward" in e for e in res["errors"])
    SP.start_wf(SID, UID, v["id"], loader=lambda syms, asof: {}, runner=fake_wf, background=False)
    assert SP.wf_done(v["id"])
    res = SP.apply_version(SID, UID, v["id"], "live", "yes")
    assert not res["ok"] and any("Type LIVE" in e for e in res["errors"])
    assert repo.acts["live"]["params_version_id"] is None and repo.writes == []
    res = SP.apply_version(SID, UID, v["id"], "live", "LIVE", plan_check=lambda syms: ["universe overlaps"])
    assert not res["ok"] and repo.writes == []
    res = SP.apply_version(SID, UID, v["id"], "live", " live ", plan_check=lambda syms: [])
    assert res["ok"] and repo.acts["live"]["params_version_id"] == v["id"]
    assert repo.cfg["params"]["stop_mode"] == "atr"
    ev, meta = repo.events[-1]
    assert ev == f"params_apply_{v['id']}_live" and meta["activation_id"] == 41
    assert SP.live_version(SID, UID)["id"] == v["id"]


def test_live_apply_without_live_activation(monkeypatch):
    r = FakeRepo()
    monkeypatch.setattr(SP, "repo", r)
    SP.ensure_baseline(SID, UID)
    v = SP.create_version(SID, UID, {"dip": 4})["version"]
    SP.start_wf(SID, UID, v["id"], loader=lambda s, a: {}, runner=fake_wf, background=False)
    res = SP.apply_version(SID, UID, v["id"], "live", "LIVE")
    assert not res["ok"] and any("no live activation" in e for e in res["errors"])


def test_walkforward_is_cached(repo):
    SP.ensure_baseline(SID, UID)
    v = SP.create_version(SID, UID, {"dip": 4})["version"]
    calls = []

    def runner(*a):
        calls.append(1); return fake_wf(*a)
    r1 = SP.start_wf(SID, UID, v["id"], loader=lambda s, a: {}, runner=runner, background=False)
    r2 = SP.start_wf(SID, UID, v["id"], loader=lambda s, a: {}, runner=runner, background=False)
    assert r1["run_id"] == r2["run_id"] and r2["cached"] and len(calls) == 1
    v3 = SP.create_version(SID, UID, {"dip": 3})["version"]      # same params as baseline -> new version
    SP.start_wf(SID, UID, v3["id"], loader=lambda s, a: {}, runner=runner, background=False)
    assert len(calls) == 2
    assert SP.wf_status(r1["run_id"], OTHER) is None


# ── chat proposal -> explicit confirmation ──────────────────────────────────
def test_chat_proposal_requires_user_confirmation(repo):
    p = SP.create_proposal(SID, UID, {"stop_mode": "atr", "stop_k": 2.0}, "widen semis stop to 2x ATR")
    assert p["ok"] and len(p["code"]) == 6 and "stop_mode" in p["diff_md"]
    assert len(repo.vs) == 1, "a proposal saves nothing"
    assert not SP.confirm_proposal(p["code"], OTHER)["ok"]
    c = SP.confirm_proposal(p["code"], UID)
    assert c["ok"] and c["version"]["version"] == 2 and c["version"]["source"] == "chat"
    assert not SP.confirm_proposal(p["code"], UID)["ok"]          # single use
    assert repo.writes == [] and repo.acts["live"]["params_version_id"] is None
    bad = SP.create_proposal(SID, UID, {"stop_k": 50})
    assert not bad["ok"] and "stop_k" in bad["errors"]
    p2 = SP.create_proposal(SID, UID, {"regime_filter": "SPY"})
    repo.props[p2["code"]]["age_s"] = 7200
    assert "expired" in SP.confirm_proposal(p2["code"], UID)["message"]


def test_chat_confirm_command_reply(repo, monkeypatch):
    from engine.web import ph_chat
    p = SP.create_proposal(SID, UID, {"regime_filter": "SPY"})
    text, fups = ph_chat._confirm_params_reply(p["code"], UID)
    assert "Saved **v2**" in text and "Nothing running has changed" in text and fups
    text2, _ = ph_chat._confirm_params_reply(p["code"], UID)
    assert "already saved" in text2
    assert "Sign in" in ph_chat._confirm_params_reply(p["code"], "")[0]


def test_chat_tools_registered():
    from engine.ai.deepagent_tools import STRATEGY_TOOLS
    names = {t.name for t in STRATEGY_TOOLS}
    assert {"get_strategy_params", "propose_strategy_params", "run_strategy_walkforward", "list_my_strategies"} <= names
    from engine.ai.deepagent_tools import propose_strategy_params
    assert "/confirm-params" in propose_strategy_params.description


# ── walk-forward engine ─────────────────────────────────────────────────────
def _synth(start, n, seed, syms):
    rnd = random.Random(seed); out = {}
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5: days.append(d.isoformat())
        d += timedelta(days=1)
    for i, s in enumerate(syms):
        px, rows = 100.0 + 10 * i, []
        for t in days:
            o = px * math.exp(rnd.gauss(0.0003, 0.01)); c = o * math.exp(rnd.gauss(0, 0.015))
            rows.append({"t": t, "o": o, "h": max(o, c) * 1.005, "l": min(o, c) * 0.995, "c": c}); px = c
        out[s] = rows
    return out


def test_run_wf_folds_segments_and_curve():
    bars = _synth(date(2014, 1, 1), 252 * 4, 3, ["AAA", "BBB", "SPY", "SMH", "QQQ"])
    P = R.validate_params({"symbols": ["AAA", "BBB"], "pos_frac": 0.3})
    L = R.validate_params({"symbols": ["AAA", "BBB"], "pos_frac": 0.3, "regime_filter": "SPY"})
    msgs = []
    res = WF.run_wf(P, L, bars, lambda m, part: msgs.append(m), asof="2017-10-10")
    assert [f["test"][0][:4] for f in res["folds"]] == ["2016", "2017"]
    assert res["folds"][0]["fit"] == ["2013-01-01", "2015-12-31"]
    assert set(res["segments"]) == {"2016-2022", "2023+"}
    f0 = res["folds"][0]
    assert f0["cand"]["total_pct"] is not None and f0["spy"]["total_pct"] is not None
    assert f0["cand"] != f0["live"] and not res["same_as_live"]
    assert res["oos"]["cand"]["sharpe"] is not None and len(res["curve"]["dates"]) == len(res["curve"]["cand"])
    assert msgs and "Fold 1/2" in msgs[0]
    md = SP.wf_summary_md(res, 3)
    assert "Walk-forward of v3" in md and "2016-2022" in md


def test_cache_key_changes_with_params_and_date():
    a = R.validate_params({})
    assert WF.cache_key(a, a, "2026-10-15") == WF.cache_key(dict(a), dict(a), "2026-10-15")
    assert WF.cache_key(a, a, "2026-10-15") != WF.cache_key({**a, "dip": 4.0}, a, "2026-10-15")
    assert WF.cache_key(a, a, "2026-10-15") != WF.cache_key(a, a, "2026-10-16")


def test_load_bars_uses_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WF_CACHE_DIR", str(tmp_path))
    calls = []

    def fetch(syms, start, end):
        calls.append(list(syms)); return {s: [{"t": "2026-01-02", "o": 1, "h": 1, "l": 1, "c": 1}] for s in syms}
    WF.load_bars(["NVDA"], "2026-10-15", fetch=fetch)
    WF.load_bars(["NVDA"], "2026-10-15", fetch=fetch)
    assert len(calls) == 1 and set(calls[0]) == {"NVDA", "SPY", "SMH", "QQQ"}


# ── UI ──────────────────────────────────────────────────────────────────────
def test_form_html_groups_defaults_help_and_mobile_css():
    from engine.web import ph_strategy_params as UI
    h = UI.form_html(SID, R.validate_params({}), {"dip": "between 0.5 and 25"})
    for g in R.PARAM_GROUPS:
        assert f"<legend>{g.replace('&', '&amp;')}</legend>" in h
    for k in R.PARAM_SPEC:
        assert f"name='{k}'" in h
    assert "between 0.5 and 25" in h and "Save as new version" in h and "Default:" in h
    assert "data-dep='stop_mode'" in h
    assert "@media (max-width:640px)" in UI.CSS and "font-size:16px" in UI.CSS


def test_live_confirm_page_shows_diff_and_typed_live(repo):
    from engine.web import ph_strategy_params as UI
    SP.ensure_baseline(SID, UID)
    v = SP.create_version(SID, UID, {"stop_mode": "atr"})["version"]
    ov = SP.overview(SID, UID)
    h = UI.live_confirm_html(SID, ov, v, None)
    assert "Real money" in h and "Type <b>LIVE</b>" in h and "Stop mode" in h and "No completed walk-forward" in h

"""PostgreSQL integration for engine/leaderboard/params.SqlRepo + sql/56 (v0.51.0).
Runs when PARAMS_TEST_DATABASE_URL points at a throwaway database (CI postgres service)."""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL = os.getenv("PARAMS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="PARAMS_TEST_DATABASE_URL not set")
UID = "33333333-3333-3333-3333-333333333333"

BOOT = """
DROP SCHEMA IF EXISTS alpatrade CASCADE; CREATE SCHEMA alpatrade;
CREATE TABLE alpatrade.users (user_id UUID PRIMARY KEY, email TEXT);
"""


@pytest.fixture
def sp(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    eng = create_engine(URL)
    with eng.begin() as c:
        c.execute(text(BOOT))
        for f in ("26_activation_events.sql", "42_user_strategies.sql", "47_user_strategy_configs.sql",
                  "49_user_strategy_activations.sql", "56_strategy_param_versions.sql"):
            sql = (ROOT / "sql" / f).read_text()
            if f.startswith("26_"):
                sql = sql.split("-- Backfill")[0] if "-- Backfill" in sql else sql.split("INSERT INTO")[0]
            c.execute(text(sql))
        c.execute(text("INSERT INTO alpatrade.users VALUES (CAST(:u AS UUID), 'p@example.invalid')"), {"u": UID})
        sid = c.execute(text("INSERT INTO alpatrade.user_strategies (user_id, name) VALUES (CAST(:u AS UUID), 'Semis') "
                             "RETURNING id"), {"u": UID}).scalar()
        c.execute(text("INSERT INTO alpatrade.user_strategy_configs (user_id, user_strategy_id, template, params) "
                       "VALUES (CAST(:u AS UUID), :i, 'buy_the_dip', CAST(:p AS JSONB))"),
                  {"u": UID, "i": sid, "p": '{"symbols": ["NVDA", "AMD"], "dip": 3, "tp": 8, "sl": 1.5, "max_hold": 3, "pos_frac": 0.1}'})
        c.execute(text("INSERT INTO alpatrade.user_strategy_activations (user_id, user_strategy_id, mode, account_ref, "
                       "cid_prefix, allocation_usd, status) VALUES (CAST(:u AS UUID), :i, 'live', 'L1', 'uaaaaaa', 1000, 'active'), "
                       "(CAST(:u AS UUID), :i, 'paper', 'P1', 'ubbbbbb', 10000, 'active')"), {"u": UID, "i": sid})
    Session = sessionmaker(bind=eng)

    class Pool:
        @contextmanager
        def get_session(self):
            s = Session()
            try:
                yield s; s.commit()
            except Exception:
                s.rollback(); raise
            finally:
                s.close()
    from engine.leaderboard import params as SP
    monkeypatch.setattr(SP, "_pool", lambda: Pool())
    monkeypatch.setattr(SP, "_schema_ok", True)
    repo = SP.SqlRepo()
    repo.strategy = lambda i: {"id": i, "user_id": UID, "name": "Semis"} if i == sid else None

    def config(i, u):
        with eng.connect() as c:
            r = c.execute(text("SELECT template, params, execution, mode FROM alpatrade.user_strategy_configs "
                               "WHERE user_strategy_id = :i"), {"i": i}).mappings().first()
        return dict(r) if r else None
    repo.config = config
    monkeypatch.setattr(SP, "repo", repo)
    SP._test = (eng, sid)
    return SP


def test_sql_version_flow_and_live_gate(sp):
    from sqlalchemy import text
    eng, sid = sp._test
    vs = sp.ensure_baseline(sid, UID)
    assert vs[0]["version"] == 1 and vs[0]["status"] == "baseline"
    v = sp.create_version(sid, UID, {"stop_mode": "atr", "stop_k": 2.5}, source="ui")["version"]
    assert v["version"] == 2 and v["params"]["stop_k"] == 2.5
    assert sp.apply_version(sid, UID, v["id"], "paper")["ok"]
    with eng.connect() as c:
        acts = dict(c.execute(text("SELECT mode, params_version_id FROM alpatrade.user_strategy_activations")).all())
        cfg = c.execute(text("SELECT params FROM alpatrade.user_strategy_configs")).scalar()
    assert acts == {"paper": v["id"], "live": None} and cfg.get("stop_mode") is None
    assert not sp.apply_version(sid, UID, v["id"], "live", "LIVE")["ok"]       # no walk-forward yet
    fake = lambda p, l, b, prog, asof: (prog("x", {"folds": []}), {"oos": {}, "folds": [], "segments": {}})[1]  # noqa: E731
    r = sp.start_wf(sid, UID, v["id"], loader=lambda s, a: {}, runner=fake, background=False)
    assert sp.wf_status(r["run_id"], UID)["status"] == "done"
    assert sp.start_wf(sid, UID, v["id"], loader=lambda s, a: {}, runner=fake, background=False)["cached"]
    assert sp.apply_version(sid, UID, v["id"], "live", "LIVE", plan_check=lambda s: [])["ok"]
    with eng.connect() as c:
        live_v = c.execute(text("SELECT params_version_id FROM alpatrade.user_strategy_activations WHERE mode='live'")).scalar()
        cfg = c.execute(text("SELECT params FROM alpatrade.user_strategy_configs")).scalar()
        evs = [e for (e,) in c.execute(text("SELECT event FROM alpatrade.activation_events ORDER BY id")).all()]
    assert live_v == v["id"] and cfg["stop_mode"] == "atr"
    assert f"params_apply_{v['id']}_live" in evs and f"params_edit_{v['id']}" in evs
    p = sp.create_proposal(sid, UID, {"regime_filter": "SPY"})
    assert sp.confirm_proposal(p["code"], UID)["version"]["version"] == 3
    assert not sp.confirm_proposal(p["code"], UID)["ok"]
    rows = sp.admin_versions()
    assert len(rows) == 3 and rows[-1]["version"] == 1 and "live" in (next(r for r in rows if r["version"] == 2)["applied_to"])


def test_runner_reads_applied_version(sp):
    from sqlalchemy import text
    from utils.user_live_runner import load_activation
    eng, sid = sp._test
    sp.ensure_baseline(sid, UID)
    v = sp.create_version(sid, UID, {"dip": 5})["version"]
    sp.apply_version(sid, UID, v["id"], "paper")
    with eng.connect() as c:
        pid = c.execute(text("SELECT id FROM alpatrade.user_strategy_activations WHERE mode='paper'")).scalar()
        lid = c.execute(text("SELECT id FROM alpatrade.user_strategy_activations WHERE mode='live'")).scalar()
    assert load_activation(eng, pid).params["dip"] == 5.0
    assert load_activation(eng, lid).params["dip"] == 3

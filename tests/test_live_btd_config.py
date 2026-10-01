"""DB-backed strategy config for the live BTD runner (utils/live_btd_config.py, sql/40).

Pure tests always run. The PostgreSQL test applies sql/40 twice to an isolated, freshly
created database when LIVE_BTD_TEST_DATABASE_URL (or PREMARKET_TEST_DATABASE_URL) names a
loopback server (CI provides one); the database is dropped afterwards.
"""
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.live_btd_config import (  # noqa: E402
    DEFAULT_EXECUTION, DEFAULT_PARAMS, DEFAULT_STRATEGY, ConfigError, coerce_params, exit_order,
    ext_exit_action, ext_limit_price, merge_execution, resolve)
from utils.live_btd_store import STRATEGY_SLUG  # noqa: E402

SQL = ROOT / "sql" / "40_strategy_configs.sql"
HP_PARAMS = {**DEFAULT_PARAMS, "pos_frac": 0.142857}   # HP ExecStart: --live --pos-frac 0.142857
EXEC = merge_execution(None)


def row(params=None, execution=None, *, rid=1, name=DEFAULT_STRATEGY, version=3, active=True):
    return (rid, name, params if params is not None else dict(HP_PARAMS),
            execution if execution is not None else {}, version, active)


def loader(r):
    return lambda key: r


def boom(_key):
    raise OSError("could not connect to server: Connection refused")


# ------------------------------------------------------------------ resolve
def test_db_row_wins_over_defaults():
    c = resolve(DEFAULT_STRATEGY, {}, row_loader=loader(row()))
    assert c.db_ok and c.params == HP_PARAMS
    assert set(c.sources.values()) == {"db"}
    assert c.source == f"db:alpatrade.strategy_configs#1 {DEFAULT_STRATEGY} v3"
    assert c.config_id == 1 and c.version == 3


def test_partial_row_fills_from_defaults():
    c = resolve("x", {}, row_loader=loader(row({"pos_frac": 0.2})))
    assert c.params["pos_frac"] == 0.2 and c.sources["pos_frac"] == "db"
    assert c.params["tp"] == 8.0 and c.sources["tp"] == "default"


def test_cli_overrides_db_and_is_reported():
    c = resolve("x", {"pos_frac": 0.05, "symbols": "aapl, nvda", "tp": None},
                row_loader=loader(row()))
    assert c.db_ok
    assert c.params["pos_frac"] == 0.05 and c.sources["pos_frac"] == "cli"
    assert c.params["symbols"] == ["AAPL", "NVDA"] and c.sources["symbols"] == "cli"
    assert c.params["tp"] == 8.0 and c.sources["tp"] == "db"   # None = flag not given
    assert c.source.endswith("+ cli(pos_frac,symbols)")


@pytest.mark.parametrize("ld", [boom, loader(None), loader(row(active=False)),
                                loader(row({"ref": "vwap"})), loader(row({"pos_frac": 5}))])
def test_unavailable_or_invalid_row_falls_back_to_defaults_not_ok(ld):
    c = resolve("x", {}, row_loader=ld)
    assert not c.db_ok and c.error
    assert c.params == DEFAULT_PARAMS
    assert c.execution == DEFAULT_EXECUTION and c.execution["extended_hours_exit"]["enabled"] is False
    assert c.source.startswith("defaults (DB config unavailable")


def test_no_database_url_is_not_ok():
    c = resolve("x", {"dip": 4}, database_url=None)
    assert not c.db_ok and "DATABASE_URL" in c.error and c.params["dip"] == 4.0


def test_numeric_id_and_json_strings():
    seen = []
    c = resolve("7", {}, row_loader=lambda k: seen.append(k) or
                (7, "n", '{"dip": 2.5}', '{"extended_hours_exit": {"discount_bps": 25}}', 1, True))
    assert seen == ["7"] and c.db_ok and c.params["dip"] == 2.5
    assert c.execution["extended_hours_exit"]["discount_bps"] == 25.0
    assert c.execution["extended_hours_exit"]["max_reprices"] == 2  # merged default


def test_snapshot_has_source_and_execution():
    s = resolve("x", {}, row_loader=loader(row())).snapshot()
    assert s["strategy_config"]["db_ok"] and s["strategy_config"]["version"] == 3
    assert s["execution"]["regular_hours_exit"]["order_type"] == "market"


def test_coerce_rejects_bad_values():
    for bad in ({"entry_window": "5-15"}, {"symbols": ""}, {"dip": -1}, {"tp": "x"}):
        with pytest.raises(ConfigError):
            coerce_params(bad)
    with pytest.raises(ConfigError):
        merge_execution({"extended_hours_exit": {"order_type": "market"}})


def test_default_strategy_is_runner_slug():
    assert DEFAULT_STRATEGY == STRATEGY_SLUG


# ------------------------------------------------------------------ exit orders
def test_ext_limit_price_discount_and_tick():
    assert ext_limit_price(200.00, 15) == 199.70          # 200 * (1 - 0.0015)
    assert ext_limit_price(100.37, 15) == 100.21          # 100.21944 -> rounded down
    assert ext_limit_price(0.5, 15) == 0.4992
    with pytest.raises(ValueError):
        ext_limit_price(0, 15)


def test_exit_order_regular_is_market_day():
    b = exit_order("AAPL", "1.5", "btdx-AAPL-20261001", "regular", EXEC)
    assert b == {"symbol": "AAPL", "qty": "1.5", "side": "sell", "type": "market",
                 "time_in_force": "day", "client_order_id": "btdx-AAPL-20261001"}


def test_exit_order_extended_is_discounted_limit():
    b = exit_order("NVDA", "2", "c1", "extended", EXEC, bid=180.0)
    assert b["type"] == "limit" and b["extended_hours"] is True and b["time_in_force"] == "day"
    assert b["limit_price"] == "179.73"


def test_ext_exit_action_reprice_then_wait_then_fallback():
    t0 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    kw = dict(submitted_at=t0, execution=EXEC, market_open=False)
    assert ext_exit_action(now=t0 + timedelta(minutes=4), reprices=0, **kw) == "wait"
    assert ext_exit_action(now=t0 + timedelta(minutes=5), reprices=0, **kw) == "reprice"
    assert ext_exit_action(now=t0 + timedelta(minutes=5), reprices=1, **kw) == "reprice"
    assert ext_exit_action(now=t0 + timedelta(minutes=60), reprices=2, **kw) == "wait"   # max 2
    kw["market_open"] = True
    assert ext_exit_action(now=t0 + timedelta(minutes=1), reprices=0, **kw) == "fallback"


# ------------------------------------------------------------------ migration
def _seed_json():
    import json
    text = SQL.read_text()
    blobs = [b for b in re.findall(r"'(\{.*?\})'::jsonb", text, re.S) if b != "{}"]
    return json.loads(blobs[0]), json.loads(blobs[1])


def test_seed_matches_hp_params_and_execution_defaults():
    params, execution = _seed_json()
    assert coerce_params(params) == HP_PARAMS
    assert merge_execution(execution) == DEFAULT_EXECUTION
    e = execution["extended_hours_exit"]
    assert (e["discount_bps"], e["reprice_after_min"], e["max_reprices"]) == (15, 5, 2)
    assert e["fallback"] == "market_day_at_regular_open" and e["enabled"] is False


def test_migration_is_idempotent_sql():
    t = SQL.read_text()
    assert "CREATE TABLE IF NOT EXISTS alpatrade.strategy_configs" in t
    assert "ON CONFLICT (name) DO NOTHING" in t


def test_runner_param_flags_default_to_none():
    src = (ROOT / "scripts" / "live_btd_minhold.py").read_text()
    for flag in ("symbols", "dip", "tp", "sl", "min-hold", "max-hold", "pos-frac", "max-exposure",
                 "ref", "feed", "entry-window", "close-window"):
        m = re.search(rf'add_argument\("--{flag}"[^\n]*', src)
        assert m and "default=None" in m.group(0), flag
    assert "ALLOW_ENTRIES = False" in src.split("if not CFG.db_ok:")[1].split("def lease_ok")[0]


@pytest.fixture(scope="module")
def pg_url():
    value = os.getenv("LIVE_BTD_TEST_DATABASE_URL") or os.getenv("PREMARKET_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set LIVE_BTD_TEST_DATABASE_URL for isolated PostgreSQL tests.")
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Only a loopback database server is accepted.")
    name = "live_btd_config_" + uuid.uuid4().hex[:12]
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()


def test_postgres_migration_seed_and_resolve(pg_url):
    from sqlalchemy import create_engine, text
    eng = create_engine(pg_url)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS alpatrade")
        c.execute(text(SQL.read_text()))
    with eng.begin() as c:   # edit, then re-run: the seed must not clobber the edit
        c.execute(text("UPDATE alpatrade.strategy_configs SET params = params || '{\"dip\": 3.5}', "
                       "version = version + 1 WHERE name = :n"), {"n": DEFAULT_STRATEGY})
        c.execute(text(SQL.read_text()))
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM alpatrade.strategy_configs")).scalar() == 1
    cfg = resolve(DEFAULT_STRATEGY, {}, database_url=pg_url)
    assert cfg.db_ok and cfg.version == 2
    assert cfg.params == {**HP_PARAMS, "dip": 3.5}
    by_id = resolve(str(cfg.config_id), {}, database_url=pg_url)
    assert by_id.db_ok and by_id.params == cfg.params
    assert not resolve("nope", {}, database_url=pg_url).db_ok
    eng.dispose()

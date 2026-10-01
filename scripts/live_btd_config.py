#!/usr/bin/env python3
"""Show / edit / force-reload the live strategy config (alpatrade.strategy_configs).

  python scripts/live_btd_config.py show  [--strategy NAME|ID]
  python scripts/live_btd_config.py set   pos_frac=0.142857 tp=8   [--execution extended_hours_exit.enabled=true]
  python scripts/live_btd_config.py bump  # version + 1 -> every scheduler reloads within 15 min / next event

Every UPDATE bumps `version` via the sql/41 trigger. Values are validated with the runner's
own rules (utils/live_btd_config.coerce_params) before writing. DATABASE_URL from env or .env.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import text  # noqa: E402
from utils.live_btd_config import DEFAULT_STRATEGY, coerce_params, make_engine, merge_execution  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _val(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("show", "set", "bump"))
    ap.add_argument("pairs", nargs="*", help="param=value (set)")
    ap.add_argument("--execution", action="append", default=[], help="section.key=value (set)")
    ap.add_argument("--strategy", default=os.getenv("BTD_STRATEGY") or DEFAULT_STRATEGY)
    ap.add_argument("--by", default=os.getenv("USER") or "cli")
    a = ap.parse_args(argv)
    url = os.getenv("DATABASE_URL") or dotenv_values(os.path.join(REPO, ".env")).get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not set")
    where = "id = :k" if a.strategy.isdigit() else "name = :k"
    k = int(a.strategy) if a.strategy.isdigit() else a.strategy
    eng = make_engine(url)
    with eng.begin() as c:
        row = c.execute(text(f"SELECT id, name, params, execution, version, is_active, updated_at, updated_by "
                             f"FROM alpatrade.strategy_configs WHERE {where} FOR UPDATE"), {"k": k}).mappings().first()
        if not row:
            sys.exit(f"no strategy config {a.strategy!r}")
        if a.cmd == "set":
            params = dict(row["params"]); execution = json.loads(json.dumps(row["execution"]))
            for pr in a.pairs:
                key, _, v = pr.partition("="); params[key] = _val(v)
            for pr in a.execution:
                path, _, v = pr.partition("="); sect, _, key = path.partition(".")
                execution.setdefault(sect, {})[key] = _val(v)
            unknown = set(params) - set(coerce_params(params)) - {"symbols"}
            if unknown:
                sys.exit(f"unknown params {sorted(unknown)}")
            merge_execution(execution)
            c.execute(text(f"UPDATE alpatrade.strategy_configs SET params = CAST(:p AS JSONB), "
                           f"execution = CAST(:x AS JSONB), updated_by = :by WHERE {where}"),
                      {"p": json.dumps(params), "x": json.dumps(execution), "by": a.by, "k": k})
        elif a.cmd == "bump":
            c.execute(text(f"UPDATE alpatrade.strategy_configs SET version = version + 1, updated_by = :by "
                           f"WHERE {where}"), {"by": a.by, "k": k})
        row = c.execute(text(f"SELECT id, name, params, execution, version, is_active, updated_at, updated_by "
                             f"FROM alpatrade.strategy_configs WHERE {where}"), {"k": k}).mappings().first()
    print(json.dumps(dict(row), indent=1, default=str))
    if a.cmd != "show":
        print(f"-> v{row['version']}: the schedulers reload within 15 minutes or at the next open/entry/close "
              f"event (immediately: kill -HUP the scheduler process on a machine)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

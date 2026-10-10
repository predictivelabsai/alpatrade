#!/usr/bin/env python3
"""Audit a backtest before reporting or publishing its numbers (utils/backtest_audit.py).

    python scripts/audit_backtest.py --strategy-id 17            # leaderboard entry
    python scripts/audit_backtest.py --run-id <uuid>              # alpatrade.runs backtest
    python scripts/audit_backtest.py --btd-live buy_the_dip_mag7_minhold_live \
        --start 2025-10-01 --end 2026-10-09 --slippage-bps 5      # fresh BTD backtest with the
                                                                  # live strategy_configs params
Options: --json (machine-readable), --save (store the result in the leaderboard row's
backtest_metrics.audit; --strategy-id only), --label research|live.
Exit code: 0 pass, 1 warn, 2 fail, 3 error. Agents: run this and quote its status before
reporting any backtest figure (skills/backtest-audit/SKILL.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from utils import backtest_audit as ba  # noqa: E402

EXIT = {ba.PASS: 0, ba.WARN: 1, ba.FAIL: 2}


def _session():
    from engine.db.pool import DatabasePool
    return DatabasePool().get_session()


def live_params(slug: str) -> dict | None:
    from sqlalchemy import text
    with _session() as s:
        p = s.execute(text("SELECT params FROM alpatrade.strategy_configs WHERE name = :n AND is_active "
                           "ORDER BY version DESC LIMIT 1"), {"n": slug}).scalar()
    return json.loads(p) if isinstance(p, str) else p


def by_strategy(sid: int, save: bool):
    from sqlalchemy import text
    with _session() as s:
        r = s.execute(text("SELECT id, name, kind, backtest_metrics, live_strategy_slug FROM "
                           "alpatrade.user_strategies WHERE id = :i"), {"i": sid}).mappings().first()
    if not r:
        sys.exit(f"strategy {sid} not found")
    bm = r["backtest_metrics"] or {}
    bm = json.loads(bm) if isinstance(bm, str) else bm
    if r["kind"] != "backtest" or not bm:
        raise SystemExit(f"strategy {sid} ({r['name']}) has no stored backtest (kind={r['kind']}); its "
                         "figures are a live track record. Audit a backtest with --run-id or --btd-live.")
    lp = None
    slug = (bm.get("audit_input") or {}).get("label") == "live" and bm.get("live_slug")
    if slug:
        lp = live_params(slug)
    rep = ba.audit(ba.from_leaderboard_metrics(bm, live_params=lp))
    if save:
        from sqlalchemy import text as t2
        with _session() as s:
            s.execute(t2("UPDATE alpatrade.user_strategies SET backtest_metrics = jsonb_set("
                         "backtest_metrics, '{audit}', CAST(:a AS JSONB)) WHERE id = :i"),
                      {"a": json.dumps(rep.to_dict()), "i": sid})
    return r["name"], rep


def by_run(run_id: str, label: str | None):
    from sqlalchemy import text
    with _session() as s:
        run = s.execute(text("SELECT config, results, strategy FROM alpatrade.runs WHERE run_id = :r"),
                        {"r": run_id}).mappings().first()
        if not run:
            sys.exit(f"run {run_id} not found")
        trades = [dict(t) for t in s.execute(text(
            "SELECT symbol AS ticker, shares, entry_time, exit_time, entry_price, exit_price, target_price, "
            "stop_price, hit_target, hit_stop, pnl, capital_after, total_fees FROM alpatrade.trades "
            "WHERE run_id = :r AND trade_type = 'backtest' ORDER BY exit_time"), {"r": run_id}).mappings()]
    cfg = run["config"] if isinstance(run["config"], dict) else json.loads(run["config"] or "{}")
    res = run["results"] if isinstance(run["results"], dict) else json.loads(run["results"] or "{}")
    best = res.get("best_config") or {}
    m = best.get("metrics") or best
    cap = float(cfg.get("initial_capital") or 10_000)
    a = ba.AuditInput(
        trades=trades, initial_capital=cap,
        final_equity=float(trades[-1]["capital_after"]) if trades and trades[-1].get("capital_after") is not None else None,
        reported_return_pct=m.get("total_return"), slippage_bps=cfg.get("slippage_bps"),
        label=label or cfg.get("label"), params=best.get("params") or cfg.get("params"),
        fill_rule=cfg.get("fill_rule"), universe=cfg.get("symbols"), period_start=cfg.get("start_date"),
        annualised_pct=m.get("annualized_return"), sharpe=m.get("sharpe_ratio"),
        max_drawdown_pct=m.get("max_drawdown"), n_trades=len(trades))
    return f"run {run_id} ({run['strategy']})", ba.audit(a)


def by_btd_live(slug: str, start: str, end: str, slippage: float, label: str | None):
    from utils.buy_the_dip import backtest_buy_the_dip
    lp = live_params(slug)
    if not lp:
        sys.exit(f"no active strategy_configs row {slug}")
    params = {"dip_threshold": lp["dip"] / 100, "take_profit": lp["tp"] / 100, "stop_loss": lp["sl"] / 100,
              "hold_days": lp["max_hold"], "min_hold_days": lp.get("min_hold", 0)}
    out = backtest_buy_the_dip(lp["symbols"], datetime.fromisoformat(start), datetime.fromisoformat(end),
                               initial_capital=10_000, position_size=float(lp.get("pos_frac") or 1 / 7),
                               include_taf_fees=True, include_cat_fees=True, slippage_bps=slippage,
                               **params)
    trades_df, metrics = out[0], out[1]
    a = ba.from_buy_the_dip(trades_df, metrics, initial_capital=10_000, slippage_bps=slippage,
                            params=params, label=label or "live", live_params=lp, universe=lp["symbols"],
                            period_start=start, period_end=end, fill_rule="close",
                            same_bar_policy="stop_first")   # b47e6de: stop-before-target
    return f"{slug} BTD backtest {start}→{end}, {slippage:g} bps", ba.audit(a)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--strategy-id", type=int)
    g.add_argument("--run-id")
    g.add_argument("--btd-live", metavar="STRATEGY_CONFIG_NAME")
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default=datetime.now().date().isoformat())
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--label", choices=["live", "research"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.strategy_id is not None:
            what, rep = by_strategy(a.strategy_id, a.save)
        elif a.run_id:
            what, rep = by_run(a.run_id, a.label)
        else:
            what, rep = by_btd_live(a.btd_live, a.start, a.end, a.slippage_bps, a.label)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps({"subject": what, **rep.to_dict()}, indent=2, default=str))
    else:
        print(what)
        print(ba.format_report(rep))
    return EXIT[rep.status]


if __name__ == "__main__":
    raise SystemExit(main())

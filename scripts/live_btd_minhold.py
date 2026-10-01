#!/usr/bin/env python3
"""Mag-7 buy-the-dip LIVE runner, single pass (CLI). The pass logic lives in
utils/live_btd_runner.py; the long-running in-memory event scheduler that drives it on the
HP / Mac / box is scripts/live_btd_scheduler.py (docs/strategy_methodology.md).

Default is DRY RUN (computes everything, prints intended orders, submits nothing).
Orders are only submitted with `--live`. Credentials: ALPACA_LIVE_API_KEY /
ALPACA_LIVE_SECRET_KEY / ALPACA_LIVE_BASE_URL in the environment or the repo .env.

Params: alpatrade.strategy_configs (--strategy <name|id> or $BTD_STRATEGY, default
buy_the_dip_mag7_minhold_live); explicit flags override the row (testing); code defaults apply
only if the row cannot be read, and then a --live pass places no entries.

Events (--event, default auto = chosen from the market clock):
  open   place/refresh broker-side TP/SL exits for positions past the calendar min-hold
         (never on the buy date: PDT-safe); market sell if already beyond TP/SL
  entry  dip check + buys in the entry window (15:45-15:55 ET)
  close  max-hold exits in the close window (cancels the runner's broker exits first)
  post   record fills / performance only
  heartbeat  DB lease renew only

Examples:  python scripts/live_btd_minhold.py                     # dry run, auto event
           python scripts/live_btd_minhold.py --event entry --ignore-hours
Seed the DB state once: python scripts/live_btd_minhold.py --seed-state --seed-run-id <uuid>
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.live_btd_runner import (ET, PassStop, Runner, build_parser, setup_logging)  # noqa: E402
from utils.live_btd_state import empty_state, in_session_gate  # noqa: E402
from utils.live_btd_store import LiveRecorder, STRATEGY_NAME  # noqa: E402

a = build_parser().parse_args()
if a.live and a.ignore_hours:
    sys.exit("--ignore-hours is dry-run only.")
if not (a.any_time or a.ignore_hours or a.record_test or a.seed_state) and not in_session_gate(datetime.now(ET)):
    sys.exit(0)
log = setup_logging()
try:
    runner = Runner(a, log)
except PassStop as s:
    sys.exit(s.code)
CFG = runner.load_config()
for _k, _v in CFG.params.items():
    setattr(a, _k, ",".join(_v) if _k == "symbols" else _v)
get, BASE, DB_URL, USER_EMAIL, INSTANCE = runner.get, runner.base, runner.db_url, runner.user_email, runner.instance


def make_store(account_number):
    return runner.store(account_number)


def run_config(extra=None):
    return {"strategy_name": STRATEGY_NAME, "mode": "live", "symbols": CFG.params["symbols"],
            "take_profit": a.tp, "stop_loss": a.sl, **CFG.snapshot(), **(extra or {})}


if a.seed_state:
    if not a.seed_run_id: sys.exit("--seed-state needs --seed-run-id")
    acct0 = get(f"{BASE}/v2/account"); pos0 = get(f"{BASE}/v2/positions")
    oo0 = get(f"{BASE}/v2/orders", status="open", limit=500)
    basket = {s.strip().upper() for s in a.symbols.split(",") if s.strip()}
    log.info("seed: Alpaca account %s equity=%s cash=%s positions=%s open_orders=%s",
             acct0.get("account_number"), acct0.get("equity"), acct0.get("cash"),
             [(x["symbol"], x["qty"], x.get("asset_class")) for x in pos0], [(o["symbol"], o["side"]) for o in oo0])
    clash = sorted({x["symbol"] for x in pos0} & basket | {o["symbol"] for o in oo0} & basket)
    if clash and not a.force_seed:
        sys.exit(f"seed: basket symbols held/pending at Alpaca {clash}; they would be treated as pre-existing. "
                 "Re-run with --force-seed if that is intended.")
    store = make_store(acct0["account_number"])
    if not store: sys.exit("seed: DATABASE_URL not set")
    from sqlalchemy import text
    st = empty_state(a.seed_run_id)
    with store._engine.connect() as c:
        run = c.execute(text("SELECT config, results FROM alpatrade.runs WHERE run_id = :r"),
                        {"r": a.seed_run_id}).first()
    if run is None: sys.exit(f"seed: run {a.seed_run_id} not found in alpatrade.runs")
    cfg = run.config or {}; res = run.results or {}
    st["rec"].update({"start_equity": cfg.get("start_equity"), "start_spy": cfg.get("start_spy"),
                      "started": cfg.get("started")})
    daily = res.get("daily") or {}
    if daily: st["rec"]["last_daily"] = max(daily)
    st["seeded"] = {"at": datetime.now(ET).isoformat(), "by": INSTANCE,
                    "from": "last known HP state (positions {}, pending [])",
                    "preexisting_positions": sorted(x["symbol"] for x in pos0)}
    ok = store.seed(st, a.seed_run_id, force=a.force_seed)
    log.info("seed: %s state row %s (run %s): %s", "wrote" if ok else "NOT overwritten (exists; use --force-seed)",
             store.runner_key, a.seed_run_id, json.dumps(st, default=str))
    sys.exit(0 if ok else 1)

if a.record_test:
    rec = LiveRecorder(DB_URL, USER_EMAIL, log=log)
    if not rec.enabled: sys.exit("record-test: recorder not enabled (see warning above)")
    rid = rec.ensure_run(None, run_config({"strategy_name": "[TEST] " + STRATEGY_NAME, "test": True}))
    cid = f"btd-TEST-{datetime.now(ET):%Y%m%d%H%M%S}"
    rec.entry_submitted(rid, "TEST", cid, 100.0, 3.5, 100.0)
    rec.entry_filled(rid, cid, 1.0, 100.0, None, a.tp, a.sl)
    rec.sync_positions(rid, [{"symbol": "TEST", "qty": "1", "avg_entry_price": "100", "current_price": "101",
                              "market_value": "101", "unrealized_pl": "1", "unrealized_plpc": "0.01",
                              "cost_basis": "100"}], {"TEST": None})
    rec.exit_filled(rid, cid, 1.0, 108.0, None, "TP test")
    rec.sync_positions(rid, [], {})
    rec.record_performance(rid, {"equity": 1, "strategy_return_pct": 0.0, "test": True}, daily_key="test",
                           closed=rec.realized(rid))
    from sqlalchemy import text
    with rec._engine.connect() as c:
        r = c.execute(text("SELECT r.run_id, r.mode, r.strategy, u.email, r.user_id, r.results->'latest'->>'test' "
                           "FROM alpatrade.runs r JOIN alpatrade.users u USING (user_id) WHERE r.run_id=:r"), {"r": rid}).first()
        t = c.execute(text("SELECT trade_type, symbol, shares, entry_price, exit_price, pnl, reason, user_id "
                           "FROM alpatrade.trades WHERE run_id=:r"), {"r": rid}).all()
        ps = c.execute(text("SELECT symbol, status FROM alpatrade.positions WHERE run_id=:r"), {"r": rid}).all()
        pn = c.execute(text("SELECT trade_count, total_pnl, win_rate FROM alpatrade.pnl_summary WHERE run_id=:r"), {"r": rid}).all()
    log.info("record-test run: %s", r); log.info("record-test trades: %s", t)
    log.info("record-test positions: %s  pnl_summary: %s", ps, pn)
    rec.delete_run(rid)
    with rec._engine.connect() as c:
        left = c.execute(text("SELECT COUNT(*) FROM alpatrade.runs WHERE run_id=:r"), {"r": rid}).scalar()
    log.info("record-test cleanup: remaining run rows=%s (enabled=%s)", left, rec.enabled)
    sys.exit(0 if rec.enabled and left == 0 else 1)


if a.event == "heartbeat":
    lr = runner.heartbeat()
    log.info("heartbeat%s: ok=%s act=%s reason=%s", "" if a.live else " (dry-run: read-only peek, nothing written)",
             lr.ok, lr.act, lr.reason)
    sys.exit(0)
res = runner.run([a.event], CFG)
sys.exit(res.code)

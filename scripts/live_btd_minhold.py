#!/usr/bin/env python3
"""Mag-7 buy-the-dip LIVE runner with TRUE calendar min-hold (PDT-safe).

Standalone: not imported by the web app/API and not started by docker-compose.
Default is DRY RUN (computes signals, prints intended orders, submits nothing).
Orders are only submitted with `--live`. Credentials come from ALPACA_LIVE_API_KEY /
ALPACA_LIVE_SECRET_KEY / ALPACA_LIVE_BASE_URL in the environment or the repo .env.
State + logs live outside the repo in $BTD_STATE_DIR (default ~/.alpatrade-live).

Sizing (default): 10% of current equity per position, notional/fractional, one position
per symbol, cash only (never exceeds min(cash, non_marginable_buying_power)).
Use --pos-frac 0.142857 for 1/7 of equity per name (fully deployed at 7 positions).

Example (dry run):  python scripts/live_btd_minhold.py --ignore-hours
Example (live):     python scripts/live_btd_minhold.py --live

Recording: live passes also write the run, its trades (trade_type='live'), runner-owned
positions and performance into AlpaTrade's DB (DATABASE_URL) under the AlpaTrade user
$BTD_USER_EMAIL (default kaljuvee@gmail.com). Best-effort: DB errors are logged and
never block or change trading. `--record-test` writes a marked test run, reads it
back and deletes it (no orders, no Alpaca writes).

Each invocation is one idempotent pass (run from cron/systemd every 5 min in RTH):
  1. exits : positions opened by this runner that are >= MIN_HOLD calendar days old (ET)
             -> sell if P&L >= +TP or <= -SL, or if age >= MAX_HOLD and we're in the
             close window. Never sells a position opened today (PDT guard).
  2. entries: only in the ENTRY window (default 15:45-15:55 ET). dip = (ref - last)/ref,
             ref = previous daily close (default) or 20-bar high (repo backtester).
             Notional (fractional) market buy, one position per symbol, cash-only.
"""
import argparse, fcntl, json, logging, os, sys
from datetime import datetime, date, timedelta, time as dtime
from zoneinfo import ZoneInfo
import requests
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.live_btd_store import LiveRecorder, STRATEGY_NAME, STRATEGY_SLUG  # noqa: E402

ET = ZoneInfo("America/New_York")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.expanduser(os.getenv("BTD_STATE_DIR", "~/.alpatrade-live"))
os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
STATE = os.path.join(HERE, "state.json")
ENV_PATH = os.path.join(REPO, ".env")
DATA_URL = "https://data.alpaca.markets"

p = argparse.ArgumentParser()
p.add_argument("--symbols", default="AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA")
p.add_argument("--dip", type=float, default=3.0)
p.add_argument("--tp", type=float, default=8.0)
p.add_argument("--sl", type=float, default=1.5)
p.add_argument("--min-hold", type=int, default=3, help="calendar days before TP/SL allowed")
p.add_argument("--max-hold", type=int, default=3, help="calendar days; exit at close window once reached")
p.add_argument("--pos-frac", type=float, default=0.10, help="fraction of equity per position")
p.add_argument("--max-exposure", type=float, default=0.0, help="$ cap on total exposure (0 = cash only)")
p.add_argument("--ref", choices=["prev_close", "high20"], default="high20",
               help="dip reference: high20 = 20-bar high (matches utils/buy_the_dip.py backtests); prev_close = prior daily close")
p.add_argument("--feed", default="iex")
p.add_argument("--entry-window", default="15-5",
               help="minutes before the session close (from /v2/clock, so half-days work): 15-5 = 15:45-15:55 ET")
p.add_argument("--close-window", default="15-2", help="minutes before close for max-hold exits")
p.add_argument("--live", action="store_true", help="really submit orders to the LIVE account (default: dry run)")
p.add_argument("--ignore-hours", action="store_true", help="dry-run only: evaluate as if in entry window")
p.add_argument("--record-test", action="store_true",
               help="write a clearly marked test run to the AlpaTrade DB, read it back, delete it; no orders")
a = p.parse_args()

EXECUTE = bool(a.live)
if EXECUTE and a.ignore_hours:
    sys.exit("--ignore-hours is dry-run only.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(HERE, "logs", "btd.log"))])
log = logging.getLogger("btd")

env = {**dotenv_values(ENV_PATH), **{k: v for k, v in os.environ.items() if k.startswith("ALPACA_LIVE_")}}
if not env.get("ALPACA_LIVE_API_KEY") or not env.get("ALPACA_LIVE_SECRET_KEY"):
    sys.exit("ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY not set")
DB_URL = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
USER_EMAIL = os.environ.get("BTD_USER_EMAIL", "kaljuvee@gmail.com")
ACCOUNT_NO = env.get("ALPACA_LIVE_ACCOUNT") or os.environ.get("ALPACA_LIVE_ACCOUNT")
BASE = env.get("ALPACA_LIVE_BASE_URL", "https://api.alpaca.markets").rstrip("/")
H = {"APCA-API-KEY-ID": env["ALPACA_LIVE_API_KEY"], "APCA-API-SECRET-KEY": env["ALPACA_LIVE_SECRET_KEY"]}

def get(url, **params):
    r = requests.get(url, headers=H, params=params, timeout=20); r.raise_for_status(); return r.json()

def post_order(body):
    if not EXECUTE:
        log.info("DRY-RUN would POST /v2/orders %s", json.dumps(body)); return {"dry_run": True}
    r = requests.post(f"{BASE}/v2/orders", headers=H, json=body, timeout=20)
    if r.status_code == 422 and "client_order_id" in r.text:
        log.warning("duplicate client_order_id %s -> already submitted, skipping", body.get("client_order_id")); return {}
    r.raise_for_status(); return r.json()

def win(s, now):
    """True if the market is open and now is within [hi, lo] minutes of today's close."""
    if not clock.get("is_open"): return False
    far, near = [float(x) for x in s.split("-")]
    mins = (datetime.fromisoformat(clock["next_close"]).astimezone(ET) - now).total_seconds() / 60
    return near <= mins <= far

def load_state():
    try: return json.load(open(STATE))
    except FileNotFoundError: return {"positions": {}}

def save_state(s):
    tmp = STATE + ".tmp"; json.dump(s, open(tmp, "w"), indent=2); os.replace(tmp, STATE)

def run_config(extra=None):
    return {"strategy_name": STRATEGY_NAME, "strategy_slug": STRATEGY_SLUG, "mode": "live",
            "broker": "alpaca", "account_number": ACCOUNT_NO, "symbols": a.symbols.split(","),
            "dip_threshold": a.dip, "dip_reference": a.ref, "take_profit": a.tp,
            "stop_loss": a.sl, "min_hold_days": a.min_hold, "hold_days": a.max_hold,
            "position_size": a.pos_frac, "sizing": "notional, fraction of equity, cash only",
            "runner": "scripts/live_btd_minhold.py", **(extra or {})}

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

lock = open(os.path.join(HERE, ".lock"), "w")
try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError: sys.exit("another run in progress")

now = datetime.now(ET); today = now.date()
clock = get(f"{BASE}/v2/clock")
acct = get(f"{BASE}/v2/account")
positions = {x["symbol"]: x for x in get(f"{BASE}/v2/positions")}
open_orders = get(f"{BASE}/v2/orders", status="open", limit=500)
state = load_state()
syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]

equity = float(acct["equity"]); cash = float(acct["cash"])
nmbp = float(acct.get("non_marginable_buying_power", cash))
dtc = acct.get("daytrade_count")  # removed by Alpaca 2026-07-06 (FINRA retired PDT); None = n/a
log.info("MODE=%s market_open=%s equity=%.2f cash=%.2f nonmarg_bp=%.2f bp=%.2f daytrade_count=%s PDT=%s blocked=%s",
         "LIVE" if EXECUTE else "DRY-RUN", clock["is_open"], equity, cash, nmbp, float(acct["buying_power"]),
         dtc, acct.get("pattern_day_trader"), acct.get("trading_blocked"))
if acct.get("trading_blocked") or acct.get("account_blocked"):
    sys.exit("account blocked")
market_ok = clock["is_open"] or (a.ignore_hours and not EXECUTE)

# ---------------- recording (best-effort, never affects trading) ----------------
rec = LiveRecorder(DB_URL, USER_EMAIL, log=log) if EXECUTE else None
R = state.setdefault("rec", {}) if EXECUTE else {}
R.setdefault("pending", [])

def record_pending_fills():
    """Poll orders this runner submitted; record fills / failures. Read-only broker calls."""
    if not rec or not R.get("run_id"): return
    keep = []
    for it in R["pending"]:
        try:
            o = get(f"{BASE}/v2/orders:by_client_order_id", client_order_id=it["cid"])
        except Exception as exc:  # noqa: BLE001
            log.warning("record: order lookup %s failed: %s", it["cid"], exc); keep.append(it); continue
        st = o.get("status"); fq = float(o.get("filled_qty") or 0); fp = float(o.get("filled_avg_price") or 0)
        final = st in ("filled", "canceled", "expired", "rejected", "done_for_day", "replaced")
        if not final: keep.append(it); continue
        if it["side"] == "buy":
            if fq > 0: rec.entry_filled(R["run_id"], it["cid"], fq, fp, o.get("filled_at"), a.tp, a.sl)
            else: rec.entry_failed(R["run_id"], it["cid"], st)
        elif fq > 0:
            rec.exit_filled(R["run_id"], it["entry_cid"], fq, fp, o.get("filled_at"), it.get("reason"))
        log.info("record: %s %s %s qty=%s px=%s", it["side"], it["cid"], st, fq, fp)
    R["pending"] = keep

if rec and rec.enabled:
    try:
        if not R.get("run_id"):
            R["start_equity"] = equity; R["started"] = today.isoformat()
            try:
                R["start_spy"] = float(get(f"{DATA_URL}/v2/stocks/snapshots", symbols="SPY", feed=a.feed)["SPY"]["latestTrade"]["p"])
            except Exception: R["start_spy"] = None  # noqa: BLE001
        rid = rec.ensure_run(R.get("run_id"), run_config({"start_equity": R.get("start_equity"),
                                                         "start_spy": R.get("start_spy"), "started": R.get("started")}))
        if rid and not R.get("run_id"):
            R["run_id"] = rid; log.info("record: AlpaTrade run %s (user %s)", rid, rec.user_id)
        record_pending_fills()
    except Exception as exc:  # noqa: BLE001
        log.warning("record: setup failed: %s", exc)

# ---------------- exits ----------------
pending_sell = {o["symbol"] for o in open_orders if o["side"] == "sell"}
for sym, meta in list(state["positions"].items()):
    pos = positions.get(sym)
    if not pos and any(o["symbol"] == sym and o["side"] == "buy" for o in open_orders):
        log.info("%s: entry order still open -> keep tracking", sym); continue
    if not pos:
        log.info("%s: tracked but no broker position -> dropping from state", sym)
        state["positions"].pop(sym); continue
    entry_d = date.fromisoformat(meta["entry_date"])
    age = (today - entry_d).days
    plpc = float(pos["unrealized_plpc"]) * 100
    reason = None
    if age >= a.min_hold:
        if plpc >= a.tp: reason = f"TP {plpc:.2f}%"
        elif plpc <= -a.sl: reason = f"SL {plpc:.2f}%"
    if not reason and age >= a.max_hold and (win(a.close_window, now) or a.ignore_hours):
        reason = f"MAX_HOLD age={age}d pl={plpc:.2f}%"
    log.info("%s: held age=%dd pl=%.2f%% qty=%s -> %s", sym, age, plpc, pos["qty"], reason or "hold")
    if not reason: continue
    if entry_d >= today:  # PDT guard: never a same-day round trip
        log.warning("%s: PDT guard refuses same-day exit", sym); continue
    if sym in pending_sell or not market_ok: continue
    xcid = f"btdx-{sym}-{today:%Y%m%d}"
    post_order({"symbol": sym, "qty": pos["qty_available"], "side": "sell", "type": "market",
                "time_in_force": "day", "client_order_id": xcid})
    if EXECUTE:
        meta["exit_submitted"] = now.isoformat()
        if not any(it["cid"] == xcid for it in R["pending"]):
            R["pending"].append({"cid": xcid, "side": "sell", "sym": sym, "reason": reason,
                                 "entry_cid": meta.get("client_id") or f"btd-{sym}-{meta['entry_date'].replace('-', '')}"})
# never touch positions not opened by this runner
for sym in positions:
    if sym not in state["positions"]:
        log.info("%s: pre-existing/untracked position -> ignored by runner (blocks new entry)", sym)

# ---------------- entries ----------------
in_entry = win(a.entry_window, now)
if not (in_entry or (a.ignore_hours and not EXECUTE)):
    log.info("outside entry window (%s min before close) -> no entries", a.entry_window)
else:
    snaps = get(f"{DATA_URL}/v2/stocks/snapshots", symbols=",".join(syms), feed=a.feed)
    bars = get(f"{DATA_URL}/v2/stocks/bars", symbols=",".join(syms), timeframe="1Day",
               start=(today - timedelta(days=40)).isoformat(), feed=a.feed, limit=1000, adjustment="split")["bars"]
    pending_buy_val = sum(float(o.get("notional") or 0) or float(o.get("qty") or 0) * float(o.get("limit_price") or 0) for o in open_orders if o["side"] == "buy")
    exposure = sum(abs(float(p["market_value"])) for p in positions.values())
    avail = min(cash, nmbp) - pending_buy_val
    target = round(equity * a.pos_frac, 2)
    log.info("sizing: target/position=$%.2f (%.1f%% equity) available_cash=$%.2f exposure=$%.2f",
             target, a.pos_frac * 100, avail, exposure)
    for sym in syms:
        sn = snaps.get(sym) or {}
        last = float((sn.get("latestTrade") or {}).get("p") or 0)
        daily = sn.get("dailyBar") or {}; prev = sn.get("prevDailyBar") or {}
        # prev close = last completed session before today's session
        # dailyBar dated today => today's session exists, prev close = prevDailyBar;
        # otherwise (pre-open) the last completed session is dailyBar itself.
        if daily.get("t", "")[:10] == today.isoformat(): prev_close = float(prev.get("c") or 0)
        else: prev_close = float(daily.get("c") or 0)
        high20 = max([b["h"] for b in bars.get(sym, [])][-20:] or [0])
        ref = prev_close if a.ref == "prev_close" else high20
        dip = (ref - last) / ref * 100 if ref else 0
        dip_h = (high20 - last) / high20 * 100 if high20 else 0
        sig = dip >= a.dip
        log.info("%s: last=%.2f prev_close=%.2f dip_vs_prev=%.2f%% | high20=%.2f dip_vs_high20=%.2f%% -> %s",
                 sym, last, prev_close, (prev_close - last) / prev_close * 100 if prev_close else 0,
                 high20, dip_h, "SIGNAL" if sig else "no")
        if not sig: continue
        if sym in positions or sym in state["positions"] or any(o["symbol"] == sym for o in open_orders):
            log.info("%s: already held/pending -> skip (one per symbol)", sym); continue
        if state.get("last_entry", {}).get(sym) == today.isoformat():
            log.info("%s: already entered today -> skip", sym); continue
        asset = get(f"{BASE}/v2/assets/{sym}")
        if not (asset.get("tradable") and asset.get("fractionable")):
            log.info("%s: not tradable/fractionable -> skip", sym); continue
        notional = target
        if a.max_exposure and exposure + notional > a.max_exposure:
            log.info("%s: would exceed exposure cap $%.0f -> skip", sym, a.max_exposure); continue
        if notional > avail:
            log.info("%s: notional $%.2f > available cash $%.2f -> skip (no margin)", sym, notional, avail); continue
        cid = f"btd-{sym}-{today:%Y%m%d}"
        post_order({"symbol": sym, "notional": f"{notional:.2f}", "side": "buy", "type": "market",
                    "time_in_force": "day", "client_order_id": cid})
        avail -= notional; exposure += notional
        if EXECUTE:
            state["positions"][sym] = {"entry_date": today.isoformat(), "notional": notional, "ref": ref,
                                       "dip": dip, "client_id": cid}
            state.setdefault("last_entry", {})[sym] = today.isoformat()
            R["pending"].append({"cid": cid, "side": "buy", "sym": sym})
            if rec and R.get("run_id"): rec.entry_submitted(R["run_id"], sym, cid, notional, dip, ref)
# ---------------- performance (best-effort) ----------------
if rec and rec.enabled and R.get("run_id"):
    try:
        mine = [positions[s] for s in state["positions"] if s in positions]
        rec.sync_positions(R["run_id"], mine, {s: m.get("entry_date") for s, m in state["positions"].items()})
        closed = rec.realized(R["run_id"]) or {}
        unreal = sum(float(x["unrealized_pl"]) for x in mine)
        realized = float(closed.get("total_pnl") or 0)
        start_eq = float(R.get("start_equity") or equity)
        spy = None; spy_day = None
        try:
            sn = get(f"{DATA_URL}/v2/stocks/snapshots", symbols="SPY", feed=a.feed)["SPY"]
            spy = float(sn["latestTrade"]["p"]); spy_day = (sn.get("dailyBar") or {}).get("t", "")[:10] or None
        except Exception: pass  # noqa: BLE001
        perf = {"as_of": now.isoformat(), "account_number": ACCOUNT_NO, "equity": equity, "cash": cash,
                "start_equity": start_eq, "open_positions": len(mine),
                "exposure": round(sum(float(x["market_value"]) for x in mine), 2),
                "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
                "total_pnl": round(realized + unreal, 2),
                "strategy_return_pct": round((realized + unreal) / start_eq * 100, 3) if start_eq else None,
                "account_return_pct": round((equity / start_eq - 1) * 100, 3) if start_eq else None,
                "closed_trades": int(closed.get("trade_count") or 0), "spy": spy,
                "spy_return_pct": round((spy / R["start_spy"] - 1) * 100, 3) if spy and R.get("start_spy") else None}
        daily_key = None
        if not clock["is_open"] and spy_day and R.get("last_daily") != spy_day:
            daily_key = spy_day  # last completed session: once per day, after the close
        if rec.record_performance(R["run_id"], perf, daily_key=daily_key, closed=closed) and daily_key:
            R["last_daily"] = daily_key; log.info("record: daily performance snapshot %s", daily_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("record: performance failed: %s", exc)

if EXECUTE: save_state(state)
log.info("pass complete")

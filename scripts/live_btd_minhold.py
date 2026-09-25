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
    post_order({"symbol": sym, "qty": pos["qty_available"], "side": "sell", "type": "market",
                "time_in_force": "day", "client_order_id": f"btdx-{sym}-{today:%Y%m%d}"})
    if EXECUTE: meta["exit_submitted"] = now.isoformat()
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
        post_order({"symbol": sym, "notional": f"{notional:.2f}", "side": "buy", "type": "market",
                    "time_in_force": "day", "client_order_id": f"btd-{sym}-{today:%Y%m%d}"})
        avail -= notional; exposure += notional
        if EXECUTE:
            state["positions"][sym] = {"entry_date": today.isoformat(), "notional": notional, "ref": ref, "dip": dip}
            state.setdefault("last_entry", {})[sym] = today.isoformat()
if EXECUTE: save_state(state)
log.info("pass complete")

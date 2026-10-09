"""Importable live Mag-7 BTD runner logic (one event pass), shared by the CLI
(scripts/live_btd_minhold.py) and the in-memory event scheduler (utils/live_btd_scheduler.py).

Events (all idempotent: deterministic client_order_ids, Alpaca re-checked before every order):
  open      ~09:31 ET  place/refresh BROKER-SIDE exits (OCO TP+stop / stop) for positions past
                       their calendar min-hold (never on the buy date); immediate market sell if
                       price is already beyond TP/SL. Re-run on failover takeover (catch-up).
  entry     15:45/15:50/15:55 ET (close-15/-10/-5): evaluate dips, buy (cash only).
  close     ~15:58 ET (close-2): max-hold exits; cancels the runner's broker exits first.
  post      close+3: record fills + daily performance snapshot. No orders.
  heartbeat every 3 min in the session: DB lease renew + heartbeat only (no Alpaca calls).

Failover is unchanged (utils/live_btd_state.py): every live event and heartbeat takes the DB
lease in one transaction (primary > backup > tertiary, 8-min TTL, 12-min takeover); only the
holder trades; DB unreachable -> no entries (exits only from the local cache if this instance
acted last). If the strategy config was not loaded from the DB, entries are disabled too.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import dotenv_values

from utils.live_btd_config import (DEFAULT_PARAMS, DEFAULT_STRATEGY, ConfigResult, exit_order,
                                   ext_exit_action, resolve as resolve_config)
from utils.live_btd_exits import (cids, exit_eligible, fallback_full_stop, order_fill, own_open_exits,
                                  plan_broker_exits)
from utils.live_btd_state import (LeaseResult, RunnerStateStore, adopt_runner_position, alpaca_symbol_busy,
                                  degraded_policy, merge_dirty_cache, normalize_state)
from utils.live_btd_store import STRATEGY_NAME, STRATEGY_SLUG, LiveRecorder
from utils.strategy_allocation import PRIMARY_PREFIX, Sleeve, buying_power, sleeve_value

ET = ZoneInfo("America/New_York")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO, ".env")
DATA_URL = "https://data.alpaca.markets"
EVENTS = ("open", "entry", "close", "post")
PKEYS = ("symbols", "dip", "tp", "sl", "min_hold", "max_hold", "pos_frac", "max_exposure", "ref", "feed",
         "entry_window", "close_window")
CACHE_META = ("acted_last", "db_dirty", "cache_written_at", "cache_instance", "db_version")
OPEN_ST = ("new", "accepted", "pending_new", "partially_filled", "held", "accepted_for_bidding",
           "pending_replace", "pending_cancel")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default=None,
                   help=f"alpatrade.strategy_configs name or id (default: $BTD_STRATEGY or {DEFAULT_STRATEGY})")
    # Overrides only (testing / one-off). Precedence per key: flag > DB row > DEFAULT_PARAMS.
    p.add_argument("--symbols", default=None, help=f"override (default {','.join(DEFAULT_PARAMS['symbols'])})")
    p.add_argument("--dip", type=float, default=None, help="override, %% below ref (default 3)")
    p.add_argument("--tp", type=float, default=None, help="override, take profit %% (default 8)")
    p.add_argument("--sl", type=float, default=None, help="override, stop loss %% (default 1.5)")
    p.add_argument("--min-hold", type=int, default=None, help="override: calendar days before TP/SL allowed (default 3)")
    p.add_argument("--max-hold", type=int, default=None, help="override: calendar days; exit at close once reached (default 3)")
    p.add_argument("--pos-frac", type=float, default=None, help="override: fraction of equity per position (default 0.10)")
    p.add_argument("--max-exposure", type=float, default=None, help="override: $ cap on total exposure (0 = cash only)")
    p.add_argument("--ref", choices=["prev_close", "high20"], default=None, help="override dip reference (default high20)")
    p.add_argument("--feed", default=None, help="override market-data feed (default iex)")
    p.add_argument("--entry-window", default=None, help="override: minutes before close, default 15-5 = 15:45-15:55 ET")
    p.add_argument("--close-window", default=None, help="override: minutes before close for max-hold exits (default 15-2)")
    p.add_argument("--event", default="auto", choices=("auto",) + EVENTS + ("heartbeat",),
                   help="CLI single pass: which event to run (auto = by the market clock)")
    p.add_argument("--live", action="store_true", help="really submit orders to the LIVE account (default: dry run)")
    p.add_argument("--ignore-hours", action="store_true", help="dry-run only: evaluate entries as if in the window")
    p.add_argument("--record-test", action="store_true",
                   help="write a clearly marked test run to the AlpaTrade DB, read it back, delete it; no orders")
    p.add_argument("--role", choices=["primary", "backup", "tertiary"], default=None,
                   help="failover role (default: $BTD_ROLE or primary)")
    p.add_argument("--instance", default=None, help="instance name for the lease (default: $BTD_INSTANCE or hostname)")
    p.add_argument("--lease-ttl-min", type=float, default=8.0, help="leader lease TTL (minutes)")
    p.add_argument("--takeover-min", type=float, default=12.0,
                   help="lower role takes over when every higher-priority heartbeat is older than this (minutes)")
    p.add_argument("--any-time", action="store_true",
                   help="run even outside Mon-Fri 09:00-16:05 ET (trading is still gated by /v2/clock)")
    p.add_argument("--seed-state", action="store_true",
                   help="create the authoritative DB state row (empty positions/pending) and exit; no orders")
    p.add_argument("--seed-run-id", default=None, help="run id to seed (the existing alpatrade.runs row)")
    p.add_argument("--force-seed", action="store_true", help="overwrite an existing state row when seeding")
    return p


def state_dir() -> str:
    d = os.path.expanduser(os.getenv("BTD_STATE_DIR", "~/.alpatrade-live"))
    os.makedirs(os.path.join(d, "logs"), exist_ok=True)
    return d


def setup_logging() -> logging.Logger:
    """Console + $BTD_STATE_DIR/logs/btd.log on the root logger (idempotent per state dir)."""
    path = os.path.join(state_dir(), "logs", "btd.log")
    root = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(path) for h in root.handlers):
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        if not any(type(h) is logging.StreamHandler for h in root.handlers):
            sh = logging.StreamHandler(); sh.setFormatter(fmt); root.addHandler(sh)
        fh = logging.FileHandler(path); fh.setFormatter(fmt); root.addHandler(fh)
    root.setLevel(logging.INFO)
    return logging.getLogger("btd")


def code_version() -> Optional[str]:
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def auto_events(clock: Dict[str, Any], now: datetime, entry_window: str, close_window: str) -> List[str]:
    """CLI --event auto: what a scheduler would run at this instant."""
    if not clock.get("is_open"):
        return ["post"]
    mins = (datetime.fromisoformat(clock["next_close"]).astimezone(ET) - now).total_seconds() / 60
    ev = []
    if _in(close_window, mins): ev.append("close")
    if _in(entry_window, mins): ev.append("entry")
    return ev or ["open"]


def _in(window: str, mins: float) -> bool:
    far, near = [float(x) for x in window.split("-")]
    return near <= mins <= far


def held_by_others(acct_state: Dict[str, Any], sleeve) -> set:
    """Symbols tracked by every OTHER strategy sharing this account state."""
    out = set()
    if not sleeve.is_primary:
        out |= set((acct_state.get("positions") or {}).keys())
    for name, sub in (acct_state.get("sleeves") or {}).items():
        if sleeve.is_primary or name != sleeve.strategy_name:
            out |= set(((sub or {}).get("positions") or {}).keys())
    return out


class PassStop(Exception):
    """Early, orderly end of a pass (code 0 = fine)."""
    def __init__(self, code: Any = 0):
        super().__init__(code); self.code = code


@dataclass
class PassResult:
    events: List[str]
    acted: bool = False
    reason: str = ""
    code: Any = 0
    lease: Optional[LeaseResult] = None
    orders: List[Dict[str, Any]] = field(default_factory=list)


class Runner:
    """One instance per process. ``run(events, cfg)`` = one pass; ``heartbeat()`` = lease only."""

    def __init__(self, a: argparse.Namespace, log: Optional[logging.Logger] = None):
        self.a = a
        self.log = log or logging.getLogger("btd")
        self.execute = bool(a.live)
        if self.execute and a.ignore_hours:
            raise PassStop("--ignore-hours is dry-run only.")
        self.here = state_dir()
        self.state_path = os.path.join(self.here, "state.json")
        env = {**dotenv_values(ENV_PATH), **{k: v for k, v in os.environ.items() if k.startswith("ALPACA_LIVE_")}}
        if not env.get("ALPACA_LIVE_API_KEY") or not env.get("ALPACA_LIVE_SECRET_KEY"):
            raise PassStop("ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY not set")
        self.env = env
        self.db_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
        self.user_email = os.environ.get("BTD_USER_EMAIL", "kaljuvee@gmail.com")
        self.account_no = env.get("ALPACA_LIVE_ACCOUNT") or os.environ.get("ALPACA_LIVE_ACCOUNT")
        self.base = env.get("ALPACA_LIVE_BASE_URL", "https://api.alpaca.markets").rstrip("/")
        self.role = a.role or os.environ.get("BTD_ROLE") or env.get("BTD_ROLE") or "primary"
        self.instance = a.instance or os.environ.get("BTD_INSTANCE") or env.get("BTD_INSTANCE") or socket.gethostname()
        if self.role not in ("primary", "backup", "tertiary"):
            raise PassStop(f"BTD_ROLE must be primary, backup or tertiary, got {self.role!r}")
        self.strategy = a.strategy or os.environ.get("BTD_STRATEGY") or env.get("BTD_STRATEGY") or DEFAULT_STRATEGY
        self.headers = {"APCA-API-KEY-ID": env["ALPACA_LIVE_API_KEY"], "APCA-API-SECRET-KEY": env["ALPACA_LIVE_SECRET_KEY"]}
        self._store: Optional[RunnerStateStore] = None
        self._store_acct: Optional[str] = None

    # ------------------------------------------------------------------ config
    def cli_overrides(self) -> Dict[str, Any]:
        return {k: getattr(self.a, k, None) for k in PKEYS}

    def load_config(self) -> ConfigResult:
        cfg = resolve_config(self.strategy, self.cli_overrides(), database_url=self.db_url)
        self.log_config(cfg, "loaded")
        return cfg

    def log_config(self, cfg: ConfigResult, what: str) -> None:
        (self.log.info if cfg.db_ok else self.log.warning)(
            "strategy config %s [%s/%s]: source=%s params=%s sources=%s execution=%s", what, self.instance,
            self.role, cfg.source, json.dumps(cfg.params, sort_keys=True), json.dumps(cfg.sources, sort_keys=True),
            json.dumps(cfg.execution, sort_keys=True))

    def load_sleeves(self, account_number, primary_name):
        """(primary allocation or None, [(Sleeve, ConfigResult)]) from alpatrade.strategy_allocations."""
        if not self.db_url or not account_number:
            return None, []
        from utils.live_btd_config import make_engine
        from utils.strategy_allocation import load_sleeves, primary_allocation
        eng = getattr(self, "_alloc_engine", None) or make_engine(self.db_url)
        self._alloc_engine = eng
        pa = primary_allocation(eng, account_number, primary_name)
        out = [(sl, resolve_config(sl.strategy_name, {}, engine=eng)) for sl in load_sleeves(eng, account_number, primary_name)]
        return pa, out

    # ------------------------------------------------------------------ HTTP
    def get(self, url, **params):
        r = requests.get(url, headers=self.headers, params=params, timeout=20); r.raise_for_status(); return r.json()

    def post_order(self, body):
        if not self.execute:
            self.log.info("DRY-RUN would POST /v2/orders %s", json.dumps(body)); return {"dry_run": True}
        r = requests.post(f"{self.base}/v2/orders", headers=self.headers, json=body, timeout=20)
        if r.status_code == 422 and "client_order_id" in r.text:
            self.log.warning("duplicate client_order_id %s -> already submitted, skipping", body.get("client_order_id"))
            return {}
        r.raise_for_status(); return r.json()

    def broker_call(self, method, path, body=None):
        """PATCH/DELETE on the trading API (live only; dry run logs)."""
        if not self.execute:
            self.log.info("DRY-RUN would %s %s %s", method, path, json.dumps(body) if body else "")
            return {"dry_run": True}
        r = requests.request(method, f"{self.base}{path}", headers=self.headers, json=body, timeout=20)
        r.raise_for_status(); return r.json() if r.content else {}

    # ------------------------------------------------------------------ DB
    def store(self, account_number: Optional[str]) -> Optional[RunnerStateStore]:
        if not self.db_url or not account_number:
            return None
        if self._store is None or self._store_acct != account_number:
            self._store = RunnerStateStore(
                self.db_url, f"{STRATEGY_SLUG}:{account_number}", instance=self.instance, role=self.role,
                log=self.log, lease_ttl_s=self.a.lease_ttl_min * 60, takeover_s=self.a.takeover_min * 60,
                code_version=code_version())
            self._store_acct = account_number
        return self._store

    def load_cache(self):
        try:
            return json.load(open(self.state_path))
        except FileNotFoundError:
            return {"positions": {}}

    def save_cache(self, s):
        tmp = self.state_path + ".tmp"; json.dump(s, open(tmp, "w"), indent=2, default=str); os.replace(tmp, self.state_path)

    @staticmethod
    def strip_meta(doc):
        return normalize_state({k: v for k, v in (doc or {}).items() if k not in CACHE_META})

    def heartbeat(self) -> LeaseResult:
        """Lease renew + heartbeat only (no Alpaca calls, no state change)."""
        acct = self.account_no
        if not acct:
            acct = self.account_no = self.get(f"{self.base}/v2/account").get("account_number")
        st = self.store(acct)
        if not st:
            return LeaseResult(ok=False, reason="DATABASE_URL not set")
        lr = st.acquire() if self.execute else st.peek()
        return lr

    # ------------------------------------------------------------------ the pass
    def run(self, events: List[str], cfg: ConfigResult) -> PassResult:
        lock = open(os.path.join(self.here, ".lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return PassResult(events, code="another run in progress", reason="locked")
        try:
            return self._run(list(events), cfg)
        except PassStop as s:
            return PassResult(events, code=s.code, reason=str(s.code or "stopped"))
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN); lock.close()

    def _run(self, events: List[str], cfg: ConfigResult) -> PassResult:  # noqa: C901
        a, log, get, base, EXECUTE = self.a, self.log, self.get, self.base, self.execute
        P = cfg.params
        res = PassResult(events)
        now = datetime.now(ET); today = now.date()
        clock = get(f"{base}/v2/clock")
        acct = get(f"{base}/v2/account")
        if "auto" in events:
            events = res.events = auto_events(clock, now, P["entry_window"], P["close_window"])
        log.info("event pass %s [%s/%s] config v%s (%s)", "+".join(events), self.instance, self.role,
                 cfg.version, "db" if cfg.db_ok else "DEFAULTS")

        def win(s):
            if not clock.get("is_open"): return False
            return _in(s, (datetime.fromisoformat(clock["next_close"]).astimezone(ET) - now).total_seconds() / 60)

        # ---------------- failover: DB lease + authoritative state ----------------
        cache = self.load_cache()
        store = self.store(acct.get("account_number") or self.account_no)
        DEGRADED = False; ALLOW_ENTRIES = True; DEADLINE = float("inf")
        if EXECUTE:
            lr = store.acquire() if store else LeaseResult(ok=False, reason="DATABASE_URL not set")
            res.lease = lr
            if lr.ok and lr.missing:
                log.error("failover: %s -> not trading", lr.reason)
                cache["acted_last"] = False; self.save_cache(cache); raise PassStop(0)
            if lr.ok and not lr.act:
                log.info("failover: %s [%s/%s] -> standby, no action this pass", lr.reason, self.instance, self.role)
                cached = normalize_state(lr.state)
                self.save_cache({**cached, "acted_last": False, "db_dirty": False, "cache_written_at": now.isoformat(),
                                 "cache_instance": self.instance, "db_version": lr.version})
                res.reason = "standby"; return res
            if lr.ok:
                state = normalize_state(lr.state); DEADLINE = lr.deadline_mono
                if cache.get("db_dirty"):
                    state = merge_dirty_cache(state, self.strip_meta(cache))
                    log.warning("failover: merged local changes made while the DB was unreachable")
                log.info("failover: %s [%s/%s] lease until %s (state v%s, run %s)", lr.reason, self.instance, self.role,
                         lr.lease_expires_at, lr.version, (state.get("rec") or {}).get("run_id"))
            else:
                pol = degraded_policy(cache)
                log.warning("failover: %s -> DEGRADED: %s", lr.reason, pol["reason"])
                if not pol["exits"]: raise PassStop(0)
                DEGRADED = True; ALLOW_ENTRIES = False; state = self.strip_meta(cache)
        else:
            lr = store.peek() if store else LeaseResult(ok=False, reason="DATABASE_URL not set")
            res.lease = lr
            if lr.ok and not lr.missing:
                state = normalize_state(lr.state)
                log.info("failover (dry-run, read-only): state v%s run %s positions=%s pending=%d | lease=%s until %s | "
                         "as %s/%s a live pass would: %s (%s)", lr.version, state["rec"].get("run_id"),
                         sorted(state["positions"]), len(state["rec"]["pending"]), lr.info.get("lease_holder"),
                         lr.info.get("lease_expires_at"), self.instance, self.role, "ACT" if lr.act else "STAND BY", lr.reason)
                for hb in lr.info.get("heartbeats", []):
                    log.info("failover heartbeat: %s", hb)
            else:
                state = self.strip_meta(cache)
                log.warning("failover (dry-run): %s -> using the local cache", lr.reason)
        res.acted = EXECUTE and not DEGRADED

        if not cfg.db_ok:
            if EXECUTE: ALLOW_ENTRIES = False
            log.warning("strategy config not loaded from the DB (%s) -> %s", cfg.error,
                        "entries disabled this pass" if EXECUTE else "a live pass would disable entries")

        def lease_ok():
            if not EXECUTE or DEGRADED: return True
            if time.monotonic() < DEADLINE: return True
            log.error("failover: local lease deadline passed -> not submitting further orders this pass"); return False

        def persist():
            if not EXECUTE: return
            ok = False if DEGRADED else bool(store and store.save(acct_state))
            self.save_cache({**acct_state, "acted_last": True, "db_dirty": not ok, "cache_written_at": datetime.now(ET).isoformat(),
                             "cache_instance": self.instance})

        def submit(body):
            r = self.post_order(body); res.orders.append(body); return r

        acct_state = state

        def strategy_pass(state, cfg, sleeve, sleeves):  # noqa: C901
            """One strategy (sleeve) inside this pass: same lease, own sub-state, own cid prefix."""
            P = cfg.params; EXEC = cfg.execution; EXT = EXEC["extended_hours_exit"]  # noqa: F841
            syms = list(P["symbols"]); PFX = sleeve.cid_prefix
            other_held = held_by_others(acct_state, sleeve)
            sleeve_val = sleeve_value(sleeve, float(acct["equity"]), sleeves)
            if not sleeve.is_primary or len(sleeves) > 1:
                log.info("strategy %s [prefix %s]: sleeve $%.2f (%s) symbols=%s", sleeve.strategy_name, PFX, sleeve_val,
                         "rest of account" if sleeve.allocation_usd is None else "fixed allocation", ",".join(syms))
            positions = {x["symbol"]: x for x in get(f"{base}/v2/positions")}
            open_orders = get(f"{base}/v2/orders", status="open", limit=500)
            if EXECUTE and not DEGRADED:  # safety net: re-adopt runner entries the state lost track of
                for sym in syms:
                    if sym in positions and sym not in state["positions"]:
                        meta = adopt_runner_position(get, base, sym, PFX)
                        if meta:
                            state["positions"][sym] = meta
                            log.warning("%s: broker position came from a runner entry (%s) but was not in state -> adopted",
                                        sym, meta["client_id"])

            equity = float(acct["equity"]); cash = float(acct["cash"])
            nmbp = float(acct.get("non_marginable_buying_power", cash))
            log.info("MODE=%s market_open=%s equity=%.2f cash=%.2f nonmarg_bp=%.2f bp=%.2f daytrade_count=%s PDT=%s blocked=%s",
                     "LIVE" if EXECUTE else "DRY-RUN", clock["is_open"], equity, cash, nmbp, float(acct["buying_power"]),
                     acct.get("daytrade_count"), acct.get("pattern_day_trader"), acct.get("trading_blocked"))
            if acct.get("trading_blocked") or acct.get("account_blocked"):
                raise PassStop("account blocked")
            market_ok = clock["is_open"] or (a.ignore_hours and not EXECUTE)

            # ---------------- recording (best-effort, never affects trading) ----------------
            rec = LiveRecorder(self.db_url, self.user_email, log=log) if EXECUTE and not DEGRADED else None
            R = state.setdefault("rec", {}) if EXECUTE else {}
            R.setdefault("pending", [])

            def run_config(extra=None):
                return {"strategy_name": STRATEGY_NAME if sleeve.is_primary else (cfg.name or sleeve.strategy_name),
                        "strategy_slug": STRATEGY_SLUG if sleeve.is_primary else sleeve.strategy_name, "mode": "live",
                        "cid_prefix": PFX, "allocation_usd": sleeve.allocation_usd,
                        "broker": "alpaca", "account_number": self.account_no, "symbols": syms,
                        "dip_threshold": P["dip"], "dip_reference": P["ref"], "take_profit": P["tp"],
                        "stop_loss": P["sl"], "min_hold_days": P["min_hold"], "hold_days": P["max_hold"],
                        "position_size": P["pos_frac"],
                        "sizing": ("notional, fraction of equity, cash only" if sleeve.allocation_usd is None and len(sleeves) == 1
                                   else "notional, fraction of the strategy's cash allocation (sleeve), cash only"),
                        "max_exposure": P["max_exposure"], "entry_window": P["entry_window"],
                        "close_window": P["close_window"], "feed": P["feed"], "exits": "broker-side OCO/stop after min-hold",
                        "runner": "utils/live_btd_runner.py", **cfg.snapshot(), **(extra or {})}

            def record_pending_fills():
                """Poll orders this runner submitted; record fills once every order of an exit group is final."""
                if not rec or not R.get("run_id"): return
                looked = {}
                for it in R["pending"]:
                    try:
                        looked[it["cid"]] = get(f"{base}/v2/orders:by_client_order_id", client_order_id=it["cid"], nested="true")
                    except Exception as exc:  # noqa: BLE001
                        log.warning("record: order lookup %s failed: %s", it["cid"], exc)
                keep = []
                groups: Dict[str, List[Dict[str, Any]]] = {}
                for it in R["pending"]:
                    o = looked.get(it["cid"])
                    if o is None: keep.append(it); continue
                    fq, fp, final = order_fill(o)
                    it["_fill"] = (fq, fp, final, o.get("filled_at"), o.get("status"))
                    if it["side"] == "buy":
                        if not final: keep.append(it); continue
                        if fq > 0: rec.entry_filled(R["run_id"], it["cid"], fq, fp, o.get("filled_at"), P["tp"], P["sl"])
                        else: rec.entry_failed(R["run_id"], it["cid"], o.get("status"))
                        log.info("record: buy %s %s qty=%s px=%s", it["cid"], o.get("status"), fq, fp)
                    else:
                        groups.setdefault(it.get("entry_cid") or it["cid"], []).append(it)
                for entry_cid, items in groups.items():
                    if not all(i["_fill"][2] for i in items):
                        keep.extend(items); continue
                    q = sum(i["_fill"][0] for i in items)
                    if q > 0:
                        px = sum(i["_fill"][0] * i["_fill"][1] for i in items) / q
                        why = "; ".join(f"{i.get('reason')} {i['cid']} {i['_fill'][4]}" for i in items if i["_fill"][0] > 0)
                        rec.exit_filled(R["run_id"], entry_cid, q, px, max((i["_fill"][3] or "") for i in items) or None, why)
                    log.info("record: exit group %s final qty=%s (%s)", entry_cid, q, [i["cid"] for i in items])
                for it in R["pending"]:
                    it.pop("_fill", None)
                R["pending"] = keep

            if rec and rec.enabled:
                try:
                    if not R.get("run_id"):
                        R["start_equity"] = equity if sleeve.is_primary else round(sleeve_val, 2); R["started"] = today.isoformat()
                        try:
                            R["start_spy"] = float(get(f"{DATA_URL}/v2/stocks/snapshots", symbols="SPY", feed=P["feed"])["SPY"]["latestTrade"]["p"])
                        except Exception: R["start_spy"] = None  # noqa: BLE001
                    rid = rec.ensure_run(R.get("run_id"), run_config({"start_equity": R.get("start_equity"),
                                                                     "start_spy": R.get("start_spy"), "started": R.get("started")}))
                    if rid and not R.get("run_id"):
                        R["run_id"] = rid; log.info("record: AlpaTrade run %s (user %s)", rid, rec.user_id)
                    record_pending_fills()
                except Exception as exc:  # noqa: BLE001
                    log.warning("record: setup failed: %s", exc)

            def latest_bid(sym):
                q = get(f"{DATA_URL}/v2/stocks/{sym}/quotes/latest", feed=P["feed"]).get("quote") or {}
                return float(q.get("bp") or 0)

            def ext_session():
                if clock.get("is_open"): return False
                nxt = datetime.fromisoformat(clock["next_open"]).astimezone(ET)
                return (nxt - now).total_seconds() <= 20.5 * 3600 or (now.weekday() < 5 and dtime(16) <= now.time() < dtime(20))

            def fresh_sell_check(sym):
                """Re-check Alpaca right before a sell: (position or None, open orders in sym)."""
                try:
                    pos = get(f"{base}/v2/positions/{sym}")
                except Exception as exc:  # noqa: BLE001
                    if getattr(getattr(exc, "response", None), "status_code", None) == 404: pos = None
                    else: raise
                oo = get(f"{base}/v2/orders", status="open", symbols=sym, limit=50) or []
                return pos, [o for o in oo if o.get("symbol") == sym]

            def entry_cid_of(sym, meta):
                return meta.get("client_id") or f"{PFX}-{sym}-{meta['entry_date'].replace('-', '')}"

            def track(cid, sym, reason, meta, extra=None):
                if EXECUTE and not any(it["cid"] == cid for it in R["pending"]):
                    R["pending"].append({"cid": cid, "side": "sell", "sym": sym, "reason": reason,
                                         "entry_cid": entry_cid_of(sym, meta), **(extra or {})})

            # ---------------- extended-hours exit management (reprice / fallback at the open) ----------------
            if EXECUTE:
                for it in list(R.get("pending", [])):
                    x = it.get("ext")
                    if it.get("side") != "sell" or not x: continue
                    try:
                        o = get(f"{base}/v2/orders:by_client_order_id", client_order_id=it["cid"])
                        if o.get("status") not in OPEN_ST: continue
                        act = ext_exit_action(submitted_at=datetime.fromisoformat(x["submitted_at"]), now=now,
                                              reprices=int(x.get("reprices", 0)), market_open=bool(clock.get("is_open")),
                                              execution=EXEC)
                        log.info("ext-exit: %s %s status=%s limit=%s reprices=%s -> %s", it["sym"], it["cid"],
                                 o.get("status"), o.get("limit_price"), x.get("reprices"), act)
                        if act == "wait" or not lease_ok(): continue
                        if act == "reprice":
                            n = int(x.get("reprices", 0)) + 1; ncid = f"{x['base_cid']}-r{n}"
                            px = exit_order(it["sym"], o["qty"], ncid, "extended", EXEC, latest_bid(it["sym"]))["limit_price"]
                            self.broker_call("PATCH", f"/v2/orders/{o['id']}", {"limit_price": px, "client_order_id": ncid})
                            it["cid"] = ncid; x.update(reprices=n, submitted_at=now.isoformat())
                        else:
                            self.broker_call("DELETE", f"/v2/orders/{o['id']}")
                            for _ in range(10):
                                o = get(f"{base}/v2/orders/{o['id']}")
                                if o.get("status") not in OPEN_ST: break
                                time.sleep(1)
                            left = float(o.get("qty") or 0) - float(o.get("filled_qty") or 0)
                            if o.get("status") in OPEN_ST or left <= 0: continue
                            mcid = f"{x['base_cid']}-mkt"
                            submit(exit_order(it["sym"], f"{left:g}", mcid, "regular", EXEC))
                            if float(o.get("filled_qty") or 0) > 0:
                                R["pending"].append({k: v for k, v in it.items() if k != "ext"} | {"cid": mcid})
                            else:
                                it["cid"] = mcid; it.pop("ext", None)
                        persist()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("ext-exit: %s failed: %s", it.get("sym"), exc)

            # ---------------- drop positions that are gone at the broker ----------------
            for sym, meta in list(state["positions"].items()):
                if sym in positions: continue
                if any(o["symbol"] == sym and o["side"] == "buy" for o in open_orders):
                    log.info("%s: entry order still open -> keep tracking", sym); continue
                log.info("%s: tracked but no broker position -> dropping from state", sym)
                state["positions"].pop(sym)
            for sym in (positions if sleeve.is_primary else [x for x in syms if x in positions]):
                if sym not in state["positions"] and sym not in other_held:
                    log.info("%s: pre-existing/untracked position -> ignored by runner (blocks new entry)", sym)

            # ---------------- OPEN: broker-side TP/SL after the min-hold ----------------
            if "open" in events:
                for sym, meta in list(state["positions"].items()):
                    pos = positions.get(sym)
                    if not pos: continue
                    entry_d = date.fromisoformat(meta["entry_date"]); age = (today - entry_d).days
                    plpc = float(pos.get("unrealized_plpc") or 0) * 100
                    if not exit_eligible(entry_d, today, P["min_hold"]):
                        if age >= P["min_hold"] and entry_d >= today:
                            log.warning("%s: PDT guard refuses same-day exit orders", sym)
                        else:
                            log.info("%s: held age=%dd pl=%.2f%% -> min-hold not met, no exit orders", sym, age, plpc)
                        continue
                    if not market_ok:
                        log.info("%s: market closed -> broker exits wait for the open", sym); continue
                    mine = own_open_exits(open_orders, sym, PFX)
                    if mine:
                        log.info("%s: broker exits already open %s -> nothing to do", sym, [o["client_order_id"] for o in mine]); continue
                    if any(o["symbol"] == sym and o["side"] == "sell" for o in open_orders):
                        log.warning("%s: a foreign open sell order exists -> no runner exits (would double)", sym); continue
                    entry_px = float(pos.get("avg_entry_price") or 0)
                    if entry_px <= 0 and pos.get("current_price"):
                        entry_px = float(pos["current_price"]) / (1 + plpc / 100)
                    if entry_px <= 0 and -P["sl"] < plpc < P["tp"]:
                        log.warning("%s: no avg_entry_price -> cannot price exits", sym); continue
                    plan = plan_broker_exits(sym, pos["qty_available"], entry_px, P["tp"], P["sl"], today,
                                             plpc_pct=plpc, prefix=PFX)
                    log.info("%s: held age=%dd pl=%.2f%% qty=%s entry=%.2f -> %s (TP %.2f / SL %.2f)", sym, age, plpc,
                             pos["qty_available"], entry_px, plan["reason"], plan["tp"], plan["sl"])
                    if not lease_ok(): break
                    fpos, foo = fresh_sell_check(sym)
                    if fpos is None or [o for o in foo if o.get("side") == "sell"]:
                        log.warning("%s: Alpaca re-check: position=%s open sells=%d -> skip", sym, bool(fpos), len(foo)); continue
                    if float(fpos.get("qty_available") or 0) != float(pos["qty_available"]):
                        log.warning("%s: qty_available changed (%s -> %s) -> skip this event", sym, pos["qty_available"],
                                    fpos.get("qty_available")); continue
                    for body in plan["orders"]:
                        try:
                            submit(body)
                            track(body["client_order_id"], sym, plan["reason"] if plan["action"] == "market"
                                  else ("TP/SL OCO" if body.get("order_class") == "oco" else "SL stop"), meta)
                        except requests.HTTPError as exc:
                            if body.get("order_class") != "oco": raise
                            log.warning("%s: OCO rejected (%s) -> fallback: one stop for the full qty", sym,
                                        getattr(exc.response, "text", exc))
                            fb = fallback_full_stop(sym, pos["qty_available"], plan["sl"], today, PFX)
                            submit(fb); track(fb["client_order_id"], sym, "SL stop (OCO fallback)", meta)
                            break
                    meta["broker_exits"] = today.isoformat()
                    persist()
                state["last_open_event"] = today.isoformat()

            # ---------------- CLOSE: max-hold exits (cancel the runner's broker exits first) ----------------
            if "close" in events:
                for sym, meta in list(state["positions"].items()):
                    pos = positions.get(sym)
                    if not pos: continue
                    entry_d = date.fromisoformat(meta["entry_date"]); age = (today - entry_d).days
                    if age < P["max_hold"]:
                        log.info("%s: held age=%dd -> before max-hold, keep", sym, age); continue
                    if not (win(P["close_window"]) or a.ignore_hours):
                        log.info("%s: max-hold reached but outside the close window -> wait", sym); continue
                    if entry_d >= today:
                        log.warning("%s: PDT guard refuses same-day exit", sym); continue
                    if not market_ok and not (EXT["enabled"] and ext_session()): continue
                    if not lease_ok(): break
                    mine = own_open_exits(open_orders, sym, PFX)
                    for o in mine:
                        log.info("%s: cancelling broker exit %s before the max-hold sell", sym, o["client_order_id"])
                        self.broker_call("DELETE", f"/v2/orders/{o['id']}")
                    if mine and EXECUTE:
                        for _ in range(10):
                            _, foo = fresh_sell_check(sym)
                            if not [o for o in foo if o.get("side") == "sell"]: break
                            time.sleep(1)
                    fpos, foo = fresh_sell_check(sym)
                    if fpos is None:
                        log.info("%s: position gone at the broker (an exit filled) -> nothing to sell", sym); continue
                    if [o for o in foo if o.get("side") == "sell"] and EXECUTE:
                        log.warning("%s: open sell still present after cancel -> skip (would double)", sym); continue
                    qty = fpos.get("qty_available") or pos["qty_available"]
                    session = "regular" if market_ok else "extended"
                    xcid = cids(sym, today, PFX)["market"]
                    try:
                        body = exit_order(sym, qty, xcid, session, EXEC, latest_bid(sym) if session == "extended" else None)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("%s: cannot build %s exit (%s) -> skip", sym, session, exc); continue
                    reason = f"MAX_HOLD age={age}d pl={float(pos.get('unrealized_plpc') or 0) * 100:.2f}%"
                    log.info("%s: %s -> %s-session exit %s", sym, reason, session, json.dumps(body))
                    submit(body)
                    if EXECUTE:
                        meta["exit_submitted"] = now.isoformat()
                        track(xcid, sym, reason, meta, {"ext": {"base_cid": xcid, "submitted_at": now.isoformat(),
                                                               "reprices": 0}} if session == "extended" else None)
                        persist()

            # ---------------- ENTRY ----------------
            if "entry" in events:
                if not ALLOW_ENTRIES:
                    log.warning("entries disabled this pass (DB unreachable or strategy config not loaded from the DB)")
                elif not (win(P["entry_window"]) or (a.ignore_hours and not EXECUTE)):
                    log.info("outside entry window (%s min before close) -> no entries", P["entry_window"])
                else:
                    self._entries(state, R, rec, positions, open_orders, P, syms, equity, cash, nmbp, today,
                                  lease_ok, persist, submit, sleeve=sleeve, sleeve_val=sleeve_val,
                                  other_held=other_held)

            # ---------------- performance (best-effort) ----------------
            if rec and rec.enabled and R.get("run_id"):
                try:
                    mine = [positions[s] for s in state["positions"] if s in positions]  # this strategy only
                    rec.sync_positions(R["run_id"], mine, {s: m.get("entry_date") for s, m in state["positions"].items()})
                    closed = rec.realized(R["run_id"]) or {}
                    unreal = sum(float(x["unrealized_pl"]) for x in mine)
                    realized = float(closed.get("total_pnl") or 0)
                    start_eq = float(R.get("start_equity") or equity)
                    spy = None; spy_day = None
                    try:
                        sn = get(f"{DATA_URL}/v2/stocks/snapshots", symbols="SPY", feed=P["feed"])["SPY"]
                        spy = float(sn["latestTrade"]["p"]); spy_day = (sn.get("dailyBar") or {}).get("t", "")[:10] or None
                    except Exception: pass  # noqa: BLE001
                    perf = {"as_of": now.isoformat(), "account_number": self.account_no, "equity": equity, "cash": cash,
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
                        daily_key = spy_day
                    if rec.record_performance(R["run_id"], perf, daily_key=daily_key, closed=closed) and daily_key:
                        R["last_daily"] = daily_key; log.info("record: daily performance snapshot %s", daily_key)
                except Exception as exc:  # noqa: BLE001
                    log.warning("record: performance failed: %s", exc)


        primary = Sleeve(cfg.name or self.strategy, PRIMARY_PREFIX, None, True)
        extra = []
        try:
            primary.allocation_usd, extra = self.load_sleeves(acct.get("account_number") or self.account_no, primary.strategy_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("strategy allocations unavailable (%s) -> primary strategy only, whole account", exc)
        sleeves = [primary] + [sl for sl, _ in extra]
        strategy_pass(acct_state, cfg, primary, sleeves)
        for sl, scfg in extra:
            subs = acct_state.setdefault("sleeves", {})
            sub = subs[sl.strategy_name] = normalize_state(subs.get(sl.strategy_name))
            if not scfg.db_ok:
                log.warning("strategy %s: config not loaded from the DB (%s) -> skipped this pass", sl.strategy_name, scfg.error)
                continue
            try:
                strategy_pass(sub, scfg, sl, sleeves)
            except PassStop:
                raise
            except Exception as exc:  # noqa: BLE001 -- one sleeve never breaks the primary
                log.error("strategy %s pass failed: %s", sl.strategy_name, exc)
        persist()
        log.info("pass complete (%s)", "+".join(events))
        return res

    def _entries(self, state, R, rec, positions, open_orders, P, syms, equity, cash, nmbp, today,
                 lease_ok, persist, submit, sleeve=None, sleeve_val=None, other_held=frozenset()):
        get, base, log, EXECUTE = self.get, self.base, self.log, self.execute
        sleeve = sleeve or Sleeve(self.strategy, PRIMARY_PREFIX, None, True)
        snaps = get(f"{DATA_URL}/v2/stocks/snapshots", symbols=",".join(syms), feed=P["feed"])
        bars = get(f"{DATA_URL}/v2/stocks/bars", symbols=",".join(syms), timeframe="1Day",
                   start=(today - timedelta(days=40)).isoformat(), feed=P["feed"], limit=1000, adjustment="split")["bars"]
        pending_buy_val = sum(float(o.get("notional") or 0) or float(o.get("qty") or 0) * float(o.get("limit_price") or 0)
                              for o in open_orders if o["side"] == "buy")
        exposure = sum(abs(float(p["market_value"])) for p in positions.values())
        avail = min(cash, nmbp) - pending_buy_val
        if sleeve_val is None or (sleeve.is_primary and sleeve.allocation_usd is None and sleeve_val >= equity):
            # whole account (no other sleeves): exactly the pre-sleeve behaviour
            target = round(equity * P["pos_frac"], 2)
            log.info("sizing: target/position=$%.2f (%.1f%% equity) available_cash=$%.2f exposure=$%.2f",
                     target, P["pos_frac"] * 100, avail, exposure)
        else:
            own = [p for s, p in positions.items() if s in state["positions"]]
            exposure = sum(abs(float(p["market_value"])) for p in own)
            own_pending = sum(float(o.get("notional") or 0) or float(o.get("qty") or 0) * float(o.get("limit_price") or 0)
                              for o in open_orders if o["side"] == "buy" and sleeve.owns_cid(o.get("client_order_id")))
            avail = buying_power(sleeve_val=sleeve_val, own_exposure=exposure, own_pending=own_pending,
                                 account_avail=avail)
            target = round(sleeve_val * P["pos_frac"], 2)
            log.info("sizing [%s]: sleeve=$%.2f target/position=$%.2f (%.1f%% of sleeve) own_exposure=$%.2f "
                     "available=$%.2f (min of account cash and sleeve headroom)", sleeve.strategy_name, sleeve_val,
                     target, P["pos_frac"] * 100, exposure, avail)
        for sym in syms:
            sn = snaps.get(sym) or {}
            last = float((sn.get("latestTrade") or {}).get("p") or 0)
            daily = sn.get("dailyBar") or {}; prev = sn.get("prevDailyBar") or {}
            if daily.get("t", "")[:10] == today.isoformat(): prev_close = float(prev.get("c") or 0)
            else: prev_close = float(daily.get("c") or 0)
            high20 = max([b["h"] for b in bars.get(sym, [])][-20:] or [0])
            ref = prev_close if P["ref"] == "prev_close" else high20
            dip = (ref - last) / ref * 100 if ref else 0
            dip_h = (high20 - last) / high20 * 100 if high20 else 0
            sig = dip >= P["dip"]
            log.info("%s: last=%.2f prev_close=%.2f dip_vs_prev=%.2f%% | high20=%.2f dip_vs_high20=%.2f%% -> %s",
                     sym, last, prev_close, (prev_close - last) / prev_close * 100 if prev_close else 0,
                     high20, dip_h, "SIGNAL" if sig else "no")
            if not sig: continue
            if sym in other_held:
                log.info("%s: held by another strategy on this account -> skip", sym); continue
            if sym in positions or sym in state["positions"] or any(o["symbol"] == sym for o in open_orders):
                log.info("%s: already held/pending -> skip (one per symbol)", sym); continue
            if state.get("last_entry", {}).get(sym) == today.isoformat():
                log.info("%s: already entered today -> skip", sym); continue
            asset = get(f"{base}/v2/assets/{sym}")
            if not (asset.get("tradable") and asset.get("fractionable")):
                log.info("%s: not tradable/fractionable -> skip", sym); continue
            notional = target
            if P["max_exposure"] and exposure + notional > P["max_exposure"]:
                log.info("%s: would exceed exposure cap $%.0f -> skip", sym, P["max_exposure"]); continue
            if notional > avail:
                log.info("%s: notional $%.2f > available cash $%.2f -> skip (no margin)", sym, notional, avail); continue
            cid = sleeve.entry_cid(sym, today)
            busy = alpaca_symbol_busy(get, base, sym, cid)
            if busy:
                log.info("%s: %s -> skip (pre-buy safety check)", sym, busy); continue
            if not lease_ok(): break
            submit({"symbol": sym, "notional": f"{notional:.2f}", "side": "buy", "type": "market",
                    "time_in_force": "day", "client_order_id": cid})
            avail -= notional; exposure += notional
            if EXECUTE:
                state["positions"][sym] = {"entry_date": today.isoformat(), "notional": notional, "ref": ref,
                                           "dip": dip, "client_id": cid}
                state.setdefault("last_entry", {})[sym] = today.isoformat()
                R["pending"].append({"cid": cid, "side": "buy", "sym": sym})
                persist()
                if rec and R.get("run_id"): rec.entry_submitted(R["run_id"], sym, cid, notional, dip, ref)

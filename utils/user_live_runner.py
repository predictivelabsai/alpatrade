"""One USER's own live strategy on that user's own Alpaca account: one process per activation.

Julian approved (2026-10-11): after a user confirms Activate Live (web:
engine/leaderboard/activate.py -> alpatrade.user_strategy_activations, status 'pending_runner'),
a dedicated process trades that user's account with that user's strategy.

Design (one OS process per activation, started by scripts/user_live_supervisor.py):
  * Separate process per (user, strategy): own config, keys, allocation, state dir, log file,
    flock, DB lease key and alpatrade.runs row. Nothing is shared with the operator's
    scheduler (scripts/live_btd_scheduler.py), so an exception, hang or slow API call on a user
    account cannot block or delay Julian's Mag-7 / Semi-7 orders: they are different processes.
  * Same event engine as the operator runner (utils/live_btd_runner.Runner._run via the
    plan_sleeves / entry_gate / pre_order hooks, whose defaults are the operator behaviour), so
    exits, idempotent client_order_ids, pre-buy broker checks and fill recording are identical.
  * Config comes ONLY from the user's own rows: alpatrade.user_strategy_configs.params (their
    cloned/edited universe, dip, TP/SL, holds, pos_frac). It never reads
    alpatrade.strategy_configs / strategy_allocations or DEFAULT_PARAMS for strategy values;
    missing required params -> the activation is refused.
  * Orders: the user's decrypted keys, the user's ``u<6hex>`` prefix; sizing as a fixed sleeve
    (allocation_usd): every buy re-checked at order time against min(account cash,
    non-marginable buying power) minus pending buys AND the sleeve headroom (allocation - own
    exposure - own pending); never margin; no order when cash is short.
  * Single order placer: the per-activation lease (key ``user-btd:<account>:<prefix>``) uses the
    same primary > backup > tertiary protocol as the operator runner, AND a user process only acts
    on the instance that currently holds the operator lease (``btd-live:<operator account>``,
    read-only peek). So at any moment at most one machine places orders for every account.
  * Kill switches: env USER_LIVE_TRADING_ENABLED must be "1" (else the supervisor runs nothing
    and any running process stops submitting); activation status 'paused' -> no new entries
    (exits keep managing open positions); 'deactivated' -> the supervisor stops the process.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from utils.live_btd_config import DEFAULT_EXECUTION, ConfigResult, make_engine
from utils.live_btd_runner import PassStop, Runner, state_dir
from utils.live_btd_state import LeaseResult, RunnerStateStore
from utils.live_btd_store import STRATEGY_SLUG
from utils.strategy_allocation import Sleeve

FLAG = "USER_LIVE_TRADING_ENABLED"
RUNNABLE = ("pending_runner", "active", "paused")
DRYRUN_TEST = "dryrun_test"      # paper dry-run harness only: never runnable live, ignored by the supervisor
REQUIRED = ("symbols", "dip", "tp", "sl", "max_hold", "pos_frac")
# execution plumbing only (not strategy choices); the user's params override each one
NEUTRAL = {"min_hold": 0, "max_exposure": 0.0, "ref": "high20", "feed": "iex",
           "entry_window": "15-5", "close_window": "15-2"}


def flag_on(env: Optional[dict] = None) -> bool:
    return str((env if env is not None else os.environ).get(FLAG, "")).strip() == "1"


def lease_key(account_number: str, prefix: str) -> str:
    return f"user-btd:{account_number}:{prefix}"


def user_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The user's own params -> runner params. Raises ValueError if a strategy value is missing."""
    raw = dict(raw or {})
    missing = [k for k in REQUIRED if raw.get(k) in (None, "", [])]
    if missing:
        raise ValueError(f"user strategy is missing {', '.join(missing)}")
    p = {**NEUTRAL, **{k: raw[k] for k in NEUTRAL if raw.get(k) is not None}}
    syms = raw["symbols"]
    if isinstance(syms, str):
        syms = [x.strip() for x in syms.split(",")]
    p["symbols"] = [str(x).upper() for x in syms if str(x).strip()][:25]
    for k in ("dip", "tp", "sl", "pos_frac"):
        p[k] = float(raw[k])
    p["max_hold"] = int(raw["max_hold"]); p["min_hold"] = int(p["min_hold"])
    for k in ("dip", "tp", "sl"):          # percent units like the operator config (0.03 -> 3.0)
        if 0 < p[k] < 0.5:
            p[k] = round(p[k] * 100, 6)
    if not (0 < p["pos_frac"] <= 1):
        raise ValueError("pos_frac must be in (0, 1]")
    if not p["symbols"]:
        raise ValueError("user strategy has no symbols")
    return p


@dataclass
class Activation:
    id: int
    user_id: str
    email: str
    user_strategy_id: int
    account_number: str
    cid_prefix: str
    allocation_usd: float
    status: str
    params: Dict[str, Any]
    execution: Dict[str, Any]
    name: str


def load_activation(engine, activation_id: int) -> Optional[Activation]:
    from sqlalchemy import text
    with engine.connect() as c:
        r = c.execute(text("""
            SELECT a.id, a.user_id::text AS user_id, u.email, a.user_strategy_id, a.account_ref, a.cid_prefix,
                   a.allocation_usd, a.status, c.params, c.execution, s.name
            FROM alpatrade.user_strategy_activations a
            JOIN alpatrade.users u ON u.user_id = a.user_id
            JOIN alpatrade.user_strategy_configs c ON c.user_strategy_id = a.user_strategy_id AND c.user_id = a.user_id
            JOIN alpatrade.user_strategies s ON s.id = a.user_strategy_id AND s.user_id = a.user_id
            WHERE a.id = :i AND a.mode = 'live'"""), {"i": int(activation_id)}).mappings().first()
    if not r:
        return None
    return Activation(int(r["id"]), r["user_id"], r["email"], int(r["user_strategy_id"]), str(r["account_ref"]),
                      str(r["cid_prefix"]), float(r["allocation_usd"]), str(r["status"]), dict(r["params"] or {}),
                      dict(r["execution"] or {}), str(r["name"] or ""))


def load_status(engine, activation_id: int) -> Optional[str]:
    from sqlalchemy import text
    with engine.connect() as c:
        return c.execute(text("SELECT status FROM alpatrade.user_strategy_activations WHERE id = :i"),
                         {"i": int(activation_id)}).scalar()


def trading_credentials(engine, user_id: str, account_number: str) -> Optional[dict]:
    """Decrypt the user's OWN live keys for the user's OWN linked account. Never log the result."""
    from sqlalchemy import text
    from engine.auth import decrypt_key
    with engine.connect() as c:
        r = c.execute(text("""SELECT api_key_enc, secret_key_enc FROM alpatrade.user_live_broker_accounts
                              WHERE user_id = CAST(:u AS UUID) AND account_number = :a AND is_active"""),
                      {"u": str(user_id), "a": str(account_number)}).first()
    if not r:
        return None
    return {"api_key": decrypt_key(bytes(r[0])), "secret_key": decrypt_key(bytes(r[1]))}


def paper_credentials(engine, user_id: str) -> Optional[dict]:
    """The user's own PAPER keys (alpatrade.user_accounts) for paper-mode testing of this runner."""
    from sqlalchemy import text
    from engine.auth import decrypt_key
    with engine.connect() as c:
        r = c.execute(text("""SELECT alpaca_api_key_enc, alpaca_secret_key_enc FROM alpatrade.user_accounts
                              WHERE user_id = CAST(:u AS UUID) AND is_active AND alpaca_api_key_enc IS NOT NULL
                              ORDER BY created_at LIMIT 1"""), {"u": str(user_id)}).first()
    if not r:
        return None
    k = lambda v: decrypt_key(v.encode() if isinstance(v, str) else bytes(v))  # noqa: E731
    return {"api_key": k(r[0]), "secret_key": k(r[1])}


def config_version(act: Activation) -> int:
    import json
    import zlib
    return zlib.crc32(json.dumps([act.params, act.execution, act.allocation_usd], sort_keys=True,
                                 default=str).encode())


def user_config(act: Activation) -> ConfigResult:
    import copy
    ex = copy.deepcopy(DEFAULT_EXECUTION)          # order mechanics only (market/day exits)
    for sect, vals in (act.execution or {}).items():
        if isinstance(vals, dict):
            ex.setdefault(sect, {}).update(vals)
    ex.setdefault("extended_hours_exit", {})["enabled"] = False
    p = user_params(act.params)
    return ConfigResult(params=p, execution=ex, sources={k: "user" for k in p}, source="user_strategy_configs",
                        db_ok=True, config_id=act.user_strategy_id, version=config_version(act), name=f"user:{act.cid_prefix}",
                        meta={"activation_id": act.id, "user_id": act.user_id})


class _GatedStore:
    """Per-activation lease that only acts while this instance holds the operator lease."""

    def __init__(self, inner: RunnerStateStore, operator_holder):
        self.inner, self.operator_holder = inner, operator_holder

    def acquire(self, *a, **k) -> LeaseResult:
        holder = self.operator_holder()
        if holder != self.inner.instance:
            peek = self.inner.peek()
            return LeaseResult(ok=True, act=False, state=peek.state, version=peek.version, missing=peek.missing,
                               reason=f"operator lease held by {holder or 'nobody'}; user runners act only on the "
                                      f"single order placer")
        return self.inner.acquire(*a, **k)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class UserRunner(Runner):
    def __init__(self, a, activation_id: int, log: Optional[logging.Logger] = None, *, engine=None,
                 env: Optional[dict] = None, creds_fn=None, operator_holder=None, paper: bool = False):
        from dotenv import dotenv_values
        from utils.live_btd_runner import ENV_PATH
        self.a = a
        self.log = log or logging.getLogger("btd.user")
        self.execute = bool(a.live)
        if self.execute and a.ignore_hours:
            raise PassStop("--ignore-hours is dry-run only.")
        base_env = {**dotenv_values(ENV_PATH), **os.environ} if env is None else dict(env)
        self.env = {k: v for k, v in base_env.items() if not k.startswith("ALPACA_LIVE_API")
                    and not k.startswith("ALPACA_LIVE_SECRET")}           # never the operator's keys
        self.db_url = base_env.get("DATABASE_URL")
        if base_env.get("ENCRYPTION_KEY") and not os.environ.get("ENCRYPTION_KEY"):
            # engine.auth reads the Fernet key from os.environ; systemd/launchd only have it in .env
            os.environ["ENCRYPTION_KEY"] = base_env["ENCRYPTION_KEY"]
        self._eng = engine or (make_engine(self.db_url) if self.db_url else None)
        if self._eng is None:
            raise PassStop("DATABASE_URL not set")
        self.activation_id = int(activation_id)
        act = load_activation(self._eng, self.activation_id)
        if not act:
            raise PassStop(f"activation {activation_id} not found")
        self.act = act
        self.operator_account = base_env.get("ALPACA_LIVE_ACCOUNT")
        if act.account_number == str(self.operator_account or ""):
            raise PassStop("user activations never run on the operator account (its sleeves are managed by "
                           "/live/allocations)")
        self.paper = bool(paper)
        if creds_fn is None:
            creds_fn = ((lambda: paper_credentials(self._eng, act.user_id)) if paper else
                        (lambda: trading_credentials(self._eng, act.user_id, act.account_number)))
        creds = creds_fn()
        if not creds:
            raise PassStop("the user's " + ("paper keys are" if paper else "live link is") + " missing or disconnected")
        self.headers = {"APCA-API-KEY-ID": creds["api_key"], "APCA-API-SECRET-KEY": creds["secret_key"]}
        self.base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.account_no = act.account_number
        self.user_email = act.email
        self.role = a.role or base_env.get("BTD_ROLE") or "primary"
        import socket
        self.instance = a.instance or base_env.get("BTD_INSTANCE") or socket.gethostname()
        self.strategy = f"user:{act.cid_prefix}"
        self.sleeve = Sleeve(self.strategy, act.cid_prefix, float(act.allocation_usd), False)
        self.here = os.path.join(state_dir(), "users", act.cid_prefix + ("-paper" if paper else ""))
        os.makedirs(self.here, exist_ok=True)
        self.state_path = os.path.join(self.here, "state.json")
        self._store = None; self._store_acct = None
        self._operator_holder = operator_holder or self._peek_operator_holder

    def __repr__(self):
        return f"UserRunner(activation={self.activation_id}, prefix={self.act.cid_prefix})"

    # ---------------------------------------------------------------- config (user's only)
    def cli_overrides(self):
        return {}

    def load_config(self) -> ConfigResult:
        act = load_activation(self._eng, self.activation_id) or self.act
        self.act = act
        cfg = user_config(act)
        self.log_config(cfg, "loaded")
        return cfg

    def load_sleeves(self, account_number, primary_name):
        return None, []                                # never the operator's allocations table

    def plan_sleeves(self, acct, cfg):
        self.sleeve.allocation_usd = float(self.act.allocation_usd)
        return self.sleeve, []

    # ---------------------------------------------------------------- lease
    def _peek_operator_holder(self) -> Optional[str]:
        if not self.operator_account:
            return None
        from sqlalchemy import text
        try:
            with self._eng.connect() as c:
                r = c.execute(text("SELECT lease_holder FROM alpatrade.live_runner_state WHERE runner_key = :k "
                                   "AND lease_expires_at > now()"),
                              {"k": f"{STRATEGY_SLUG}:{self.operator_account}"}).first()
            return r[0] if r else None
        except Exception:  # noqa: BLE001
            return None

    def store(self, account_number):
        if self._store is None:
            from utils.live_btd_runner import code_version
            key = lease_key(self.act.account_number, self.act.cid_prefix) + (":paper" if self.paper else "")
            inner = RunnerStateStore(self.db_url, key,
                                     instance=self.instance, role=self.role, log=self.log, engine=self._eng,
                                     lease_ttl_s=self.a.lease_ttl_min * 60, takeover_s=self.a.takeover_min * 60,
                                     code_version=code_version())
            self._store = _GatedStore(inner, self._operator_holder)
        return self._store

    def ensure_seeded(self) -> bool:
        st = self.store(self.account_no).inner
        return st.seed({"positions": {}, "rec": {"pending": []}}, None)

    def verify_account(self) -> str:
        """The keys must belong to the activation's account (live mode); returns the account number."""
        try:
            got = str(self.get(f"{self.base}/v2/account").get("account_number") or "")
        except Exception as exc:  # noqa: BLE001 -- never echo headers
            code = getattr(getattr(exc, "response", None), "status_code", None)
            raise PassStop(f"Alpaca rejected the user's keys (HTTP {code})" if code in (401, 403)
                           else f"Alpaca account check failed ({type(exc).__name__})") from None
        if not self.paper and got != self.act.account_number:
            raise PassStop("the user's keys do not belong to the activated account")
        self._verified = got
        return got

    # ---------------------------------------------------------------- kill switches
    def _status(self) -> Optional[str]:
        st = load_status(self._eng, self.activation_id)
        if st == DRYRUN_TEST and self.paper and not self.execute:
            return "active"
        return st

    def version(self) -> Optional[int]:
        act = load_activation(self._eng, self.activation_id)
        return config_version(act) if act else None

    def entry_gate(self) -> Optional[str]:
        if not flag_on(self.env):
            return f"{FLAG} is not 1 (global kill switch)"
        st = self._status()
        if st == "paused":
            return "paused by the user"
        if st not in RUNNABLE:
            return f"activation is {st}"
        return None

    def pre_order(self, body) -> None:
        if not self.paper and getattr(self, "_verified", None) != self.act.account_number:
            raise PassStop("account not verified for this activation")
        if not flag_on(self.env):
            raise PassStop(f"{FLAG} turned off")
        st = self._status()
        if st not in RUNNABLE or (st == "paused" and body.get("side") == "buy"):
            raise PassStop(f"activation {st} -> no order")
        if not self.sleeve.owns_cid(body.get("client_order_id")):
            raise PassStop("refusing an order without this user's client_order_id prefix")
        if body.get("side") == "buy" and float(body.get("notional") or 0) > float(self.act.allocation_usd) + 1e-6:
            raise PassStop("buy notional above the user's allocation")

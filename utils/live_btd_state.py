"""Authoritative state + leader lease for the live BTD runner (HP primary, Mac backup).

Why: two machines can run ``scripts/live_btd_minhold.py`` against the same real-money
Alpaca account (the HP workstation = primary, Mac.home = backup). They must never both
trade and neither may lose track of the positions the runner owns. The authoritative
runner state therefore lives in AlpaTrade Postgres, not in a machine-local file:

* ``alpatrade.live_runner_state``      one row per runner (``runner_key``): the JSON state
  (owned positions, pending orders, last entries, run id + recording metadata), a
  monotonically increasing ``version`` and the leader **lease** (holder, host, role,
  acquired_at, expires_at).
* ``alpatrade.live_runner_heartbeats`` one row per (runner, instance): last live pass,
  last pass that acted, the decision taken. This is the "is the primary alive?" signal.

Per-pass protocol (``RunnerStateStore.acquire``), all inside ONE transaction that holds
``SELECT ... FOR UPDATE`` on the state row, using the DB clock (no host clock skew):

1. lease held by someone else and not expired            -> stand by.
2. role=primary                                          -> act (take / renew the lease).
3. role=backup and a primary heartbeat is fresh (< takeover, default 12 min)
                                                         -> stand by; if the backup holds
                                                            the lease it hands it back
                                                            (expires it) so the primary
                                                            resumes on its next pass.
4. role=backup, backup already holds the live lease      -> act (renew).
5. role=backup, primary stale/absent, lease free/expired -> act (take over), except during
   the first ``takeover`` minutes after 09:00 ET (primary gets its first passes of the day).

Every live pass (acting or not) upserts its heartbeat in the same transaction. The lease
TTL (default 8 min) is shorter than the takeover threshold (12 min), so a dead holder's
lease has always expired before the backup considers the primary stale. The acting
instance only submits orders while its *local monotonic* lease deadline (TTL minus a
safety margin, measured from before the acquire query) has not passed, and writes the
state back (``save``) only while it still holds the lease.

Dry run (default) only *reads* the row (``peek``) and logs what it would decide; it never
takes the lease or writes a heartbeat, so a dry run on the primary can never mask a dead
live runner.

DB unreachable (``degraded_policy``): the instance cannot know whether another instance
is acting, so it NEVER opens positions. It may still EXIT positions from its local cache,
and only if its last decided pass was an acting (lease-holding) pass. A standby instance
does nothing. Double exits are harmless: exit orders use the deterministic client id
``btdx-<SYM>-<YYYYMMDD>`` (Alpaca rejects the duplicate) and sell ``qty_available`` of
an existing position only.

Extra safety net before every buy (``alpaca_symbol_busy``): a fresh per-symbol Alpaca
check for an existing position, an open order, or an order that already used today's
deterministic client id ``btd-<SYM>-<YYYYMMDD>``. Any lookup error fails closed (no buy).
"""
from __future__ import annotations

import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

LOG = logging.getLogger("btd.state")
ET = ZoneInfo("America/New_York")

DEFAULT_LEASE_TTL_S = 8 * 60
DEFAULT_TAKEOVER_S = 12 * 60
LEASE_SAFETY_MARGIN_S = 60
SESSION_GATE = (dtime(9, 0), dtime(16, 5))   # ET, Mon-Fri; passes outside are no-ops

DDL = """
CREATE TABLE IF NOT EXISTS alpatrade.live_runner_state (
    runner_key        VARCHAR(96) PRIMARY KEY,
    run_id            VARCHAR(64),
    state             JSONB NOT NULL DEFAULT '{}'::jsonb,
    version           BIGINT NOT NULL DEFAULT 0,
    lease_holder      VARCHAR(128),
    lease_host        VARCHAR(255),
    lease_role        VARCHAR(16),
    lease_acquired_at TIMESTAMPTZ,
    lease_expires_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by        VARCHAR(128)
);
CREATE TABLE IF NOT EXISTS alpatrade.live_runner_heartbeats (
    runner_key     VARCHAR(96) NOT NULL,
    instance       VARCHAR(128) NOT NULL,
    host           VARCHAR(255),
    role           VARCHAR(16),
    mode           VARCHAR(16),
    last_pass_at   TIMESTAMPTZ,
    last_acted_at  TIMESTAMPTZ,
    last_decision  VARCHAR(32),
    last_detail    TEXT,
    code_version   VARCHAR(64),
    PRIMARY KEY (runner_key, instance)
);
"""


def empty_state(run_id: Optional[str] = None) -> Dict[str, Any]:
    return {"positions": {}, "last_entry": {}, "rec": {"run_id": run_id, "pending": []}}


def normalize_state(s: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    s = dict(s or {})
    s.setdefault("positions", {})
    s.setdefault("last_entry", {})
    rec = s.setdefault("rec", {})
    rec.setdefault("pending", [])
    return s


# ----------------------------------------------------------------------- policy (pure)
@dataclass
class Decision:
    act: bool
    reason: str
    release: bool = False       # backup hands the lease back to the primary
    code: str = "standby"       # act | renew | takeover | standby | handback | holdoff


def in_session_gate(now_et: datetime) -> bool:
    """Mon-Fri 09:00 <= t < 16:05 ET. Holidays pass the gate; /v2/clock handles them."""
    return now_et.weekday() < 5 and SESSION_GATE[0] <= now_et.time() < SESSION_GATE[1]


def in_backup_holdoff(now_et: datetime, takeover_s: float = DEFAULT_TAKEOVER_S) -> bool:
    """First `takeover` minutes after 09:00 ET: the primary's last heartbeat is from the
    previous session, so it would look stale; give it its first passes of the day."""
    start = now_et.replace(hour=9, minute=0, second=0, microsecond=0)
    return start <= now_et < start + timedelta(seconds=takeover_s)


def decide(*, me: str, role: str, now: datetime, lease_holder: Optional[str],
           lease_expires_at: Optional[datetime], primary_last_pass: Optional[datetime],
           takeover_s: float = DEFAULT_TAKEOVER_S, holdoff: bool = False) -> Decision:
    lease_live = bool(lease_holder) and lease_expires_at is not None and lease_expires_at > now
    mine = lease_live and lease_holder == me
    if lease_live and not mine:
        return Decision(False, f"lease held by {lease_holder} until {lease_expires_at.isoformat()}")
    if role == "primary":
        return Decision(True, "primary: renewing lease" if mine else "primary: lease free/expired -> taking it",
                        code="renew" if mine else "act")
    primary_fresh = primary_last_pass is not None and (now - primary_last_pass).total_seconds() < takeover_s
    if primary_fresh:
        age = int((now - primary_last_pass).total_seconds())
        if mine:
            return Decision(False, f"backup: primary is back (heartbeat {age}s old) -> handing lease back",
                            release=True, code="handback")
        return Decision(False, f"backup: primary heartbeat fresh ({age}s old) -> stand by")
    if mine:
        return Decision(True, "backup: already holds the lease, primary still stale -> renewing", code="renew")
    if holdoff:
        return Decision(False, "backup: session-start hold-off (primary gets the first passes)", code="holdoff")
    seen = primary_last_pass.isoformat() if primary_last_pass else "never"
    return Decision(True, f"backup: primary heartbeat stale (last {seen}) -> taking over", code="takeover")


def degraded_policy(cache: Dict[str, Any]) -> Dict[str, Any]:
    """What an instance may do when the DB (lease + authoritative state) is unreachable."""
    acted = bool(cache.get("acted_last"))
    return {"entries": False, "exits": acted,
            "reason": ("DB unreachable: no entries; exits allowed for positions in the local cache "
                       "because this instance held the lease on its last decided pass") if acted else
                      ("DB unreachable and this instance was not the lease holder on its last decided "
                       "pass -> no trading at all")}


def merge_dirty_cache(db_state: Dict[str, Any], cache: Dict[str, Any]) -> Dict[str, Any]:
    """Fold changes made while the DB was unreachable (or a failed save) into the DB state.
    Positions/pending are unioned (by symbol / client order id); stale entries self-heal on
    the next pass (tracked-but-not-held positions are dropped, final orders are recorded)."""
    s = normalize_state(json.loads(json.dumps(db_state)))
    c = normalize_state(cache)
    for sym, meta in c["positions"].items():
        s["positions"].setdefault(sym, meta)
    have = {it.get("cid") for it in s["rec"]["pending"]}
    for it in c["rec"]["pending"]:
        if it.get("cid") not in have:
            s["rec"]["pending"].append(it)
    for sym, d in c["last_entry"].items():
        if d > s["last_entry"].get(sym, ""):
            s["last_entry"][sym] = d
    return s


# ------------------------------------------------------------------ Alpaca safety net
def _status(exc: Exception) -> Optional[int]:
    return getattr(getattr(exc, "response", None), "status_code", None)


def alpaca_symbol_busy(get: Callable[..., Any], base: str, sym: str, cid: str) -> Optional[str]:
    """Return a reason not to buy `sym` (fresh Alpaca state), or None. Fails closed."""
    try:
        get(f"{base}/v2/positions/{sym}")
        return "Alpaca already holds a position"
    except Exception as exc:  # noqa: BLE001
        if _status(exc) != 404:
            return f"position check failed ({exc}) -> fail closed"
    try:
        if any(o.get("symbol") == sym for o in get(f"{base}/v2/orders", status="open", symbols=sym, limit=50) or []):
            return "Alpaca has an open order"
    except Exception as exc:  # noqa: BLE001
        return f"open-order check failed ({exc}) -> fail closed"
    try:
        o = get(f"{base}/v2/orders:by_client_order_id", client_order_id=cid)
        if o:
            return f"order {cid} already exists (status {o.get('status')})"
    except Exception as exc:  # noqa: BLE001
        if _status(exc) != 404:
            return f"client-order-id check failed ({exc}) -> fail closed"
    return None


_CID = re.compile(r"^btd-([A-Z.]+)-(\d{8})$")


def adopt_runner_position(get: Callable[..., Any], base: str, sym: str) -> Optional[Dict[str, Any]]:
    """A basket position the state doesn't know: adopt it only if its latest filled order is
    a runner entry (client id btd-<SYM>-<YYYYMMDD>). Anything else stays pre-existing."""
    try:
        orders = get(f"{base}/v2/orders", status="closed", symbols=sym, limit=50, direction="desc") or []
    except Exception:  # noqa: BLE001
        return None
    for o in orders:
        if o.get("symbol") != sym or float(o.get("filled_qty") or 0) <= 0:
            continue
        m = _CID.match(o.get("client_order_id") or "")
        if o.get("side") == "buy" and m and m.group(1) == sym:
            d = m.group(2)
            return {"entry_date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "client_id": o["client_order_id"],
                    "notional": float(o.get("notional") or 0) or None, "adopted": True}
        return None  # latest fill is not a runner entry -> pre-existing
    return None


# ------------------------------------------------------------------------ DB store
@dataclass
class LeaseResult:
    ok: bool                     # DB reachable and the protocol completed
    act: bool = False
    reason: str = ""
    state: Optional[Dict[str, Any]] = None
    version: Optional[int] = None
    run_id: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    deadline_mono: float = 0.0   # local monotonic deadline for submitting orders
    missing: bool = False        # no state row (seed it first)
    info: Dict[str, Any] = field(default_factory=dict)


class RunnerStateStore:
    def __init__(self, database_url: Optional[str], runner_key: str, instance: Optional[str] = None,
                 role: str = "primary", host: Optional[str] = None, log: logging.Logger = LOG,
                 engine=None, lease_ttl_s: float = DEFAULT_LEASE_TTL_S,
                 takeover_s: float = DEFAULT_TAKEOVER_S, code_version: Optional[str] = None):
        if role not in ("primary", "backup"):
            raise ValueError("role must be primary or backup")
        self.log, self.runner_key, self.role = log, runner_key, role
        self.host = host or socket.gethostname()
        self.instance = instance or self.host
        self.lease_ttl_s, self.takeover_s, self.code_version = lease_ttl_s, takeover_s, code_version
        self._engine = engine
        self._schema_ok = False
        if self._engine is None and database_url:
            from sqlalchemy import create_engine
            self._engine = create_engine(
                database_url, pool_pre_ping=True, pool_size=1, max_overflow=0,
                connect_args={"connect_timeout": 5, "application_name": f"alpatrade-live-btd-{self.instance}"[:63],
                              "options": "-c statement_timeout=15000 -c lock_timeout=5000"})

    @property
    def configured(self) -> bool:
        return self._engine is not None

    def ensure_schema(self):
        if self._schema_ok:
            return
        from sqlalchemy import text
        with self._engine.begin() as c:
            c.execute(text("CREATE SCHEMA IF NOT EXISTS alpatrade"))
            for stmt in [s for s in DDL.split(";") if s.strip()]:
                c.execute(text(stmt))
        self._schema_ok = True

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _state_of(v) -> Dict[str, Any]:
        return normalize_state(json.loads(v) if isinstance(v, str) else v)

    def _primary_last_pass(self, c, text):
        return c.execute(text("""
            SELECT MAX(last_pass_at) FROM alpatrade.live_runner_heartbeats
             WHERE runner_key = :k AND role = 'primary' AND instance <> :me AND mode = 'live'
        """), {"k": self.runner_key, "me": self.instance}).scalar()

    # ------------------------------------------------------------------ protocol
    def acquire(self, now: Optional[datetime] = None, now_et: Optional[datetime] = None) -> LeaseResult:
        """One transaction: lock row, decide, take/renew/release lease, heartbeat."""
        from sqlalchemy import text
        t0 = time.monotonic()
        try:
            self.ensure_schema()
            with self._engine.begin() as c:
                db_now = c.execute(text("SELECT now()")).scalar()
                now = now or db_now
                row = c.execute(text("""
                    SELECT run_id, state, version, lease_holder, lease_expires_at
                      FROM alpatrade.live_runner_state WHERE runner_key = :k FOR UPDATE
                """), {"k": self.runner_key}).first()
                if row is None:
                    self._heartbeat(c, text, now, False, "missing", "no state row; seed it (--seed-state)")
                    return LeaseResult(ok=True, act=False, missing=True,
                                       reason=f"no state row for {self.runner_key}; seed it first (--seed-state)")
                prim = self._primary_last_pass(c, text)
                holdoff = self.role == "backup" and in_backup_holdoff((now_et or now.astimezone(ET)), self.takeover_s)
                d = decide(me=self.instance, role=self.role, now=now, lease_holder=row.lease_holder,
                           lease_expires_at=row.lease_expires_at, primary_last_pass=prim,
                           takeover_s=self.takeover_s, holdoff=holdoff)
                expires = None
                if d.act:
                    expires = now + timedelta(seconds=self.lease_ttl_s)
                    c.execute(text("""
                        UPDATE alpatrade.live_runner_state
                           SET lease_acquired_at = CASE WHEN lease_holder = :me AND lease_expires_at > :now
                                                        THEN lease_acquired_at ELSE :now END,
                               lease_holder = :me, lease_host = :host, lease_role = :role,
                               lease_expires_at = :exp
                         WHERE runner_key = :k
                    """), {"k": self.runner_key, "me": self.instance, "host": self.host,
                           "role": self.role, "now": now, "exp": expires})
                elif d.release:
                    c.execute(text("""
                        UPDATE alpatrade.live_runner_state SET lease_expires_at = :now
                         WHERE runner_key = :k AND lease_holder = :me
                    """), {"k": self.runner_key, "me": self.instance, "now": now})
                self._heartbeat(c, text, now, d.act, d.code, d.reason)
                return LeaseResult(
                    ok=True, act=d.act, reason=d.reason, state=self._state_of(row.state),
                    version=int(row.version), run_id=row.run_id, lease_expires_at=expires,
                    deadline_mono=(t0 + self.lease_ttl_s - LEASE_SAFETY_MARGIN_S) if d.act else 0.0,
                    info={"lease_holder": row.lease_holder, "lease_expires_at": row.lease_expires_at,
                          "primary_last_pass": prim, "decision": d.code, "db_now": db_now})
        except Exception as exc:  # noqa: BLE001
            return LeaseResult(ok=False, reason=f"DB unreachable: {str(exc).splitlines()[0][:200]}")

    def _heartbeat(self, c, text, now, acted: bool, code: str, detail: str):
        c.execute(text("""
            INSERT INTO alpatrade.live_runner_heartbeats
                   (runner_key, instance, host, role, mode, last_pass_at, last_acted_at,
                    last_decision, last_detail, code_version)
            VALUES (:k, :me, :host, :role, 'live', :now, CASE WHEN :acted THEN CAST(:now AS TIMESTAMPTZ) END,
                    :code, :detail, :ver)
            ON CONFLICT (runner_key, instance) DO UPDATE SET
                   host = EXCLUDED.host, role = EXCLUDED.role, mode = 'live',
                   last_pass_at = EXCLUDED.last_pass_at,
                   last_acted_at = COALESCE(EXCLUDED.last_acted_at, alpatrade.live_runner_heartbeats.last_acted_at),
                   last_decision = EXCLUDED.last_decision, last_detail = EXCLUDED.last_detail,
                   code_version = EXCLUDED.code_version
        """), {"k": self.runner_key, "me": self.instance, "host": self.host, "role": self.role,
               "now": now, "acted": acted, "code": code, "detail": detail[:500], "ver": self.code_version})

    def peek(self, now: Optional[datetime] = None, now_et: Optional[datetime] = None) -> LeaseResult:
        """Read-only (dry run): state + what `acquire` would decide. Writes nothing."""
        from sqlalchemy import text
        try:
            with self._engine.connect() as c:
                db_now = c.execute(text("SELECT now()")).scalar()
                now = now or db_now
                try:
                    row = c.execute(text("""
                        SELECT run_id, state, version, lease_holder, lease_expires_at
                          FROM alpatrade.live_runner_state WHERE runner_key = :k
                    """), {"k": self.runner_key}).first()
                except Exception:  # noqa: BLE001 - table not created yet
                    row = None
                if row is None:
                    return LeaseResult(ok=True, missing=True, reason=f"no state row for {self.runner_key}")
                prim = self._primary_last_pass(c, text)
                holdoff = self.role == "backup" and in_backup_holdoff((now_et or now.astimezone(ET)), self.takeover_s)
                d = decide(me=self.instance, role=self.role, now=now, lease_holder=row.lease_holder,
                           lease_expires_at=row.lease_expires_at, primary_last_pass=prim,
                           takeover_s=self.takeover_s, holdoff=holdoff)
                hbs = [dict(r._mapping) for r in c.execute(text("""
                    SELECT instance, host, role, last_pass_at, last_acted_at, last_decision
                      FROM alpatrade.live_runner_heartbeats WHERE runner_key = :k ORDER BY instance
                """), {"k": self.runner_key})]
                return LeaseResult(ok=True, act=d.act, reason=d.reason, state=self._state_of(row.state),
                                   version=int(row.version), run_id=row.run_id,
                                   info={"lease_holder": row.lease_holder, "lease_expires_at": row.lease_expires_at,
                                         "primary_last_pass": prim, "decision": d.code, "heartbeats": hbs,
                                         "db_now": db_now})
        except Exception as exc:  # noqa: BLE001
            return LeaseResult(ok=False, reason=f"DB unreachable: {str(exc).splitlines()[0][:200]}")

    def save(self, state: Dict[str, Any], renew: bool = True) -> bool:
        """Write state back iff we still hold an unexpired lease (and renew it)."""
        from sqlalchemy import text
        try:
            with self._engine.begin() as c:
                res = c.execute(text("""
                    UPDATE alpatrade.live_runner_state
                       SET state = CAST(:s AS JSONB), run_id = COALESCE(:rid, run_id),
                           version = version + 1, updated_at = now(), updated_by = :me,
                           lease_expires_at = CASE WHEN :renew THEN GREATEST(lease_expires_at, now() + make_interval(secs => :ttl))
                                                   ELSE lease_expires_at END
                     WHERE runner_key = :k AND lease_holder = :me AND lease_expires_at > now()
                """), {"k": self.runner_key, "me": self.instance, "s": json.dumps(state, default=str),
                       "rid": (state.get("rec") or {}).get("run_id"), "renew": renew,
                       "ttl": float(self.lease_ttl_s)})
                if res.rowcount != 1:
                    self.log.error("state save refused: %s no longer holds the lease for %s",
                                   self.instance, self.runner_key)
                    return False
                return True
        except Exception as exc:  # noqa: BLE001
            self.log.error("state save failed (DB): %s", str(exc).splitlines()[0][:200])
            return False

    def seed(self, state: Dict[str, Any], run_id: Optional[str], force: bool = False) -> bool:
        """Create the state row (no lease). Refuses to overwrite unless force."""
        from sqlalchemy import text
        self.ensure_schema()
        with self._engine.begin() as c:
            exists = c.execute(text("SELECT version FROM alpatrade.live_runner_state WHERE runner_key = :k FOR UPDATE"),
                               {"k": self.runner_key}).first()
            if exists and not force:
                return False
            if exists:
                c.execute(text("""UPDATE alpatrade.live_runner_state SET state = CAST(:s AS JSONB), run_id = :rid,
                                  version = version + 1, updated_at = now(), updated_by = :me WHERE runner_key = :k"""),
                          {"k": self.runner_key, "s": json.dumps(state, default=str), "rid": run_id,
                           "me": f"seed:{self.instance}"})
            else:
                c.execute(text("""INSERT INTO alpatrade.live_runner_state (runner_key, run_id, state, version, updated_by)
                                  VALUES (:k, :rid, CAST(:s AS JSONB), 1, :me)"""),
                          {"k": self.runner_key, "s": json.dumps(state, default=str), "rid": run_id,
                           "me": f"seed:{self.instance}"})
        return True

    def release(self) -> bool:
        from sqlalchemy import text
        try:
            with self._engine.begin() as c:
                return c.execute(text("""UPDATE alpatrade.live_runner_state SET lease_expires_at = now()
                                         WHERE runner_key = :k AND lease_holder = :me AND lease_expires_at > now()"""),
                                 {"k": self.runner_key, "me": self.instance}).rowcount == 1
        except Exception:  # noqa: BLE001
            return False

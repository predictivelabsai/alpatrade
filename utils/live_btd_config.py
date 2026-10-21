"""DB-backed strategy parameters + order-execution settings for the live BTD runner.

One row in ``alpatrade.strategy_configs`` (sql/40_strategy_configs.sql) is the shared
source of truth for every runner instance (HP primary, Mac backup, box tertiary).
Rules are DB-only (v0.55.0): every key in REQUIRED_PARAM_KEYS must be stored in the row. CLI flags\n(dry-run testing only; the live runner refuses them) may override a stored key.

If the row cannot be read (DB unreachable, row missing/incomplete, bad JSON) ``db_ok`` is False
and the last rule set loaded from the DB on this machine (same version) is used for exits and
stops only; the runner sends no entries. With no snapshot at all the runner places nothing
(the broker-side resting stops stay in place).

Pure helpers for exits: ``exit_order`` builds the Alpaca order body for the regular or the
extended/overnight session, ``ext_limit_price`` applies the bid discount and
``ext_exit_action`` decides wait / reprice / fall back to a DAY market order at the open.
"""
from __future__ import annotations

import os

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

DEFAULT_STRATEGY = "buy_the_dip_mag7_minhold_live"   # which ROW to load (a lookup key, not a rule)

# v0.55.0 (Julian 2026-10-21): rules live in the DB ONLY. These are the keys a rule set must carry;
# there are no code defaults. sql/57_rules_db_only.sql seeded the former fallback values into the rows.
REQUIRED_PARAM_KEYS = ("symbols", "dip", "tp", "sl", "min_hold", "max_hold", "pos_frac", "max_exposure", "ref",
                       "feed", "entry_window", "close_window", "regime_filter", "stop_mode", "stop_k", "tp_mult",
                       "stop_timing", "vol_filter", "vol_max", "regime_mode", "regime_sma", "max_exposure_pct",
                       "session_mode", "stop_exempt")
REQUIRED_EXECUTION_KEYS = {"regular_hours_exit": ("order_type", "time_in_force"),
                           "extended_hours_exit": ("enabled", "order_type", "limit_ref", "discount_bps",
                                                   "reprice_after_min", "max_reprices", "fallback", "max_spread_bps")}

_TYPES = {"dip": float, "tp": float, "sl": float, "min_hold": int, "max_hold": int,
          "pos_frac": float, "max_exposure": float, "ref": str, "feed": str,
          "entry_window": str, "close_window": str, "regime_filter": str, "session_mode": str,
          "stop_mode": str, "stop_k": float, "tp_mult": float, "stop_timing": str, "vol_filter": str,
          "vol_max": float, "regime_mode": str, "regime_sma": int, "max_exposure_pct": float}
_CHOICES = {"stop_mode": ("pct", "atr", "stdev"), "stop_timing": ("always", "exit_day"),
            "vol_filter": ("off", "atr", "spy_atr"), "regime_mode": ("low5", "sma"),
            "session_mode": ("regular", "stops_24_5", "full_24_5")}


class ConfigError(ValueError):
    pass


def _window(v: Any) -> str:
    far, near = [float(x) for x in str(v).split("-")]
    if far < near or near < 0:
        raise ConfigError(f"bad window {v!r} (want 'far-near' minutes before close)")
    return str(v)


def coerce_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate/normalise known keys; unknown keys are dropped."""
    out: Dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if v is None:
            continue
        if k == "symbols":
            syms = v.split(",") if isinstance(v, str) else list(v)
            syms = [s.strip().upper() for s in syms if str(s).strip()]
            if not syms:
                raise ConfigError("symbols is empty")
            out[k] = syms
        elif k == "stop_exempt":
            if not isinstance(v, (dict, str)):
                raise ConfigError("stop_exempt must be {SYM: YYYY-MM-DD}")
            out[k] = v
        elif k in _TYPES:
            try:
                out[k] = _TYPES[k](v)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"{k}={v!r}: {exc}") from exc
    if "ref" in out and out["ref"] not in ("prev_close", "high20"):
        raise ConfigError(f"ref must be prev_close or high20, got {out['ref']!r}")
    for k, ok in _CHOICES.items():
        if k in out and out[k] not in ok:
            raise ConfigError(f"{k} must be one of {', '.join(ok)}, got {out[k]!r}")
    for k in ("stop_k", "tp_mult", "vol_max", "max_exposure_pct", "regime_sma"):
        if k in out and out[k] < 0:
            raise ConfigError(f"{k} must be >= 0")
    for k in ("entry_window", "close_window"):
        if k in out:
            _window(out[k])
    if "pos_frac" in out and not 0 < out["pos_frac"] <= 1:
        raise ConfigError(f"pos_frac must be in (0, 1], got {out['pos_frac']}")
    for k in ("dip", "tp", "sl", "max_exposure", "min_hold", "max_hold"):
        if k in out and out[k] < 0:
            raise ConfigError(f"{k} must be >= 0")
    return out


def merge_execution(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate the DB execution JSON. Every key in REQUIRED_EXECUTION_KEYS must be stored (no code
    defaults since v0.55.0)."""
    ex = copy.deepcopy(raw or {})
    missing = [f"{sect}.{k}" for sect, keys in REQUIRED_EXECUTION_KEYS.items() for k in keys
               if k not in (ex.get(sect) or {})]
    if missing:
        raise ConfigError("execution missing " + ", ".join(missing) + " (rules are DB-only; see sql/57)")
    e = ex["extended_hours_exit"]
    e["enabled"] = bool(e.get("enabled"))
    e["discount_bps"] = float(e.get("discount_bps", 15))
    e["reprice_after_min"] = float(e.get("reprice_after_min", 5))
    e["max_reprices"] = int(e.get("max_reprices", 2))
    e["max_spread_bps"] = float(e["max_spread_bps"])
    if not 0 <= e["discount_bps"] < 1000:
        raise ConfigError(f"discount_bps out of range: {e['discount_bps']}")
    if e.get("order_type", "limit") != "limit":
        raise ConfigError("extended_hours_exit.order_type must be limit (Alpaca rejects others)")
    return ex


@dataclass
class ConfigResult:
    params: Dict[str, Any]
    execution: Dict[str, Any]
    sources: Dict[str, str]                 # key -> cli | db | default
    source: str                             # summary for logs / run snapshot
    db_ok: bool = False
    config_id: Optional[int] = None
    version: Optional[int] = None
    name: Optional[str] = None
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return {"strategy_config": {"name": self.name, "id": self.config_id, "version": self.version,
                                    "source": self.source, "db_ok": self.db_ok, "sources": self.sources},
                "execution": self.execution}


def fetch_row(engine, strategy: str):
    """Return (id, name, params, execution, version, is_active) or None."""
    from sqlalchemy import text
    by_id = str(strategy).isdigit()
    sql = ("SELECT id, name, params, execution, version, is_active FROM alpatrade.strategy_configs "
           + ("WHERE id = :k" if by_id else "WHERE name = :k"))
    with engine.connect() as c:
        return c.execute(text(sql), {"k": int(strategy) if by_id else strategy}).first()


def make_engine(database_url: str):
    """NullPool: runners/config reads are sparse (minutes apart), so hold no idle connection."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    return create_engine(database_url, poolclass=NullPool,
                         connect_args={"connect_timeout": 5,
                                       "application_name": os.getenv("DB_APPLICATION_NAME", "alpatrade-live-btd-config")[:63],
                                       "options": "-c statement_timeout=10000 -c idle_in_transaction_session_timeout=60000"})


def resolve(strategy: str, cli: Dict[str, Any], *, database_url: Optional[str] = None,
            engine=None, row_loader=None) -> ConfigResult:
    """Load the named (or numeric id) row and merge: CLI > DB > defaults. Never raises."""
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    db_params: Dict[str, Any] = {}
    db_exec: Dict[str, Any] = {}
    err = None; row = None
    try:
        if row_loader is not None:
            row = row_loader(strategy)
        else:
            if engine is None:
                if not database_url:
                    raise ConfigError("DATABASE_URL not set")
                engine = make_engine(database_url)
            row = fetch_row(engine, strategy)
        if row is None:
            raise ConfigError(f"no alpatrade.strategy_configs row {strategy!r}")
        rid, name, rp, rx, ver, active = row[:6]
        if not active:
            raise ConfigError(f"strategy config {name!r} (#{rid}) is inactive")
        rp = json.loads(rp) if isinstance(rp, str) else (rp or {})
        rx = json.loads(rx) if isinstance(rx, str) else (rx or {})
        db_params = coerce_params(rp)
        db_exec = rx
        merge_execution(db_exec)  # validate
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
        row = None; db_params = {}; db_exec = {}

    cli_p = coerce_params(cli)
    if row is not None:
        missing = [k for k in REQUIRED_PARAM_KEYS if k not in db_params]
        if missing:
            err = f"ConfigError: strategy_configs row missing {', '.join(missing)} (rules are DB-only; run sql/57)"
            row = None
    if row is not None:
        params = {k: (cli_p[k] if k in cli_p else copy.deepcopy(db_params[k])) for k in REQUIRED_PARAM_KEYS}
        sources = {k: ("cli" if k in cli_p else "db") for k in REQUIRED_PARAM_KEYS}
        execution = merge_execution(db_exec)
        rid, name, ver = row[0], row[1], row[4]
        src = f"db:alpatrade.strategy_configs#{rid} {name} v{ver}"
        overridden = sorted(k for k, s in sources.items() if s == "cli")
        if overridden:
            src += " + cli(" + ",".join(overridden) + ")"
        out = ConfigResult(params, execution, sources, src, True, rid, ver, name)
        save_last_good(strategy, out)
        return out
    # DB unavailable / row incomplete: FAIL SAFE. The last rule set this machine loaded from the DB
    # (same version id) is used for exits and stops only; db_ok=False -> the runner sends no entries.
    lg = load_last_good(strategy)
    if lg is not None:
        lg.db_ok = False; lg.error = err
        lg.source = f"last-good DB snapshot v{lg.version} (DB config unavailable: {err})"
        return lg
    return ConfigResult({}, {}, {}, f"none (DB config unavailable: {err}; no last-good snapshot)", False,
                        None, None, strategy, err)


def _last_good_path(strategy: str) -> str:
    d = os.environ.get("BTD_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".alpatrade", "btd")
    return os.path.join(d, f"config_last_good_{str(strategy).replace('/', '_')}.json")


def save_last_good(strategy: str, cfg: "ConfigResult") -> None:
    """Cache of the last DB-loaded rule set (NOT a source of truth: only read while the DB is down,
    and then entries are off)."""
    if any(v == "cli" for v in cfg.sources.values()):
        return
    try:
        p = _last_good_path(strategy); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump({"params": cfg.params, "execution": cfg.execution, "id": cfg.config_id,
                       "version": cfg.version, "name": cfg.name}, f, default=str)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def load_last_good(strategy: str) -> Optional["ConfigResult"]:
    try:
        with open(_last_good_path(strategy)) as f:
            d = json.load(f)
        return ConfigResult(d["params"], d["execution"], {k: "last_good" for k in d["params"]}, "", False,
                            d.get("id"), d.get("version"), d.get("name"))
    except (OSError, ValueError, KeyError):
        return None


# ------------------------------------------------------------------ exit orders
from utils.btd_rules import ext_limit_price  # noqa: E402  (v0.55.0: the rule lives in btd_rules)


def exit_order(sym: str, qty: Any, cid: str, session: str, execution: Dict[str, Any],
               bid: Optional[float] = None) -> Dict[str, Any]:
    """Alpaca sell body. session = 'regular' (market, day) or 'extended' (limit at bid
    discount, extended_hours=true, day — Alpaca requires limit+day for extended/overnight)."""
    if session == "regular":
        r = execution.get("regular_hours_exit", {})
        return {"symbol": sym, "qty": str(qty), "side": "sell", "type": r.get("order_type", "market"),
                "time_in_force": r.get("time_in_force", "day"), "client_order_id": cid}
    e = execution["extended_hours_exit"]
    return {"symbol": sym, "qty": str(qty), "side": "sell", "type": "limit",
            "limit_price": f"{ext_limit_price(bid, e['discount_bps'])}", "time_in_force": "day",
            "extended_hours": True, "client_order_id": cid}


from utils.btd_rules import ext_exit_action  # noqa: E402,F401  (v0.55.0: the rule lives in btd_rules)

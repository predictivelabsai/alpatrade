"""DB-backed strategy parameters + order-execution settings for the live BTD runner.

One row in ``alpatrade.strategy_configs`` (sql/40_strategy_configs.sql) is the shared
source of truth for every runner instance (HP primary, Mac backup, box tertiary).
Precedence, per key:  explicit CLI flag  >  DB row  >  code defaults (``DEFAULT_PARAMS``).

If the row cannot be read (DB unreachable, table/row missing, bad JSON) the runner falls
back to the defaults and ``ConfigResult.db_ok`` is False; the runner then disables entries
for that live pass (never buy on unverified params). Exits still run.

Pure helpers for exits: ``exit_order`` builds the Alpaca order body for the regular or the
extended/overnight session, ``ext_limit_price`` applies the bid discount and
``ext_exit_action`` decides wait / reprice / fall back to a DAY market order at the open.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

DEFAULT_STRATEGY = "buy_the_dip_mag7_minhold_live"

# Code defaults == the argparse defaults the runner had before configs moved to the DB.
DEFAULT_PARAMS: Dict[str, Any] = {
    "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"],
    "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
    "pos_frac": 0.10, "max_exposure": 0.0, "ref": "high20", "feed": "iex",
    "entry_window": "15-5", "close_window": "15-2",
}

DEFAULT_EXECUTION: Dict[str, Any] = {
    "regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
    "extended_hours_exit": {"enabled": False, "order_type": "limit", "limit_ref": "bid",
                            "discount_bps": 15, "reprice_after_min": 5, "max_reprices": 2,
                            "fallback": "market_day_at_regular_open"},
}

_TYPES = {"dip": float, "tp": float, "sl": float, "min_hold": int, "max_hold": int,
          "pos_frac": float, "max_exposure": float, "ref": str, "feed": str,
          "entry_window": str, "close_window": str}


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
        elif k in _TYPES:
            try:
                out[k] = _TYPES[k](v)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"{k}={v!r}: {exc}") from exc
    if "ref" in out and out["ref"] not in ("prev_close", "high20"):
        raise ConfigError(f"ref must be prev_close or high20, got {out['ref']!r}")
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
    ex = copy.deepcopy(DEFAULT_EXECUTION)
    for sect, vals in (raw or {}).items():
        if isinstance(vals, dict):
            ex.setdefault(sect, {}).update(vals)
    e = ex["extended_hours_exit"]
    e["enabled"] = bool(e.get("enabled"))
    e["discount_bps"] = float(e.get("discount_bps", 15))
    e["reprice_after_min"] = float(e.get("reprice_after_min", 5))
    e["max_reprices"] = int(e.get("max_reprices", 2))
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
    from sqlalchemy import create_engine
    return create_engine(database_url, pool_pre_ping=True, pool_size=1, max_overflow=0,
                         connect_args={"connect_timeout": 5, "application_name": "alpatrade-live-btd-config",
                                       "options": "-c statement_timeout=10000"})


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
    params, sources = {}, {}
    for k, dv in DEFAULT_PARAMS.items():
        if k in cli_p:
            params[k], sources[k] = cli_p[k], "cli"
        elif k in db_params:
            params[k], sources[k] = db_params[k], "db"
        else:
            params[k], sources[k] = copy.deepcopy(dv), "default"
    execution = merge_execution(db_exec)
    if row is not None:
        rid, name, ver = row[0], row[1], row[4]
        src = f"db:alpatrade.strategy_configs#{rid} {name} v{ver}"
        overridden = sorted(k for k, s in sources.items() if s == "cli")
        if overridden:
            src += " + cli(" + ",".join(overridden) + ")"
        return ConfigResult(params, execution, sources, src, True, rid, ver, name)
    src = f"defaults (DB config unavailable: {err})"
    if any(s == "cli" for s in sources.values()):
        src += " + cli(" + ",".join(sorted(k for k, s in sources.items() if s == "cli")) + ")"
    return ConfigResult(params, execution, sources, src, False, None, None, strategy, err)


# ------------------------------------------------------------------ exit orders
def ext_limit_price(bid: float, discount_bps: float) -> float:
    """Limit = bid x (1 - discount). Rounded DOWN to a valid tick (>= $1: 0.01, else 0.0001)."""
    if not bid or bid <= 0:
        raise ValueError("no bid")
    px = bid * (1 - discount_bps / 10_000.0)
    tick = 0.01 if px >= 1 else 0.0001
    return round(int(px / tick + 1e-9) * tick, 4 if tick < 0.01 else 2)


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


def ext_exit_action(*, submitted_at: datetime, now: datetime, reprices: int, market_open: bool,
                    execution: Dict[str, Any]) -> str:
    """For an open extended-hours limit sell: 'fallback' (cancel -> DAY market) once the
    regular session is open, 'reprice' every reprice_after_min while reprices < max_reprices,
    otherwise 'wait' (for more time, or for the regular open once reprices are used up)."""
    e = execution["extended_hours_exit"]
    if market_open:
        return "fallback"
    if reprices < e["max_reprices"] and (now - submitted_at).total_seconds() >= e["reprice_after_min"] * 60:
        return "reprice"
    return "wait"

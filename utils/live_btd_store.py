"""Best-effort persistence of the live BTD runner into AlpaTrade's own tables.

Rows land in the existing ``alpatrade`` schema under the owning AlpaTrade user:

* ``runs``        one long-lived row per deployment, ``mode='live'`` (config = params,
                  broker account number; results = latest + daily performance).
* ``trades``      one row per round trip, ``trade_type='live'``: inserted when the entry
                  order is submitted, completed on entry fill, closed on exit fill.
                  ``order_id`` holds the entry client_order_id (idempotency key).
* ``positions``   runner-owned open positions (status open/closed), refreshed each pass.
* ``pnl_summary`` one aggregate row per run (symbol NULL).

``account_id`` is left NULL: it is a FK to ``user_accounts`` (the app's linked, key-bearing
Alpaca accounts) and the live account is intentionally not linked there.

Every public method is wrapped: a DB problem logs a warning and returns None. The first
failure disables the recorder for the rest of the pass so a dead DB costs one timeout,
never a blocked or altered trade.
"""
from __future__ import annotations

import functools
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Optional

LOG = logging.getLogger("btd.store")

STRATEGY_NAME = "Mag-7 BTD min-hold 3d"
STRATEGY_SLUG = "buy_the_dip_mag7_minhold_live"


def _best_effort(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if not self.enabled:
            return None
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - recording must never affect trading
            self.log.warning("DB record %s failed (%s); recorder disabled for this pass",
                             fn.__name__, str(exc).splitlines()[0][:200])
            self.enabled = False
            return None
    return wrapper


class LiveRecorder:
    def __init__(self, database_url: Optional[str], user_email: Optional[str] = None,
                 user_id: Optional[str] = None, log: logging.Logger = LOG, engine=None):
        self.log = log
        self.user_id = user_id
        self.user_email = user_email
        self.enabled = bool(engine is not None or database_url)
        self._engine = engine
        if not self.enabled:
            self.log.warning("DATABASE_URL not set; live trades will not be recorded in AlpaTrade")
            return
        if self._engine is None:
            try:
                from sqlalchemy import create_engine
                self._engine = create_engine(
                    database_url, pool_pre_ping=True, pool_size=1, max_overflow=0,
                    connect_args={"connect_timeout": 5, "application_name": "alpatrade-live-btd",
                                  "options": "-c statement_timeout=10000"})
            except Exception as exc:  # noqa: BLE001
                self.log.warning("DB engine init failed (%s); recording disabled", exc)
                self.enabled = False
                return
        if not self.user_id:
            self.user_id = self._resolve_user()
            if not self.user_id and self.enabled:
                self.log.warning("no active AlpaTrade user with email %s; recording disabled",
                                 user_email)
                self.enabled = False

    # ------------------------------------------------------------------ helpers
    def _exec(self, sql: str, params: Dict[str, Any]):
        from sqlalchemy import text
        with self._engine.begin() as conn:
            return conn.execute(text(sql), params)

    @_best_effort
    def _resolve_user(self) -> Optional[str]:
        row = self._exec(
            "SELECT user_id FROM alpatrade.users WHERE lower(email) = lower(:e) "
            "AND COALESCE(is_active, TRUE) ORDER BY created_at LIMIT 1",
            {"e": self.user_email or ""}).first()
        return str(row[0]) if row else None

    # --------------------------------------------------------------------- runs
    @_best_effort
    def ensure_run(self, run_id: Optional[str], config: Dict[str, Any]) -> Optional[str]:
        run_id = run_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        self._exec("""
            INSERT INTO alpatrade.runs (run_id, mode, strategy, status, config, started_at,
                                        strategy_slug, user_id, agent_name, heartbeat_at)
            VALUES (:run_id, 'live', :strategy, 'running', CAST(:config AS JSONB), :now,
                    :slug, CAST(:uid AS UUID), 'live_btd_minhold', :now)
            ON CONFLICT (run_id) DO UPDATE SET heartbeat_at = EXCLUDED.heartbeat_at
        """, {"run_id": run_id, "strategy": config.get("strategy_name", STRATEGY_NAME),
              "config": json.dumps(config, default=str), "now": now,
              "slug": config.get("strategy_slug", STRATEGY_SLUG), "uid": self.user_id})
        return run_id

    # ------------------------------------------------------------------- trades
    @_best_effort
    def entry_submitted(self, run_id: str, symbol: str, client_order_id: str,
                        notional: float, dip_pct: float, ref: float) -> bool:
        self._exec("""
            INSERT INTO alpatrade.trades (run_id, trade_type, symbol, direction, entry_time,
                                          dip_pct, order_id, reason, capital_after, user_id)
            SELECT :run_id, 'live', :sym, 'long', :now, :dip, :cid, :reason, NULL,
                   CAST(:uid AS UUID)
            WHERE NOT EXISTS (SELECT 1 FROM alpatrade.trades
                              WHERE run_id = :run_id AND order_id = :cid)
        """, {"run_id": run_id, "sym": symbol, "now": datetime.now(timezone.utc),
              "dip": dip_pct, "cid": client_order_id, "uid": self.user_id,
              "reason": f"entry submitted: notional ${notional:.2f}, ref {ref:.2f}"})
        return True

    @_best_effort
    def entry_filled(self, run_id: str, client_order_id: str, qty: float, price: float,
                     filled_at: Optional[str], tp_pct: float, sl_pct: float) -> bool:
        self._exec("""
            UPDATE alpatrade.trades
               SET shares = :qty, entry_price = :px, entry_time = COALESCE(:ts, entry_time),
                   target_price = :tp, stop_price = :sl, reason = 'open'
             WHERE run_id = :run_id AND order_id = :cid AND trade_type = 'live'
        """, {"run_id": run_id, "cid": client_order_id, "qty": qty, "px": price,
              "ts": filled_at, "tp": price * (1 + tp_pct / 100), "sl": price * (1 - sl_pct / 100)})
        return True

    @_best_effort
    def entry_failed(self, run_id: str, client_order_id: str, status: str) -> bool:
        self._exec("""
            UPDATE alpatrade.trades SET reason = :r, shares = 0
             WHERE run_id = :run_id AND order_id = :cid AND trade_type = 'live'
        """, {"run_id": run_id, "cid": client_order_id, "r": f"entry {status}"})
        return True

    @_best_effort
    def exit_filled(self, run_id: str, entry_client_order_id: str, qty: float, price: float,
                    filled_at: Optional[str], exit_reason: str) -> bool:
        reason = (exit_reason or "exit")
        self._exec("""
            UPDATE alpatrade.trades
               SET exit_price = :px, exit_time = COALESCE(:ts, NOW()),
                   pnl = (:px - entry_price) * :qty,
                   pnl_pct = CASE WHEN entry_price > 0 THEN (:px / entry_price - 1) * 100 END,
                   hit_target = :tp, hit_stop = :sl, reason = :reason
             WHERE run_id = :run_id AND order_id = :cid AND trade_type = 'live'
        """, {"run_id": run_id, "cid": entry_client_order_id, "qty": qty, "px": price,
              "ts": filled_at, "tp": reason.startswith("TP"), "sl": reason.startswith("SL"),
              "reason": reason})
        return True

    # ---------------------------------------------------------------- positions
    @_best_effort
    def sync_positions(self, run_id: str, broker_positions: Iterable[Dict[str, Any]],
                       entry_dates: Dict[str, str]) -> bool:
        now = datetime.now(timezone.utc)
        held = []
        for p in broker_positions:
            sym = p["symbol"]
            held.append(sym)
            vals = {"run_id": run_id, "sym": sym, "qty": float(p["qty"]),
                    "avg": float(p["avg_entry_price"]), "cur": float(p["current_price"]),
                    "mv": float(p["market_value"]), "upl": float(p["unrealized_pl"]),
                    "uplpc": float(p["unrealized_plpc"]) * 100, "cb": float(p["cost_basis"]),
                    "opened": entry_dates.get(sym), "uid": self.user_id, "now": now}
            res = self._exec("""
                UPDATE alpatrade.positions SET shares=:qty, avg_entry_price=:avg,
                       current_price=:cur, market_value=:mv, unrealized_pnl=:upl,
                       unrealized_pnl_pct=:uplpc, cost_basis=:cb, updated_at=:now
                 WHERE run_id=:run_id AND symbol=:sym AND status='open'
            """, vals)
            if res.rowcount == 0:
                self._exec("""
                    INSERT INTO alpatrade.positions (run_id, symbol, side, shares, avg_entry_price,
                           current_price, market_value, unrealized_pnl, unrealized_pnl_pct,
                           cost_basis, status, opened_at, user_id, created_at, updated_at)
                    VALUES (:run_id, :sym, 'long', :qty, :avg, :cur, :mv, :upl, :uplpc, :cb,
                            'open', :opened, CAST(:uid AS UUID), :now, :now)
                """, vals)
        self._exec("""
            UPDATE alpatrade.positions SET status='closed', closed_at=:now, updated_at=:now
             WHERE run_id=:run_id AND status='open' AND NOT (symbol = ANY(:held))
        """, {"run_id": run_id, "now": now, "held": held})
        return True

    # -------------------------------------------------------------- performance
    @_best_effort
    def realized(self, run_id: str) -> Dict[str, float]:
        row = self._exec("""
            SELECT COUNT(*) FILTER (WHERE exit_price IS NOT NULL),
                   COUNT(*) FILTER (WHERE pnl > 0), COUNT(*) FILTER (WHERE pnl <= 0),
                   COALESCE(SUM(pnl), 0), AVG(pnl), AVG(pnl_pct), MAX(pnl), MIN(pnl)
              FROM alpatrade.trades WHERE run_id = :run_id AND trade_type = 'live'
               AND exit_price IS NOT NULL
        """, {"run_id": run_id}).first()
        keys = ["trade_count", "win_count", "loss_count", "total_pnl", "avg_pnl",
                "avg_pnl_pct", "best", "worst"]
        return {k: (float(v) if v is not None else None) for k, v in zip(keys, row)}

    @_best_effort
    def record_performance(self, run_id: str, perf: Dict[str, Any],
                           daily_key: Optional[str] = None,
                           closed: Optional[Dict[str, float]] = None) -> bool:
        now = datetime.now(timezone.utc)
        perf = {**perf, "updated_at": now.isoformat()}
        patch = {"latest": perf}
        self._exec("""
            UPDATE alpatrade.runs
               SET results = COALESCE(results, '{}'::jsonb) || CAST(:patch AS JSONB),
                   heartbeat_at = :now
             WHERE run_id = :run_id
        """, {"run_id": run_id, "patch": json.dumps(patch, default=str), "now": now})
        if daily_key:
            self._exec("""
                UPDATE alpatrade.runs
                   SET results = jsonb_set(COALESCE(results, '{}'::jsonb) ||
                                   CASE WHEN results ? 'daily' THEN '{}'::jsonb
                                        ELSE '{"daily": {}}'::jsonb END,
                                   ARRAY['daily', :k], CAST(:snap AS JSONB), true)
                 WHERE run_id = :run_id
            """, {"run_id": run_id, "k": daily_key, "snap": json.dumps(perf, default=str)})
        c = closed or {}
        n = int(c.get("trade_count") or 0)
        vals = {"run_id": run_id, "n": n, "w": int(c.get("win_count") or 0),
                "l": int(c.get("loss_count") or 0), "pnl": float(c.get("total_pnl") or 0),
                "avg": c.get("avg_pnl"), "avgpct": c.get("avg_pnl_pct"), "best": c.get("best"),
                "worst": c.get("worst"), "ret": perf.get("strategy_return_pct"),
                "wr": (float(c.get("win_count") or 0) / n * 100) if n else None,
                "uid": self.user_id, "now": now}
        res = self._exec("""
            UPDATE alpatrade.pnl_summary SET trade_count=:n, win_count=:w, loss_count=:l,
                   total_pnl=:pnl, avg_pnl=:avg, avg_pnl_pct=:avgpct, best_trade_pnl=:best,
                   worst_trade_pnl=:worst, total_return_pct=:ret, win_rate=:wr, updated_at=:now
             WHERE run_id=:run_id AND symbol IS NULL
        """, vals)
        if res.rowcount == 0:
            self._exec("""
                INSERT INTO alpatrade.pnl_summary (run_id, symbol, trade_count, win_count,
                       loss_count, total_pnl, total_fees, avg_pnl, avg_pnl_pct, best_trade_pnl,
                       worst_trade_pnl, total_return_pct, win_rate, user_id, created_at, updated_at)
                VALUES (:run_id, NULL, :n, :w, :l, :pnl, 0, :avg, :avgpct, :best, :worst,
                        :ret, :wr, CAST(:uid AS UUID), :now, :now)
            """, vals)
        return True

    # ------------------------------------------------------------- test helper
    @_best_effort
    def delete_run(self, run_id: str) -> bool:
        for t in ("pnl_summary", "positions", "trades"):
            self._exec(f"DELETE FROM alpatrade.{t} WHERE run_id = :r", {"r": run_id})
        self._exec("DELETE FROM alpatrade.runs WHERE run_id = :r", {"r": run_id})
        return True

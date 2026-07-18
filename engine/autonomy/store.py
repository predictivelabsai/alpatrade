"""Postgres persistence for autonomy runs, checkpoints, events, and promotions.

Uses the shared ``engine.db.pool`` (parameterised ``text()`` SQL, ``alpatrade`` schema).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text

from engine.db.pool import DatabasePool


def _pool():
    return DatabasePool()


def create_run(kind: str = "full", config: Optional[dict] = None,
               user_id: Optional[str] = None, account_id: Optional[str] = None) -> str:
    with _pool().get_session() as s:
        rid = s.execute(text("""
            INSERT INTO alpatrade.autonomy_runs (kind, config, user_id, account_id)
            VALUES (:kind, :config, :uid, :aid) RETURNING run_id
        """), {"kind": kind, "config": json.dumps(config or {}),
               "uid": user_id, "aid": account_id}).scalar()
    return str(rid)


def get_run(run_id: str) -> Optional[dict]:
    with _pool().get_session() as s:
        row = s.execute(text("""
            SELECT run_id, kind, status, config, attempt, claimed_by, error
            FROM alpatrade.autonomy_runs WHERE run_id = :rid
        """), {"rid": run_id}).fetchone()
    if not row:
        return None
    return {"run_id": str(row[0]), "kind": row[1], "status": row[2], "config": row[3],
            "attempt": row[4], "claimed_by": row[5], "error": row[6]}


def set_status(run_id: str, status: str, error: Optional[str] = None) -> None:
    with _pool().get_session() as s:
        s.execute(text("""
            UPDATE alpatrade.autonomy_runs
            SET status = :st, error = COALESCE(:err, error), updated_at = NOW()
            WHERE run_id = :rid
        """), {"st": status, "err": error, "rid": run_id})


def save_step(run_id: str, node: str, output: Any = None,
              status: str = "done", input: Any = None) -> None:
    """Upsert one pipeline node result — the resumable checkpoint."""
    with _pool().get_session() as s:
        s.execute(text("""
            INSERT INTO alpatrade.autonomy_run_steps (run_id, node, status, input, output)
            VALUES (:rid, :node, :st, :inp, :out)
            ON CONFLICT (run_id, node) DO UPDATE
            SET status = EXCLUDED.status, input = EXCLUDED.input,
                output = EXCLUDED.output, created_at = NOW()
        """), {"rid": run_id, "node": node, "st": status,
               "inp": json.dumps(input) if input is not None else None,
               "out": json.dumps(output) if output is not None else None})


def completed_steps(run_id: str) -> set[str]:
    with _pool().get_session() as s:
        rows = s.execute(text("""
            SELECT node FROM alpatrade.autonomy_run_steps
            WHERE run_id = :rid AND status = 'done'
        """), {"rid": run_id}).fetchall()
    return {r[0] for r in rows}


def append_event(run_id: Optional[str], message: str, level: str = "info") -> None:
    with _pool().get_session() as s:
        s.execute(text("""
            INSERT INTO alpatrade.autonomy_events (run_id, level, message)
            VALUES (:rid, :lvl, :msg)
        """), {"rid": run_id, "lvl": level, "msg": message})


def record_promotion(run_id: Optional[str], strategy_slug: str, symbol: str,
                     evidence: dict) -> int:
    with _pool().get_session() as s:
        pid = s.execute(text("""
            INSERT INTO alpatrade.autonomy_promotions (run_id, strategy_slug, symbol, evidence)
            VALUES (:rid, :slug, :sym, :ev) RETURNING id
        """), {"rid": run_id, "slug": strategy_slug, "sym": symbol,
               "ev": json.dumps(evidence)}).scalar()
    return int(pid)


def pending_promotions(limit: int = 50) -> list[dict]:
    with _pool().get_session() as s:
        rows = s.execute(text("""
            SELECT id, strategy_slug, symbol, evidence, created_at
            FROM alpatrade.autonomy_promotions WHERE status = 'candidate'
            ORDER BY created_at DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
    return [{"id": r[0], "strategy_slug": r[1], "symbol": r[2],
             "evidence": r[3], "created_at": r[4]} for r in rows]

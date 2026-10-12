"""Stale-run reaper (v0.42.0).

Marks ``alpatrade.runs`` rows still ``running`` with no heartbeat for too long as
``stopped`` (paper) / ``failed`` (backtest) with ``completed_at``. LIVE runs are never
touched. Scheduled every 15 min from the autonomy worker (``start()``); also runnable
once: ``python -m engine.runs_reaper [--dry-run]``.
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

PAPER_STALE_HOURS = float(os.getenv("REAPER_PAPER_STALE_HOURS", "6"))
BACKTEST_STALE_HOURS = float(os.getenv("REAPER_BACKTEST_STALE_HOURS", "24"))
INTERVAL_SECONDS = int(os.getenv("REAPER_INTERVAL_SECONDS", "900"))

# (mode list, new status, hours) — 'live' is deliberately absent.
RULES = (
    (("paper", "full"), "stopped", PAPER_STALE_HOURS),
    (("backtest",), "failed", BACKTEST_STALE_HOURS),
)

_SQL = """
    {verb} alpatrade.runs {set_clause}
    WHERE status = 'running' AND mode = ANY(:modes) AND mode <> 'live'
      AND COALESCE(heartbeat_at, started_at, created_at) < NOW() - make_interval(secs => :secs)
    {returning}
"""


def build_sql(dry_run: bool) -> str:
    if dry_run:
        return _SQL.format(verb="SELECT run_id, mode FROM", set_clause="", returning="")
    return _SQL.format(verb="UPDATE", set_clause="SET status = :status, completed_at = NOW()",
                       returning="RETURNING run_id, mode")


def reap(dry_run: bool = False) -> dict[str, list[str]]:
    from sqlalchemy import text
    from utils.db.db_pool import DatabasePool
    out: dict[str, list[str]] = {}
    with DatabasePool().get_session() as session:
        for modes, status, hours in RULES:
            rows = session.execute(text(build_sql(dry_run)),
                                   {"modes": list(modes), "status": status,
                                    "secs": hours * 3600}).fetchall()
            out[status] = [str(r[0]) for r in rows]
    n = sum(len(v) for v in out.values())
    if n:
        log.warning("RUNS_REAPER %s %d stale run(s): %s", "would mark" if dry_run else "marked",
                    n, {k: [x[:8] for x in v] for k, v in out.items()})
    return out


def _loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            reap()
        except Exception as exc:  # noqa: BLE001
            log.warning("runs reaper failed: %s", type(exc).__name__)
        stop.wait(INTERVAL_SECONDS)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="runs-reaper", daemon=True).start()
    return stop


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(reap(dry_run="--dry-run" in sys.argv))

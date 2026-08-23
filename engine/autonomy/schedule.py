"""NYSE-aware daily-advisor scheduler owned exclusively by the autonomy worker.

The scheduler polls rather than assuming a fixed UTC close. Alpaca's calendar is
the authority for holidays, early closes, and daylight-saving transitions. The
database queue's tenant/session dedupe key makes repeated polls harmless.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("autonomy.schedule")

_started = False
_enqueued_users: set[tuple[date, str]] = set()
_session_closes: dict[date, Optional[datetime]] = {}


def _enabled() -> bool:
    return os.getenv("ADVISOR_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _delay_minutes() -> int:
    return max(0, int(os.getenv("ADVISOR_CLOSE_DELAY_MINUTES", "15")))


def advisor_is_due(
    now: datetime,
    session_close: Optional[datetime],
    delay_minutes: int = 15,
) -> bool:
    """Return whether the session close plus configured delay has passed."""
    if session_close is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if session_close.tzinfo is None:
        session_close = session_close.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc) >= (
        session_close.astimezone(timezone.utc) + timedelta(minutes=delay_minutes)
    )


def enqueue_due_advisor_jobs(now: Optional[datetime] = None) -> list[str]:
    """Enqueue one deduplicated post-close advisor batch per eligible tenant."""
    if not _enabled():
        return []

    from engine.autonomy import queue
    from engine.reporting.advisor import (
        EASTERN,
        active_advisor_users,
        market_session_close,
        scheduler_dedupe_key,
        usable_paper_accounts,
    )

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    session_date = now.astimezone(EASTERN).date()
    _enqueued_users.intersection_update({
        item for item in _enqueued_users if item[0] == session_date
    })
    for cached_date in list(_session_closes):
        if cached_date != session_date:
            _session_closes.pop(cached_date, None)
    users = active_advisor_users()
    pending_users = [
        user for user in users
        if (session_date, user["user_id"]) not in _enqueued_users
    ]
    if not pending_users:
        return []
    # Cache ``None`` as well as a close timestamp. On holidays/weekends, a
    # missing session is authoritative for the date and should not trigger a
    # broker-calendar request for every scheduler poll and linked account.
    if session_date not in _session_closes:
        _session_closes[session_date] = market_session_close(session_date)
    close = _session_closes[session_date]
    if not advisor_is_due(now, close, _delay_minutes()):
        return []

    job_ids = []
    for user in pending_users:
        user_id = user["user_id"]
        accounts = usable_paper_accounts(user_id)
        if not accounts:
            continue
        job_ids.append(queue.enqueue(
            kind="deepagent_advisor",
            config={
                "session_date": session_date.isoformat(),
                "account_ids": [str(account["account_id"]) for account in accounts],
            },
            user_id=user_id,
            account_id=None,
            dedupe_key=scheduler_dedupe_key(user_id, session_date),
        ))
        _enqueued_users.add((session_date, user_id))
    log.info(
        "daily advisor scheduler enqueued %d tenant batch(es) for %s",
        len(job_ids), session_date,
    )
    return job_ids


def _loop() -> None:
    poll_seconds = max(30, int(os.getenv("ADVISOR_SCHEDULER_POLL_SECONDS", "60")))
    log.info(
        "daily advisor scheduler started (close delay=%sm, poll=%ss, email=%s)",
        _delay_minutes(),
        poll_seconds,
        os.getenv("ADVISOR_EMAIL_ENABLED", "false"),
    )
    while True:
        try:
            enqueue_due_advisor_jobs()
        except Exception as exc:  # noqa: BLE001
            log.exception("daily advisor scheduling tick failed: %s", exc)
        threading.Event().wait(poll_seconds)


def start() -> None:
    """Start the worker-owned scheduler once in this process."""
    global _started
    if _started:
        return
    if not _enabled():
        log.info("daily advisor scheduler disabled (ADVISOR_ENABLED=false)")
        return
    _started = True
    threading.Thread(
        target=_loop, name="daily-advisor-scheduler", daemon=True
    ).start()


__all__ = ["advisor_is_due", "enqueue_due_advisor_jobs", "start"]

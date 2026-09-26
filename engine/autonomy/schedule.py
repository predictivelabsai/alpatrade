"""Worker-owned schedulers: the NYSE-aware daily advisor and the nightly paper
PnL report. Both are started once per process from the autonomy worker (safe to
start from the web app too — each is idempotent per process).

Advisor scheduler:
  Polls rather than assuming a fixed UTC close. Alpaca's calendar is the authority
  for holidays, early closes, and daylight-saving transitions. The database queue's
  tenant/session dedupe key makes repeated polls harmless.
    ADVISOR_ENABLED               = true                 (default)
    ADVISOR_CLOSE_DELAY_MINUTES   = 15
    ADVISOR_SCHEDULER_POLL_SECONDS = 60

PnL-report scheduler:
  A single daemon thread that sleeps until the next fire time, sends one
  tenant/account report to each owner, and re-sleeps.
    PNL_REPORT_FREQUENCY = daily | off      (default: daily)
    PNL_REPORT_HOUR_UTC  = 21               (0-23; ~1h after the 20:00 UTC US close)
    Account owners are resolved from DB; no cross-account distribution list is used.

Live-report scheduler (scripts/daily_live_report.py — separate from the paper report):
  Polls like the advisor. On US trading days only (Alpaca calendar via each owner's
  GET-only live client; weekends/holidays send nothing) it fires once the session
  close + delay has passed — 16:20 ET = 23:20 Tallinn by default, DST-proof — and
  emails each linked live account's report to that account's own user email only.
  A DB claim (alpatrade.live_report_deliveries) keeps it once per account per day.
    LIVE_REPORT_ENABLED              = true      (default)
    LIVE_REPORT_CLOSE_DELAY_MINUTES  = 20
    LIVE_REPORT_POLL_SECONDS         = 60
"""
from __future__ import annotations

import logging
import os
import threading
import time
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


def _cfg():
    return (os.getenv("PNL_REPORT_FREQUENCY", "daily").strip().lower(),
            int(os.getenv("PNL_REPORT_HOUR_UTC", "21")))


def _next_fire(freq: str, hour: int) -> datetime | None:
    if freq != "daily":
        return None
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _run_pnl_report():
    """Send one tenant/account report to its owner (best-effort)."""
    try:
        from scripts.daily_pnl_report import (
            claim_report_delivery, finish_report_delivery, gather, reconcile_stale_runs,
            render, report_targets,
        )
        from utils.email_util import send_email_to
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for target in report_targets():
            if not claim_report_delivery(target["user_id"], target["account_id"], day):
                continue
            ok = False
            try:
                reconcile_stale_runs(target["user_id"], target["account_id"])
                data = gather(keys=target["keys"], user_id=target["user_id"],
                              account_id=target["account_id"])
                data["owner_email"] = target["email"]
                data["account_name"] = target["account_name"]
                subject = (f"AlpaTrade Paper PnL — {datetime.now(timezone.utc).strftime('%b %d, %Y')} "
                           f"({'+' if data['day_pnl'] >= 0 else ''}${data['day_pnl']:,.0f})")
                ok = send_email_to(target["email"], subject, render(data))
            except Exception as exc:  # one account cannot suppress every owner's report
                log.exception("daily PnL report account=%s failed: %s",
                              target["account_id"], exc)
            finally:
                finish_report_delivery(target["user_id"], target["account_id"], day, ok)
            log.info("daily PnL report account=%s → owner: %s",
                     target["account_id"], "sent" if ok else "FAILED")
    except Exception as e:  # noqa: BLE001
        log.exception("daily PnL report failed: %s", e)


def _live_enabled() -> bool:
    return os.getenv("LIVE_REPORT_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _live_delay_minutes() -> int:
    return max(0, int(os.getenv("LIVE_REPORT_CLOSE_DELAY_MINUTES", "20")))


_live_done: set[tuple[date, str, str]] = set()
_live_closes: dict[date, Optional[datetime]] = {}


def run_due_live_reports(now: Optional[datetime] = None) -> list[dict]:
    """Send today's live report to each linked owner once the close + delay passed.

    Returns one result dict per attempted target. No-op on non-trading days."""
    if not _live_enabled():
        return []
    from engine.reporting.advisor import EASTERN
    from scripts.daily_live_report import (
        client_for, report_targets, send_report, session_for,
    )

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    session_date = now.astimezone(EASTERN).date()
    _live_done.intersection_update({k for k in _live_done if k[0] == session_date})
    for cached in list(_live_closes):
        if cached != session_date:
            _live_closes.pop(cached, None)
    if session_date in _live_closes and _live_closes[session_date] is None:
        return []  # known non-trading day
    targets = [t for t in report_targets()
               if (session_date, t["user_id"], t["account_number"]) not in _live_done]
    if not targets:
        return []
    results = []
    for target in targets:
        key = (session_date, target["user_id"], target["account_number"])
        try:
            client = client_for(target)
            if client is None:
                _live_done.add(key)
                continue
            if session_date not in _live_closes:
                sess = session_for(client, session_date)
                _live_closes[session_date] = sess["close"] if sess else None
            close = _live_closes[session_date]
            if close is None:
                log.info("live report: %s is not a trading day — nothing sent", session_date)
                return results
            if not advisor_is_due(now, close, _live_delay_minutes()):
                return results
            res = send_report(target, day=session_date, client=client)
            _live_done.add(key)
            results.append(res)
            log.info("daily LIVE report acct=%s → owner: %s%s", target["account_number"],
                     "sent" if res.get("sent") else "not sent",
                     f" ({res.get('error')})" if res.get("error") else "")
        except Exception as exc:  # noqa: BLE001 — one owner cannot block the others
            log.exception("daily LIVE report acct=%s failed: %s",
                          target.get("account_number"), exc)
            _live_done.add(key)
    return results


def _live_loop() -> None:
    poll_seconds = max(30, int(os.getenv("LIVE_REPORT_POLL_SECONDS", "60")))
    log.info("live-report scheduler started (close delay=%sm, poll=%ss)",
             _live_delay_minutes(), poll_seconds)
    while True:
        try:
            run_due_live_reports()
        except Exception as exc:  # noqa: BLE001
            log.exception("live-report scheduling tick failed: %s", exc)
        threading.Event().wait(poll_seconds)


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


def _advisor_loop() -> None:
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


def _pnl_loop() -> None:
    freq, hour = _cfg()
    log.info("PnL-report scheduler: freq=%s hour_utc=%s", freq, hour)
    while True:
        nxt = _next_fire(*_cfg())
        if nxt is None:
            time.sleep(3600)  # 'off' — re-check hourly in case .env changes on restart
            continue
        time.sleep(max(1, (nxt - datetime.now(timezone.utc)).total_seconds()))
        _run_pnl_report()
        time.sleep(60)  # avoid a double-fire in the same minute


def start() -> None:
    """Start the worker-owned schedulers once in this process.

    The advisor scheduler runs when ADVISOR_ENABLED is set; the nightly PnL-report
    scheduler runs unless PNL_REPORT_FREQUENCY is 'off'. They are independent, so
    one being disabled never suppresses the other.
    """
    global _started
    if _started:
        return
    _started = True

    if _enabled():
        threading.Thread(
            target=_advisor_loop, name="daily-advisor-scheduler", daemon=True
        ).start()
    else:
        log.info("daily advisor scheduler disabled (ADVISOR_ENABLED=false)")

    freq, _ = _cfg()
    if freq != "off":
        threading.Thread(
            target=_pnl_loop, name="pnl-report-scheduler", daemon=True
        ).start()
    else:
        log.info("PnL-report scheduler disabled (PNL_REPORT_FREQUENCY=off)")

    if _live_enabled():
        threading.Thread(
            target=_live_loop, name="live-report-scheduler", daemon=True
        ).start()
    else:
        log.info("live-report scheduler disabled (LIVE_REPORT_ENABLED=false)")


__all__ = ["advisor_is_due", "enqueue_due_advisor_jobs", "run_due_live_reports", "start"]

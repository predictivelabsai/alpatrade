"""In-process scheduler — nightly paper PnL report, no external cron.

Mirrors the liquidround pattern: a single daemon thread, config via .env, sleeps until
the next fire time, runs, re-sleeps. Started from the autonomy worker (and safe to start
from the web app too — it's idempotent per process).

Env:
  PNL_REPORT_FREQUENCY = daily | off      (default: daily)
  PNL_REPORT_HOUR_UTC  = 21               (0-23; ~1h after the 20:00 UTC US close)
  Account owners are resolved from DB; no cross-account distribution list is used.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("autonomy.schedule")

_started = False


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


def _loop():
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
    """Start the scheduler daemon once per process (no-op if freq is off)."""
    global _started
    if _started:
        return
    freq, _ = _cfg()
    if freq == "off":
        log.info("PnL-report scheduler disabled (PNL_REPORT_FREQUENCY=off)")
        return
    _started = True
    threading.Thread(target=_loop, name="pnl-report-scheduler", daemon=True).start()

"""In-memory event scheduler for the live BTD runner — one long-running process per machine
(HP primary, Mac backup, box tertiary). Same pattern as the report schedulers in
engine/autonomy/schedule.py: a poll loop (``threading.Event().wait``), Alpaca's calendar as
the authority for holidays / early closes / DST (``scripts.daily_live_report.session_for``,
cached per ET date, ``None`` cached for non-trading days), due checks via
``engine.autonomy.schedule.advisor_is_due``, an in-memory done-set per session date, and a DB
claim for cross-machine idempotency — here the runner's lease (one transaction, FOR UPDATE)
plus deterministic client_order_ids. No cron/timer is involved; the OS supervisor only keeps
this process alive.

Events per trading session (ET, from the calendar; early closes shift with the close):
  open      open + 1 min (09:31)          broker-side TP/SL for positions past min-hold
  entry-15  close - 15 min + 45 s (15:45:45) dip check + buys
  entry-10  close - 10 min        (15:50)
  entry-5   close - 5 min - 45 s  (15:54:15)
  close     close - 2 min - 45 s  (15:57:15, ~15:58) max-hold exits (cancel broker exits first)
  post      close + 3 min         (16:03)  record fills + daily performance, no orders
  heartbeat every 3 min from open - 30 min to close + 5 min: lease renew only (no Alpaca calls)
Backup / tertiary run every event 10 s / 20 s after the primary (cosmetic: the lease already
makes them stand by while the primary's heartbeat is fresh). Entry/close times sit 45 s inside
the configured windows so a slightly late tick still passes the runner's window check. Missed
events run late only within a grace (entry 4 min, close 40 s, post 10 min); "open" may catch up until 30 min before the close, and a
heartbeat that holds the lease re-runs "open" if the DB state shows it has not run today
(failover takeover after a dead primary).

Config: loaded once at start and cached. Re-read only when (a) the version column changed —
checked cheaply (SELECT version) every 15 min and at the open, first entry and close events —
or (b) forced with SIGHUP. ``scripts/live_btd_config.py bump`` bumps the version so all three
machines reload within 15 minutes or at the next event; an UPDATE trigger (sql/41) bumps the
version on every edit and fires NOTIFY strategy_config_changed for future listeners.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from engine.autonomy.schedule import advisor_is_due
from scripts.daily_live_report import session_for
from utils.live_btd_config import ConfigResult, make_engine

log = logging.getLogger("btd.schedule")
from zoneinfo import ZoneInfo  # noqa: E402
ET = ZoneInfo("America/New_York")

ROLE_OFFSET_S = {"primary": 0, "backup": 10, "tertiary": 20}
INWARD_S = 45
GRACE = {"open": None, "entry": timedelta(minutes=4), "post": timedelta(minutes=10)}


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Event:
    at: datetime
    kind: str          # open | entry | close | post
    key: str           # unique per session (open, entry-15, entry-10, entry-5, close, post)


def session_events(session: Dict[str, Any], entry_window: str = "15-5", close_window: str = "15-2", *,
                   role: str = "primary", open_delay_min: float = 1.0, post_close_min: float = 3.0,
                   step_min: int = 5) -> List[Event]:
    """Event times for one calendar session ({open, close} tz-aware)."""
    off = timedelta(seconds=ROLE_OFFSET_S.get(role, 0))
    o, c = session["open"], session["close"]
    far, near = [float(x) for x in entry_window.split("-")]
    ev = [Event(o + timedelta(minutes=open_delay_min) + off, "open", "open")]
    m = far
    while m >= near - 1e-9:
        t = c - timedelta(minutes=m)
        if m == far: t += timedelta(seconds=INWARD_S)
        if abs(m - near) < 1e-9: t -= timedelta(seconds=INWARD_S)
        ev.append(Event(t + off, "entry", f"entry-{m:g}"))
        m -= step_min
    cnear = float(close_window.split("-")[1])
    ev.append(Event(c - timedelta(minutes=cnear, seconds=INWARD_S) + off, "close", "close"))
    ev.append(Event(c + timedelta(minutes=post_close_min) + off, "post", "post"))
    return sorted(ev, key=lambda e: e.at)


def grace_deadline(e: Event, session: Dict[str, Any]) -> datetime:
    if e.kind == "open":
        return session["close"] - timedelta(minutes=30)
    if e.kind == "close":
        return e.at + timedelta(seconds=40)  # stays inside the close window (>= close - 2 min)
    return e.at + GRACE[e.kind]


def due_events(events: List[Event], done: set, now: datetime, session: Dict[str, Any]
               ) -> Tuple[List[Event], List[Event]]:
    """(due, missed): due = time reached (advisor_is_due), not done, within grace."""
    due, missed = [], []
    for e in events:
        if e.key in done or not advisor_is_due(now, e.at, 0):
            continue
        (due if now <= grace_deadline(e, session) else missed).append(e)
    return due, missed


def heartbeat_due(session: Dict[str, Any], now: datetime, last: Optional[datetime], every_min: float = 3.0) -> bool:
    if not (session["open"] - timedelta(minutes=30) <= now <= session["close"] + timedelta(minutes=5)):
        return False
    return last is None or (now - last) >= timedelta(minutes=every_min)


def needs_open_catchup(lease_state: Optional[Dict[str, Any]], today: date, now: datetime,
                       session: Dict[str, Any], open_event: Event) -> bool:
    """Lease holder whose authoritative state shows no open event today (e.g. after takeover)."""
    if not lease_state or not (lease_state.get("positions") or {}):
        return False
    return (lease_state.get("last_open_event") != today.isoformat()
            and open_event.at <= now < session["close"] - timedelta(minutes=30))


class ConfigCache:
    """Strategy config cached in memory; cheap version checks; full reload on change / SIGHUP."""

    def __init__(self, loader: Callable[[], ConfigResult], version_fn: Callable[[], Optional[int]],
                 check_every_min: float = 15.0, log_fn: Optional[Callable[[ConfigResult, str], None]] = None):
        self._loader, self._version_fn, self._every = loader, version_fn, timedelta(minutes=check_every_min)
        self._log = log_fn or (lambda cfg, what: log.info("strategy config %s: %s", what, cfg.source))
        self.cfg: Optional[ConfigResult] = None
        self.last_check: Optional[datetime] = None
        self.force = False
        self.reloads = 0

    def _reload(self, why: str) -> ConfigResult:
        old = self.cfg.version if self.cfg else None
        self.cfg = self._loader(); self.reloads += 1; self.force = False
        self._log(self.cfg, f"reloaded ({why}; v{old} -> v{self.cfg.version})")
        return self.cfg

    def get(self, now: datetime, at_event: bool = False) -> ConfigResult:
        if self.cfg is None:
            self.cfg = self._loader(); self.last_check = now
            self._log(self.cfg, "loaded at scheduler start")
            return self.cfg
        if self.force:
            self.last_check = now
            return self._reload("forced (SIGHUP)")
        if not self.cfg.db_ok:  # never trade entries on defaults longer than necessary
            self.last_check = now
            return self._reload("previous load did not come from the DB")
        if at_event or self.last_check is None or now - self.last_check >= self._every:
            self.last_check = now
            try:
                v = self._version_fn()
            except Exception as exc:  # noqa: BLE001
                log.warning("strategy config version check failed (%s) -> keeping cached v%s", exc, self.cfg.version)
                return self.cfg
            if v is not None and v != self.cfg.version:
                return self._reload(f"version changed in the DB to v{v}")
        return self.cfg


def db_version_fn(database_url: Optional[str], strategy: str) -> Callable[[], Optional[int]]:
    eng = {"e": None}

    def fn() -> Optional[int]:
        if not database_url:
            return None
        from sqlalchemy import text
        if eng["e"] is None:
            eng["e"] = make_engine(database_url)
        by_id = str(strategy).isdigit()
        with eng["e"].connect() as c:
            return c.execute(text("SELECT version FROM alpatrade.strategy_configs WHERE "
                                  + ("id = :k" if by_id else "name = :k")),
                             {"k": int(strategy) if by_id else strategy}).scalar()
    return fn


class AlpacaCalendar:
    """GET-only calendar client for session_for()."""
    def __init__(self, get: Callable[..., Any], base: str):
        self._get, self._base = get, base

    def get_calendar(self, start: str, end: str) -> list:
        data = self._get(f"{self._base}/v2/calendar", start=start, end=end)
        return data if isinstance(data, list) else []


def run_with_watchdog(fn: Callable[[], Any], timeout_s: float, what: str) -> Any:
    """Run fn in a thread; a hung pass kills the process so the supervisor restarts it."""
    box: Dict[str, Any] = {}

    def target():
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc
    t = threading.Thread(target=target, name=f"btd-{what}", daemon=True)
    t.start(); t.join(timeout_s)
    if t.is_alive():
        log.critical("%s exceeded %.0fs -> exiting so the supervisor restarts the scheduler", what, timeout_s)
        logging.shutdown(); os._exit(70)
    if "e" in box:
        raise box["e"]
    return box.get("r")


class Scheduler:
    def __init__(self, runner, cache: ConfigCache, calendar=None, *, heartbeat_min: Optional[float] = None,
                 poll_s: Optional[float] = None, event_timeout_s: Optional[float] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.runner, self.cache = runner, cache
        self.calendar = calendar or AlpacaCalendar(runner.get, runner.base)
        self.heartbeat_min = heartbeat_min or _f("BTD_HEARTBEAT_MIN", 3.0)
        self.poll_s = poll_s or max(1.0, _f("BTD_SCHED_POLL_SECONDS", 5.0))
        self.event_timeout_s = event_timeout_s or _f("BTD_EVENT_TIMEOUT_SECONDS", 240.0)
        self.now = clock
        self.stop = threading.Event()
        self._done: set = set()
        self._sessions: Dict[date, Optional[Dict[str, Any]]] = {}
        self._events: Dict[date, List[Event]] = {}
        self._last_hb: Optional[datetime] = None
        self._logged_day: Optional[date] = None

    # ---------------------------------------------------------------- calendar
    def session(self, day: date) -> Optional[Dict[str, Any]]:
        for cached in list(self._sessions):
            if cached != day:
                self._sessions.pop(cached, None); self._events.pop(cached, None)
        self._done = {k for k in self._done if k[0] == day}
        if day not in self._sessions:
            self._sessions[day] = session_for(self.calendar, day)
        return self._sessions[day]

    def events_for(self, day: date, session: Dict[str, Any], cfg: ConfigResult) -> List[Event]:
        if day not in self._events:
            self._events[day] = session_events(session, cfg.params["entry_window"], cfg.params["close_window"],
                                               role=self.runner.role)
        return self._events[day]

    # ---------------------------------------------------------------- tick
    def tick(self, now: Optional[datetime] = None) -> List[str]:
        now = (now or self.now()).astimezone(ET)
        day = now.date()
        sess = self.session(day)
        ran: List[str] = []
        if sess is None:
            if self._logged_day != day:
                log.info("btd scheduler: %s is not a trading day (Alpaca calendar) -> no events", day)
                self._logged_day = day
            return ran
        cfg = self.cache.get(now)
        events = self.events_for(day, sess, cfg)
        if self._logged_day != day:
            log.info("btd scheduler [%s/%s]: session %s %s-%s ET; events %s", self.runner.instance, self.runner.role,
                     day, sess["open"].strftime("%H:%M"), sess["close"].strftime("%H:%M"),
                     ", ".join(f"{e.key}@{e.at.astimezone(ET):%H:%M:%S}" for e in events))
            self._logged_day = day

        due, missed = due_events(events, {k[1] for k in self._done}, now, sess)
        for e in missed:
            self._done.add((day, e.key))
            log.warning("btd scheduler: missed %s (due %s ET, now %s ET) -> skipped", e.key,
                        e.at.astimezone(ET).strftime("%H:%M:%S"), now.strftime("%H:%M:%S"))
        for e in due:
            first_entry = e.kind == "entry" and not any(k[1].startswith("entry") for k in self._done)
            cfg = self.cache.get(now, at_event=e.kind in ("open", "close") or first_entry)
            self._done.add((day, e.key))
            res = run_with_watchdog(lambda: self.runner.run([e.kind], cfg), self.event_timeout_s, e.key)
            log.info("btd scheduler: %s done (acted=%s reason=%s code=%s orders=%d, config v%s)", e.key,
                     getattr(res, "acted", None), getattr(res, "reason", ""), getattr(res, "code", None),
                     len(getattr(res, "orders", []) or []), cfg.version)
            if getattr(res, "lease", None) is not None and res.lease.ok:
                self._last_hb = now
            ran.append(e.key)

        if heartbeat_due(sess, now, self._last_hb, self.heartbeat_min):
            self._last_hb = now
            lr = run_with_watchdog(self.runner.heartbeat, 60, "heartbeat")
            log.info("btd heartbeat [%s/%s]: ok=%s act=%s %s", self.runner.instance, self.runner.role,
                     lr.ok, lr.act, lr.reason)
            ran.append("heartbeat")
            open_ev = next(e for e in events if e.kind == "open")
            if (lr.ok and lr.act and self.runner.execute and (day, "open-catchup") not in self._done
                    and needs_open_catchup(lr.state, day, now, sess, open_ev)):
                self._done.add((day, "open-catchup"))  # at most once per session per process
                cfg = self.cache.get(now, at_event=True)
                log.warning("btd scheduler: lease held but no open event today in the DB state -> catch-up open")
                run_with_watchdog(lambda: self.runner.run(["open"], cfg), self.event_timeout_s, "open-catchup")
                self._done.add((day, "open"))
                ran.append("open-catchup")
        return ran

    def loop(self) -> None:
        log.info("btd scheduler started [%s/%s] live=%s poll=%ss heartbeat=%smin event-timeout=%ss lease-ttl=%smin "
                 "takeover=%smin", self.runner.instance, self.runner.role, self.runner.execute, self.poll_s,
                 self.heartbeat_min, self.event_timeout_s, self.runner.a.lease_ttl_min, self.runner.a.takeover_min)
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                log.exception("btd scheduler tick failed: %s", exc)
            self.stop.wait(self.poll_s)
        log.info("btd scheduler stopped")

    def install_signals(self) -> None:
        def hup(_s, _f):
            self.cache.force = True
            log.info("btd scheduler: SIGHUP -> strategy config reload on the next tick")
        def term(_s, _f):
            log.info("btd scheduler: stop requested"); self.stop.set()
        signal.signal(signal.SIGHUP, hup)
        signal.signal(signal.SIGTERM, term)
        signal.signal(signal.SIGINT, term)


__all__ = ["ConfigCache", "Event", "Scheduler", "due_events", "heartbeat_due", "needs_open_catchup",
           "session_events"]

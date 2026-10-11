#!/usr/bin/env python3
"""Keeps exactly one scripts/user_live_scheduler.py child per runnable user activation (live AND paper).
State lives only in Postgres (alpatrade.user_strategy_activations), so a supervisor/app restart
re-creates every child on its next poll.

  python scripts/user_live_supervisor.py            # dry-run children (no orders)
  python scripts/user_live_supervisor.py --live     # children trade the users' own accounts

Separate OS service from the operator scheduler (never started, stopped or signalled by it and
vice versa). Global kill switch: USER_LIVE_TRADING_ENABLED must be "1" (re-read every poll from
the environment AND the repo .env); when it is not, all children are stopped and none started.
Per-user: status 'paused' keeps the child (exits only), 'deactivated' stops it.
"""
import argparse, logging, os, signal, subprocess, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from dotenv import dotenv_values  # noqa: E402

from utils.user_live_runner import FLAG, RUNNABLE, flag_on  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true")
ap.add_argument("--poll", type=float, default=60.0)
ap.add_argument("--once", action="store_true", help="one reconcile pass, print the plan, exit (no children)")
a = ap.parse_args()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [user-supervisor] %(message)s")
log = logging.getLogger("user-supervisor")


def env():
    return {**dotenv_values(os.path.join(REPO, ".env")), **os.environ}


def wanted(db_url, operator_account):
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with eng.connect() as c:
            rows = c.execute(text("SELECT id, account_ref, cid_prefix, status, mode FROM alpatrade.user_strategy_activations "
                                  "WHERE mode IN ('live', 'paper') AND cid_prefix IS NOT NULL AND status = ANY(:st)"),
                             {"st": list(RUNNABLE)}).fetchall()
    finally:
        eng.dispose()
    return {int(r[0]): r for r in rows if str(r[1]) != str(operator_account or "")}


children = {}
backoff = {}


def stop(aid, why):
    p = children.pop(aid, None)
    if p and p.poll() is None:
        log.info("stopping activation %s (%s)", aid, why)
        p.terminate()
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()


def term(*_):
    for aid in list(children):
        stop(aid, "supervisor exit")
    sys.exit(0)


signal.signal(signal.SIGTERM, term); signal.signal(signal.SIGINT, term)
while True:
    e = env()
    try:
        if not flag_on(e):
            for aid in list(children):
                stop(aid, f"{FLAG} != 1")
            log.info("%s is off -> no user live runners", FLAG)
        else:
            want = wanted(e["DATABASE_URL"], e.get("ALPACA_LIVE_ACCOUNT"))
            log.info("%d runnable user live activation(s): %s", len(want), sorted(want))
            for aid in list(children):
                if aid not in want:
                    stop(aid, "deactivated")
            for aid, r in want.items():
                p = children.get(aid)
                if p and p.poll() is None:
                    continue
                if p is not None:
                    log.warning("activation %s exited with %s -> restart after backoff", aid, p.returncode)
                    children.pop(aid, None); backoff[aid] = time.time() + min(600, 30 * 2 ** min(5, backoff.get(f"n{aid}", 0)))
                    backoff[f"n{aid}"] = backoff.get(f"n{aid}", 0) + 1
                if time.time() < backoff.get(aid, 0):
                    continue
                cmd = [sys.executable, os.path.join(REPO, "scripts", "user_live_scheduler.py"),
                       "--activation-id", str(aid)] + (["--live"] if a.live else [])
                if a.once:
                    log.info("would start: %s (account %s prefix %s status %s)", " ".join(cmd[1:]), r[1], r[2], r[3])
                    continue
                log.info("starting activation %s (account %s, prefix %s, %s)", aid, r[1], r[2],
                         ("PAPER" if r[4] == "paper" else "LIVE") if a.live else "dry-run")
                children[aid] = subprocess.Popen(cmd, cwd=REPO, start_new_session=True)
    except Exception as exc:  # noqa: BLE001 -- never die; children keep running
        log.error("reconcile failed: %s", type(exc).__name__)
    if a.once:
        break
    time.sleep(a.poll)

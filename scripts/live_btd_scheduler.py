#!/usr/bin/env python3
"""Long-running in-memory event scheduler for the live Mag-7 BTD runner (one per machine).

  python scripts/live_btd_scheduler.py --live          # HP / Mac / box (role from BTD_ROLE)
  python scripts/live_btd_scheduler.py                 # dry run: same events, no orders

Started and kept alive by the OS supervisor only (systemd Restart=always on the HP, launchd
KeepAlive on the Mac, deploy/box/btd-keepalive.sh on the box); all timing lives here.
Reload the strategy config: `kill -HUP <pid>` or `python scripts/live_btd_config.py bump`.
See docs/strategy_methodology.md.
"""
import fcntl, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.live_btd_runner import PassStop, Runner, build_parser, setup_logging, state_dir  # noqa: E402
from utils.live_btd_scheduler import ConfigCache, Scheduler, db_version_fn  # noqa: E402

a = build_parser().parse_args()
if a.ignore_hours:
    sys.exit("--ignore-hours is not supported by the scheduler")
log = setup_logging()
lock = open(os.path.join(state_dir(), "scheduler.lock"), "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit("another live_btd_scheduler is already running on this machine")
try:
    runner = Runner(a, log)
except PassStop as s:
    sys.exit(s.code)
def _load():
    from utils.live_btd_config import resolve
    return resolve(runner.strategy, runner.cli_overrides(), database_url=runner.db_url)


cache = ConfigCache(_load, db_version_fn(runner.db_url, runner.strategy), log_fn=runner.log_config)
sched = Scheduler(runner, cache)
sched.install_signals()
sched.loop()

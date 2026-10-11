#!/usr/bin/env python3
"""ONE user's live strategy (one activation) in its own long-running process.

  python scripts/user_live_scheduler.py --activation-id 7            # dry run: same events, no orders
  python scripts/user_live_scheduler.py --activation-id 7 --live     # trades the USER's live account
  python scripts/user_live_scheduler.py --activation-id 7 --paper    # dry run against the user's PAPER keys
  python scripts/user_live_scheduler.py --activation-id 7 --event entry --ignore-hours   # one dry pass

Started by scripts/user_live_supervisor.py (one child per activation); never by the operator
scheduler. State/log: $BTD_STATE_DIR/users/<prefix>/ (own flock, own logs/btd.log).
"""
import fcntl, logging, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.live_btd_runner import PassStop, build_parser  # noqa: E402

p = build_parser()
p.add_argument("--activation-id", type=int, required=True)
p.add_argument("--paper", action="store_true", help="use the user's PAPER keys/endpoint (testing)")
p.add_argument("--seed", action="store_true", help="create this activation's lease/state row and exit")
a = p.parse_args()
if a.paper and a.live:
    sys.exit("--paper is for dry-run testing only")

from utils.user_live_runner import UserRunner  # noqa: E402

try:
    runner = UserRunner(a, a.activation_id, logging.getLogger(f"btd.user.{a.activation_id}"), paper=a.paper)
except PassStop as s:
    sys.exit(f"not starting: {s.code}")
os.makedirs(os.path.join(runner.here, "logs"), exist_ok=True)
fmt = logging.Formatter("%(asctime)s %(levelname)s [user %(name)s] %(message)s")
root = logging.getLogger(); root.setLevel(logging.INFO)
for h in (logging.StreamHandler(), logging.FileHandler(os.path.join(runner.here, "logs", "btd.log"))):
    h.setFormatter(fmt); root.addHandler(h)
lock = open(os.path.join(runner.here, "scheduler.lock"), "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit("this activation already runs on this machine")
try:
    acct = runner.verify_account()
except PassStop as s:
    sys.exit(f"not starting: {s.code}")
runner.log.info("user runner activation=%s prefix=%s account=%s allocation=$%.2f live=%s paper=%s instance=%s/%s",
                runner.act.id, runner.act.cid_prefix, acct, runner.act.allocation_usd, runner.execute, runner.paper,
                runner.instance, runner.role)
if a.seed or runner.execute:
    runner.log.info("state row %s", "created" if runner.ensure_seeded() else "already exists")
    if a.seed:
        sys.exit(0)
if a.event != "auto" or a.ignore_hours:
    ev = ["entry"] if a.event == "auto" else [a.event]
    res = runner.run(ev, runner.load_config())
    runner.log.info("single pass %s -> code=%s reason=%s orders=%d", ev, res.code, res.reason, len(res.orders))
    sys.exit(0)

from utils.live_btd_scheduler import ConfigCache, Scheduler  # noqa: E402
cache = ConfigCache(lambda: runner.load_config(), runner.version, check_every_min=5, log_fn=runner.log_config)
sched = Scheduler(runner, cache)
sched.install_signals()
sched.loop()

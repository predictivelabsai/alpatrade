# Live Mag-7 buy-the-dip with true min-hold (`scripts/live_btd_minhold.py`)

Standalone runner for the LIVE Alpaca account. It is **not** imported by the web app/API
and **not** started by `docker-compose.yaml`, so deploying alpatrade.chat never runs it.
Nothing trades unless you pass `--live`.

> **Methodology, event scheduler, supervisors and config:** see
> [`docs/strategy_methodology.md`](strategy_methodology.md). This page keeps the operational
> details (failover protocol, recording, read-only account view).

Strategy parameters live in the DB (`alpatrade.strategy_configs`, row
`buy_the_dip_mag7_minhold_live`): Mag-7, dip ≥3% vs the 20-day high, TP +8%, SL −1.5%,
min-hold = max-hold = 3 calendar days, 1/7 of equity per position, cash only. The runner only
manages positions it opened (authoritative state in `alpatrade.live_runner_state`;
`$BTD_STATE_DIR/state.json`, default `~/.alpatrade-live`, is a local cache only); pre-existing
positions are ignored but block a new entry in that symbol.

The logic is `utils/live_btd_runner.py`, driven by one long-running in-memory event scheduler
per machine (`scripts/live_btd_scheduler.py`): 09:31 ET broker-side TP/SL (OCO + stop) for
positions past the min-hold, 15:45/15:50/15:55 ET entries, ~15:58 ET max-hold exits,
16:03 ET recording, plus a 3-minute DB-lease heartbeat. No cron, no timers, no 5-minute scans.

```bash
# single dry-run pass (no orders); --event auto picks by the clock
.venv/bin/python scripts/live_btd_minhold.py --event entry --ignore-hours
# the scheduler in dry-run mode (same events, no orders)
.venv/bin/python scripts/live_btd_scheduler.py
```

## Supervisors (start + keep alive only)

| machine | role | supervisor | file |
|---|---|---|---|
| HP | primary | systemd user service, `Restart=always` (no timer) | `deploy/systemd/alpatrade-btd-scheduler.service` |
| Mac.home | backup | launchd agent, `KeepAlive` + `RunAtLoad` (no calendar interval) | `deploy/launchd/com.predictivelabs.alpatrade-btd.plist` |
| agent box | tertiary | `setsid nohup` + `flock` keep-alive loop (no systemd/cron on the box) | `deploy/box/btd-keepalive.sh` |

Logs: `~/.alpatrade-live/logs/btd.log` (runner + scheduler) and the supervisor's own log
(`journalctl --user -u alpatrade-btd-scheduler`, `launchd.*.log`, box `logs/loop.log`).

## Failover: HP primary + Mac backup + box tertiary (`utils/live_btd_state.py`)

Three instances run the same event scheduler: the HP workstation
(systemd service above, `BTD_ROLE=primary`, `BTD_INSTANCE=hp`), Mac.home (launchd,
`BTD_ROLE=backup`, `BTD_INSTANCE=mac`), and the agent Linux box (`BTD_ROLE=tertiary`,
`BTD_INSTANCE=box`). They coordinate only through Postgres:

| table | content |
|---|---|
| `alpatrade.live_runner_state` | one row per runner (`buy_the_dip_mag7_minhold_live:<account>`): JSON state (owned positions, pending orders, last entries, `rec.run_id` + start equity/SPY) + `version` + leader lease (holder, host, role, acquired/expires) |
| `alpatrade.live_runner_heartbeats` | one row per instance: last live pass, last acting pass, decision (`act/renew/takeover/standby/handback/holdoff/missing`), code version |

Priority order: **primary > backup > tertiary**. Per `--live` pass, one transaction locks the
state row (`SELECT … FOR UPDATE`, DB clock):
- a live lease held by another instance → stand by;
- **primary** → act (take/renew the 8-min lease);
- **backup** → act only if the primary's last heartbeat is older than 12 min (`--takeover-min`)
  or it already holds the lease; hands back as soon as the primary is fresh again;
- **tertiary** → act only if BOTH primary and backup heartbeats are older than 12 min (or it
  already holds the lease); hands back as soon as either higher role is fresh again;
- no takeover by backup/tertiary during 09:00–09:12 ET (the primary's heartbeat is from the
  previous session);
- every live pass writes its heartbeat in that transaction; the acting instance writes the state
  back after every order and at the end, only while it still holds the lease, and stops submitting
  orders once its local lease deadline (TTL − 60 s) has passed;
- missing state row → nobody trades (seed it: `--seed-state --seed-run-id <run uuid>`).

**DB unreachable** (chosen policy): the instance cannot prove it is alone, so it never buys.
It may still sell positions from its local cache, and only if its last decided pass held the lease
(a standby instance does nothing). Exit client ids are deterministic (`btdx-SYM-YYYYMMDD`), so an
exit submitted by both instances is rejected as a duplicate by Alpaca; changes made in this mode
are merged back into the DB state (positions/pending union) when it returns.

**Before every buy** the runner re-checks Alpaca for a position, an open order, or an order that
already used today's client id `btd-SYM-YYYYMMDD` in that symbol; any lookup error skips the buy.
A basket position whose latest fill is a runner entry (`btd-SYM-YYYYMMDD`) but which is missing
from the state is re-adopted; anything else stays pre-existing (ignored, blocks an entry).

**Dry run** reads the DB state and logs what a live pass would decide; it never takes the lease or
writes a heartbeat. Passes outside Mon–Fri 09:00–16:05 ET exit immediately (`--any-time` overrides;
orders still require `/v2/clock` open). The event scheduler only calls the runner at event times.

Mac (launchd KeepAlive agent running the scheduler; the scheduler handles the ET session):
```bash
sed "s#/Users/juliankaljuvee#$HOME#g" deploy/launchd/com.predictivelabs.alpatrade-btd.plist \
  > ~/Library/LaunchAgents/com.predictivelabs.alpatrade-btd.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.predictivelabs.alpatrade-btd.plist
launchctl print gui/$(id -u)/com.predictivelabs.alpatrade-btd | head   # status
# off: launchctl bootout gui/$(id -u)/com.predictivelabs.alpatrade-btd
pmset -g | grep -E ' sleep'   # must be 0 on AC power, else: sudo pmset -c sleep 0
```
Inspect: `SELECT * FROM alpatrade.live_runner_heartbeats;` and `SELECT runner_key, run_id, version,
lease_holder, lease_expires_at, state FROM alpatrade.live_runner_state;`

## Recording in AlpaTrade (alpatrade.chat → Trade → Live runs, `/live`)

`--live` passes write, best-effort, to the app DB (`DATABASE_URL`) under the AlpaTrade user
`$BTD_USER_EMAIL` (default `kaljuvee@gmail.com`; if no such user exists recording is disabled,
never created):

| table | content |
|---|---|
| `alpatrade.runs` | one row, `mode='live'`, strategy "Mag-7 BTD min-hold 3d", config = params + account number; `results.latest` each pass, `results.daily[<session date>]` once per day after the close |
| `alpatrade.trades` | `trade_type='live'`, one row per round trip keyed by entry `client_order_id` (submitted → filled → exited, with P&L) |
| `alpatrade.positions` | runner-owned open/closed positions |
| `alpatrade.pnl_summary` | aggregate row (symbol NULL) |

`account_id` stays NULL (the live account is not linked in `user_accounts`). The run id is kept
in the DB state (`alpatrade.live_runner_state.state.rec.run_id`, cached in `state.json`). Any DB error logs a warning and disables recording
for that pass only. Verify DB access without trading: `scripts/live_btd_minhold.py --record-test`.

## Read-only live account view (`/live/account`)

Sidebar → Trade → **Live account** shows the signed-in user's linked Alpaca LIVE
account: equity, cash, buying power, day P&L (equity − last_equity), positions and
open orders. It is strictly read-only:

- `engine/brokers/alpaca_live_readonly.py` issues only `GET /v2/account`,
  `GET /v2/positions`, `GET /v2/orders?status=open` against the fixed host
  `https://api.alpaca.markets`, and refuses to render if the returned account number
  differs from the linked one. (Alpaca has no read-only trading keys, so this is
  enforced in code.)
- Keys live Fernet-encrypted in `alpatrade.user_live_broker_accounts`
  (`sql/35_live_broker_accounts.sql`, `read_only` CHECK-constrained TRUE), a table
  separate from `alpatrade.user_accounts`, so chat trading tools, paper jobs,
  reconcile/cleanup and the account switcher never see them.
- `AlpacaAPI` order/cancel/close methods refuse non-paper clients, and
  `store_alpaca_keys` refuses live (`AK…`) key IDs.

Link / re-link (e.g. after regenerating keys) from a checkout whose `.env` has the
prod `DATABASE_URL`/`ENCRYPTION_KEY` and `ALPACA_LIVE_*`:

    python run_migration.py sql/35_live_broker_accounts.sql   # once
    python scripts/link_live_account.py --email you@example.com --check
    python scripts/link_live_account.py --email you@example.com
    python scripts/link_live_account.py --email you@example.com --unlink

Local UI testing: start the app with `ALPATRADE_DEV_LOGIN=1` and open
`http://localhost:5001/dev/login?email=...` (route only exists with that env var and
only answers loopback clients with a localhost Host header; never set it in prod).


## Strategy config (`alpatrade.strategy_configs`, `utils/live_btd_config.py`)

Migration: `python run_migration.py sql/40_strategy_configs.sql` (idempotent; the seed row
is `ON CONFLICT DO NOTHING`, so re-running never overwrites edits).

| column | content |
|---|---|
| `name` | lookup key; the runner uses `--strategy <name or id>`, else `$BTD_STRATEGY`, else `buy_the_dip_mag7_minhold_live` |
| `params` | `symbols, dip, tp, sl, min_hold, max_hold, pos_frac, max_exposure, ref, feed, entry_window, close_window` |
| `execution` | `regular_hours_exit` (market, day) and `extended_hours_exit` (see below) |
| `version` | bump on every edit; logged on every pass and snapshotted with the source into the run config |

Precedence per key: explicit CLI flag (testing / one-off) > DB row > code defaults.
Every pass logs `strategy config [instance/role]: source=db:alpatrade.strategy_configs#<id> <name> v<n>
params=… sources=… execution=…`. If the row cannot be read (DB unreachable, missing/inactive row,
invalid values) the pass uses the code defaults, logs a warning, and a `--live` pass **places no
entries** (exits still run). Edit params with SQL, e.g.

```sql
UPDATE alpatrade.strategy_configs
SET params = params || '{"pos_frac": 0.142857}', version = version + 1, updated_at = NOW(), updated_by = 'julian'
WHERE name = 'buy_the_dip_mag7_minhold_live';
```

**Exit execution.** Regular session: market, DAY. Extended/overnight session (market closed,
pre-market / post-market / overnight on a trading night): `limit` at `bid × (1 − discount_bps/10000)`
(default 15 bps, rounded down to the tick), `extended_hours=true`, DAY; reprice to the current bid
discount after `reprice_after_min` (5) minutes, at most `max_reprices` (2) times; when the regular
session opens, cancel and sell the remainder with a DAY market order. Off unless
`execution.extended_hours_exit.enabled` is `true` (seeded `false`). The scheduler's exit events
(09:31 and ~15:58 ET) are in the regular session, so the extended-hours path is only used by a
manual pass run outside it (`--event close --any-time`).

**Broker-side TP/SL.** See `docs/strategy_methodology.md`: at the 09:31 ET open event the runner
places DAY exit orders for positions past the min-hold (OCO for whole shares + stop for the
fraction; one stop for the full qty if the OCO is rejected), never on the buy date.

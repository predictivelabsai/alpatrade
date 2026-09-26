# Live Mag-7 buy-the-dip with true min-hold (`scripts/live_btd_minhold.py`)

Standalone runner for the LIVE Alpaca account. It is **not** imported by the web app/API
and **not** started by `docker-compose.yaml`, so deploying alpatrade.chat never runs it.
Nothing trades unless you pass `--live`.

Strategy defaults: AAPL MSFT GOOGL AMZN META TSLA NVDA; buy when price is ≥3% below the
20-bar high (same reference as `utils/buy_the_dip.py`; `--ref prev_close` for a
close-to-close dip); TP +8%, SL −1.5%, min-hold 3 calendar days (TP/SL cannot fire
earlier), max-hold 3 calendar days (exit in the last minutes of the first session on/after day 3).
Sizing: 10% of equity per position (`--pos-frac 0.142857` = 1/7), notional/fractional
market orders, one position per symbol, cash only (≤ min(cash, non_marginable_buying_power)).
The runner only manages positions it opened (authoritative state in the AlpaTrade DB,
`alpatrade.live_runner_state`; `$BTD_STATE_DIR/state.json`, default `~/.alpatrade-live`, is a
local cache only); pre-existing positions are ignored but block a new entry in that symbol.

Each run = one idempotent pass (flock, deterministic `client_order_id`s, state file):
exits all session, entries only 15→5 min before the close (reads `/v2/clock`, so half-days work).

```bash
# dry run (no orders); --ignore-hours evaluates as if in the entry window
.venv/bin/python scripts/live_btd_minhold.py --ignore-hours
```

## Switching it on (manual, not done by CI)

`~/.config/systemd/user/alpatrade-btd.service`
```ini
[Unit]
Description=AlpaTrade live Mag-7 BTD min-hold pass
[Service]
Type=oneshot
WorkingDirectory=%h/dev/plai/alpatrade
ExecStart=%h/dev/plai/alpatrade/.venv/bin/python scripts/live_btd_minhold.py --live
```
`~/.config/systemd/user/alpatrade-btd.timer`
```ini
[Unit]
Description=Every 5 min in US market hours
[Timer]
OnCalendar=Mon..Fri *-*-* 09..15:00/5:00 America/New_York
Persistent=false
[Install]
WantedBy=timers.target
```
```bash
systemctl --user daemon-reload && systemctl --user enable --now alpatrade-btd.timer
loginctl enable-linger $USER   # keep user timers running when logged out
# off:  systemctl --user disable --now alpatrade-btd.timer
```
Logs: `~/.alpatrade-live/logs/btd.log` and `journalctl --user -u alpatrade-btd`.

## Failover: HP primary + Mac backup (`utils/live_btd_state.py`)

Two instances may run the same `--live` pass every 5 minutes: the HP workstation
(systemd timer above, `BTD_ROLE` unset = `primary`) and Mac.home (launchd,
`BTD_ROLE=backup`, `BTD_INSTANCE=mac`). They coordinate only through Postgres:

| table | content |
|---|---|
| `alpatrade.live_runner_state` | one row per runner (`buy_the_dip_mag7_minhold_live:<account>`): JSON state (owned positions, pending orders, last entries, `rec.run_id` + start equity/SPY) + `version` + leader lease (holder, host, role, acquired/expires) |
| `alpatrade.live_runner_heartbeats` | one row per instance: last live pass, last acting pass, decision (`act/renew/takeover/standby/handback/holdoff/missing`), code version |

Per `--live` pass, one transaction locks the state row (`SELECT … FOR UPDATE`, DB clock):
- a live lease held by another instance → stand by;
- **primary** → act (take/renew the 8-min lease);
- **backup** → act only if the primary's last heartbeat is older than 12 min (`--takeover-min`)
  or it already holds the lease; as soon as the primary heartbeats again (its standby passes
  still write heartbeats) the backup expires its lease and the primary resumes on its next pass.
  No takeover during 09:00–09:12 ET (the primary's heartbeat is from the previous session).
- every live pass writes its heartbeat in that transaction; the acting instance writes the state
  back after every order and at the end, only while it still holds the lease, and stops submitting
  orders once its local lease deadline (TTL − 60 s) has passed.
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
orders still require `/v2/clock` open), so schedulers can fire every 5 minutes.

Mac (launchd; fires every 5 min in local time, the script handles the ET session):
```bash
sed "s#__REPO__#$HOME/dev/plai/alpatrade#g; s#__HOME__#$HOME#g" deploy/launchd/com.predictivelabs.alpatrade-btd.plist \
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

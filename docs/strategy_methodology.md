# Live Mag-7 buy-the-dip: methodology and operations

All times are **US Eastern (ET)**. Code: `utils/live_btd_runner.py` (pass logic),
`utils/live_btd_scheduler.py` + `scripts/live_btd_scheduler.py` (event scheduler),
`utils/live_btd_exits.py` (broker-side exits), `utils/live_btd_config.py` (DB config),
`utils/live_btd_state.py` (failover), `utils/live_btd_store.py` (recording). Operational
details: [`docs/live_btd_minhold.md`](live_btd_minhold.md).

## 1. Strategy rules

| rule | value |
|---|---|
| universe | Mag-7: AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA |
| signal | last price ≥ **3%** below the **20-day high**: the max of the last 20 daily-bar intraday highs, today's partial bar included (`ref: high20`, same as `utils/buy_the_dip.py`) |
| entry window | **15:45–15:55 ET** (close − 15 → close − 5 min; from the Alpaca calendar, so early closes shift it) |
| sizing | **1/7 of equity** per position (`pos_frac 0.142857`), notional/fractional market buy, one position per symbol, cash only (≤ min(cash, non-marginable buying power)), no exposure cap |
| take profit | **+8%** vs the average entry price |
| stop loss | **−1.5%** vs the average entry price |
| min hold | **3 calendar days** (ET dates): TP/SL may not act earlier |
| max hold | **3 calendar days**: anything still held is sold in the close window (~15:58 ET) of the first session on or after day 3 |
| close window | 15:45–15:58 ET (`close_window 15-2`); the scheduler fires the max-hold exit at ~15:57–15:58 |
| scope | the runner manages only positions it opened; pre-existing positions are ignored but block a new entry in that symbol |

With min-hold = max-hold = 3, a position bought on day D can only be sold from day D+3
(the first session on or after it), via broker-side TP/SL from the 09:31 open, or at market
in that day's close window.

### PDT safety: never sell on the buy date

A position is never sold on its buy date, whatever the config: exit eligibility requires
`entry_date < today` **and** `(today − entry_date).days ≥ min_hold`
(`utils/live_btd_exits.exit_eligible`). The max-hold path has the same guard ("PDT guard
refuses same-day exit"). Broker-side exit orders are only created at the open event of an
eligible day, and they are DAY orders, so they can never exist on the buy date. (FINRA retired
the PDT rule and Alpaca removed `daytrade_count` on 2026-07-06; the guard stays as a design
invariant.) Tests: `tests/test_live_btd_exits.py`, `tests/test_live_btd_scheduler.py`.

## 2. Config table `alpatrade.strategy_configs`

Migrations: `sql/40_strategy_configs.sql` (table + seed) and `sql/41_strategy_config_versioning.sql`
(version trigger + NOTIFY). Both are idempotent.

| column | type | content |
|---|---|---|
| `id` | serial PK | numeric lookup (`--strategy 1`) |
| `name` | varchar(96), unique | lookup key; default `buy_the_dip_mag7_minhold_live` (`--strategy` / `$BTD_STRATEGY`) |
| `display_name`, `description` | text | labels |
| `params` | jsonb | `symbols, dip, tp, sl, min_hold, max_hold, pos_frac, max_exposure, ref, feed, entry_window, close_window` |
| `execution` | jsonb | `regular_hours_exit`, `extended_hours_exit` (§3) |
| `is_active` | bool | inactive row means not loaded (defaults, no entries) |
| `version` | int | bumped on every edit by the trigger; logged on every load and pass |
| `created_at`, `updated_at`, `updated_by` | audit | |

Seeded row (id 1, v1). These are exactly the params that were in effect on the HP primary
(systemd `--live --pos-frac 0.142857` plus the script defaults):

```json
{"symbols": ["AAPL","MSFT","GOOGL","AMZN","META","TSLA","NVDA"], "dip": 3.0, "tp": 8.0, "sl": 1.5,
 "min_hold": 3, "max_hold": 3, "pos_frac": 0.142857, "max_exposure": 0.0, "ref": "high20",
 "feed": "iex", "entry_window": "15-5", "close_window": "15-2"}
```
```json
{"regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
 "extended_hours_exit": {"enabled": false, "order_type": "limit", "limit_ref": "bid", "discount_bps": 15,
                         "reprice_after_min": 5, "max_reprices": 2, "fallback": "market_day_at_regular_open"}}
```

**Precedence**, per key: explicit CLI flag (testing only) > DB row > code defaults
(`DEFAULT_PARAMS`; note the code default for `pos_frac` is 10%). If the row cannot be read (DB
unreachable, row missing or inactive, invalid values), the pass uses the defaults, logs a
warning, and a live pass **places no buys**. Sells still run.

**Caching and reload.** Each scheduler loads the row once at start and caches it. It compares
only the `version` column (one cheap `SELECT version`) every 15 minutes and at the open, first
entry and close events, and does a full re-read only when the version changed. It also reloads
on SIGHUP. Every load and reload is logged with the source, params, execution settings and
`vOLD -> vNEW`.

Edit and force a reload:

```bash
python scripts/live_btd_config.py show
python scripts/live_btd_config.py set pos_frac=0.142857 tp=8          # validated; trigger bumps version
python scripts/live_btd_config.py set --execution extended_hours_exit.discount_bps=15
python scripts/live_btd_config.py bump    # version+1 only: all three machines reload within 15 min / next event
# immediate, one machine:
systemctl --user reload alpatrade-btd-scheduler                      # HP (SIGHUP)
launchctl kill HUP gui/$(id -u)/com.predictivelabs.alpatrade-btd    # Mac
pkill -HUP -f live_btd_scheduler.py                                  # box
```
Plain SQL works too (the trigger bumps `version` and fires
`NOTIFY strategy_config_changed '<name>:<version>'`):
```sql
UPDATE alpatrade.strategy_configs SET params = params || '{"tp": 8}', updated_by = 'julian'
WHERE name = 'buy_the_dip_mag7_minhold_live';
```
LISTEN/NOTIFY is emitted but not consumed yet. A persistent LISTEN connection from three home
machines adds reconnect and keepalive complexity for edits that are rare, so the version check is
the mechanism. NOTIFY is there for a future listener.

## 3. Execution

| situation | order |
|---|---|
| entries | notional **market**, DAY, `client_order_id btd-SYM-YYYYMMDD`; Alpaca is re-checked first (no position, no open order, cid unused) |
| broker-side TP/SL (open event, position past min-hold) | whole shares: **OCO** (`order_class=oco`, TP limit at entry × 1.08 rounded up, stop at entry × 0.985 rounded down), DAY, `btdtp-SYM-date`; fractional remainder: **stop** at the SL price, DAY, `btdsl-SYM-date` |
| OCO rejected | fallback: one **stop** for the full qty (`btdsl-…`) |
| TP/SL already hit at the open (Alpaca unrealized P&L ≥ +8% or ≤ −1.5%) | immediate **market** sell, DAY (`btdx-…`) |
| max-hold, regular hours (close event) | cancel the runner's own `btdtp-/btdsl-` orders, wait for the cancel, re-read the position, then **market** sell `qty_available`, DAY (`btdx-…`) |
| extended / overnight exit (manual pass outside RTH, if `extended_hours_exit.enabled`) | **limit** at bid × (1 − 15 bps), rounded down to the tick, `extended_hours=true`, DAY; reprice to the current bid − 15 bps after 5 min, max 2 reprices; at the regular open, cancel and sell the remainder at DAY market |

Why the fraction gets only a stop: Alpaca does not support OCO or bracket orders for fractional
quantities. Fractional limit and stop orders are DAY-only, and a second sell order for the same
shares is rejected for insufficient quantity. So the whole-share part gets the full OCO, and the
fraction (always < 1 share) gets the protective leg. Its upside is realised by the max-hold sell
at the close event, the same day. Because all exit orders are DAY orders (a fractional
requirement), they expire at the close and are re-placed at the next open while the position is
held. Before every order the runner re-reads the Alpaca position and the open orders for that
symbol and skips on any mismatch or foreign sell order. Deterministic client order ids make every
event idempotent across restarts and failovers.

OCO on the live account is implemented per Alpaca's docs and has not yet been exercised live.
The OCO-rejected fallback covers a rejection.

## 4. In-memory event scheduler

One long-running Python process per machine: `scripts/live_btd_scheduler.py --live`. It follows the
same pattern as the email report schedulers in `engine/autonomy/schedule.py`: a poll loop
(`threading.Event().wait`, 5 s); the Alpaca calendar as the authority for holidays, early closes
and DST (`scripts.daily_live_report.session_for`, cached per ET date, with `None` cached for
non-trading days); due checks with `engine.autonomy.schedule.advisor_is_due`; and an in-memory
done-set per session date. Cross-machine idempotency comes from a DB claim: the runner's lease
transaction plus deterministic client order ids, playing the role of `live_report_deliveries`.
Each tick's exceptions are logged and the loop continues. A pass that hangs longer than 240 s
kills the process, and the supervisor restarts it.

| event | time (regular day) | early close (13:00) | does |
|---|---|---|---|
| heartbeat | every 3 min, 09:00–16:05 | 09:00–13:05 | DB lease renew + heartbeat only; **no Alpaca calls, no scans** |
| open | 09:31:00 | 09:31:00 | broker-side TP/SL for eligible positions (§3) |
| entry-15 / -10 / -5 | 15:45:45 / 15:50:00 / 15:54:15 | 12:45:45 / 12:50 / 12:54:15 | dip check + buys |
| close | 15:57:15 (~15:58) | 12:57:15 | max-hold exits (cancel OCO/stop first) |
| post | 16:03:00 | 13:03:00 | record fills, daily performance snapshot; no orders |

- The entry and close times sit 45 s inside the configured windows, so a slightly late tick still
  passes the runner's own window check.
- The backup and tertiary fire each event 10 s and 20 s after the primary. This is cosmetic: the
  lease already decides who acts.
- A missed event runs late only within a grace period: entry 4 min, close 40 s, post 10 min. The
  open event can catch up until 30 min before the close.
- If a heartbeat wins the lease (takeover) and the DB state shows no open event today, the open
  event is re-run once.
- Weekends and holidays: no events at all, one log line.

**Supervisors**. Their only job is to start the scheduler and keep it alive. There is no
scheduling logic in them:

| machine | role | supervisor |
|---|---|---|
| HP workstation | primary | systemd **user service** `alpatrade-btd-scheduler.service`, `Restart=always`, `RestartSec=15`, `ExecReload=kill -HUP` (`deploy/systemd/`); the old `alpatrade-btd.timer` is removed |
| Mac.home | backup | launchd agent `com.predictivelabs.alpatrade-btd`, `KeepAlive` + `RunAtLoad`, no `StartCalendarInterval` (`deploy/launchd/`) |
| agent box | tertiary | `loop.sh` = `deploy/box/btd-keepalive.sh`: `flock` + restart-on-exit loop started by `setsid nohup` from `ensure.sh` (the box has no systemd/cron) |

**Could it run in the prod autonomy container instead?** Not recommended as a replacement for
the three-tier setup:
- The autonomy worker is explicitly **paper-only**, and putting live-trading keys in the web
  stack weakens that wall.
- Every Coolify deploy restarts the container.
- Your rule is HP primary, Mac backup, box tertiary.

A reasonable later option is a separate, minimal `live-btd` container (not the autonomy process)
as an extra tertiary, using the same scheduler and lease.

## 5. Failover: HP primary, Mac backup, box tertiary

Implemented in `utils/live_btd_state.py`, with the authoritative state in
`alpatrade.live_runner_state` and heartbeats in `alpatrade.live_runner_heartbeats`. Every live
event and every heartbeat takes the lease in one transaction (`SELECT … FOR UPDATE`, DB clock):
- priority is primary > backup > tertiary; the lease TTL is 8 min;
- a lower role takes over only when every higher-priority heartbeat is older than **12 min**,
  and hands the lease back as soon as a higher role is fresh again;
- there is no takeover between 09:00 and 09:12;
- only the lease holder trades, and it stops submitting orders once its local lease deadline has
  passed.

With 3-minute heartbeats, a live primary always holds the lease (8 min > 2 heartbeats). A dead
primary is replaced after 12–15 min (simulated in `tests/test_live_btd_scheduler.py`). Because the
TP/SL orders sit at the broker, a primary failure during the day no longer delays a TP/SL
execution. Only the entry and close events depend on a live lease holder.

**DB unreachable**: the instance cannot prove it is alone, so it **never buys**. Exits run only
from the local cache, and only if this instance acted last. The same no-buy rule applies when the
strategy config was not loaded from the DB.

## 6. Monitoring and reporting

- **Hourly failover monitor**: checks `alpatrade.live_runner_heartbeats` and the lease (who holds
  it, heartbeat ages per instance) and alerts when the primary is stale or a backup holds the
  lease.
- **Daily live email** at about 16:20 ET (close + 20 min, `engine.autonomy.schedule` live-report
  scheduler, `scripts/daily_live_report.py`): one email per linked live account, to that account's
  owner only. Idempotent via `alpatrade.live_report_deliveries`.
- **Chat P&L digest** at 16:45 ET: a daily realised/unrealised P&L summary posted to chat.
- **Per-user report preferences** (`alpatrade.user_report_preferences`, set on `/settings`):
  `report_live_daily` (default ON) and `report_paper_daily` (default OFF). Opted-out owners are
  skipped and logged.
- The live run is recorded in `alpatrade.runs` / `trades` / `positions` / `pnl_summary`
  (`trade_type='live'`) and shown on alpatrade.chat under Trade → Live runs.

## 7. Backtest methodology and results so far

**Method.** Walk-forward over Yahoo daily bars (auto-adjusted), Mag-7 basket, $10k:
- 8 folds, each with **12 months of training and 6 months of out-of-sample testing**, rolling.
  The combined out-of-sample window is 2022-09-26 → 2026-09-29.
- TP/SL (and the trigger threshold, where tuned) are chosen in-sample by P&L, then traded unseen.
- Same exits, min-hold and 1/7 sizing as live.
- Benchmark: SPY buy-and-hold.
- Scripts: `scripts/scratch/btd_daily_trigger_wf.py` and `btd_adaptive_tp_wf.py` on the HP
  (research only, not committed); the earlier 8×(60d/30d) walk-forward is in
  `docs/walk_forward_btd_20260720T105423.md`.

**Baseline vs daily-drop triggers** (OOS, 0 bps slippage):

| strategy | P&L ($10k) | CAGR | Sharpe | Max DD | trades | win % |
|---|---:|---:|---:|---:|---:|---:|
| SPY buy & hold | $11,883 | +21.5% | 1.32 | −18.8% | 1 | – |
| **Live baseline** (20d-high dip ≥ 3%, TP 8 / SL 1.5, hold 3d) | **$15,927** | **+26.8%** | 1.18 | −27.1% | 1,998 | 49.7% |
| baseline, WF-tuned TP/SL | $16,595 | +27.6% | 1.21 | −25.5% | 1,998 | 51.5% |
| previous-day return ≤ −1% | $7,056 | +14.2% | 0.82 | −22.3% | 1,338 | 49.2% |
| previous-day return ≤ −1.5% | $6,911 | +14.0% | 0.87 | −20.8% | 1,044 | 49.6% |
| previous-day return ≤ −3% | $1,649 | +3.9% | 0.38 | −14.3% | 441 | 47.6% |
| same-day move ≤ −1% | $9,139 | +17.5% | 0.98 | −24.4% | 1,331 | 48.6% |
| same-day move ≤ −1.5% | $8,115 | +15.9% | 1.01 | −23.1% | 1,026 | 48.9% |
| same-day, WF-tuned X + TP/SL | $7,173 | +14.4% | 0.86 | −25.1% | 1,233 | 52.3% |

**The daily-drop triggers lost to the baseline at every threshold.** They trade less, with much
lower exposure, and earn about half or less. The 20-day-high reference stays.

**Slippage sensitivity** (live baseline, OOS 2022-09-28 → 2026-09-30; cells are P&L / CAGR / Sharpe):

| entry \ exit bps | 0 | 5 | 10 | 15 |
|---|---:|---:|---:|---:|
| 0 | $15,158 / +25.9% / 1.15 | $11,609 / +21.2% / 0.98 | $8,741 / +17.0% / 0.82 | $6,253 / +12.9% / 0.66 |
| 5 | $12,039 / +21.8% / 1.00 | $9,076 / +17.5% / 0.84 | $6,384 / +13.1% / 0.67 | $4,209 / +9.2% / 0.51 |
| 10 | $8,890 / +17.2% / 0.82 | $6,382 / +13.1% / 0.66 | $4,274 / +9.3% / 0.51 | $2,379 / +5.5% / 0.35 |

- Break-even round-trip cost vs SPY's P&L is **4.7 bps**. With about 2,000 round trips in four
  years, execution cost dominates.
- Longer max-holds and adaptive exits are more cost-robust: TP 8 with a 5-day max-hold breaks
  even at 9.6 bps; scale-out (WF-tuned, 20-day) at 15.2 bps.
- This is the main reason for the limit and extended-hours execution settings and for the
  adaptive-TP research.

### Adaptive-TP results (pending)

_Placeholder: the adaptive take-profit walk-forward (ATR / stdev / dip-depth / time-decay /
trailing / scale-out TP rules, max-hold 3–20 d, with cost sensitivity) is being finalised in a
separate task. Results and the go/no-go decision for changing the live row go here._

## 8. Oct 1, 2026: manual overnight exit

The four positions bought on Mon Sep 28 at 15:45 ET (3 calendar days earlier, so past the
min-hold) were sold manually in Alpaca's **overnight session** on Thu Oct 1, using extended-hours
DAY limit sells at the bid minus a small discount:

| symbol | qty | entry (Sep 28) | limit | fill | filled at (ET) | P&L |
|---|---:|---:|---:|---:|---|---:|
| GOOGL | 1.138894246 | 342.174 | 353.66 | 353.80 | 01:00:33 | +$13.24 (+3.40%) |
| AMZN | 1.583476904 | 246.104 | 251.13 | 251.20 | 01:00:33 | +$8.07 (+2.07%) |
| TSLA | 1.087447887 | 358.362 | 357.47 | 357.71 | 01:00:34 | −$0.71 (−0.18%) |
| META | 0.543220683 | 717.388 | 731.19, repriced to 727.75 | 731.0125 | 01:04:50 | +$7.40 (+1.90%) |

**Realised: about +$28.00.** The runner's DB state was reconciled at 01:22 ET: the four positions
are closed with reason `manual_overnight_exit`, state is v257, and only AAPL (bought Sep 29) is
still held.

_Hypothetical backtests; not financial advice._

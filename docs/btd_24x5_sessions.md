# BTD 24/5 sessions and DB-only rules (v0.55.0)

Decided by Julian on 2026-10-21. Backtest, paper and live must be identical. A setting goes live only after Julian has seen the backtest, so this release changes **no live behaviour**. Migration sql/57 seeds `session_mode = 'regular'` on every row.

## Session modes (`strategy_configs.params.session_mode`, DB only)

| mode | regular session (09:30-16:00 ET) | post 16:00-20:00, overnight 20:00-04:00, pre 04:00-09:30 ET |
|---|---|---|
| `regular` (seeded, current) | entries 15:45, OCO TP/SL, stops, max-hold exit | none. Resting GTC/DAY stops gap-fill at the open |
| `stops_24_5` | as regular | always-on stop: if the bid is at or below the stop, cancel the resting stop and send an extended-hours sell |
| `full_24_5` | as regular | stops, take-profits and dip entries (with the regime filter and the same hold_age rule) every ~5 min |

Shared rules live in `utils/btd_rules.py`:

- **Session and trade day.** `session_of` and `trade_day_of`: post belongs to today's trade day; overnight and pre belong to the next session's trade day. That makes `hold_age`, `stop_live` and the regime filter use the trade day, and a same-day buy is never sold in that day's post session (PDT guard).
- **Breach and take-profit tests.** `ext_stop_breach` (bid ≤ stop) and `ext_tp_hit`.
- **Quote guard.** `ext_usable_bid` acts only when the spread is ≤ `execution.extended_hours_exit.max_spread_bps`.
- **Order prices and management.** `ext_limit_price` (bid − 15 bps) and `ext_buy_limit` (+15 bps). `ext_exit_action` decides reprice (after 5 min, at most 2 times) or market at the open. `ext_order_expired`: a post-session DAY order expires at 20:00 and is placed again off the overnight bid.
- **Fills.** `ext_sell_fill` / `ext_buy_fill`: the next 5-min bar's high or low reaches the limit.
- **Check calendar.** `ext_check_allowed`: checks run on session dates only. The 20:00-24:00 window runs only when the next calendar day is a session.

**Live and paper** use the same Runner path. Scheduler `ext` events (`utils/live_btd_scheduler.ext_events`, every 5 min) cover 00:00-04:00, 04:00-open, close+5 min-20:00, and 20:00-24:00 when the next day is a session. Each pass is lease-gated, so only the primary acts. Each pass is idempotent: one live ext sell per symbol, deterministic `<pfx>x-SYM-<tradeday>-e` cids, reprices `-rN`. Unfilled ext entry limits are cancelled after `reprice_after_min`. Entries in ext sessions are limit buys by qty, because Alpaca accepts notional only on market orders.

**Backtest.** `utils/btd_event_backtest.run(..., ext_windows=, execution=, config_version=)` is an event-driven mirror of the same steps on 5-min bars, with ts = bar end and bid proxy = bar close. `Result.config_version` records the rule-set version and `Result.ext_exits` counts the extended-hours exits.

**Parity.** `tests/test_btd_parity.py::test_ext_stops_parity_after_hours_breach` (3 seeds) and `::test_full_24_5_parity` (2 seeds) replay synthetic daily and 5-min extended bars, with after-hours shocks, through the real Runner on the mocked Alpaca and through the backtester. They require identical trades, quantities, prices and equity. `tests/test_btd_ext_rules.py` holds the unit tests.

## Alpaca limits and how they are handled

| limit | handling |
|---|---|
| Extended and overnight orders must be `limit` with TIF `day`/`gtc` and `extended_hours=true` | `exit_order(..., "extended")` and ext buys always send DAY + limit + extended_hours. The fake broker rejects anything else |
| Fractional qty | Allowed in all extended sessions (pre, post, overnight). The ext sell carries the whole fractional position in one order, after the GTC whole-share stop and the DAY fractional stop are cancelled |
| Overnight session 20:00-04:00 runs Sun-Thu nights only (none on Friday night or a holiday eve) | `ext_check_allowed` plus the scheduler `_next_is_session` (Alpaca calendar). **Sunday 20:00-24:00 is not covered**: the scheduler only runs on session dates. Monday 00:00-04:00 is covered |
| Post-session DAY ext order expires at 20:00 | `ext_order_expired`: placed again off the overnight bid (counters reset) |
| **Real-time quotes on our keys:** IEX only. Real-time `sip` and `boats` return 403 ("subscription does not permit"). The free `overnight` feed is indicative (AAPL 308.88 × 366.64 at 03:46 UTC on 2026-10-21) | `max_spread_bps` guard (seeded 50). With the current subscription, live ext checks act only when an IEX quote is tight. IEX has no overnight quotes and sparse post/pre quotes, so **live coverage will be thinner than the backtest** until a SIP/BOATS real-time subscription exists. `execution.extended_hours_exit.quote_feed` (optional, DB) selects the feed |
| Historical 5-min bars | SIP pre/post 04:00-20:00 ET from 2016-01-04 (paper keys). BOATS overnight from 2024-09-16. IEX bars cover regular hours only. Cache: `data/intraday/<feed>/<SYM>.pkl.gz` (`scripts/fetch_intraday_bars.py`, incremental, fails on truncation) |
| Half days (13:00 close) | 13:00-16:00 is treated as regular by `session_of`, so no ext checks run in that window (about 3 days a year) |

## Rule-source inventory (where each one moved)

| rule / parameter | before | now |
|---|---|---|
| dip/tp/sl/min_hold/max_hold/pos_frac/max_exposure/ref/feed/windows/regime/stop/vol keys | DB row, with gaps filled from `live_btd_config.DEFAULT_PARAMS` | DB row only (`REQUIRED_PARAM_KEYS`). An incomplete row is refused. sql/57 wrote the old fallback values into the rows |
| universes (`symbols`) | DB, with `DEFAULT_PARAMS` Mag-7 as fallback | DB only |
| execution (regular/extended exit mechanics) | DB merged over `DEFAULT_EXECUTION` | DB only (`REQUIRED_EXECUTION_KEYS`), seeded by sql/57 |
| per-user fill-ins (`user_live_runner.NEUTRAL`) | code | `user_strategy_configs.params` and `strategy_param_versions.params` (sql/57). The runner requires every key |
| per-user `extended_hours_exit.enabled=False` override (`user_live_runner.user_config`) | code, forced | removed. sql/57 stored `enabled=false` in user rows, so behaviour is unchanged |
| stop exemptions `BTD_STOP_EXEMPT` env | env | `params.stop_exempt` `{SYM: date}` (seeded `{}`; the env was unset on the HP). Runner, backtester and daily parity all read P |
| session coverage | none | `params.session_mode` (seeded `regular`) |
| quote sanity | none | `execution.extended_hours_exit.max_spread_bps` (seeded 50) |
| paper explicit params | filled from `DEFAULT_PARAMS`/`DEFAULT_EXECUTION` | must be a complete set incl. execution, else refused. The normal path loads the same DB row as live |
| CLI flags (`--pos-frac` etc.) | override DB live | dry-run only. A live pass with an override stops. The HP/box/launchd units pass none |
| creation of a new user rule row (clone) | partial params | `btd_rules.NEW_ROW_TEMPLATE_*` (== sql/57 seed) is written into the new row once. Runtime never reads it |
| DB unavailable | defaults, entries off | last rule set loaded from the DB on this machine (same version, `config_last_good_<name>.json`), exits and stops only, no entries. With no snapshot nothing is placed, and the broker-side resting stops stay |
| **not moved (follow-up)** | `btd_rules` lookback constants `HIGH_LOOKBACK=20`, `REGIME_LOOKBACK=5`, `ATR_LOOKBACK=14`, `STDEV_LOOKBACK=20`, `EXT_STEP_MIN=5`; market model `DEFAULT_SLIPPAGE_BPS=10` (backtest fills); scheduler timing `INWARD_S`, grace windows, `ROLE_OFFSET_S`, `BTD_PROTECT_CHECKS`/`BTD_HEARTBEAT_MIN` env (operations); `PARAM_SPEC` defaults (form prefill for new versions) | still code. Listed so they can move in a follow-up |

## Rollout (after Julian has seen the comparison)

1. `python run_migration.py sql/57_rules_db_only.sql`. This writes the existing values only, and sql/41 bumps the versions.
2. Deploy the code.
3. Change only what Julian picks, e.g. `python scripts/live_btd_config.py set session_mode=stops_24_5 --strategy 1`, then `bump`.

# Change Log

## v0.44.1 — 2026-10-13 — Active strategies and leaderboard returns

- My strategies lists only the signed-in user's current paper or live activations, including the original live strategy linked to a running live run. Drafts and stopped strategies remain saved and accessible by their direct links.
- The public Leaderboard shows simple annualised return from the first trading day, including short records. It excludes strategies with negative annualised returns while retaining them in the database for backtesting. The JSON feed uses the same selection.
- My strategies marks active live strategies with a light green Live label. The signed-in header displays the beta version and release date.
- Tests: targeted leaderboard, activation, and route checks.

## v0.44.0 — 2026-10-12 — Clone to Grok Bot (strategy templates)

- **"Clone to Grok Bot" on every Leaderboard strategy** (next to Open in Grok / Copy to clipboard / Clone strategy) and on the new public **`/templates`** page, modelled on skillsdojo.com/templates. A small modal lists what you get and offers **Open in Grok Bot** (when a share id exists), **Copy setup prompt** (otherwise), **Copy template link** and **Download JSON**. Works signed out; set `GROKBOT_CLONE_REQUIRES_LOGIN=1` to put it behind sign-in (default off).
- **Template JSON** at `/templates/grokbot/<slug>.json` (public, `Cache-Control: max-age=300`, CORS `*`), format `alpatrade.grokbot-template/v1` (`engine/leaderboard/grokbot.py`): bot name "AlpaTrade <strategy>", instructions (Alpaca keys only via the bot's secure secret request, verify `GET /v2/account`, typed `CONFIRM LIVE TRADING …` before live, cash only, PDT 3-day min hold), one skill = the strategy `skill_md` (rules + Parameters JSON), secrets, routines in ET (entry 15:45–15:55, exits 09:31, close window 15:50, daily P&L digest 16:15) calling Alpaca REST from the bot's box, and the Predictive Labs Ltd research-only disclaimer.
- **Share links.** SkillsDojo cards are plain `https://x.ai/bot/<shareId>` links, and a share id can only be created inside the Grok Bot app. Once created from a template, map it with `GROKBOT_SHARE_IDS` (`slug=id,…` or JSON); the modal then shows "Open in Grok Bot".
- **Anonymous click analytics.** `alpatrade.grokbot_template_clicks` (`sql/54_grokbot_template_clicks.sql`, created on first use): per strategy / action / day counts, no user or IP. Admin JSON at `/admin/grokbot-clicks`.
- Tests: `tests/test_grokbot_templates.py`.

## v0.43.0 — 2026-10-12 — Excluded ("junk") securities filter

- **One exclusion rule set for every P&L / position report.** New table `alpatrade.excluded_securities` (`sql/53_excluded_securities.sql`: symbol, scope `global` | `account` + `account_ref`, reason, auto, created_at) and one helper, `engine/reporting/exclusions.py`. It replaces the hard-coded BNBX filters in `pnl_dashboard.py`, `ph_live_account.py`, `ph_pnl.py` and `scripts/daily_live_report.py`. Seeded with **BNBX** (global, leftover dust) and **CDTX** (account `PA3QUCXV3HJJ`, Kairi paper, not tradable / inactive on Alpaca).
- **Auto rule.** A position whose Alpaca asset is `inactive` or `tradable=false` is excluded automatically. Asset status is cached in `alpatrade.asset_status_cache` and refreshed daily. Turn it off with `EXCLUSION_AUTO_ASSET_STATUS=0`. Optional dust rule: `EXCLUSION_DUST_USD=5` excludes positions under $5 market value (off by default).
- **How figures change.** Excluded positions are hidden from position tables, with a small "excluded" footnote, and their unrealised P&L is dropped. Their *current* market value is subtracted from current equity **and** from the baseline / every history point. Period P&L (equity − baseline − net deposits) therefore doesn't jump when an exclusion is added. Equity and % denominators cover the tradable book only. Covered: `/dashboard` (paper and live views, all-accounts aggregate), `/live/account` (KPIs, positions, since-inception), the daily LIVE email (positions, runner lots, day / MTD / YTD / since-start), the daily paper / user P&L email (positions, unrealised, MTD / YTD from snapshots; raw equity stays in `account_equity_snapshots` so history doesn't move) and the activation unrealised P&L on `/leaderboard` (SQL filter on the same table). `/paper` and `/live` list runner-computed run results and have no account positions to filter.
- **Admin.** `/admin` now has an "Excluded securities" panel (admin only): list, add (symbol, optional account, reason) and remove. It works on mobile.
- Kairi paper (`PA3QUCXV3HJJ`): equity $100,595.02 → $100,373.64 (CDTX $221.38 excluded). Unrealised went from +$199.64 to $0, CDTX left the positions table, and 1D P&L (+$283.91) and YTD P&L (+$14.11) are unchanged. Julian live (`885504372`): equity −$1.80 (BNBX), open unrealised now +$33.05 without BNBX, and day / YTD P&L are unchanged.
- Tests: `tests/test_exclusions.py` (scopes, auto rule, dust, no jump when an exclusion is added, dashboard = paper email figures, admin panel). `tests/conftest.py` pins the rule set so tests use no DB or Alpaca.

## v0.42.0 — 2026-10-12 — One metrics definition, faster dashboard, stale-run reaper

- **Single metrics module (`engine/metrics.py`).** Annualised return everywhere (dashboard, Leaderboard, backtests, live account, daily LIVE email) is **CAGR** = (1+r)^(252/d)−1 on the deposit-adjusted time-weighted return, NYSE trading days. **It is not annualised under 60 trading days**: the UI shows the total return and "n/a (<60d)". The old simple ×252/d figure is gone from headlines. SPY 2016–2026 now reads ~13–14 %/yr; the old simple figure read ~26 %.
- **Dashboard −153.66 % fixed.** Root cause: the paper account's initial $10,000 funding was booked as a deposit *after* its first equity point. The TWR treated it as a deposit that never arrived, giving −100 %, and the simple ×252/164 then gave −153.66 %. `cash_flows.phantom_flow` now ignores a booked deposit that never shows up in equity (logged `METRICS_GUARD`). The same account now reads +10.99 % total, +17.37 % CAGR.
- **One live return.** `/live`, `/live/account` (since inception), the dashboard's live view and `/leaderboard` all use `metrics.live_strategy_return` (TWR from the run's daily snapshots plus the owner's cash flows, as of the last completed session). This replaces the runner snapshot (3.16 %), the intraday portfolio-history TWR (3.66 %) and the leaderboard TWR (3.44 %); all now show 3.44 %. The intraday value is kept only for the mismatch log.
- **Backtests list.** Finished orchestrator backtests with no `is_best` summary row now show Return/Sharpe from `results.best_config` instead of "—". A Sharpe beyond ±10 is flagged.
- **Dashboard speed.** Per-account broker reads run in parallel. Since-start, paper rankings and backtest rankings run concurrently. Rankings are cached for 5 min. New index `sql/52_runs_dashboard_index.sql` (`runs(user_id, mode, started_at DESC)`) is applied once on first dashboard load. Local `dashboard_data` time: ~17 s → ~4–6 s.
- **Guardrails.** `metrics.sanity_issues` / `guard` check that the annualised sign matches the total, \|annualised\| ≤ 1000 %, the value is ≥ −100 %, nothing is annualised under 60 days, and \|Sharpe\| ≤ 10. Bad values are logged and hidden, never shown. `spy_benchmark_issue` checks that a long SPY window compounds at 5–25 %/yr, which catches a simple-vs-CAGR mixup. `check_consistency` logs `METRICS_MISMATCH` when pages disagree. Admins can see recent mismatches at `/admin/metrics` (JSON). CI step: `tests/test_metrics_consistency.py`.
- **Stale-run reaper (`engine/runs_reaper.py`).** Scheduled every 15 min in the autonomy worker. A `running` paper/full run with no heartbeat for 6 h is marked `stopped`. A `running` backtest with no heartbeat for 24 h is marked `failed`. Both get `completed_at`. **Live runs are never touched.** Thresholds are set by `REAPER_*` env vars. Run it once with `python -m engine.runs_reaper --dry-run`.
- Ops (2026-10-12): Julian's 52 orphaned `running` paper runs (from the `paper-strategy` service restarts) were marked `stopped`. His 4 stuck backtests (2026-09-10 ×2, 09-26 and 09-28) were marked `failed`. The live run was not touched.

## v0.41.2 — 2026-10-12 — Live runners move to the server; smaller DB footprint

- **Live runners on Coolify (server = primary).** New `Dockerfile.runner` (python:3.13-slim + `tzdata`) and `docker-compose.runner.yaml`, deployed as a separate Coolify application (`alpatrade-live-runners`), not part of the web stack: `btd-scheduler` (`scripts/live_btd_scheduler.py --live`, Julian's Mag-7/Semi-7 BTD) and `user-live` (`scripts/user_live_supervisor.py --live`, per-user activations). Healthcheck on the process, `restart: unless-stopped`, 300/330 s stop grace, a `runner-data` volume for `$BTD_STATE_DIR`, `TZ=America/New_York`. Env (Coolify only): `DATABASE_URL`, `ENCRYPTION_KEY`, `ALPACA_LIVE_*`, `BTD_ROLE`, `BTD_INSTANCE`, `BTD_USER_EMAIL`, `USER_LIVE_TRADING_ENABLED`. The compose default role is `backup` (safe); the cut-over sets `BTD_ROLE=primary`, `BTD_INSTANCE=server`. HP is demoted (its systemd units are disabled); Mac.home stays backup and the box tertiary. Runbook: `docs/user_live_runner_deploy.md` § Server primary.
- **DB connections.** The shared Postgres (max 100) kept hitting "remaining connection slots are reserved". Runner, lease, recorder, config-loader and user-supervisor engines now use `NullPool` (no idle connections between the minutes-apart passes) with an `application_name` and `idle_in_transaction_session_timeout=60s`. `DatabasePool` defaults are now `pool_size=2`, `max_overflow=2`, `pool_recycle=300`, with `pre_ping` and the same idle-tx guard (`DB_IDLE_IN_TX_TIMEOUT_MS`). Web/api compose default `DB_POOL_SIZE` goes from 3 to 2. The legacy `news_db_util` engine is small and named. **Fix:** the news worker's advisory-lock connection ran in autobegin and sat "idle in transaction" for the whole cycle; it now uses AUTOCOMMIT.

## v0.41.1 — 2026-10-12 — Paper-strategy service paused

- The prod `paper-strategy` compose service (`scripts/run_paper_strategy.py`, the fixed BTD paper runner on Julian's paper account) is **off by default**: unless `PAPER_STRATEGY_ENABLED=1` it registers no run, places no orders and idles. Idling keeps the healthcheck happy, so `restart: unless-stopped` doesn't loop; every restart used to leave another orphaned `running` paper run. Paper only; live is untouched.
- Tests: `tests/test_run_paper_strategy_flag.py`.

## v0.41.0 — 2026-10-12 — Referrals, admin + RBAC, TypeSafe jev judge, Trade menu review

- **Referrals (`/invite`).** Each signed-in user gets a stable 8-character referral code and can invite up to 5 friends (lifetime; failed sends don't count). Invites are deduped per (referrer, email). Registered emails and the user's own address are skipped. A recipient gets at most one invite per 24 h across all referrers. The form is limited to 3 submissions per 10 min. Sent and accepted invites are tracked in a table (times shown in ET · UK · Tallinn). `/register?ref=CODE` keeps the code in the session; on signup (password or Google) the new user gets `referred_by` and matching invites flip to `accepted`. An invited email that signs up without the link is still attributed. Email: an HTML cover letter with the key features, a Join button with the referral link and code, a linked YouTube thumbnail (https://youtu.be/rfbsMxSUGh4) and the user guide PDF attached (`docs/user_guide/alpatrade_user_guide.pdf`, copied from `feat/alpaca-assisted-connect`, re-included in the Docker build context), sent via Postmark (`POSTMARK_API_KEY`, `FROM_EMAIL`). One test invite was sent to kaljuvee@gmail.com only (code `TEST2026`, not a real code).
- **RBAC + admin.** Roles are `admin`, `member` (in a team) and `user`. Migration `sql/51_rbac_referrals_logins.sql` (additive, idempotent, applied on first use) adds the `teams` table, `users.role` / `team_id` / `last_login_at` / `referral_code` / `referred_by`, `user_logins` and `referral_invites`. It seeds kaljuvee@gmail.com, and existing `is_admin` users, as admin. **`/admin`** is admin-only and checked server-side (`engine.rbac.is_admin` reads `users.role`). It shows total and new users per day and week (ET), DAU / WAU / MAU (signed in or a logged request), logins by method, paper/live activations, invites sent/accepted, referred signups, backtests run and teams. The nav link appears only for admins.
- **Login tracking.** Every sign-in (password, Google, register, email verify) writes `user_logins` (method, IP, user agent) and stamps `last_login_at`. Tracking never blocks sign-in.
- **TypeSafe jev judge (`LLM_JUDGE_PROVIDER=typesafe`, default `grok`).** New `engine/ai/judge.py` falls back to Grok on any error. Switched to jev: the `/research/news` sector-impact analysis and the autonomy promote ranking note. The full inventory and reasoning are in `docs/llm_judge_jev.md`. Benchmark on 10 live headlines: jev 0.73 s vs Grok 29.1 s, top sector agreement 8/10, ~97% cheaper per call.
- **Fix: `/research/news` "(secs || []).slice is not a function".** `plotBoard` was handed the `sector_counts` object; it now accepts the object or the AI board array.
- **Fix: on phones (≤960 px) News starts minimised** so it no longer covers the dashboard/chat on first load. Desktop is unchanged.
- **Deploy:** `docker-compose.yaml` passes `LLM_JUDGE_PROVIDER` (default `grok`) and `TYPESAFE_API_KEY` to the api, agui, autonomy, news and hermes-jobs services (not the isolated hermes gateway).
- **Review:** `docs/reviews/trade_menu_review.md`, prioritised findings for every Trade page (no large changes made).
- Tests: `tests/test_referrals.py`, `tests/test_rbac_admin.py`, `tests/test_judge.py` (20 new). The full suite matches `origin/main` (the same 53 pre-existing failures, none new). Screenshots: `screenshots/referrals_admin/{invite,admin}_{mobile,desktop}.png` (390 px / 1366 px, no horizontal overflow).

## v0.40.1 — 2026-10-11 — Fix since-activation P&L query

- `activation_metrics` read `positions.unrealized_pl`; the column is `unrealized_pnl`. The query failed, so pages fell back to backtest figures. Verified on the prod DB: Kairi's strategy #39 now reads live, +0.00%, $670 allocation, 0 fills.

## v0.40.0 — 2026-10-11 — Per-user daily reports, 0% at activation, durable paper activations

- **Daily live report for each user, scoped to their own strategies.** The report already went to every owner of an active live link (their own account, their own email, honouring `report_live_daily`, default on). A user's account was still laid out as the operator's: a "Mag-7 BTD · btd- · rest of account" sleeve and a "Live runner (Mag-7 buy-the-dip)" heading. Now the Strategies table and runner heading come from the user's own live activations (their clone's name, universe, `u…` prefix and allocation, `user_sleeves()`). The operator account is unchanged. Times are ET, returns are deposit-adjusted TWR, and the chart is the same.
- **Return at activation is 0.00%.** For an activated user strategy (live preferred, else paper), My strategies, the dashboard card, the strategy page and Leaderboard rows now show figures measured from the activation timestamp against its allocation. Only that activation's own fills and positions count (runs with its prefix); the account's pre-existing holdings, history and the old backtest are excluded. Alpha shows "—" until the first fill. This replaces the backtest figures (e.g. a −29.99% alpha) that a just-activated clone showed.
- **Paper activations are durable and actually run.** Activate Paper used to queue an LLM `deepagent_paper` job. The prod autonomy loop has been paused since 2026-09-28, so the job never ran, and a container restart would have failed it. Paper activations now run like live ones: a per-user runner process started by the supervisors on HP, Mac.home and the box. They use the user's own paper keys and the same prefix/allocation/kill-switch guards, and record runs and trades as `paper`. All state is in Postgres (`user_strategy_activations`), so Coolify redeploys don't affect them and a supervisor restart re-creates every child on its next poll. Legacy queued paper rows are migrated idempotently (prefix + $10,000 paper allocation, old job cancelled).
- Runner: new `Runner.recorder()` hook (default identical: `LiveRecorder`); `UserRunner` records paper runs and trades as `paper`, and paper activations use the activation's own paper account.
- Fix: `runner_trades_account()` ignores per-user runner runs (`strategy_slug 'user:…'`), so a user's own recorded run never makes their account look like the operator's.
- Tests: `tests/test_activation_return.py`, plus additions to `test_activate.py`, `test_user_live_runner.py` and `test_daily_live_report.py`.

## v0.39.1 — 2026-10-11 — Settings: Check saved Alpaca keys

- **Check button** next to every saved paper and live key in Settings > Integrations. It decrypts the stored pair and makes ONE read-only `GET /v2/account` on the matching endpoint (paper → paper-api.alpaca.markets, live → api.alpaca.markets) and shows the result inline: OK with account number and status, or Alpaca's exact HTTP status and message. Also flags problems on our side: decrypt failure, whitespace/newlines in the stored key or secret, wrong environment (AK saved as paper / PK as live), and live keys that belong to a different account number.
- `last_checked_at` and `last_check_result` stored on `user_accounts` and `user_live_broker_accounts` (`sql/50_key_check_columns.sql`, applied idempotently) and shown under the button.
- Diagnosis of poder.kairi76's earlier paper 401: decrypts fine; the key is PK-prefixed, 26 chars, the secret is 44 chars, with no whitespace or non-printable characters; the call went to paper-api. Alpaca returns `401 unauthorized.` on paper, on live and with key/secret swapped, so the cause is on Alpaca's side (the pair is not valid there, e.g. regenerated or reset), not on ours.
- Tests: `tests/test_key_check.py`. Mobile 375/414: the accounts table stacks and doesn't overflow.

## v0.39.0 — 2026-10-11 — Activation points everywhere; user live trading on

- **User live trading enabled** (`USER_LIVE_TRADING_ENABLED=1` on HP, Mac.home, box). A confirmed Activate Live starts the user's own per-user process within one supervisor poll (≤60s), no operator step. All guards unchanged: typed LIVE confirmation, cash only, allocation cap at order time, own `u`+hex prefix, Julian's accounts refused, per-user Pause/Deactivate, global flag as emergency stop.
- **Activate Paper / Activate Live… on every Leaderboard row** (signed in; signed out the button goes through sign-in + clone) and **on every strategy page**. Activating a strategy you don't own clones it first, so it always appears under My strategies.
- **My strategies and a new dashboard "My strategies" card** show status badges (Paper running/starting/stopped, Live starting/running/paused · $allocation) with Activate Paper, Activate Live…, Stop paper, Pause/Resume live, Deactivate live — no chat needed.
- New routes: `POST /strategies/{id}/paper/stop`, `POST /strategies/{id}/live/{pause|resume|deactivate}`; activate routes clone-first and honour a safe local `back` URL. Paper re-activation after a stop gets a fresh job (dedupe key per minute).
- Tests: `tests/test_activation_points.py`. Mobile checked at 375/414 (no horizontal overflow).

## 2026-10-11 — v0.38.1: user live runner loads ENCRYPTION_KEY from the runner .env

- `UserRunner` exports `ENCRYPTION_KEY` from the repo `.env` into the process env (engine.auth reads
  `os.environ`), so per-user processes under systemd/launchd can decrypt the user's keys. Runner key =
  the prod web key (same SHA-256 as Coolify; all stored key rows decrypt).

## 2026-10-11 — v0.38.0: per-user live runner (one process per user strategy) + kill switches

Julian approved: a confirmed Activate Live request trades the user's OWN live account with the
user's OWN strategy. Web side deploys now; the runner side (new scripts) is NOT started on the
HP / Mac.home / box until Julian approves the runner rollout.

- `utils/user_live_runner.UserRunner`: one process per activation
  (`scripts/user_live_scheduler.py --activation-id N`), kept alive by its own service
  `scripts/user_live_supervisor.py` (one child per runnable activation, crash backoff). Own
  config (only `user_strategy_configs.params`; required universe/dip/TP/SL/hold/pos_frac, never
  `strategy_configs`, `strategy_allocations` or `DEFAULT_PARAMS`), own decrypted keys, own
  `u<6hex>` client_order_id prefix, own state dir/log/flock (`$BTD_STATE_DIR/users/<prefix>/`)
  and own lease key `user-btd:<account>:<prefix>`. Refuses the operator account.
- Order-time guards (`pre_order`): kill switches re-read, own prefix only, buy notional ≤
  allocation, keys verified to belong to the activated account; sizing as a fixed sleeve:
  min(account cash / non-marginable BP − pending buys, allocation − own exposure − own pending);
  no order when cash is short; never margin.
- Single order placer: same primary > backup > tertiary lease protocol per activation, and a
  user process only acts on the instance that currently holds the operator lease.
- Kill switches: `USER_LIVE_TRADING_ENABLED=1` required (supervisor stops all children; running
  passes stop submitting); per-user Pause (no new entries, exits continue) / Resume / Deactivate
  in Settings > Integrations > Live strategies; disconnecting live keys deactivates them.
- Operator runner: three no-op hooks (`plan_sleeves`, `entry_gate`, `pre_order`) whose defaults
  are byte-for-byte the previous behaviour; Julian's Mag-7 (`btd`) / Semi-7 (`s7btd`) unchanged.
- Fills go to `alpatrade.runs` / `trades` / `positions` / `pnl_summary` via the same
  `LiveRecorder`, attributed to the user (`user_id`) and account (`runs.config.account_number`).

## 2026-10-11 — v0.37.0: live keys in Settings > Integrations for every user; Activate Paper / Activate Live

- **Why live keys could not be saved:** Settings only had a paper-key form, and
  `store_alpaca_keys` refuses `AK…` live keys (by design: `user_accounts` feeds every paper path),
  so pasting live keys there crashed the POST (unhandled `ValueError`, HTTP 500). Live accounts
  could only be linked by an operator with `scripts/link_live_account.py`. No admin gate; nothing
  in the DB blocked it.
- **Settings > Integrations** (`/settings#integrations`): separate *Alpaca paper* and *Alpaca live
  (real money)* cards for any signed-in user, each listing the connected accounts (name/number,
  key hint, date). Live keys are checked with one read-only `GET /v2/account` on
  `api.alpaca.markets` (`engine.live_accounts.validate_live_keys`), then stored Fernet-encrypted
  in `alpatrade.user_live_broker_accounts` (same encryption as paper keys). Paper keys are now
  validated against `paper-api.alpaca.markets` before saving, and wrong-type keys get a clear
  message instead of a 500. Live accounts can be disconnected (keys wiped).
- **Activate Paper / Activate Live** buttons after every clone/backtest result in chat
  (`clone_bt.result_markdown`, used by `/backtest-strategy` and `backtest_my_strategy`).
  Paper queues one `deepagent_paper` job (one week) on the user's own paper account with the
  strategy's BTD params; without paper keys it sends the user to Settings > Integrations.
  Live opens a confirmation page (real money, cash only, dollar allocation, type LIVE), validated
  with the sleeve rules (`validate_allocations`: allocation ≤ free cash and, with the account's
  other sleeves, ≤ equity; unique `u<6hex>` client_order_id prefix; universe disjoint from the
  account's active sleeves, e.g. a Mag-7 clone is refused on the account where the runner's Mag-7
  primary trades). It is recorded as `pending_runner` in the new
  `alpatrade.user_strategy_activations` (sql/49); it never writes `strategy_configs` /
  `strategy_allocations` and never places orders. The shared live runner does not trade per-user
  accounts yet; that needs an operator decision.

## 2026-10-11 — v0.36.2: three shared performance charts (equity vs SPY, drawdown, daily returns)

- `engine/reporting/perf_chart.chart_html` now renders all three strategy-page charts from the
  same deposit-adjusted daily TWR series: equity vs SPY (base 100, trade markers), drawdown %
  (account filled, SPY drawdown line) and daily returns % (account bars, SPY daily line);
  `risk_series()` computes drawdown / daily returns for account and SPY on the same dates.
  Same layout and colours as before; the MTD/YTD shading applies to all three on /dashboard.
- Used everywhere through that one function: /dashboard (live: since inception, period shaded;
  paper: selected period), /live/account, /strategies/<id>#details and the Leaderboard detail.
  The Leaderboard-only drawdown/daily JS (`_DETAIL_JS`) is deleted; backtests omit daily returns
  as before. Element ids: `<id>`, `<id>-dd`, `<id>-dr`.
- X-axis ticks are 'dd Mon' (no second year line), so legends no longer overlap the axis labels.
- Leaderboard live headline stays simple annualised (×252 / trading days); compounded in the tooltip.
- Tests: three charts from one series (deposit day is a TWR step, not a jump), all four surfaces
  render the three charts via the shared function. Mobile checked at 375 / 414 px.

## 2026-10-11 — v0.36.1: live dashboard deposit-adjusted (TWR) returns, one shared performance chart

- **Verified against Alpaca (account 885504372) and the runner DB** (snapshot 2026-10-11):
  equity $4,819.61, cash $3,320.02, buying power $17,473.88, unrealized $6.60 (BNBX hidden),
  3 open positions, MTD P&L $74.25 (= 4,819.61 − Sep 30 close 2,745.36 − $2,000 CSD on Oct 9),
  since inception +$94.02, SPY $767.29 → $778.57 (+1.47%), runner P&L +$86.33 (realised
  $79.73 + open $6.60, 12 closed) — all correct.
- **Fixed MTD/YTD return**: was P&L / (base + deposits) = +1.56% (diluted by the deposit); now the
  time-weighted return, +2.70% MTD (each day net of that day's cash flows). Same for paper and
  "All accounts". Since-start annualised KPI now uses the TWR as well (was the diluted ratio).
- **Annualised return**: Julian's standing rule — simple r × 252 / trading days since strategy
  start, compounded only in the tooltip — everywhere: dashboard (was "n/a (<90d)", now +72.44%
  over 12 sessions), daily LIVE email, and the Leaderboard live rows (were compounded).
  `annualize()` no longer suppresses short periods; below 63 sessions the tooltip carries a
  short-period hint.
- **Live account vs SPY panel** (/dashboard and /live/account): "since start" → "since inception",
  "Live run started" → "Inception"; new MTD / YTD / since-inception table (account, SPY, excess vs
  SPY) on the same TWR chain; footnote rewritten (deposits/withdrawals are excluded).
- **One shared chart**: `engine/reporting/perf_chart.py` (`performance_series`, `period_returns`,
  `chart_html`) holds the strategy-page (/strategies/<id>#details) equity-vs-SPY chart code,
  extracted verbatim, now used by the strategy page/Leaderboard detail, /dashboard (live: since
  inception with the MTD/YTD period shaded; paper: the selected period) and /live/account.
  `live_perf.equity_curves` and the daily email PNG use the same TWR index, so the $2,000 deposit
  no longer shows as a jump. Old dashboard / live-account Plotly chart code removed;
  `leaderboard.detail.index_series` delegates to the shared function.
- Note: the runner's `results.daily` SPY snapshots differ from official SPY closes by up to ~$2.6
  on some days (e.g. Sep 30 764.90 vs close 762.63). The dashboard uses market-data closes; the
  strategy page SPY line still uses the runner snapshots (runner not changed).
- Tests: tests/test_perf_chart.py (deposit day has no jump, MTD/YTD rows, labels, shared chart on
  the strategy page); updated annualise / leaderboard / live-account tests. Mobile checked at
  375 / 414 px (no horizontal overflow).

## 2026-10-11 — news enrichment: own $20/day budget, backlog throughput 150 rows / 15 min

- Approved by Julian: news enrichment (summaries/tags, every article, no ticker filter) gets
  its **own** daily budget `NEWS_LLM_DAILY_BUDGET_USD` (default $20) via
  `enforce_news_budget()`, which fails closed. The $3 `PLATFORM_LLM_DAILY_BUDGET_USD` was a
  shared platform-wide cap (chat, autonomy reason, premarket, news); it is unchanged for
  those callers, and news spend (agent "news") is now excluded from that shared total, so
  $20 of news can't exhaust it and news no longer competes with chat for the $3.
- `news-backfill`: `NEWS_BACKFILL_BATCH_SIZE` 20 → 150 (every 15 min, max ~14.4k rows/day),
  `NEWS_BACKFILL_MAX_PER_DAY` 800 → 12000 (~$15/day at ~$0.00125/row). Calls stay serial
  (~20 req/min, well under xAI limits). Newest-first, back-off, pause after 3 failed cycles
  and the 24 h row cooldown are unchanged. Set in docker-compose.yaml and the Coolify env.

## 2026-10-11 — news-backfill daily limit 400 → 800 rows

- Approved by Julian: `NEWS_BACKFILL_MAX_PER_DAY` default in the `news-backfill` compose
  service raised to 800 (~$1/day at ~$0.0012/row) because CityTicker's news_worker adds
  un-enriched rows faster than 400/day. The $3/day `PLATFORM_LLM_DAILY_BUDGET_USD` stop, back-off,
  failure pause and 24 h row cooldown are unchanged.

## 2026-10-11 — v0.36.0: mobile research API and Android download

- Added REST leaderboard search, visibility-scoped strategy detail and owner-scoped CRUD/cloning and background backtest launch/status using the existing leaderboard services.
- Added authenticated 13F screening, estimated fund performance, activist filings, IPO listings and pipeline endpoints.
- Added DB-free access-control and contract tests to CI. Validated 79 focused tests and 104 full regression tests; Android emulator integration passed for mobile 1.1.0.
- Deployment: API and mobile must be released together; no new schema is introduced (existing leaderboard / 13F migrations are required). Release uses the existing CI/CD pipeline. The landing download now points to the mobile repository’s stable latest APK asset.

## 2026-10-11 — news worker: GlobeNewswire 403, fair publisher mix, guarded enrichment backlog

- **GlobeNewswire returned nothing since Fri 9 Oct ~16:37 EEST:** `www.globenewswire.com/RssFeed/*`
  now answers server clients with 403 (verified with curl from the HP; last GNW row in
  public.news 9 Oct 13:16 UTC). All 262 GNW feeds in `news_scheduler/config` now use
  `rss.globenewswire.com` (same paths, 200 + items); `gnw_rss_url()` also rewrites
  `NEWS_PUBLISHER_FEEDS` overrides. Same rewrite CityTicker's news_worker uses.
- **PR Newswire crowded out other publishers (e.g. 16/25 items, no GNW):** round-robin
  counted *yielded* items, and a GNW turn usually yielded an already-stored link that the
  worker then skipped. `collect(is_new=, batch_size=)` now skips stored links inside the
  job's own turn and gives each of the 7 jobs ceil(batch/7) items; unused quota is released
  only after every job had its share.
- **Dedupe check was a 1.2 s seq scan per article** (no index on public.news link):
  `sql/48_news_dedupe_index.sql` adds a hash index on link (now 0.03 ms) plus backlog/event
  indexes (applied CONCURRENTLY). Inserts take CityTicker's exact
  `pg_advisory_xact_lock(hashtext('publisher|link'))` before the NOT EXISTS (publisher, link)
  guard, so the two redundant writers can't race into duplicates.
- **Enrichment backfill stopped since 22 Sep:** `news-backfill` was never a deployed
  service (a manual run, killed; record stuck at "running"), and its id-ascending scan
  would walk ~239k legacy rows (~$300). Mode `backfill` now enriches
  pending_enrichment/retryable rows newest first with the 2026-09-28 cost guards
  (`BacklogGuard`): back-off after failed cycles, pause after 3 consecutive failures,
  daily limit 400 rows (fails closed), 24 h per-row cooldown, stops on
  DailyBudgetExceeded; calls stay the small plain enricher calls with usage logging. New
  compose service `news-backfill`. Old scan kept as opt-in `--mode full-backfill`.
- Backlog at fix time: ~1,045 rows (967 retryable + 78 pending) ≈ $1.30 at the measured
  $0.00126/row (grok-4.3, 2 calls/row); ~3 days at 400/day. Tests in tests/test_news_worker.py.

## 2026-10-10 — audit verdicts no longer shown publicly

- Removed the public "Audit: passed / warnings / failed" badge (and its #audit link) from the
  Leaderboard and strategy pages, the #audit section on strategy pages, and the "Backtest
  audit" line in chat backtest results. No PASS / WARN is displayed anywhere.
- The audit gate is unchanged: it still runs, its verdict is stored (`backtest_metrics.audit`,
  now also for clone backtests) and it still blocks FAILED backtests from publishing (v0.34).
  Only the owner of a backtest that fails sees a "Failed checks (only you see this)" badge and
  the failing checks on their own strategy page.

## 2026-10-10 — clone follow-up: stop-change trade count explained; clone naming

- Strategy #37 rerun with a 2% stop kept 4,952 trades: **not a bug**. `sl` reaches
  utils/buy_the_dip.py as `stop_loss=0.02` (stop exits 2,188 → 1,878, return +27.7% → +19.7%),
  but with min hold = max hold = 3 days every position lives exactly 3 days, so the entry
  schedule — and the trade count — can't depend on the stop (with min_hold 0: 7,013 vs 6,506).
  The chat result now says so for such BTD configs.
- Clones are named "<name> — clone" (a trailing "(live)" / "(copy)" is dropped) instead of
  "… (live) (copy)". Tests in tests/test_clone_flow.py.

## 2026-10-10 — v0.35.2: one-click "Clone strategy" → paper strategy + backtest streamed into chat

- **What was broken:** "Clone into AlpaTrade" only copied the skill markdown into a private
  `user_strategies` row and landed on a page with no working next step: no paper config, no
  backtest (the copy of a backtest entry lost its kind, so it showed "—"), and signed-out
  visitors were sent to /signin without `next`, so the clone never completed after sign-in.
- **Now:** a prominent **Clone strategy** button on every Leaderboard row and strategy page.
  One click (idempotent per user + source) creates the private copy (`cloned_from_id`, "Shown
  as" = email local part) plus an `alpatrade.user_strategy_configs` row (new table,
  `sql/47_user_strategy_configs.sql`: template + params, `mode` paper/simulated, `is_live`
  pinned FALSE by a CHECK, active) — never `strategy_configs` / `strategy_allocations`. It then
  redirects to `/app?new=1&autorun=/backtest-strategy <id> cloned`: the chat streams progress,
  then posts total, simple ×252 annualised, Sharpe, max DD, trades, win rate vs SPY and an
  inline Plotly equity curve vs SPY (`strategy_vs_spy` chart, dates on x), linked to the
  strategy page. The job runs in a background thread and saves its result into the chat
  thread too. Results are stored on the clone's `backtest_metrics` with `engine_stamp` +
  `audit_input` (scripts/audit_backtest.py --strategy-id works).
- **Engines:** BTD → utils.buy_the_dip (v0.33.6+ fixes, TAF/CAT fees, 10 bps slippage, yfinance
  data — no Alpaca keys needed); Chat With Traders templates (relative_strength, trend_ma,
  volume_spike, donchian, trend_template, dip, gap, breakout) → engine.backtest.templates /
  breakout with the cloned params. Only BTD can paper-trade today; other templates are marked
  simulated with a note. Without Alpaca paper keys a BTD clone is "Paper (simulated) — connect
  Alpaca paper keys" with a link to /settings.
- **Chat follow-ups:** new DeepAgents tool `backtest_my_strategy(strategy_id, param_overrides)`
  (owner-only; overrides saved on the paper config), e.g. "change the stop to 2% and rerun".
- Signed-out Clone → `/signin?next=/strategies/{id}/clone`; the GET route completes the clone.
- "Run backtest" (My strategies / own strategy page) opens the same chat flow. Copy to clipboard
  keeps its "Copied" toast.
- Tests: `tests/test_clone_flow.py` (rows, idempotency, ownership, signed-out redirect, backtest
  kick-off, no live flags).

## 2026-10-10 — landing: "Works with" broker logos; CLI example moves to /developers

- **Home stats stripe removed** ("5-agent trading squad · 4 strategies built-in · Alpaca live
  paper trading · Reproducible…"). Same spot (home + /platform) now shows a single "Works with"
  row: LHV, Alpaca, Interactive Brokers, Saxo Bank, moomoo (Futu OpenAPI — the broadest global
  API footprint of the candidates: US, HK, SG, AU, CA, JP, MY). Official logo files vendored in
  `static/brokers/` (no hotlinking), each linking to the broker site, grayscale → colour on
  hover, alt text, wraps on mobile.
- **CLI backtest example** (`alpatrade backtest paper btd-7dp-05sl-1tp-1d-3m`) removed from the
  hero and added as a "Command line" section (`#cli`) on /developers with the slug format and
  artifact-folder contents. Figures are labelled as illustrative example output.
- Tests: `tests/test_landing_brokers_cli.py`.

## 2026-10-10 — v0.35.1: daily LIVE report — deposits are cash flows; per-strategy breakdown

- **Fix: a deposit day showed as a loss** (Fri Oct 9: −$1,997.44 / −41.56% instead of ≈ +$11).
  Root cause: Alpaca's 1D portfolio history has no point for the latest session until the next
  one opens, so a weekend report for Friday took *Thursday's* close as Friday's equity and then
  subtracted Friday's $2,000 CSD. New `live_perf.daily_equity_points` / `session_close_equity`
  fill the missing session close from intraday (5-min, market hours) history and never reuse
  the previous day's point; `_historical_equity` returns None rather than a wrong day.
  Day P&L = equity − last_equity − net CSD/CSW/JNLC that day (unchanged formula, now correct
  inputs).
- **Since-start, MTD and YTD returns are time-weighted** (`cash_flows.twr_pct`, flows booked at
  end of day; moved from `engine/leaderboard/perf.py`, which now delegates to it). Used by the
  daily email, `/live/account` (dashboard live_perf) and period annualisation; the dashboard
  equity curve also gets the missing latest close. The leaderboard live row already used TWR
  from the runner's daily snapshots and keeps the same numbers.
- **Per-strategy breakdown** in the email ("Strategies"): Mag-7 (prefix `btd`, rest of the
  account) and every active `strategy_allocations` sleeve (Semi 7, `s7btd`, $2,000) with sleeve
  value, open positions (by universe), market value, unrealised, and this session's fills /
  realised P&L attributed by client_order_id prefix (`Sleeve.owns_cid`). A sleeve without
  activity shows "No fills yet — $X idle". Fills tagged `s7btd*` / `btdtp-` / `btdsl-` are now
  labelled runner (was only `btd-`/`btdx-`).
- Tests: deposit day (Friday from Saturday, missing 1D point), TWR with a deposit, strategy
  breakdown + prefix attribution. Report/dashboard code only; no runner, scheduler or order code.

## 2026-10-10 — v0.35.0: CWT method templates for Marsten Parker, John Walsh, Mark Ritchie II

- **Three new backtest templates** in `engine/backtest/templates.py` (no look-ahead, 10 bps per
  side, cash only):
  - `volume_spike` (Parker): close-to-close gain ≥ `ret_min` on volume ≥ `vol_mult` × the prior
    50-day average, out of a non-extended 20-day base; buy the next open; +5% target / −7% stop
    bracket; time stop after `max_hold` sessions.
  - `donchian` (Walsh): closing 52-week high in a stock above its close a year ago; buy the next
    open; trailing stop = lowest low of the prior 20/40 sessions (only raised); risk-based sizing.
  - `trend_template` (Ritchie, Minervini-style): trend template on the prior close, buy-stop at
    the prior 20-day high, 5%/8% stop, exit on a close below SMA50, 1% risk sizing.
  - New `risk_pct` sizing (risk ÷ stop distance, capped by `pos_pct` and cash).
- **`METHOD_OVERRIDES` in `scripts/cwt_pipeline.py`**: hand-reviewed rules with transcript
  timestamps replace the LLM's breakout mapping for ep. 281, 74 and 290; `legacy_key` re-keys
  the existing Leaderboard rows so their ids are kept (7, 28, 33). Optional train-only
  sensitivity grid (max train Sharpe; the test window is never used to choose), written into
  each skill.md.
- **Fill realism parity with v0.33.6 / audit gate (all CWT templates + breakout):** stop checked
  before target, gapped stops/targets fill at the open, 10 bps slippage per side, and new FINRA
  TAF + CAT fees (`include_taf_fees` / `include_cat_fees`, default on, `utils.fees`). Sizing
  equity is now marked at the OPEN of the decision day (was the same day's close: a small
  same-bar look-ahead in `templates.run` / rotation). Every published CWT backtest was re-run
  (ENGINE_REV bump); figures moved by ≤ 0.6 pp CAGR except the three re-mapped strategies.
- Each backtest records `engine_stamp` (`cwt_<template>` + version + sha), a trade-level
  `utils.backtest_audit` result (reconciliation, cash replay incl. partial-exit legs,
  stop-first, costs) and `audit_input` (slippage, fees, stop-first, next-open, research label,
  universe as-of date, IS/OOS returns) in `backtest_metrics`.
- Tests: bracket/timing and volume condition, Donchian stop only rising, no-look-ahead and P&L
  reconciliation for the three templates, override mapping.
## 2026-10-10 — v0.34.1: live-rules BTD re-run with fees + engine stamp (audit gate)

- `scripts/btd_live_rules_wf.py` now runs with FINRA TAF + CAT fees on by default
  (`--no-fees` to omit), records `fees_paid` per run, and writes `engine_stamp`
  (`utils.engine_stamp.stamp("buy_the_dip")`), `fees_included`, `slippage_bps` and
  `same_bar_policy` into the report, so `semi7.build_metrics_live_rules` / the audit gate see
  engine version and costs. Report regenerated from a clean checkout of this commit; Semi 7
  leaderboard row 17 re-seeded from it.

## 2026-10-10 — v0.34.0: backtest audit guardrails

- **`utils/backtest_audit.py`**: every backtest result can be audited to pass / warn / fail with
  reasons. Checks: engine_version, reconciliation (Σ trade P&L = equity change, reported return),
  same_bar_exits (capital_after = initial + realised P&L whenever flat: the Semi 7 double count),
  cash (never negative without margin), tp_sl_same_bar (stop-first or fail), costs (slippage and
  fees > 0 and recorded), params (labelled live ⇒ = active `strategy_configs`, else 'research'),
  lookahead (signal ≤ fill ≤ exit; next-open / close fill rule), universe (survivorship),
  plausibility (warn > 200% annualised / Sharpe > 4 / zero DD with > 20 trades; fail > 1000% /
  Sharpe > 8 unless overridden with a note), min_trades (< 10 fail, < 30 warn), OOS vs IS.
- **Engine stamp** (`utils/engine_stamp.py`): every `alpatrade.runs` row written by
  `agent_storage.store_run` records `config.engine_stamp` (engine, app version, git sha); published
  backtests carry `backtest_metrics.engine_stamp`. buy_the_dip results older than b47e6de (v0.33.6)
  or without a stamp **fail**.
- **Publish gate** (`engine/leaderboard/audit_gate.py`): `cwt_pipeline publish` / `publish_group` and
  `seed_semi7_backtest.py` refuse a failing audit and store `backtest_metrics.audit`.
- **Leaderboard:** backtest entries show "Audit: passed / warnings / failed" (reasons on hover and
  in an Audit table on View more, `/strategies/{id}#audit`). Nothing is hidden.
- **CLI** `scripts/audit_backtest.py --strategy-id N | --run-id ID | --btd-live CONFIG` (exit 0/1/2)
  and skill `.claude/skills/backtest-audit/SKILL.md`; `agents/backtester/SKILL.md` requires it.
- **CI** step "Backtest audit guardrails" (tests/test_backtest_audit.py, tests/test_btd_equity_fixes.py),
  with synthetic reproductions of each Semi 7 bug that must fail.

## 2026-10-10 — v0.33.6: buy_the_dip backtester fixes + Semi 7 / Mag-7 re-run on the exact live rules

- **Equity bug** (`utils/buy_the_dip.py`): when several positions closed on the same bar, a position
  closed earlier in that bar was counted again at market value in later trades' `capital_after`,
  and `total_return` was read from the last trade's `capital_after`. Now already-closed positions
  are excluded and `total_return` / `total_pnl` / `final_equity` come from the true end-of-run
  equity curve (cash + open positions at the last close).
- **Fills:** stop-before-target is now the default when one daily bar touches both
  (`conservative_execution=True`); a stop that is gapped through (or stayed dormant during the
  min-hold while the price fell through it) fills at the bar's open, not at the stop price;
  slippage defaults to **10 bps per side** (`slippage_bps=10`). Same defaults in `BacktestAgent`
  and the orchestrator.
- **Re-run on the live rules** (`scripts/btd_live_rules_wf.py`; dip 3% vs 20-day high, TP 8%,
  SL 1.5%, min = max hold 3 days, 1/7 per position, cash only; report
  `docs/btd_live_rules_wf_20261010T032956.md`):
  - Semi 7, 11 Feb – 9 Oct 2026: +6.7% (simple ann. +10.1%, Sharpe 0.53, max DD −11.4%) vs SPY
    +13.4%; 2016–2026: +41.2% (simple +3.7%, CAGR +3.2%, Sharpe 0.27, max DD −38.4%) vs SPY +360.6%.
  - Mag-7, same windows: −2.2% vs SPY +13.4%; 2016–2026: +28.6% (CAGR +2.3%) vs SPY +360.6%.
  - Pre-fix code on the same rules reported Semi 7 +73.5% / Mag-7 +63.6% for 2026.
  No edge vs SPY on the live rules. The earlier Semi 7 walk-forward (+550.8% on the leaderboard)
  and the Mag-7 walk-forward (docs/walk_forward_btd_20260720T105423.md, $27,550 OOS) relied on
  the bugged code and are superseded.
- `engine/leaderboard/semi7.build_metrics_live_rules` + `scripts/seed_semi7_backtest.py
  --live-rules <json>` to re-seed leaderboard row 17 from this report (2016–2026 headline,
  2026 window as the test window).
- Tests: `tests/test_btd_equity_fixes.py` (same-bar exits, stop-before-target, gapped stop,
  10 bps default); `tests/test_cwt_pipeline.py` expectations updated for v0.33.4 simple
  annualisation.

## 2026-10-10 — v0.33.5: mobile hamburger menu in the public top nav

- At ≤960px the public top nav (home, Platform, Leaderboard, Developers, strategy pages; all
  `ph_landing._shell` pages) gets a hamburger button at the top right (3-line SVG, 40×40 tap
  target, same pattern as carhero's `.mobile-menu-btn`). It opens a full-width dropdown with every
  item: Platform, Leaderboard, Hedge Funds, Developers, Open app / Chat, Profile, Sign in, Start.
  Closes on link tap, outside tap, Escape, or resizing to desktop; `aria-expanded`/`aria-controls`.
- Desktop (>960px) nav unchanged; the duplicate mobile "Leaderboard" link is hidden ≤560px (it
  is in the menu), "Start" stays visible.
- Tests: `tests/test_mobile_nav.py`.

## 2026-10-10 — v0.33.4: backtest leaderboard rows use simple annualisation (×252/trading days)

- **Headline "Annualised return" for every `kind='backtest'` row** (Semi 7 + the CWT backtests)
  is now SIMPLE: total return × 252 / trading days of the backtest period — the same rule as live
  (`engine/reporting/annualize.py`). It is recomputed in `engine.leaderboard.perf.backtest_metrics`
  from the stored `total_return_pct` / `spy_return_pct` / `trading_days`; the stored
  `annualised_pct` (compounded CAGR) is ignored, so no DB re-seed is needed.
- **Alpha vs SPY** = simple annualised strategy − simple annualised SPY over the same days.
- **CAGR only in the tooltip** (strategy, SPY and CAGR-basis alpha). Labels say
  "simple, ×252/trading days"; the CWT out-of-sample test-window note converts its stored CAGR
  back to simple. Method note updated.
- `engine/leaderboard/semi7.py` / `scripts/seed_semi7_backtest.py` write simple `annualised_pct`
  (+ `annualised_cagr_pct`) for future seeds.
- Effect: Semi 7 +1629.7% → **+831.1%** (alpha +1608.6% → +810.9%, SPY +21.1% → +20.2%) over
  167 sessions on a stored total of +550.8%. CWT (2708 sessions) simple is *higher* than CAGR
  (e.g. Ross Haber 19.2% → 52.3%, SPY 15.2% → 33.1%); negative ones shrink (Marsten Parker
  −15.8% → −7.8%). Leaderboard order unchanged.
- **Known issue, not fixed here:** the Semi 7 total itself is inflated by a `utils/buy_the_dip.py`
  equity bug (`capital_after` double-counts positions closed earlier in the same bar, and
  `total_return` is read from the last trade's `capital_after`), plus optimistic TP-before-SL
  ordering on daily bars. Re-running the 8 folds: summed fold PnL $2,802 (+28%) vs reported
  $21,612; $644 with conservative TP/SL ordering. Needs a backtester fix + re-seed.
- Tests: `tests/test_backtest_annualised.py` (short-window 167-day case, long window, negative,
  missing days, tooltips/labels, Semi 7 build_metrics).

## 2026-10-10 — v0.33.3: Chat With Traders bulk results committed + backtest sanity fixes

- **Results committed:** `data/cwt/` episode folders (transcripts, specs, per-episode state is
  still git-ignored), `bulk_summary.json` and `strategies/<trader>-<template>/` (backtest.json,
  skill.md, equity curve). Bars, logs, captions and audio stay ignored. Final: **135 episodes,
  16 testable groups / 16 published, 119 not testable, 0 skipped**; Stan Gluzman unpublished.
- **Breakout parameter mapping** (`spec_params`): the LLM writes `0` for "not stated", which was
  clamped *up to the lower bound* (5% consolidation range, 2-day 10% partial, 5% max position,
  3 positions). `<= 0` / missing now means the template default; fractions given for percent
  fields (0.1 → 10%) are converted; the momentum window must reach ≥ 20 sessions before the
  consolidation (`mom_days ≥ cons_days + 20`) — with equal windows "≥ 10% momentum" and "≤ 5%
  range" contradicted each other, so Marsten Parker / Christian Carreon had 0 trades and Julian
  Komar 4. Now 2358 / 460 / 500 trades (all still negative vs SPY) and published.
- **Template parameters** (`group_params`): `0` is dropped for size/window fields (pos_pct,
  max_positions, top_n, lookback, rebalance_days, …) — Rob Hanna's dip had run at 2% per
  position with 1 slot (0.8% CAGR); now 10% × 10 (16.3% CAGR full, 19.5% test).
- **Relative-strength rotation** (`engine/backtest/templates.py`): rebalance at most weekly
  (`rebalance_days ≥ 5`; the LLM's daily rebalance churned 4977 / 10190 round trips) plus
  hysteresis `hold_buffer` (keep a holding while it ranks within top_n × 2). Vincent Bruzzese
  4977 → 1703 trades, Ross Haber 10190 → 3088. Costs unchanged: 10 bps per side in every fill.
- **Classification overrides** (`CLASSIFICATION_OVERRIDES`, applied on load): Stan Gluzman ep.
  171 and 211 → `intraday_only` (scalper: tape, level 2, 1–5 min charts, flat by noon). The
  `finish` step now **unpublishes** (`is_public = FALSE`, never deletes) any Chat With Traders
  row it did not publish, with the reason in `alpatrade.cwt_episodes.status_reason` and
  `bulk_summary.json → unpublished`.
- **Strategy id gaps** (e.g. no id 10): `INSERT … ON CONFLICT DO UPDATE` takes a sequence value
  even when it only updates (id 10 went to the Kullamägi pilot row's re-keyed upsert, 18–27 and
  30–31 to the second `finish` run's updates). Ids are kept (they're in `/strategies/{id}` URLs);
  publish now UPDATEs by seed_key first and only INSERTs new rows, so re-runs no longer burn ids
  (this run: new rows 32–34, sequence stayed at 34).
- Cached group backtests are re-run when the params or `ENGINE_REV` change. Tests: zero/percent
  mapping, feasible windows, rotation hysteresis + P&L reconciliation, Stan override.

## 2026-10-10 — v0.33.2: Grok-only prefill + Copy to clipboard

- Julian's test: only Grok honours the `?q=` prefill. The **Copy for ChatGPT** and **Copy for
  Claude** buttons are removed from the leaderboard and strategy pages. What's left: **Open in Grok**
  (logo; `grok.com/?q=` prefill, with a short page-link prompt plus clipboard copy for long skills)
  and **Copy to clipboard** (double-page icon; copies the full SKILL.md, toast "Copied — paste into
  Claude or ChatGPT").

## 2026-10-10 — v0.33.1: AI prefill links; no repeated SKILL.md

- **Copy for ChatGPT / Claude / Grok** now always open the chat with a prompt prefilled
  (`chatgpt.com/?q=`, `claude.ai/new?q=`, `grok.com/?q=`, URL-encoded). If the full SKILL.md would
  make the URL longer than 6,000 characters, the prefill is a short prompt with the strategy page and
  raw `/skill.md` links, and the full text is copied to the clipboard (toast says to paste it).
  Previously long skills just opened the site's home page.
- **Strategy page:** the SKILL.md repeated at the bottom of "View more" is gone; it is a single compact
  Copy button (double-page icon, "Copied" toast). Download .md and Clone stay in the top action row.

## 2026-10-10 — v0.33.0: leaderboard detail, Semi 7 backtest entry, front-page "How it works?"

- **Leaderboard annualised:** the `<90d` rule is reverted. Annualised is always the compounded
  `(1+r)^(252/d)−1` on the deposit-adjusted time-weighted return, and the ranking uses it; under
  63 trading days the tooltip adds a "Short period" hint (simple r×252/d is shown there too).
- **View more** on every strategy (`/strategies/{id}#details`, `engine/leaderboard/detail.py`):
  Plotly equity vs SPY (base 100, deposit-adjusted TWR for live), drawdown, daily returns with
  buy/sell markers from the run's trades, parameters (`strategy_configs`, or the skill's
  Parameters block for backtests), strategy prompt, SKILL.md with copy, download and clone.
- **Copy buttons** now carry the ChatGPT / Claude logos, and there is a new **Copy for Grok**
  (marks copied from predictivelabsai/fastskills `fastskills/logos.py`).
- **Semi 7 on the leaderboard** as a *Backtest* entry (`engine/leaderboard/semi7.py`,
  `scripts/seed_semi7_backtest.py`): 8 chained out-of-sample walk-forward folds from
  `docs/walk_forward_btd_semi7_20261009T195838.json`, SPY on the same dates. It switches to
  live figures automatically once `buy_the_dip_semi7_minhold_live` has a session-close snapshot
  (`backtest_metrics.live_slug`).
- **Sleeve sizing:** a strategy's own exposure now also counts every open position in its own
  universe, not only the ones in its state file, so a Mag-7 position bought from the whole
  account (META, 9 Oct 15:45 ET) uses up Mag-7 sleeve headroom (equity − other allocations).
- **Front page:** hero headline "Systematic trading, reimagined"; a new "How it works?" section
  (describe → fine-tune parameters with AI → walk-forward and go live), a short systematic-trading
  primer with an origins timeline, and a large "Why AlpaTrade?" band right under the hero (अल्प · alpa, Sanskrit for "little": "It ties into the idea of small, disciplined edges compounding over time.").

## 2026-10-09 — v0.32.1: deposits are not P&L; no annualising short records

- **Bug:** dashboard MTD P&L showed ~+$2,073 and the leaderboard Mag-7 live return +76.82%
  (annualised +1613%, alpha +75.35%) because the $2,000 instant-ACH deposit of 2026-10-09
  (Alpaca CSD, transfer b29c1438-…) was counted as an equity gain.
- **Fix** (`engine/reporting/cash_flows.py`): P&L = equity change − net deposits (CSD / CSW /
  JNLC activities booked after the baseline); return % = P&L / (baseline + deposits). Applied to
  the dashboard (day / MTD / YTD, live and paper, plus a "net deposits" KPI), `/live/account`
  day P&L and since-start, the daily LIVE email (day P&L, since start, MTD/YTD annualised; shows
  "Net deposits today") and the **leaderboard**, which now uses a **time-weighted return**
  (daily session closes chained, each day net of its flows); alpha = TWR − SPY.
- Read-only live client: one new allow-listed GET, `/v2/account/activities` with
  `activity_types=CSD,CSW,JNLC` mandatory (never an unfiltered activity listing).
- **Annualisation** (`engine/reporting/annualize.py`): not computed below 63 NYSE sessions
  (~90 calendar days); rendered "n/a (<90d)" with an explanatory tooltip. Short live records
  rank on the leaderboard by their (non-annualised) return.
- Corrected live figures (2026-10-09 close): MTD P&L +$73.29 (+1.54%), day +$10.07 with
  $2,000 net deposits; leaderboard Mag-7 return +3.44% vs SPY +1.47%, alpha +1.97%,
  annualised n/a (12 trading days).
- Tests: `tests/test_cash_flows.py` (deposit scenario across dashboard, email, leaderboard).

## 2026-10-09 — v0.32.0: Semi 7 BTD + multiple strategies per Alpaca account (sleeves)

- **Semi 7 buy-the-dip** (`buy_the_dip_semi7_minhold_live`, seeded **inactive** by
  `sql/46_strategy_allocations.sql`): the 7 largest US-listed semiconductors by market cap that
  are not Mag-7 (NVDA excluded) — TSM, AVGO, MU, AMD, ASML, INTC, AMAT (yfinance caps
  2026-10-09: $2346B / 1726B / 1159B / 992B / 684B / 552B / 402B; next LRCX $399B). Same params
  as the live Mag-7 BTD (dip 3% vs 20d high, TP 8, SL 1.5, min/max hold 3d, cash only).
- **Strategy sleeves** (`utils/strategy_allocation.py`, table `alpatrade.strategy_allocations`):
  one runner process / one DB lease + heartbeat per account trades the primary strategy plus every
  active sleeve in the same pass. Each sleeve has its own cash allocation (NULL = rest of the
  account), its own `client_order_id` prefix (`btd` = Mag-7, `s7btd` = Semi 7; entries `<p>-SYM-
  YYYYMMDD`, exits `<p>tp-/<p>sl-/<p>x-`), its own sub-state and `alpatrade.runs` row. Sizing =
  pos_frac × sleeve; buys capped at sleeve − own exposure − own pending buys and at account cash
  (no margin). Held/open-order checks are per strategy; a symbol held by another sleeve is never
  bought (Alpaca nets per symbol). **Backward compatible:** with no allocation rows the Mag-7
  runner is unchanged (pos_frac 1/7 of equity, `btd-` ids); BNBX/untracked positions still ignored.
- **Web:** `/live/allocations` sets each strategy's allocation per linked live account, validated
  against the account's equity (sum ≤ equity, ≥ 0, disjoint universes) with a warning above free
  cash. Writes only the allocations table; `/live/account` stays read-only (links to it).
- Daily live email / dashboard keep reporting the primary (Mag-7) run when sleeves add runs.
- `scripts/walk_forward_btd.py --basket semi7` + CAGR / Sharpe / max DD / win rate vs
  equal-weight buy-and-hold; report `docs/walk_forward_btd_semi7_20261009T195838.md` (+ .json).
- Tests: `tests/test_strategy_allocation.py` (allocation math, cid tagging, sleeve-capped buying
  power on a fake Alpaca, unchanged single-strategy path, web validation, metrics).

## 2026-10-10 — v0.31.0: Chat With Traders bulk run + Leaderboard filters / pagination

- **Bulk pipeline** (`scripts/cwt_pipeline.py`): resumable per-episode state
  (`data/cwt/<slug>/state.json`; finished steps are skipped), `transcribe --all --mode
  captions|whisper|auto` (YouTube captions with request sleeps; faster-whisper *small* CPU int8
  fallback in a separate venv `~/.venvs/cwt-whisper`, so the app venv is untouched), `extract
  --all` (Grok, back-off on 429/5xx) with a **classification** (daily_testable, intraday_only,
  options, futures_fx, discretionary, no_concrete_rules, macro_commentary) and a **template**,
  and a new `finish` step: groups testable episodes into **one strategy per trader + template**
  (repeat guests merged, all episodes linked), backtests each group (resumable by member hash),
  publishes groups with ≥ 10 trades and records every episode's status/reason in
  `alpatrade.cwt_episodes` (`sql/45_cwt_episodes_status.sql`: status, status_reason, category,
  template, transcript_source, strategy_key). Orchestrator: `data/cwt/logs/run_bulk.sh` (nohup).
- **Backtest templates** `engine/backtest/templates.py`: `dip` (mean reversion), `trend_ma`
  (SMA cross), `gap` (gap continuation at the open), `relative_strength` (rotation) alongside the
  pilot `breakout`; shared friction/metrics, cash only, prior-close signals, stop-before-target,
  parameters clamped (LLM percent→fraction fixed); train/test as slices of the full run.
- **Leaderboard UX for ~100 entries:** All / Live / Backtest and source filter pills with
  counts, a search box (trader or strategy), 25 per page with Previous / Next (ranks stay the
  full-board position), backtest sources list every linked episode, survivorship caveat in the
  method note. 375px: pills wrap, 40–44px tap targets, 16px search input, no overflow.
- Tests: filters/pagination/search, multi-episode source links (non-http rejected), templates
  no-look-ahead + P&L reconciliation, parameter clamping.

## 2026-10-10 — v0.30.0: Chat With Traders → backtested Leaderboard strategies (pilot: Kristjan Kullamägi)

- **Pipeline** `scripts/cwt_pipeline.py catalogue|transcribe|extract|backtest|publish|all`
  (`--episode N` / `--all`): scrapes chatwithtraders.com (sitemap + each episode page's embedded
  API state) → **135 `stocks` episodes** (of 337; 152 h), mp3 URL for all, YouTube URL for 124
  (yt-dlp `ytsearch` on the Chat With Traders channel, scored + de-duplicated) →
  `data/cwt/episodes.csv` + new table **`alpatrade.cwt_episodes`** (`sql/43_cwt_episodes.sql`).
  Transcribe = YouTube auto-captions (free), faster-whisper fallback, optional Gemini 2.5 Flash
  strategy read of the YouTube URL; extract = Grok (`grok-4.3`, JSON) → rule spec with quotes +
  timestamps + ambiguities; backtest + skill.md; publish. Bulk run **not** executed yet.
  Transcription cost/speed comparison: `docs/cwt_pipeline.md`.
- **Backtest engine** `engine/backtest/breakout.py`: daily-bar momentum breakout (prior momentum,
  tight consolidation, buy-stop at the consolidation high, low-of-day stop capped at 1 ADR,
  partial after N days + break-even stop, trail on the 10/20-day SMA, SPY 10>20 SMA filter),
  cash only, 10 bps slippage per side, signals from the prior close (no look-ahead; tested).
  Reuses the core engine's `Friction` and metric definitions. Data: Alpaca SIP daily bars,
  adjustment=all, current S&P 500 (survivorship-biased; noted in the skill).
- **Pilot ep. 212 Kristjan Kullamägi** (`data/cwt/212-…/`): 2016-01-04 → 2026-10-09 CAGR
  −1.8% vs SPY +15.2% (Sharpe −0.20, max DD −30.2%, 334 trades, 27% win rate); train 2016–21
  −0.7% vs +17.4%; test 2022–26 −3.2% vs +12.3%; train-optimised grid config OOS −3.3%. The
  daily-bar, S&P 500 version of the method does not reproduce his edge (he trades smaller,
  faster names with intraday opening-range entries).
- **Leaderboard: backtest strategies.** `alpatrade.user_strategies` gains `kind`
  ('live' | 'backtest'), `source`, `source_url`, `backtest_metrics` JSONB
  (`sql/44_user_strategies_backtest.sql`, additive). Backtests show a **Backtest** badge, the
  source link, "Backtest period" instead of "Running", CAGR and annualised alpha vs SPY on
  `/leaderboard` (always ranked after live strategies), a backtest KPI strip + "not a live track
  record" notice + out-of-sample figures on `/strategies/{id}`; `kind`/`source`/`source_url` in
  `/leaderboard.json` and the skill.md front matter. Owned by kaljuvee@gmail.com, shown as the
  trader. Strategy 1 is unchanged (Predictive Labs Ltd).
- Mobile (375px): leaderboard card + strategy page checked, no horizontal overflow.
- Follow-up: the method note defines backtest alpha as CAGR − SPY CAGR, and the "Latest data:
  session close" line only uses live strategies (a backtest end date no longer feeds it).
- Tests: `tests/test_cwt_pipeline.py` (backtest metrics, ranking, badges/source escaping, no
  look-ahead, cash/P&L reconciliation, caption + guest parsing, skill front matter/params).
- `.gitignore`: `data/cwt/` is tracked (except cached bars, caption JSON and audio).

## 2026-10-09 — v0.29.1: editable Leaderboard "Shown as" name

- **"Shown as" is now a proper per-strategy public user name** on the owner's edit view
  (`/strategies/{id}/edit`) and on New strategy (`/strategies/new`). It was already an input
  and the handler saved it, but: the edit form showed it **blank** when `author_name` was
  NULL (the page displayed a fallback the owner couldn't see/edit), new strategies and clones
  stored NULL (falling back to the profile display name), there was no sanitising beyond a
  120-char cap, and **`/strategies/{id}/skill.md` (and Copy for ChatGPT / Claude) kept the old
  name** in the skill's front-matter `author:` line.
- Now: the field is prefilled with the current public name (edit) or the **email local part**
  (new; clones get it too). On save it is trimmed, HTML tags / control characters stripped,
  whitespace collapsed, capped at **60** chars; blank falls back to the email local part.
  Everything is still HTML-escaped on render. Only the owner can edit (writes stay scoped by
  `user_id`; non-owners get 404).
- The skill's front-matter `author:` is rewritten to the "Shown as" name on save and at render
  time (`skill.with_author`), so `/leaderboard`, `/leaderboard.json`, `/strategies/{id}` and
  `/strategies/{id}/skill.md` all agree. Per-strategy only; the profile display name
  (`users.display_name`, `/profile`) is untouched and remains the fallback for legacy NULL rows.
- Mobile (375px): form inputs are 44px tall with 16px text (no iOS zoom), no horizontal overflow.
- Strategy id 1 (live Mag-7 BTD) keeps **Predictive Labs Ltd** (no data change).
- Tests: `tests/test_leaderboard.py` (sanitising, front-matter sync, prefill/escaping, owner
  edit round-trip across all four pages, non-owner 404, new/clone defaults).

## 2026-10-09 — v0.29.0: Hedge Funds replaces Pricing on the landing page; Leaderboard name

- **Pricing removed from the public site** (nav, footer, Platform hero button, `pricing_page`).
  AlpaTrade is free for everyone for now; `/pricing` now 301-redirects to `/#hedge-funds`.
- **Hedge Funds section on the home page** (`#hedge-funds`, nav + footer link in Pricing's old
  position): a real screenshot of the signed-in `/hedge-funds` page (13F-implied estimated
  annual returns vs SPY, 13F screener) with alt text, served from
  `static/landing/hedge-funds-desktop.png` (content pane only, app sidebar cropped so no
  account details show) and `hedge-funds-mobile.png` (414px phone rendering, used ≤560px via
  `<picture>`). Regenerate with `scripts/hedge_funds_snapshot.py` against a local instance
  using the dev-login bypass. **See more** CTA links to `/hedge-funds`.
- **`/hedge-funds` is now sign-in only** (it was publicly reachable): signed-out visitors get
  a 303 to `/signin?next=/hedge-funds` (query string preserved); the JSON endpoints
  (`/hedge-funds/data`, `/13f.json`, `/performance.json`) return 401 without a session.
- **Auth `next` support** (`engine/web/ph_auth.py`): `/signin`, `/register` and Google
  `/login` accept `?next=`; it is carried through a hidden form field, the Sign up / Log in
  cross-links and the Google round-trip (`session['auth_next']`), validated by `safe_next()`
  (same-site absolute paths only — `//host`, `/\host`, schemes and control chars are dropped)
  and used instead of `/dashboard` after sign-in / sign-up. Signed-in users hitting
  `/signin?next=…` go straight to the target.
- **Leaderboard public name:** the seeded live Mag-7 BTD strategy is shown as
  **Predictive Labs Ltd** (seed `author_name` + skill front matter / disclaimer). Prod row
  `alpatrade.user_strategies` id 1 (`seed_key='mag7-btd-live'`) updated in place
  (`author_name`, `skill_md`), so `/leaderboard`, `/strategies/1` and `/strategies/1/skill.md`
  no longer show the personal name.
- Mobile: checked at 375 / 414px (no horizontal overflow; phone screenshot served).
- Tests: `tests/test_landing_hedge_funds.py` (added to CI), `tests/test_leaderboard.py`,
  `tests/test_ui_navigation.py`. No changes to live trading, the runner, config, sizing or
  schedules.

## 2026-10-09 — v0.28.0: strategy Leaderboard + user strategies (moved from FastSkills)

- **`/leaderboard` (public)** — linked from the landing nav (desktop + a mobile-visible link),
  the home hero, the footer and the app sidebar (Trade → Leaderboard / My strategies).
  Lists every *public* strategy ranked by annualised return, showing only: strategy name,
  user name, description, **annualised return** (simple `return × 252 / trading days` via
  `engine/reporting/annualize.py`; compounded `(1+r)^(252/d)−1` as an indicative hover / tap
  note, since gains aren't reinvested immediately), **period running** (start date, days) and
  **alpha vs SPY** (strategy return − SPY return over the same period).
- **Figures are computed live inside AlpaTrade** from the owner's live runner run
  (`alpatrade.runs`, `mode='live'`, same `user_id`, linked by `live_strategy_slug`): start
  date / start equity / start SPY from `config`, and the latest session-close snapshot in
  `results.daily` — the same baseline as `/dashboard` and the LIVE email. No snapshot file or
  refresh job. Strategies without a live run (e.g. clones) show "—"; nothing is invented.
- **User strategies** (`alpatrade.user_strategies`, `sql/42_user_strategies.sql`, additive):
  users can own several; each is private (default) or public, with an owner-only
  public/private toggle, edit and delete on `/strategies`. Strategy page `/strategies/{id}`
  (public or own), raw skill at `/strategies/{id}/skill.md`, `/leaderboard.json`.
- **Actions:** Copy for ChatGPT / Copy for Claude copy the single-markdown strategy skill
  (rules prompt + numeric Parameters block) and open the assistant; **Clone into AlpaTrade**
  is a real in-app clone into the signed-in user's strategies (private, no live link);
  owners get "Backtest in AlpaTrade chat" (paper-only prompt built from the params).
- **Seed:** Julian Kaljuvee's live Mag-7 BTD strategy (public), skill ported from FastSkills
  `seed/trading/mag7-btd-live.md` and re-verified against `strategy_configs`
  `buy_the_dip_mag7_minhold_live` v2 (dip 3% vs 20-day high, TP 8%, SL 1.5%, min/max hold
  3 days, pos_frac 0.142857, cash only, extended-hours exits on). `python -m engine.leaderboard.seed`.
- **Mobile:** cards below 760px (checked at 375 / 414px, no horizontal overflow), 44px tap
  targets, tap-to-show tooltips on touch screens, compounded figure as secondary text.
- Tests: `tests/test_leaderboard.py` (added to the CI unit-test list).
- Deploy notes: migration 42 and the seed were applied to prod before deploy. No changes to
  live trading, the runner, `strategy_configs`, sizing or schedules.

## 2026-10-07 — Annualised return normalised since strategy start

- `/dashboard` headline **Annualised return** KPI now uses the return and NYSE trading
  days **since the strategy start** (label e.g. "Annualised return (since start · 9d)"),
  not the selected MTD/YTD window. MTD/YTD period return KPIs unchanged.
  - Live: start date + start equity from the latest live runner run (`alpatrade.runs`,
    same baseline as the LIVE email "Since start").
  - Paper: paper runner run tagged with the account (`config.account_id`), else the
    account's first portfolio-history equity. "All accounts" falls back to the period.
  - New `pnl_dashboard.since_start_annualized()`.
- Simple `r × 252 / d` stays primary; compounded `(1+r)^(252/d)−1` only in the tooltip,
  noted as indicative (we don't reinvest gains immediately).
- LIVE email: headline line "Annualised return (since start · Nd)" above the table;
  MTD/YTD rows kept as secondary ("Annualised by period").
- Tests in `tests/test_annualize.py`. No live trading / runner changes.

## 2026-10-07 — Annualised return KPI (dashboard + LIVE email)

- `/dashboard` (Live and Paper): the "Connection" KPI box is replaced by
  **Annualised return** for the selected period (MTD default / YTD).
  Formula: simple `return × 252 / trading_days`; tooltip also shows compounded
  `(1+r)^(252/d)−1`. Trading days = NYSE sessions elapsed in the window
  (completed sessions only, ET; rule-based holiday calendar). Shows "—" when < 1 day.
- LIVE daily email: new "Annualised return" table — MTD, YTD and since live start
  (return, trading days, simple, compounded) + plain-text summary lines.
  Email chart (CID PNG 2×, date axis) and BNBX exclusion unchanged.
- New `engine/reporting/annualize.py` + `tests/test_annualize.py`. No changes to
  live trading, cash-only sizing, or schedules.

## 2026-10-07 — Dashboard periods: MTD (default) and YTD only

- Account dashboard period tabs are now **MTD** (month-to-date, default) and
  **YTD** (year-to-date). Daily and weekly options removed from the UI.
- Period P&L, period return, and the paper equity curve use calendar MTD/YTD
  bounds (UTC). KPI labels read e.g. "MTD P&L" / "YTD return".
- Applies to both Live and Paper modes via the same period tabs; Live vs-SPY
  since-start curve is unchanged (not period-scoped).
- Legacy query values `daily` / `weekly` / `monthly` map to MTD so old links
  still work. Cash-only runner, BNBX exclusion, and LIVE email unchanged.


## 2026-10-06 — Dashboard: one account view + Live/Paper dropdown; sharper LIVE email chart

- **Dashboard duplicate fix:** `/dashboard` no longer stacks Live vs SPY on top of
  the paper Portfolio P&L. One page at a time — pick Live or Paper (or a specific
  account) from the account dropdown. The dropdown is always visible when accounts
  exist (including error states); it had effectively disappeared under the dual pane.
- **Live mode:** equity KPIs, since-start vs SPY curve, open positions (BNBX hidden),
  open orders. Cash-only runner sizing unchanged.
- **Paper mode:** richer paper view — portfolio P&L, advisor, rankings, recent paper
  strategy activity table, full open positions. No live block on paper.
- **LIVE email chart:** PNG rendered at 2× then downsampled (default 1120×420) for
  sharper Gmail display; visible x-axis date ticks (e.g. Sep 01 … Oct 06).
- **BNBX:** still excluded from LIVE email current-positions table and UPL (defense
  in depth in `_positions_table` + runner open lots); footnote only. Force-resend
  after deploy for verification.
- No margin/leverage changes.

## 2026-10-06 — LIVE email chart (MMG CID pattern) + hide BNBX + leverage WF

- Email chart: match MMG admin-main Postmark inline pattern — PNG attachment with
  `ContentID: cid:live-equity-curve`, `<img src="cid:…">` (double-quoted), plus
  `TextBody`. Gmail strips inline SVG; earlier CID attempt used single-quoted img.
- BNBX zombie OTC position excluded from LIVE email positions/UPL, `/live/account`,
  and `/dashboard` live view (footnote notes it is still held at the broker).
- Scratch leverage walk-forward (`scripts/scratch/btd_leverage_wf.py` on HP): Mag-7
  BTD min-hold cash-only vs 1.5x/2x buying power — at pos_frac 1/7 leverage barely
  changes OOS results (cash already covers slots). Do not enable live margin yet.
- No paper email. No live trades from this change.


## 2026-10-06 — LIVE email equity curve visible in Gmail (CID PNG)

- Root cause: daily LIVE email embedded an inline SVG equity curve; Gmail strips
  `<svg>` so Julian saw the SPY numbers but no chart (confirmed on the Oct 06
  resend: HTML had SVG, zero image attachments).
- Fix: render the same account-vs-SPY index-100 curve as a PNG via Pillow
  (`live_perf.png_equity_chart`), reference it as `cid:live-equity-curve`, and
  send it as a Postmark inline attachment (`ContentID`). Saved `--html-out`
  previews still use a data URI so the chart opens in a browser.
- `send_email_to_result` accepts optional `attachments`. No paper email / no trades.
- Tests: PNG bytes, CID in rendered HTML, attachment on send, Postmark payload.


## 2026-10-06 — Live account in /dashboard account dropdown

- Root cause: live Alpaca links live in `user_live_broker_accounts` (read-only);
  `/dashboard` only listed `user_accounts` (paper), so Julian saw paper only
  despite a linked live account 885504372 and working live email / `/live/account`.
- Fix: dashboard catalog includes linked live rows as `live:<account_number>`
  and loads them via the GET-only live client. "All accounts" stays paper-only
  (label becomes "All paper accounts" when a live link exists). Trading tools
  still cannot see live keys.
- Tests: `tests/test_pnl_dashboard.py` live dropdown / select / all-paper / render.


## 2026-10-06 — Live vs SPY equity curve on /dashboard

- Main dashboard (`/dashboard`) now shows the same Live account vs SPY summary
  and Plotly index-100 equity curve when a live broker account is linked
  (reuses `ph_live_account.load_view` / `live_perf`). Previously only on
  `/live/account` and the daily LIVE email.
- Paper daily email remains off for Julian; live daily email unchanged.

## 2026-10-06 — Live vs SPY on /live/account + email equity curve

- Shared helper `engine/reporting/live_perf.py`: since-start account/SPY/excess summary
  and daily equity curves (index 100).
- `/live/account` shows the SPY comparison table and a Plotly equity curve (account vs SPY).
- Daily LIVE email includes the same comparison plus an inline SVG equity curve.
- Paper daily email: preference row for Julian kept live ON / paper OFF (Settings path).

## Unreleased

### Per-user daily email report preferences

- Settings has a new "Email reports" card with checkboxes for the daily live
  trading report and the daily paper trading report. Users can turn both off. An
  option is disabled, with a note, when the user has no linked live account or no
  paper keys.
- Preferences are stored in `alpatrade.user_report_preferences` (migration 39,
  idempotent). A user without a row gets the defaults: live on, paper off. The
  migration keeps the paper report on for users who received it successfully in
  the last 14 days.
- The live report scheduler and the paper report scheduler both skip users who
  opted out and log each skip. Live delivery tracking
  (`live_report_deliveries`) is unchanged. If the preference lookup fails, the
  senders fall back to their previous behaviour and log a warning.
- Tests: `tests/test_report_preferences.py` (DB-free, added to CI).

### Continuous partial news ingestion

- Restored the original Finespresso behavior of saving every unique publisher
  article while retaining successful enrichment fields and using SQL nulls for
  unavailable values.
- Individual enrichment and publisher-cycle failures no longer terminate the
  continuously scheduled worker or block later articles.
- Backfill now retries incomplete rows across every event type, and the News
  Scheduler distinguishes enriched, retryable, and pending records.
- Restored all seven independently scheduled Finespresso publisher groups, including
  Euronext and OMX, with fair bounded collection and per-publisher cycle summaries.
- Replaced Euronext's obsolete anti-bot company-news URL with its official server-
  readable press-release list view; Baltics RSS remains healthy and unchanged.

### Finespresso realtime news and resumable backfill

- Added a dedicated realtime/backfill news worker with graceful shutdown,
  bounded retry, deterministic sharding, PostgreSQL checkpoints, and advisory locks.
- Preserved event-specific classifier/regressor selection from Finespresso and
  reject incomplete, placeholder, non-finite, or missing-model results.
- Added enriched press-release fields and filters plus worker progress in Data Health.
- Added a read-only News Scheduler dashboard with latest rows, event/prediction
  summaries, and durable sanitized activity events (migration 32).
- Logging now renders agent Markdown tables as accessible HTML tables, and run
  persistence replaces non-finite metrics with JSON null instead of failing a run.
- Added Coolify service configuration and focused DB-free worker tests.
- Bumped the package to 0.27.0. Deploy migration 31 before starting the worker.

### Unified LLM usage and daily budget

- Added migration 30 and tenant-safe LLM usage records for Hermes, DeepAgents,
  and LangGraph, including provider/model, input/output tokens, estimated cost,
  measurement quality, and platform-versus-BYOK attribution. Credentials and
  prompt text are never stored in the usage table.
- Restored Hermes streaming usage metadata instead of discarding the sidecar's
  final usage block. Missing provider metadata is explicitly labeled estimated.
- Added a shared configurable platform daily budget (default `$5`) and extended
  `/usage` with today's user/platform estimated spend. BYOK calls bypass platform
  spending while remaining visible to their owner and administrators.
- Added administrator-wide daily usage summaries and per-call details under
  Account → Logging, with existing owner isolation and email filtering.
- Bumped the package to 0.26.0. Deploy migration 30 before this revision.

### Unified user and agent activity logging

- Added `alpatrade.user_logging` for redacted, size-limited user questions and
  responses, including framework, outcome, thread, and timestamps.
- Added `alpatrade.agent_logging` plus idempotent PostgreSQL triggers that mirror
  Hermes jobs, canonical backtest/paper runs, and autonomy jobs. Migration 29
  also backfills existing job history without storing credentials or raw configs.
- Added `/admin/logging`: administrators can inspect and filter all users by
  email, while non-admin users are forcibly restricted to their own history.
- Logging failures are isolated from chat availability during rolling deploys.
- Tests cover migration contracts, secret redaction, ownership enforcement,
  administrator filtering, chat instrumentation, and private/admin UI states.

### Per-user xAI BYOK and starter allowance

- Added a Settings card for each signed-in user to save, replace, or remove an
  xAI API key. Keys are Fernet-encrypted in PostgreSQL; the browser receives
  only a short non-secret hint, and the Show button reveals only newly typed text.
- Routed DeepAgents and LangGraph model clients through the owning user's xAI
  key without sharing credential-bearing clients between accounts.
- Added an atomic five-query platform allowance to web chat. Failed model calls
  refund their reserved slot, while deterministic Hermes trading commands do
  not consume a model query. The allowance is configurable with
  `FREE_PLATFORM_QUERY_LIMIT` (default `5`).
- Added a deterministic `/usage` command showing the signed-in user's funding
  source, used and remaining starter queries, and percentage consumed. A saved
  chat warning is appended after a successful platform-funded response reaches
  90% of the allowance; checking usage never consumes a query.
- Extended the same visible-request gate to free-form Hermes calls. Supported
  deterministic Hermes commands stay free, and a Hermes-to-DeepAgents fallback
  reuses the original reservation rather than charging twice. The counter is a
  request guard; exact internal Hermes turns/tokens still require an LLM proxy.
- Closed the Hermes-outage fallback gap: if the app falls back to the hosted
  DeepAgents model, that call now reserves/refunds the same user allowance.
- Added idempotent migration `sql/28_xai_byok_query_gate.sql`. Deploy it before
  enabling this branch: `python run_migration.py sql/28_xai_byok_query_gate.sql`.
- Added network-free tests for the allowance boundary, safe Settings rendering,
  and API-key serialization. No xAI or Hermes calls are made by these tests.
- Added deterministic Hermes commands for the latest owned backtest's trade
  table, best/worst trade, and average holding period. Results come directly
  from user-scoped `alpatrade` tables and emphasize realized P&L and return;
  these commands never invoke xAI.
- Added safe Hermes natural-language trade analytics for owned backtest and
  paper runs. Questions about P&L, return, win rate, holding time, trade count,
  and symbol breakdowns select parameterized, read-only SQL templates restricted
  to `alpatrade`; Hermes receives neither raw SQL execution nor DB credentials.
- Clarified the consolidated daily report by separating Alpaca account-equity
  movement from realized agent P&L, adding a correct all-agent total row, and
  showing per-trade return plus normalized take-profit/stop-loss reasoning.
  Empty trade sections now distinguish a valid no-signal day from missing data.
- Expanded Hermes paper-job analysis with open-entry and completed-exit tables,
  realized return evidence, elapsed idle time, and a review/retest recommendation
  after 24 hours without any saved trade. Missing broker prices are labeled
  unavailable instead of being presented as zero unrealized P&L.
- Fixed Hermes progress messaging so ordinary research questions no longer say
  that a backtest is running; the backtest label is now shown only when the
  submitted request actually contains a backtest instruction.

### In-product daily advisor digest

- Added a polished `/advisor` page surfacing the persisted post-close advisor
  reports in-product: one section per paper account for the selected session,
  with severity and status chips, headline, summary, performance drivers,
  data-quality notes, and the mandatory disclaimer.
- Added a session-history rail (newest 30 sessions) plus date pills, so the
  digest is browsable per day instead of only latest-in-dashboard.
- Added "Test in chat" deep links from backtest recommendations — they open a
  fresh chat pre-filled with an `agent:backtest` command matching the
  recommendation's strategy, symbols, and lookback, while the exact proposed
  parameter grid stays displayed for reference.
- Linked the dashboard advisor card headline and empty state to the new page,
  and added a "Daily advisor" entry (with icon) to the Trade nav section.
- The page is read-only: it never mutates reports, enqueues runs, or bypasses
  the explicit-approval gate on advisor recommendations.

### Hermes candidate promotion correctness

- Fixed Hermes paper promotion to pass the exact approved candidate parameters
  into the standalone orchestrator. Previously, the worker stored the candidate
  under `params` but omitted `approved_best_config`, causing YAML defaults to be
  traded and reported instead.
- Forwarded the requested robustness-window count and benchmark symbol through
  the orchestrator, so the three-window Hermes validation contract is actually
  executed rather than only recorded in the queued job.
- Preserved the source backtest lookback when promoting a candidate, keeping the
  paper-run slug and daily-report lineage aligned with the research period.
- Improved Hermes-only command output: running-job queries now exclude history,
  zero-exit sessions report `WAITING` and `N/A` win rate, backtest metrics use
  explicit percentage units, and benchmark underperformance is highlighted.
- Added regression coverage for exact candidate promotion, robustness forwarding,
  running-job filtering, and zero-exit reporting.

### Hermes clarification and suggested follow-ups

- Added persistent, clickable suggested follow-ups beneath every Hermes response;
  clicking fills the composer so the user can review or edit before sending.
- Added a deterministic clarification gate for incomplete backtests, ambiguous
  paper starts, and parameter-change requests. Hermes now states what is missing
  and queues nothing instead of silently choosing defaults.
- Fixed hyphenated natural periods such as `6-month`, which previously bypassed
  the period parser and fell back to three months.
- Blocked promotion of legacy candidates whose saved job requested robustness
  validation but did not complete every requested window; their follow-up now
  proposes a fresh backtest instead of paper trading.

### Consolidated daily agent digest

- Replaced the duplicate Hermes-only daily summary with the account-owned
  AlpaTrade digest. Immediate opt-in Hermes entry/exit alerts remain independent.
- Added Today/MTD/YTD realized agent benchmarks and explicit no-data rows for
  Hermes, DeepAgents, and LangGraph.
- Corrected fractional strategy parameter display (`0.05` now renders as `5%`)
  and added an equity reconciliation notice when Alpaca prior-close P&L differs
  from the last emailed equity snapshot.
- Added a concise agent-status section with safe next commands and clearer
  zero-activity language.
- Fixed deployment recovery for older continuous Hermes jobs whose heartbeat is
  null, and reactivate the canonical run when the worker reclaims the job so
  chat status and daily reporting cannot disagree.

### Guided Hermes workflow

- Added clickable Hermes Backtest, Paper Trade, and Monitor shortcuts to the
  left Agents panel.
- Reworked `/hermes help` into a numbered quick start and explained the
  difference between job, run, and candidate IDs.
- Added no-ID analysis and pause/resume/stop commands that safely resolve the
  latest applicable paper job owned by the authenticated user. Explicit IDs
  remain supported when an account has multiple jobs.
- Tests cover sidebar rendering, deterministic help, ownership-safe job
  selection, and existing ID-based commands.

## 0.23.0 — 2026-08-25

### Attribute autonomous paper runs to a configured owner

- Closes the gap noted in 0.22.0: the paper runs seen piling up were the
  autonomy worker's **scout self-feed** (`worker.loop` → `scout.enqueue_run`),
  which enqueued runs with **no owner** (user_id NULL). Because the 0.22.0 dedup
  guard only acts on attributed runs, those orphans were never de-duplicated.
- The worker now resolves an owner via `worker.scout_owner()`
  (`AUTONOMY_OWNER_USER_ID`/`AUTONOMY_OWNER_ACCOUNT_ID`, falling back to
  `PAPER_USER_ID`/`PAPER_ACCOUNT_ID`) and passes it to the scout, so self-fed
  runs are tenant-scoped sessions and the dedup guard applies to them.
- Both ids must be set together; a half-configured pair resolves to unattributed
  (never a broken key lookup). One env pair now owns both the autonomy self-feed
  and the fixed `paper-strategy` service.
- `docker-compose.yaml`: autonomy service passes `AUTONOMY_OWNER_*` (defaulting
  to `PAPER_*`).

## 0.22.0 — 2026-08-25

### Fix: duplicate live paper runs (replace, session-scoped)

- Paper runs are no longer allowed to pile up: `run_paper_trade` now replaces this
  session's own prior identical live run(s) before starting a new one
  (`stop_duplicate_paper_runs`), marking the old ones `stopped`.
- Strictly scoped to the SAME user + account + strategy_slug + symbol-set, and a
  no-op unless the run is attributed (user_id + account_id set) — it can never
  stop another user's runs, a different config, or an unattributed run.
- Note: the runs seen piling up were unattributed system/env paper runs
  (user_id NULL); attaching them to an owner (so this guard applies) requires the
  autonomy/paper-strategy spawner to run with a user/account.

## 0.21.0 — 2026-08-24

### Daily PnL report — critique fixes (1-10)

- Unified stale-orphan run status on `'stale'` (worker sweep + report reconcile
  agreed), leaving `'stopped'` for a deliberate Ctrl+C.
- CLI `--user/--account/--framework` now render the full per-account report
  (MTD/YTD, agent benchmark, live runs), matching the scheduler.
- Hybrid MTD/YTD: seed the baseline from Alpaca portfolio history when snapshots
  don't reach the window start, so returns are correct retroactively; each window
  tags its `source`.
- Labeled baselines: "today (vs prior close)" and "unrealised (since entry)".
- Populate `net_cash_flow` from Alpaca activities so the cash-flow correction is
  real, not a silent no-op.
- Added a SPY buy-and-hold benchmark (with excess return) on MTD/YTD.
- Added cumulative realized P&L, annualized Sharpe, and max drawdown from the
  equity-snapshot curve.
- Back-dated reports show that day's equity/day-change from Alpaca history (only
  positions/cash stay live), with a precise notice.
- Added a "data unavailable" banner distinguishing an outage from "no activity".
- Consolidated recipients: `--to` wins, else the account owner, else the legacy
  `PNL_REPORT_TO` broadcast.
- Tests: analytics + render helpers, email send, run recovery (DB-free).

## 0.20.1 — 2026-08-24

### Fix: daily PnL report email actually sends

- `send_email_to()` had no body after the env check — when Postmark was
  configured it fell through and returned `None`, so the daily PnL report emailed
  nothing and the CLI aggregator crashed on `all_ok &= None`. The worker-owned
  scheduler uses the same helper, so scheduled tenant reports silently never sent.
- Added the missing Postmark POST and a strict bool return; DB-free tests cover
  send/uncleared-env/transport-error/return-type.

## 0.20.0 — 2026-08-24

- Rebuilt the standard daily paper report around per-user, per-account Alpaca
  credentials; removed the hard-coded distribution list and cross-tenant run/trade
  queries.
- Added heartbeat-verified paper-run status, process-safe delivery claims, account
  equity snapshots for honest MTD/YTD returns (superseding the 0.19.0 Alpaca
  portfolio-history period returns), and separate realized-P&L benchmark
  rows for Hermes, DeepAgents, LangGraph, and explicitly labeled legacy runs.
- Bridged the durable Hermes job heartbeat into canonical run liveness and protected
  fresh Hermes jobs during stale-run reconciliation.
- Replace `/app?new=1` with the saved thread URL after the first response so refresh
  restores the new conversation instead of showing a blank composer.
- Added migration `sql/25_tenant_agent_reporting.sql`; it only alters/creates objects
  inside `alpatrade` and does not rewrite existing trades or run statuses.
- Fixed Hermes detailed-backtest result routing so commands containing a job ID
  return the selected result instead of the general jobs list.
- Added three validation robustness windows plus SPY buy-and-hold and excess-return
  evidence to new Hermes backtests; promotion now requires positive results across
  a majority of the robustness windows.
- Added a Hermes-only paper drift guard that waits for 20 closed trades across at
  least five trading days and automatically pauses when daily paper Sharpe falls
  below half the validated Sharpe.
- Added owner-scoped notification delivery tests/history and DB-to-broker position
  reconciliation in Hermes daily reports. Default agents and live trading paths
  remain unchanged.
- Tests: result routing, delivery history, drift thresholds, reconciliation,
  robustness windows, benchmarks, default-agent isolation, tenant report isolation,
  liveness, and framework-separated rendering.

## 0.19.0 — 2026-08-23

### Daily report: period returns

- Added month-to-date, year-to-date, and overall (since-inception) arithmetic
  returns to the daily paper-PnL report, alongside the existing day change.
  Each window's baseline is the first available equity point from Alpaca's
  portfolio history; the return is `equity_now / baseline - 1`.
- Added an `AlpacaAPI.get_portfolio_history()` wrapper (normalized equity/PnL
  series, null/zero padding dropped) used by the report.
- Deposits/withdrawals are not modelled — for a paper account funded once (the
  norm) this equals the true cumulative return; missing windows render as `n/a`.
- Tests: history normalization, arithmetic-return math, graceful empty history,
  and Performance-table rendering (DB-free).

## 0.18.0 — 2026-08-23

### Stale paper-run cleanup ("zombie" runs)

- Added `heartbeat_at` to `alpatrade.runs` (`sql/24`); a live paper session now
  stamps its heartbeat each cycle so a legitimately long-running session is never
  mistaken for an orphan.
- The autonomy worker sweeps paper runs left `running` by an interrupted or
  redeployed process (heartbeat older than `RUNS_STALE_SECONDS`, default 30 min)
  to `stopped`, and the migration finalizes already-orphaned rows once. This stops
  the daily report from showing "+N older runs with identical configuration still
  marked running".
- Tests: migration hygiene, heartbeat/sweep contracts, per-cycle heartbeat, and
  the worker sweep call.

## 0.17.0 — 2026-08-23

### Daily DeepAgent trading advisor

- Added one persisted, tenant/account-scoped paper advisory after each actual
  Alpaca/NYSE session close plus 15 minutes. Deterministic policy classifies
  reports as `insufficient_data`, `monitor`, `review`, or `urgent` and keeps
  broker-account P&L separate from AlpaTrade-attributed realized P&L.
- Added a locked-down `trading-advisor` DeepAgent specialist. It may rank only
  server-generated candidate IDs; unknown evidence, unsupported claims,
  invented metrics, and altered values are rejected into a deterministic fallback.
- Added authenticated report history/detail APIs, persisted dashboard cards,
  consolidated per-user email rendering, and explicit-intent tools that queue
  a stored advisor grid or start paper trading only from an owned, completed,
  validated backtest. Scheduled reports never change a strategy or place an order.

### Scheduling, persistence, and rollout

- Added migration `sql/23_daily_advisor.sql` for `advisor_reports` and
  deduplicated `advisor_deliveries`, and moved scheduler ownership exclusively
  to the autonomy worker with holiday, early-close, and DST-aware timing. A
  dedicated advisor queue lane keeps post-close reporting responsive while a
  longer paper-trading phase occupies the general autonomy lane.
- Retired web-process, standalone-paper, hardcoded-recipient, and per-session
  daily email paths. The legacy email request field remains accepted but is
  deprecated. `ADVISOR_EMAIL_ENABLED` defaults to `false` for the first-session
  report-only rollout; `ADVISOR_ENABLED` defaults to `true` in Compose.
- Added optional `PAPER_USER_ID`/`PAPER_ACCOUNT_ID` binding for the fixed paper
  service so its runs and trades can be attributed to the matching advisor account.
- Corrected validation-count persistence (`total_trades_checked` → `total_checked`)
  so non-empty validated backtests satisfy the explicit paper-start gate.
- Added DB-free coverage for metrics, thresholds, parameter units, model-output
  filtering, fallbacks, calendar timing, deduplication, consolidation, tenant
  isolation, API contracts, and explicit-intent gates. Bumped package/lockfile
  to 0.17.0.
- Apply `python run_migration.py sql/23_daily_advisor.sql` before deploying the
  worker/API/web services. Inspect at least one generated session before setting
  `ADVISOR_EMAIL_ENABLED=true`; deployment and email activation are not included.

## 0.16.0 — 2026-08-23

### Tenant-safe DeepAgents API

- Added authenticated `POST /v2/deepagents` as the canonical DeepAgents-only
  endpoint with append-only durable threads, stable client message UUIDs,
  replay-safe response idempotency, JSON responses, and SSE streaming.
- Added sanitized tool/subagent lifecycle events and heartbeats. Traces expose
  identity, status, and timing only; arguments, results, credentials, and raw
  exceptions remain private.
- Added five native specialists for market research, caller-owned portfolio
  analysis, strategy work, paper trading, and orchestration. Disabled the
  default general-purpose subagent and blocked filesystem/shell tools.
- Routed the older `/v2/chat` and `/v2/agents/chat/invoke` wire formats through
  the shared service. Anonymous compatibility chat now receives public research
  tools only and never falls back to deployment broker credentials.

### Persistence and paper-action safety

- Added migration `sql/22_deepagent_responses.sql` for durable response,
  sanitized event, action-deduplication, and job-deduplication records.
- Added the official asynchronous PostgreSQL LangGraph checkpointer with a
  shared pool, `alpatrade` search path, idempotent setup, and pickle fallback
  disabled in the MessagePack serializer.
- Generalized the autonomy worker by job kind. Backtests, paper sessions,
  full cycles, and autonomy requests return durable job IDs; full cycles retain
  Backtest → Validate → Paper → Validate → Reconcile → Report checkpoints.
- Enforced explicit imperative intent for mutating tools, caller-owned encrypted
  Alpaca credentials, `paper=True`, deterministic paper `client_order_id`
  values, tenant-scoped cancellation, and no automatic retry after uncertain
  paper-capable worker failures.

### Tests and deployment

- Added DB-free coverage for validation, auth boundaries, replay/concurrency,
  runtime context, specialist/tool registration, trace redaction, token
  normalization, heartbeats, stream failures, and paper-client identity.
- Added `deepagents<0.7`, `langgraph-checkpoint-postgres`, and psycopg 3 pool
  dependencies and bumped the package/lockfile to 0.16.0.
- Apply `python run_migration.py sql/22_deepagent_responses.sql` before deploying
  the API and worker. Deployment itself is not included in this release.

## 0.15.0 — 2026-08-22

- Added Hermes-only conservative backtests with five-basis-point entry/exit
  slippage, regulatory fees, stop-first ambiguous daily bars, close-time entry
  attribution, and portfolio daily-equity Sharpe, Sortino, and drawdown.
- Split Hermes research into 70% training and 30% untouched validation, persist
  both date ranges and validation metrics, and block paper promotion unless the
  validation return, Sharpe, drawdown, trade-count, and stability gates pass.
- Forward the requested objective and methodology flags through the orchestrator,
  attribute research jobs/candidates to the user's linked account when available,
  and release worker claims on terminal states.
- Added explicit methodology and promotion status to saved chat results. Legacy
  candidates without validation evidence can no longer start a Hermes paper job.
- Tests: conservative metric math, objective plumbing, train/validation isolation,
  promotion gates, worker cleanup, default-agent isolation, and full CI suite.
- Fixed combined candidate-start commands containing `notify me both` so they
  queue the validated paper job instead of being mistaken for an update request.

## 0.14.0 — 2026-08-22

- Added Hermes-only performance emails with reconciled signed P&L, grouped
  fills, green/amber/red status, concise reasons, and supported next commands.
- Added detailed entry/exit alerts with quantities, prices, thresholds, P&L,
  rationale, and owned job/run/candidate attribution.
- Added `/hermes analyze paper job <job-id>` for an owner-scoped diagnosis of
  results, repeated fills, duplicate Hermes jobs, and overlapping account runs.
- Finalize stop requests whose paper worker was interrupted during deployment,
  preventing an orphaned job from remaining incorrectly marked as running.
- Accept compact Hermes backtest periods such as `lookback:6m` and
  `lookback=1y` instead of silently applying the three-month default.
- Honor the explicit `objective:sharpe_ratio` contract when selecting the best
  eligible variation, and release worker claims when jobs finish or fail.
- Kept the established AlpaTrade daily email and the DeepAgents/LangGraph
  execution paths unchanged; all Hermes execution remains paper-only.
- Tests: Hermes report calculations, alert rendering, durable trade loading,
  ownership, overlap detection, command routing, and default-template isolation.

## 0.13.0 — 2026-08-21

- Added user-scoped Hermes portfolio recommendations and persisted entry, exit,
  hold, and watch advice in `alpatrade.hermes_advice` (migration 21).
- Added selectable in-app, email, both, or disabled advice delivery per active
  Hermes paper job, with duplicate-alert suppression and daily-email advice.
- Added deterministic `/hermes help`, portfolio construction, advice history,
  and notification commands. Advice is paper-only and never places extra orders.
- Kept DeepAgents, LangGraph compatibility routing, and default chat behavior
  unchanged.
- Tests: focused Hermes contracts, CI-default DB-free suite, compile/import,
  migration transaction, secret scan, and regression suite.

## 0.12.0 — 2026-08-21

### Hermes paper operations and voice

- Added deterministic, account-owned `/hermes` commands to start a saved
  candidate in paper mode and pause, resume, or stop its durable job.
- Added daily report opt-in stored on the owned paper job; recipients resolve
  from the authenticated user's login email instead of the global `TO_EMAIL`.
- Added durable controls and responsive worker polling. Explicitly continuous
  paper jobs requeue after worker restarts; finite jobs retain fail-safe recovery.
- Added an authenticated Hermes command tool to voice mode and changed voice
  position lookup to use the logged-in user's linked Alpaca paper account.
- Live-order routes remain unavailable.

### Tests and deployment

- Added command-intent, ownership, paper-control, report, worker-recovery, and
  voice-tool contracts.
- Apply `sql/20_hermes_paper_controls.sql`, then redeploy the full Compose
  resource so both `agui` and `hermes-jobs` use version 0.12.0.

## 0.11.0 — 2026-08-20

### Durable asynchronous Hermes jobs

- Changed scoped Hermes backtests and paper sessions from blocking HTTP calls
  to PostgreSQL-backed jobs that immediately return `job_id` and `run_id`.
- Added a deterministic `/hermes ... backtest` dispatcher in the AlpaTrade web
  tier, so queue creation occurs before remote model planning or terminal tools.
- Added an isolated AlpaTrade `hermes-jobs` worker, owned job status endpoints,
  candidate creation on successful backtests, and completion/failure messages
  written into the originating saved chat.
- Added five-second chat synchronization so results appear while a chat remains
  open; users may navigate away, close the browser, or inspect jobs later.
- Interrupted backtests are safely requeued. Interrupted paper sessions are
  failed rather than replayed, preventing duplicate paper orders.
- Removed every documented fallback to general backtest, paper, authentication,
  or generated test-user routes. Live trading remains unavailable.

### Tests and deployment

- Added DB-free contracts for delegated ownership, queue submission, worker
  attribution, candidate output, recovery policy, and service isolation.
- Apply `sql/19_hermes_jobs.sql` before redeploying the complete Compose resource.

## 0.10.0 — 2026-08-20

### Hermes Agent integration — Phase 2

- Added a dedicated Hermes broker with short-lived, per-user delegation and no
  database, Alpaca, JWT, or general service credentials in the Hermes service.
- Added user-owned backtest execution, best-parameter candidate persistence,
  run inspection, and candidate-to-paper promotion under `/v2/hermes/*`.
- Added `agent_name` and `agent_framework` attribution plus the
  `alpatrade.strategy_candidates` store. Live execution remains unavailable.
- Persisted `/app` conversations per account with sidebar resume/delete, and
  added visible elapsed-time/tool progress for long Hermes operations.
- Removed duplicated browser history from persistent Hermes sessions, extended
  per-message delegation to 30 minutes, and disabled non-renderable gateway
  approval prompts inside the credential-isolated Hermes container.

### Tests and deployment

- Added security-contract coverage for delegation signing, key separation,
  Compose credential isolation, schema-qualified migration objects, owned chat
  history, and long-running progress behavior.
- Apply `sql/18_hermes_agent_attribution.sql` before redeploying, then enable
  only **Terminal & Processes** with `hermes setup tools` for the mounted skill.

## 0.9.0 — 2026-08-20

### Hermes Agent integration — Phase 1

- Replaced the Hermes-as-LangGraph placeholder with an authenticated client for
  Nous Hermes Agent's OpenAI-compatible gateway, including SSE streaming and
  stable per-user and per-thread memory scopes.
- Added one-message `/hermes`, `/deepagents`, and `/langgraph` chat overrides;
  unprefixed messages continue using the user's saved framework.
- Added a private, persistent Hermes service to the Coolify Compose topology and
  retained DeepAgents as the automatic fallback when Hermes is unavailable.

### Tests and deployment

- Added DB-free tests for Hermes request construction, authentication, remote
  invocation, and runtime-prefix routing, and included them in CI.
- No database migration is required. Coolify requires `HERMES_API_SERVER_KEY`,
  one supported Hermes model-provider credential (including XAI/Grok), and
  one-time profile setup.

## 0.8.3 — 2026-08-15

### Developer and agent documentation

- Replaced raw-JSON-first links on the Developers page with an inline catalogue
  of all callable agents, including their skills, endpoint, execution model,
  access requirement, and paper/read-only safety boundary.
- Added browser-aware navigation so direct visits to the agent catalogue and
  OpenAPI JSON open the formatted ReDoc reference, while API clients continue
  to receive the canonical machine-readable JSON contracts.
- Enriched OpenAPI operations with agent skills and vendor metadata, grouped
  ReDoc navigation, deep links, and an interactive Swagger configuration suited
  to service integrations.

### Tests and deployment

- Added DB-free coverage for agent skill metadata, ReDoc grouping, browser/API
  content negotiation, and developer-page catalogue content.
- No database migration or configuration change is required.

## 0.8.2 — 2026-08-15

### New Chat news pane

- Opened the News pane by default on New Chat and restored it whenever the New
  Chat action resets an existing conversation.
- Replaced the close icon with directional controls: `>` minimizes the open
  News pane and `< News` maximizes it again.
- Added accessible control labels and synchronized expanded state.

### Tests and deployment

- Added DB-free coverage for the default-open state, New Chat reset behavior,
  directional controls, and their accessibility attributes.
- No database migration or configuration change is required.

## 0.8.1 — 2026-08-15

### Web layout

- Added a shared, constrained scrolling viewport to every application route so
  long tool, research, monitoring, and public-market pages remain scrollable on
  desktop and mobile while the sidebar and chat composer stay fixed.
- Kept wide tables and data views horizontally accessible on narrow screens
  without introducing document-level overflow.
- Preserved the chat and guide views' internal scrolling within the new shared
  center-column container.

### Tests and deployment

- Added DB-free regression coverage for the shared page viewport and verified
  route scrolling locally in Chromium at desktop and mobile viewport sizes.
- No database migration or configuration change is required.

## 0.8.0 — 2026-08-15

### External API and agent access

- Added a public agent catalog plus typed JSON invocation endpoints for the primary
  LangChain DeepAgent, Premarket Agent, Growth and Value research agents, their
  combined view, and the paper-only autonomy scout.
- Documented the existing Backtest, Validation, Paper Trade, Reconciliation,
  Report, and Orchestrator endpoints as canonical external agent interfaces.
- Added API discovery at `/`, production server metadata, explicit Swagger UI,
  ReDoc, and OpenAPI routes, stable package-version metadata, and request IDs.

### Security and developer experience

- Replaced spoofable standalone `X-User-Id` trust with JWT, configured service API
  keys, or a short-lived signed internal identity; tenant data and actions now
  require a concrete user identity.
- Restricted browser CORS to configured AlpaTrade origins and made direct order
  placement use only the authenticated user's linked Alpaca paper account.
- Added a public `/developers` page and homepage/footer navigation to Swagger,
  ReDoc, the live OpenAPI JSON contract, and the machine-readable agent catalog.

### Tests and deployment

- Added DB-free API discovery, authentication-boundary, request-ID, agent-catalog,
  and developer-navigation regression coverage.
- No database migration is required. Configure `API_SERVICE_KEY` or
  `API_SERVICE_KEYS` before onboarding trusted service clients.

## 0.7.0 — 2026-08-15

### DeepAgents and autonomy

- Made LangChain DeepAgents the primary chat and reasoning harness while retaining
  the existing LangGraph-compatible streaming interface and compatibility alias.
- Added a safe runtime fallback chain from DeepAgents to LangGraph and Hermes.
- Added best-effort LLM annotations to autonomy scouting, backtest selection, and
  refit decisions without changing deterministic paper-trading risk gates.

### Interface

- Improved authentication form accessibility with associated labels, browser
  autofill metadata, and announced success/error notices.
- Updated the Settings framework selector and architecture documentation to show
  DeepAgents as the default.

### Tests and deployment

- Added DB-free runtime-default, subagent construction, scout, backtest, refit,
  and authentication accessibility coverage to the CI unit suite.
- Verified syntax compilation, 101 DB-free tests, and the secret scan. No database
  migration is required for this release.

## 0.6.0 — 2026-08-06

### Alpha Research

- Added a collapsed Alpha Research sidebar section with editable Growth Agent
  and Value Agent commands, plus a compact Combined View.
- Ported the concise Growth and Value methodology themes from Alpha Agents into
  an in-process, read-only AlpaTrade runner using existing company, financial,
  valuation, analyst, news, and per-user model providers.
- Added `alpha:runs` for user-scoped saved-report history and deterministic
  evidence fallback when model synthesis is unavailable.
- Added `alpha:compare` to collect evidence once, run compact Growth and Value
  synthesis concurrently, and save both perspectives as ordinary research runs.
- Added `alpha:show run-id:<uuid>` and a Saved Reports sidebar group so users
  can reopen user-scoped stored reports without new data or model calls.

### Persistence and deployment

- Added idempotent migration `sql/17_alpha_research_runs.sql` for user-scoped
  completed, partial, and failed research reports.
- Apply `python run_migration.py sql/17_alpha_research_runs.sql` before deployment.
  Reports still return with a visible not-saved warning when persistence is not
  configured or the migration has not been applied.

### Tests

- Added DB-free coverage for sidebar commands, routing, ticker validation,
  methodology prompts, evidence fallback, persistence lifecycle, and user-scoped
  recent-run queries.

## 0.5.2 — 2026-07-29

### Authentication navigation

- Restored `/` as the public landing page regardless of existing session state.
- Successful password, registration, and Google login flows now redirect directly
  to `/dashboard`; ordinary visits to the root no longer do so.
- Added a visible sign-out action to the dashboard header and styled the existing
  authenticated-sidebar sign-out link.

## 0.5.1 — 2026-07-28

### Market data providers

- Removed the retired Polygon/Massive implementation, credentials, endpoints,
  configuration choices, news fallback, documentation, and legacy imports.
- Yahoo Finance is now the default market-data provider and requires no key.
- Alpaca market data is an optional provider using the existing Alpaca account
  credentials; stale or unknown provider values fall back safely to Yahoo.
- Updated validation, paper trading, backtesting, research, regime detection,
  CLI completion, and Docker Compose services to use the shared provider adapter.

### Tests

- Added provider default/fallback coverage and updated the market-data feed tests.
- Twenty focused tests and syntax compilation passed. The broad regression retains
  its four environment `pytz` errors and two pre-existing autonomy threshold failures.

## 0.5.0 — 2026-07-28

### Portfolio dashboard

- Made an authenticated, account-scoped Portfolio P&L dashboard the default
  post-login home page.
- Added current calendar day, week, and month views using Alpaca portfolio
  history, with equity, return, cash, buying power, unrealized P&L, and Plotly
  equity/contributor charts.
- Added paper and backtest strategy leaderboards and cached, fact-grounded AI
  commentary routed through each user's configured model provider.
- Added an all-accounts view, automatic selection of a funded account, support
  for read-only paper and live Alpaca credentials, and connect-account onboarding.
- Corrected backtest account scoping to join through its owning run, retaining
  compatibility with databases where `backtest_summaries` has no `account_id`.

### Tests

- Added DB-free tests for calendar bounds, account isolation, funded-account
  selection, aggregation, and onboarding.
- Expanded Playwright coverage to assert real dashboard Plotly charts at
  desktop, tablet, and mobile widths.

## 0.4.1 — 2026-07-28

### Fixed

- Fixed streamed Plotly charts being removed when the final SSE `done` event
  rewrote the already-rendered chat bubble.
- Added an authenticated local Playwright regression that submits “Show me a
  market map” and requires real Plotly and treemap SVG nodes with no page errors.

## 0.4.0 — 2026-07-28

### Research workspace

- Migrated Finespresso research into five FastHTML submenu pages: Premarket,
  Model Analytics, News Intelligence, News Timing, and Historical Research.
- Reads the existing database through explicitly schema-qualified `public.*`
  relations; scheduler-owned premarket refreshes remain outside AlpaTrade.
- Added real Plotly sector breadth, prediction scatter, event-by-industry
  correlation heatmap, publication timing, and stored classifier/regressor metrics.
- Added `analyze_prediction_correlation` to streaming chat. The active user's
  configured AlpaTrade model interprets deterministic research results.
- Preserved historical Finespresso event aliases in a shared normalization module.

### Tests and deployment

- Added Research data, navigation, chart-transport and schema-boundary tests.
- Added Research-agent routing and LLM-judge eval cases.
- Playwright-smoked every Research route at desktop and mobile widths.
- No database migration is required. The Finespresso scheduler remains responsible
  for updating the shared public premarket tables.

## 0.3.0 — 2026-07-28

### Added

- A complete FastHTML port of the Finespresso premarket screener: 165 sector
  memberships across 11 US sectors, prior-close versus premarket OHLC moves,
  ranked gainers/fallers, sector breadth, mover detail, catalysts, and sources.
- The read-only Premarket Agent and `get_premarket_movers` chat tool, with
  persisted-scan and explicit fresh-scan modes.
- PostgreSQL migration `16_premarket_scans.sql`, with compatible local JSON
  fallback for environments where the migration has not yet been applied.
- Categorized premarket catalysts in the shared right-hand news pane.
- Agent-routing and LLM-judge eval coverage for premarket requests, plus
  desktop/mobile Playwright smoke coverage and DB-free regression tests.

### Changed

- Premarket market-data acquisition is batched rather than issuing sequential
  requests for every symbol.
- Expanded the agent eval corpus to 102 cases with tool-trajectory validation,
  per-category filtering, PASS/FAIL routing results, and UI eval reporting.
- Fixed inline chart tools such as `show_market_map` by preserving chart
  markers returned from tool events through the FastHTML SSE stream.

### Tests

- 59 DB-free CI tests passed.
- Premarket Playwright smoke passed on desktop and mobile, including catalyst
  detail and categorized-news rendering with no browser console errors.
- The broad regression suite passed 99 tests; two pre-existing autonomy
  promotion-threshold assertions remain failing and are unrelated to this port.
- Syntax compilation and secret scanning passed.

### Deploy Notes

- Apply `python run_migration.py sql/16_premarket_scans.sql` before deployment
  to enable PostgreSQL scan history. Without it, the feature safely uses JSON
  reports in `PREMARKET_REPORTS_DIR` (default `data/premarket`).
- A fresh scan is read-only and never places orders.

## 0.2.1 — 2026-07-27

### Added

- Alpaca paper-trading tools for discovering and ordering Cboe index options
  on SPX, SPXW, VIX, VIXW, DJX, and XSP.
- Paper-only execution validation, whole-contract sizing, European-style and
  cash-settlement guidance, and expiration-risk controls.
- A dedicated **Public Markets → Index Options** hub with supported products,
  strategy templates, contract-discovery prompts, and safe chat handoffs.
- An index-options agent skill, focused broker tests, strategy documentation,
  and example conversations.
- Repository contributor guidance in `AGENTS.md`.

### Changed

- Corrected legacy AssetHero package metadata, URLs, installer copy, API naming,
  and console entry points to the canonical AlpaTrade identity.
- Rebuilt IPO Map and IPO Pipeline to follow LiquidRound more closely,
  including filters, KPIs, treemap and performance charts, performer tables,
  valuation bars, private-company cards, and upcoming/completed IPO tables.
- Added a dedicated Public Markets sidebar section.
- Made top-level sidebar sections collapsed by default with `>` expand and
  `<` collapse controls.
- Fixed sidebar command navigation from `/guide` by preserving the selected
  prompt and routing it into `/app`.

### CI/CD

- CI now installs all application extras and explicitly installs pytest.
- Added unconditional index-options and UI-navigation tests.
- Fixed credential-free application import smoke tests with a non-secret
  placeholder model key.
- Verified seven focused tests, syntax compilation, import smoke tests, secret
  scanning, GitHub Actions CI, and the Coolify deployment trigger.

### Release Notes

- All trading paths added in this release are restricted to Alpaca paper
  accounts.
- Alpaca does not yet provide underlying index market data; external licensed
  data is still required for index levels, signals, quotes, and Greeks.

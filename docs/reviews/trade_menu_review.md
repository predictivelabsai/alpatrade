# Trade menu review — 2026-10-12

Scope: `/dashboard`, `/backtests`, `/paper`, `/live`, `/live/account`, `/leaderboard`, `/strategies`, `/advisor` (plus the known `/research/news` bug).
Method: read the route code (`engine/web/ph_pnl.py`, `ph_runs.py`, `ph_live_account.py`, `ph_leaderboard.py`, `ph_advisor.py`, `ph_layout.py`) and took headless Playwright screenshots at 390 px and 1366 px. Signed-out against https://alpatrade.chat (everything except `/leaderboard` redirects to `/signin`, as it should), and signed-in as Julian against a local `origin/main` server on the prod DB (read-only dev login). The signed-in screenshots are local only, at `screenshots/trade_review/*_signedin.png`. They show real account balances, so they are **not committed**.

Priority: **P0** = wrong numbers or a broken page, **P1** = a big UX or performance issue, **P2** = polish.

## Fixed in this PR (small and obvious)
- **`/research/news` crashed with "News unavailable: (secs || []).slice is not a function".** `render()` passed `sector_counts` (an object) to `plotBoard()`, which called `.slice` on it. `plotBoard` now accepts either the AI board array or the counts object. Verified: the page renders at both widths with no page errors.
- **On phones the dashboard was covered by the News panel.** `/dashboard` (and `/app`) open News by default, and at ≤960 px News is a full-width overlay, so the first screen on a phone showed only "Loading news…". News now starts minimised at ≤960 px (the toggle still opens it). Desktop is unchanged. Verified at 390 px and 1366 px.

## Cross-cutting
1. **P0 · Three different returns for the same live strategy.** Live runs: +3.16% / P&L $+86.18, updated 2026-10-09. Live account: since inception +3.66%, YTD (clipped to inception) +3.45%, runner P&L +$96.20. Leaderboard: return +3.44%. Use one source (the deposit-adjusted TWR chain) and say what each number is measured from.
2. **P1 · Timestamps have no zone.** Backtests, Paper and Live tables print `2026-10-11 19:57` with no label, and the dashboard says "updated … UTC". House rule: UI shows ET · UK · Tallinn, trading reports ET only. Add one shared formatter (`utils/tz_util`) and use it in every table.
3. **P1 · Tables are cut off on phones.** At 390 px, Backtests, Paper and Live runs cut off the columns on the right (Best params, Status, Run) and the Live account period table ("Excess vs S…"). The tables scroll sideways, but nothing shows there's more. Stack rows into cards at <600 px, as `/strategies` already does, or pin the first column and add a scroll hint.
4. **P1 · Duplication.** The sub-nav (Backtests / Paper runs / Live runs / Live account) repeats the left menu. The Daily advisor empty state appears on both the dashboard and `/advisor`. `/strategies` and `/leaderboard` render the same card for the same strategy with different action sets. Keep one strategy card component and one advisor card.
5. **P2 · Format consistency.** `$+86.18` should be `+$86.18`. Mix of `—`, `$0.00` and blank cells for "no data".

## /dashboard
- **P0 · "Annualised return (since inception · 164D): −153.66%"** sits next to MTD +1.06% and positive P&L. The annualisation is wrong: probably it compounds a deposit-distorted return, or uses equity at inception = deposits. Recompute from the TWR index, and hide it under ~60 trading days (annualising short windows is misleading anyway).
- **P1 · Slow:** 23–34 s to first byte signed in (local server against the prod DB; other Trade pages take 0.2–6 s). Profile `_load()`: per-account Alpaca calls and the SPY history are sequential. Cache per account (60 s) and load the charts via htmx after the KPIs.
- **P1 · "Paper strategy activity"** lists the same strategy several times as `running` with $0.00, 0 trades and a blank Started. These are zombie or duplicate runs (see /paper). Group by strategy, show the started time, and hide runs that haven't heartbeated in N hours.
- **P1 · The header says "Portfolio P&L PAPER"** while the account switcher also includes the live account. Show the selected account type in the title.
- **P2 · Strategy rankings** show many $0.00 / 0.0% rows. Hide strategies with no trades, or show a "no trades yet" row.

## /backtests
- **P0 · Completed runs show Return and Sharpe "—".** Results are stored, but the table doesn't read them (results-key mismatch for buy_the_dip grid runs). A backtest list with no return is the main defect on this page.
- **P1 · A run has been `running` since 2026-09-28 17:14.** Mark runs as stale or failed after a timeout.
- **P1 · Near-identical runs once a minute** (2026-09-28 17:09–17:14) clutter the list. Group by config hash and show "×N runs".
- **P2 · "Best params" prints raw Python** (`symbols ['QCOM', 'INTC', …]`). Format it as chips. The column is truncated on mobile.

## /paper
- **P0 · 25 runs are all `running`, and none has an end time** (2026-10-10 → 2026-10-11, several per hour). These are either orphaned rows from the per-user runner restarts (v0.40.0) or duplicate starts. Reconcile them with `user_strategy_activations` and the runner heartbeat, and close orphans.
- **P1 · No P&L, trade count or account column**, so the page says nothing about performance. Add the same columns as /live.
- **P2 · "Latest 25 paper runs"** has no pagination or filter.

## /live
- **P0 · Stale figures:** "Updated 2026-10-09 16:03" on 2026-10-12, so P&L lags /live/account. Update the run row from the runner's daily snapshot, or compute it live.
- **P2 · Params column is dense** (`dip 3.0% / TP 8.0% / SL 1.5% / hold 3-3d / size 14.3%`). Use a tooltip or chips; on mobile only Strategy, Account and P&L are visible.

## /live/account
- **P1 · The period table repeats inception:** the "YTD (from inception)" row shows +3.45%, but "Since inception" shows +3.66% for the same window. When YTD is clipped to inception, drop the YTD row or make it match exactly.
- **P2 · The positions table overflows on mobile.** Good: the read-only badge and the TWR explanation.

## /leaderboard
- **P0 · Backtest "Annualised" values are inconsistent.** For example, John Walsh shows annualised +56.61% with the subtitle "+56.61% vs SPY +33.15%", and SPY 2016–2026 is ~13–14% CAGR, not 33%. Kullamägi shows annualised −1.00% but alpha −34.15%. The column mixes total, simple×252 and CAGR. Pick one (CAGR), label it, and check the SPY benchmark window.
- **P1 · +72.32% annualised for the live strategy after 12 trading days.** Show the total return until ≥60 trading days; annualise after that.
- **P2 · Every card has 6 buttons** (Run backtest, View more, Open in Grok, Copy, Activate Paper, Activate Live…). On mobile that's ~3 rows of buttons per card. Move the secondary actions into a "⋯" menu.

## /strategies
- **P1 · The Activate Paper / Live… buttons don't appear on the user's own live strategy, but do appear on public backtests the user owns**, without explaining why. Show status badges consistently (as on the dashboard "My strategies" card).

## /advisor
- **P1 · An empty state is the only content** ("No post-close daily advisor report has been generated…") even though paper runs exist (25 running). Either the generator isn't running for this account, or the empty-state copy is wrong. Link to the last attempt or error, and show the next scheduled time in ET.

## Suggested order
1. Data correctness: dashboard annualised, leaderboard annualised/SPY, backtest returns, one live return.
2. Zombie paper/backtest runs (status reconciliation).
3. Dashboard performance.
4. Zone labels + mobile tables.
5. Deduplicate the cards and sub-nav.

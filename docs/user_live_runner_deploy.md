# Live runners: server primary (Coolify), since 2026-10-12

| Role | Where | How |
|---|---|---|
| primary | Coolify server, app `alpatrade-live-runners` (compose `docker-compose.runner.yaml`) | containers `btd-scheduler` + `user-live`, `restart: unless-stopped`, `BTD_ROLE=primary`, `BTD_INSTANCE=server` |
| backup | Mac.home | launchd `com.predictivelabs.alpatrade-btd` + `com.predictivelabs.alpatrade-user-live` (`BTD_ROLE=backup`) |
| tertiary | agent box | `loop.sh` / `user-live.sh` via `ensure.sh` (`BTD_ROLE=tertiary`) |
| (none) | HP | `alpatrade-btd-scheduler` + `alpatrade-user-live` **disabled** (`systemctl --user disable --now`) |

Env vars live only in Coolify (names: `DATABASE_URL`, `ENCRYPTION_KEY`, `ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY`,
`ALPACA_LIVE_BASE_URL`, `ALPACA_LIVE_ACCOUNT`, `BTD_ROLE`, `BTD_INSTANCE`, `BTD_USER_EMAIL`, `USER_LIVE_TRADING_ENABLED`).
Web deploys (app `nnjuws8sa09rthx7j7xservt`) never restart the runners, and runner deploys never touch the web app.

Cut-over / redeploy rules: trading is 24/5, so there is no idle window. Use a zero-gap handover and stay
10 min clear of every scheduled event (09:31 open, 15:45-15:58 entry/close, 16:03 post; heartbeats every 3 min
09:00-16:05 ET). The lease (FOR UPDATE on `alpatrade.live_runner_state`) allows only one order-placing instance,
even if two instances claim the same role.

Zero-gap handover (HP -> server):
1. Deploy the app as standby (`BTD_ROLE=tertiary` or `backup`). Check the logs (`btd scheduler started
   [server/...] live=True`, the supervisor is up) and a dry heartbeat
   (`python scripts/live_btd_minhold.py --event heartbeat --any-time`, peek only).
2. Set `BTD_ROLE=primary`, `BTD_INSTANCE=server` and redeploy. A second primary cannot act while
   `hp`'s lease is live ("lease held by hp").
3. `systemctl --user disable --now alpatrade-btd-scheduler alpatrade-user-live` on HP (SIGTERM: in-flight passes finish).
4. Hand over in one transaction: expire only `hp`'s lease rows
   (`UPDATE alpatrade.live_runner_state SET lease_expires_at = now() WHERE lease_holder = 'hp'`), then run
   `python scripts/live_btd_minhold.py --event heartbeat --live --any-time` in the `btd-scheduler` container
   (lease renew only, no orders). Every row now shows `lease_holder='server'`. The gap is seconds.
5. Next session: the 09:00 ET heartbeats and the 09:31 open show `[server/primary] ... act=True`.

Rollback: re-enable HP units (`systemctl --user enable --now ...`) and stop the Coolify app; the HP primary takes the lease when the server's lease expires (8 min).

---

# Per-user live runner: deploy runbook (NOT yet applied to HP / Mac.home / box)

Code: `utils/user_live_runner.py`, `scripts/user_live_scheduler.py`, `scripts/user_live_supervisor.py`,
units `deploy/systemd/alpatrade-user-live.service`, `deploy/launchd/com.predictivelabs.alpatrade-user-live.plist`,
`deploy/box/user-live-keepalive.sh`. Target commit: the HEAD of main that contains this file.

The live checkouts are at 7a91c84; the only runner-file change between 7a91c84 and the target is
`utils/live_btd_runner.py` (three no-op hooks). A dry-run on a copy produced identical operator
decisions (btd + s7btd orders, sizing) for the old and new code.

## 0. Preconditions
- Julian approved; outside 09:00-16:10 ET (16:00-23:10 Vilnius) on a trading day, or a weekend.
- `alpatrade.user_strategy_activations` exists (created by the web app / sql/49).

## 1. Each machine (HP primary, then Mac.home backup, then box tertiary)
```
cd ~/dev/plai/alpatrade            # box: /home/box/alpatrade-runner/repo
git fetch origin && git status --short          # expect only the known untracked files
git merge --ff-only <target-sha>                # fast-forward only; abort on anything else
.venv/bin/python -m pytest -q tests/test_user_live_runner.py tests/test_live_btd_scheduler.py tests/test_live_btd_failover.py
grep -q '^USER_LIVE_TRADING_ENABLED=' .env || echo 'USER_LIVE_TRADING_ENABLED=0' >> .env   # kill switch starts OFF
```
Do NOT restart `alpatrade-btd-scheduler` (Julian's): the running process keeps its loaded code;
its next natural restart loads byte-identical behaviour.

## 2. Install the user supervisor (still OFF via the flag)
- HP: `cp deploy/systemd/alpatrade-user-live.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now alpatrade-user-live.service`
- Mac: `sed "s#/Users/juliankaljuvee#$HOME#g" deploy/launchd/com.predictivelabs.alpatrade-user-live.plist > ~/Library/LaunchAgents/com.predictivelabs.alpatrade-user-live.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.predictivelabs.alpatrade-user-live.plist`
- box: `cp deploy/box/user-live-keepalive.sh /home/box/alpatrade-runner/user-live.sh` and start it like loop.sh (`setsid nohup … &`); add `USER_LIVE_TRADING_ENABLED=0` to runner.env.
- Check: `journalctl --user -u alpatrade-user-live -n 5` shows "USER_LIVE_TRADING_ENABLED is off".
- Check Julian's scheduler untouched: `systemctl --user status alpatrade-btd-scheduler` (same PID as before).

## 3. Dry-run on the machine (no orders)
`.venv/bin/python scripts/user_live_supervisor.py --once` lists runnable activations;
for each: `.venv/bin/python scripts/user_live_scheduler.py --activation-id N --event entry --ignore-hours`
(dry run: verifies the user's keys belong to the account, logs sizing and would-POST lines).

## 4. Turn on (Julian's call)
Set `USER_LIVE_TRADING_ENABLED=1` in .env / runner.env on all three machines. The supervisor picks
it up within 60 s; the first user entries happen in the next 15:45-15:55 ET window.

## Kill switches / rollback
- Global: `USER_LIVE_TRADING_ENABLED=0` (children stopped within 60 s; running passes stop submitting).
- Hard stop: `systemctl --user disable --now alpatrade-user-live` / `launchctl bootout …` / `touch USER_LIVE_STOP`.
- Per user: Settings > Integrations > Live strategies > Pause / Deactivate (or Disconnect live keys).
- Code rollback: `git checkout 7a91c84 -- utils/live_btd_runner.py` is not needed for Julian's runner
  (hooks are no-ops); removing the user service is sufficient.

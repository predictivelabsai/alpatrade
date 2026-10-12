# Plan: move AlpaTrade to a dedicated Postgres (plan only, not executed)

AlpaTrade is the only production-critical app on the shared `finespresso_db` server (72.62.114.124,
`max_connections=100`, 3 reserved). It shares connection slots with polytrade, hedgecopy, fastdatagov,
fastaccounts and several unnamed clients, and "remaining connection slots are reserved" errors have hit
live trading. Live trading runs 24/5, so there is no maintenance window: the move must be zero-gap.

## 1. Target and sizing
- Dedicated Postgres 16 (same major as today, so `pg_dump`/logical replication need no conversions), on its own
  VM or a managed instance in the same region as the Coolify server (latency to the runners matters more than size).
- Start at 2 vCPU / 4-8 GB RAM / 50 GB SSD (measure first: `pg_database_size`, `pg_total_relation_size` per
  schema for `alpatrade.*` and the AlpaTrade-owned `public.*` tables such as `news`, `model_tracking`).
- `max_connections=100` with PgBouncer (transaction pooling) in front of the web/api/workers; the runners keep
  direct connections (NullPool, session-level advisory locks and `FOR UPDATE` leases work in session mode).
  Connection budget: web+api 8, workers 6, autonomy/paper 2, server runners ~4, Mac/box standbys ~4 each.
- Role-level guards: `ALTER ROLE alpatrade SET idle_in_transaction_session_timeout='60s'`,
  `statement_timeout='60s'` (runners set tighter per-session values themselves).
- Backups: nightly `pg_dump -Fc` kept 14 days off-host, plus WAL archiving / PITR (pgBackRest or provider
  snapshots), and a monthly restore test into a scratch DB.

## 2. Schema and data copy
1. Inventory: list every table AlpaTrade reads/writes (`alpatrade` schema + `public.news`, `public.model_tracking`,
   news-related tables). Decide which shared tables move and which stay readable from the old DB
   (Finespresso's news pipeline also writes `public.news`; keep a read path or replicate one way).
2. `pg_dump --schema-only` -> apply on the new server; create roles/grants.
3. Logical replication: `CREATE PUBLICATION alpatrade_pub FOR TABLE ...` on the old server (needs
   `wal_level=logical`; if that needs a restart of the shared server, schedule it with the other app owners) and
   `CREATE SUBSCRIPTION` on the new one. Every table needs a primary key or `REPLICA IDENTITY FULL`.
4. Let it catch up; compare row counts and `max(id)`/`max(updated_at)` per table; sequences are NOT replicated,
   so `setval` every sequence to old max + margin just before the switch.

## 3. Cut-over (zero-gap, 24/5)
Pick a quiet minute: not within 10 min of 09:31 ET (open) or 15:45-16:03 ET (entry/close/post), and not during
any extended-hours job. Order:
1. Freeze config edits (no strategy_configs changes, no new activations) for ~15 min.
2. Confirm replication lag ~0 and the lease rows (`alpatrade.live_runner_state`) are identical on both sides.
3. Switch the **web app/api/workers** first (Coolify env `DATABASE_URL` -> new DB, redeploy). They hold no lease.
4. Switch the **runners as one unit**, because the lease must live in exactly one DB:
   a. stop the Mac and box standbys (launchctl bootout / kill loop) so they cannot take over on the old DB;
   b. on the server runner app set the new `DATABASE_URL` and redeploy (stop grace lets an in-flight pass finish);
   c. immediately after the old container stops, stop replication for `live_runner_state`
      (`ALTER SUBSCRIPTION ... DISABLE`), and re-run `setval`s;
   d. the new container's first heartbeat takes the (expired or own-instance) lease on the new DB; verify with
      `python scripts/live_btd_minhold.py --event heartbeat --live --any-time` (lease renew only).
   Gap: only the container restart (~30-60 s), outside any event window.
5. Update `DATABASE_URL` on Mac.home (repo .env) and the box (runner.env) and restart their standbys.
6. Drop the subscription; leave the old AlpaTrade tables read-only (`REVOKE INSERT, UPDATE, DELETE`) for 7 days.

## 4. Lease consistency
- Never let two DBs both hold a live lease: standbys are stopped before the primary switches, and the primary
  switches in one restart. A standby still on the old DB would see a stale primary heartbeat and take the old
  lease, then place orders. Stopping the standbys first rules that out.
- `client_order_id`s are deterministic, so a retried event after the switch cannot double-submit to Alpaca.

## 5. Rollback
- Before step 4: point the web app back (env + redeploy); replication is still running, so no data is lost.
- After step 4: stop the server runner, copy the rows written since the switch (`live_runner_state`, runs, trades,
  activations) back with a reverse publication, then restore the old `DATABASE_URL` everywhere.
  Then restart the primary, then the standbys.
- Keep the old database untouched (read-only) until 7 days of clean operation.

## 6. Checklist
- [ ] sizes measured, server provisioned, backups + PITR tested
- [ ] PKs/replica identity on all tables; publication + subscription caught up
- [ ] Coolify env for both apps (web `nnjuws8sa09rthx7j7xservt`, runners `alpatrade-live-runners`), Mac .env, box runner.env
- [ ] failover monitor routine updated to the new DB
- [ ] post-switch: heartbeats from server/Mac/box on the new DB, first event passes, connection counts

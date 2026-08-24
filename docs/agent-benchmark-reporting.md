# Agent Benchmark Reporting

The standard AlpaTrade daily report is account-owned. The scheduler enumerates active
`user_accounts`, decrypts that account's Alpaca paper credentials in memory, and sends
the result only to the owning user's login email. It never combines another user's
runs, trades, positions, or broker snapshot.

## Attribution

Every new run stores `agent_name` and `agent_framework` in `alpatrade.runs`. Supported
framework values are `hermes`, `deepagents`, and `langgraph`. Trades reference the run
through `run_id`, so realized results can be grouped without copying attribution onto
every trade. Old rows without attribution appear as `legacy`; they are not silently
credited to a modern agent.

The account headline (equity, cash, buying power, daily/MTD/YTD return) is shared broker
state and is never claimed by one agent. The benchmark table compares only closed paper
trades linked to each framework: MTD P&L/exits, YTD P&L, win rate, and run count. A fair
experiment should give agents the same symbols, dates, capital constraints, and paper
account conditions.

## Liveness and delivery

Migration `sql/25_tenant_agent_reporting.sql` adds `runs.heartbeat_at`, daily equity
snapshots, and delivery claims. A paper run appears as running only when its heartbeat is
less than ten minutes old. Multiple Coolify processes may wake at the report hour, but a
unique `(user_id, account_id, report_date, report_kind)` claim permits one email.

Apply before deployment:

```bash
python run_migration.py sql/25_tenant_agent_reporting.sql
```

No historical MTD/YTD values are fabricated. On the first snapshot day those periods
start at zero; accuracy grows as daily snapshots accumulate. `net_cash_flow` exists so
deposits and withdrawals can be excluded from returns when recorded.

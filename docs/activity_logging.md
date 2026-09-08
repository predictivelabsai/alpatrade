# Activity Logging

AlpaTrade keeps three complementary, tenant-scoped histories in PostgreSQL.

- `alpatrade.user_logging` pairs a signed-in user's question with its response,
  framework, status, thread, and timestamps. Credential-shaped text is redacted
  and each field is capped at 50,000 characters.
- `alpatrade.agent_logging` mirrors durable Hermes jobs, canonical backtest and
  paper runs, and autonomy jobs. It records safe identifiers, status, strategy,
  symbols, and progress—not API keys or complete runtime configuration.
- `alpatrade.llm_usage_logging` records agent, provider/model, token counts,
  estimated USD cost, measurement quality, and platform versus user BYOK. It
  never stores credentials or prompt/response text.

Open **Account → Logging** or visit `/admin/logging`. Regular users always see
only rows matching their `user_id`. Users with `users.is_admin = TRUE` see all
accounts and can filter by email. Authorization is enforced in the query layer,
not only hidden in the interface.

## Deployment

From the API or AG-UI container after deploying the new revision:

```bash
cd /app
python run_migration.py sql/29_activity_logging.sql
python run_migration.py sql/30_llm_usage_logging.sql
```

The migration is idempotent. It creates both tables and triggers, then backfills
existing Hermes, standard run, and autonomy history. New job status changes are
mirrored automatically. Trigger errors are isolated so observability can never
prevent a trading job from updating.

## Verification

1. Send a normal chat question and wait for its answer.
2. Start or inspect a backtest or paper job.
3. Open `/admin/logging`.
4. Confirm the question and response under **User activity** and the job under
   **Agent activity**.
5. Sign in as a non-admin account and confirm another user's email and records
   are not visible.

The Logging page includes today's cost by user and agent plus individual calls.
Provider token metadata is marked `measured`; the fallback is marked
`estimated`. Dollar amounts use configurable rates and are not provider
invoices. Configure `PLATFORM_LLM_DAILY_BUDGET_USD` (default `$5`),
`LLM_INPUT_USD_PER_MILLION`, `LLM_OUTPUT_USD_PER_MILLION`, and corresponding
`HERMES_*` rates. BYOK calls are logged but do not consume platform budget.

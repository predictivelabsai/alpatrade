# Finespresso News Worker

AlpaTrade runs news ingestion separately from web and API processes. Realtime mode
persists each unique publisher article first, then attempts issuer, language,
translation, event, event-specific ML, and XAI-reason enrichment. Successful fields
are retained. Missing fields remain SQL `NULL` and mark the article retryable for the
backfill worker; textual placeholders are never saved.

## Database setup

Run once before starting a worker:

```bash
python run_migration.py sql/31_news_worker_jobs.sql
python run_migration.py sql/32_news_worker_events.sql
```

The migrations create `alpatrade.news_worker_jobs` and `alpatrade.news_worker_events`.
They store shard checkpoints and sanitized operational events; neither table stores
article content or credentials. Models are selected from `public.model_tracking`;
optional mounted event-model bundles use `NEWS_MODEL_STORAGE_PATH`. Articles and all
available enrichment remain in `public.news`. Web, API, and agent paths only read it.

## Coolify service

Create a second service from the same repository and commit as the web application.
Use `Dockerfile.agui` and this command:

```bash
python -m news_scheduler.worker --mode realtime
```

For a bounded, resumable historical worker use:

```bash
python -m news_scheduler.worker --mode backfill --batch-size 25 --shard-index 0 --shard-count 1
```

Multiple backfill services may use distinct shard indexes with the same shard count.
PostgreSQL advisory locks reject duplicate workers for the same mode and shard.

Configure variable names only: `DATABASE_URL`, `XAI_API_KEY`, `XAI_MODEL`, required
market-data keys such as `EODHD_API_KEY`, `NEWS_MODEL_STORAGE_PATH`, `NEWS_WORKER_MODE`,
`NEWS_WORKER_BATCH_SIZE`, `NEWS_WORKER_INTERVAL_SECONDS`, `NEWS_WORKER_SHARD_INDEX`, and
`NEWS_WORKER_SHARD_COUNT`. Never place values in Git. `NEWS_PUBLISHER_FEEDS` optionally
overrides the publisher inventory ported from Finespresso Admin.

## Verification and monitoring

Open `/research/news-scheduler` to see worker state, enriched/retryable/pending counts,
prediction/event totals, fully enriched articles, and durable worker activity. Open
`/monitoring/data-health` as an administrator for backfill completion and sanitized
errors. Use `/press` to filter enriched results. Coolify logs emit `article_inserted`,
`article_saved_partial`, and `cycle_completed` events.

An incomplete article does not stop a realtime cycle. The worker retains it, continues
with later articles, and remains `running`. Backfill scans every incomplete news row
regardless of its current event label and retries it in bounded, resumable passes.
Stopping or redeploying is safe, and realtime inserts are idempotent by publisher and
source link.

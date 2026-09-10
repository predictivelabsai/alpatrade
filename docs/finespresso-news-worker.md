# Finespresso News Worker

AlpaTrade runs news ingestion separately from web and API processes. Both realtime and backfill use the same strict pipeline: publisher collection, issuer/language/translation enrichment, event normalization, the event’s classifier and regressor, XAI reasoning, validation, then persistence. Missing models or incomplete values remain retryable; placeholders are never saved.

## Database setup

Run once before starting a worker:

```bash
python run_migration.py sql/31_news_worker_jobs.sql
```

The migration creates `alpatrade.news_worker_jobs`. It stores shard checkpoints, counts, status, timestamps, and sanitized errors. Models are selected from `public.model_tracking`; optional mounted event-model bundles use `NEWS_MODEL_STORAGE_PATH`. Enriched articles remain in `public.news`. Web, API, and agent paths only read that feed.

## Coolify service

Create a second service from the same repository and commit as the web application. Use `Dockerfile.agui` and this command:

```bash
python -m engine.news_pipeline.worker --mode realtime
```

For a bounded, resumable historical worker use:

```bash
python -m engine.news_pipeline.worker --mode backfill --batch-size 25 --shard-index 0 --shard-count 1
```

Multiple backfill services may use distinct shard indexes with the same shard count. PostgreSQL advisory locks reject duplicate workers for the same mode and shard.

Configure variable names only: `DATABASE_URL`, `XAI_API_KEY`, `XAI_MODEL`, required market-data keys such as `EODHD_API_KEY`, `NEWS_MODEL_STORAGE_PATH`, `NEWS_WORKER_MODE`, `NEWS_WORKER_BATCH_SIZE`, `NEWS_WORKER_INTERVAL_SECONDS`, `NEWS_WORKER_SHARD_INDEX`, and `NEWS_WORKER_SHARD_COUNT`. Never place values in Git. `NEWS_PUBLISHER_FEEDS` is an optional comma-separated override; when omitted, the worker loads the publisher inventory ported from Finespresso Admin.

## Verification and monitoring

Open `/monitoring/data-health` as an administrator to see mode, state, last successful cycle, last processed/inserted IDs, counts, remaining rows, completion percentage, and sanitized error. Use `/press` to filter enriched results by ticker, company, event, side, and date range.

Stopping or redeploying is safe: each committed article advances the PostgreSQL checkpoint. A restarted worker resumes from that ID, and realtime inserts are idempotent by publisher and source link.

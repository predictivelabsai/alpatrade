# Finespresso News Worker

AlpaTrade runs news ingestion separately from web and API processes. Realtime mode
persists each unique publisher article first, then attempts issuer, language,
translation, event, event-specific ML, and XAI-reason enrichment. Successful fields
are retained. Missing fields remain SQL `NULL` and mark the article retryable for the
backfill worker; textual placeholders are never saved.

Issuer enrichment also records `company_type` as `public` or `private`. A stored
ticker is deterministic public-company evidence; otherwise the existing XAI metadata
request classifies the issuer without adding another model call. Unresolved values
remain retryable instead of being guessed.

Realtime collection preserves the seven Finespresso publisher jobs: Baltics,
Euronext, OMX, GlobeNewswire sector, GlobeNewswire country, GlobeNewswire industry,
and PR Newswire. Each job gets an equal quota of the batch ceiling
(ceil(batch/7)); already-stored links are skipped inside a job's own turn, and quota a
quiet job leaves unused is released only after every job had its share. GlobeNewswire
feeds are read from `rss.globenewswire.com` (the www host returns 403 to servers since
9 Oct 2026). Dedupe is publisher+link under `pg_advisory_xact_lock(hashtext(publisher|link))`,
identical to CityTicker's news_worker, so the two redundant writers never duplicate. A failure in one
publisher is logged by publisher name and does not block the remaining jobs.

## Database setup

Run once before starting a worker:

```bash
python run_migration.py sql/31_news_worker_jobs.sql
python run_migration.py sql/32_news_worker_events.sql
python run_migration.py sql/34_news_company_type.sql
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

The `news-backfill` compose service runs the guarded enrichment backlog:

```bash
python -m news_scheduler.worker --mode backfill
```

It enriches `pending_enrichment`/`retryable` rows newest first (including rows
CityTicker's news_worker stores un-enriched), at most `NEWS_BACKFILL_MAX_PER_DAY`
(default 400, ~$0.50/day) rows per UTC day, skips a row tried in the last 24 h,
backs off exponentially after a failed cycle and pauses
`NEWS_BACKFILL_FAILURE_PAUSE_SECONDS` after `NEWS_BACKFILL_MAX_CONSECUTIVE_FAILURES`
failed cycles. xAI calls are the small plain enricher calls, subject to
`PLATFORM_LLM_DAILY_BUDGET_USD` and logged in `alpatrade.llm_usage_logging`.

The original id-ascending scan of every incomplete historical row (~239k legacy
rows, ~$300) is opt-in only:

```bash
python -m news_scheduler.worker --mode full-backfill --batch-size 25 --shard-index 0 --shard-count 1
```

Multiple backfill services may use distinct shard indexes with the same shard count.
PostgreSQL advisory locks reject duplicate workers for the same mode and shard.

Configure variable names only: `DATABASE_URL`, `XAI_API_KEY`, `XAI_MODEL`, required
market-data keys such as `EODHD_API_KEY`, `NEWS_MODEL_STORAGE_PATH`, `NEWS_WORKER_MODE`,
`NEWS_WORKER_BATCH_SIZE`, `NEWS_WORKER_INTERVAL_SECONDS`, `NEWS_WORKER_SHARD_INDEX`, and
`NEWS_WORKER_SHARD_COUNT`. Never place values in Git. `NEWS_PUBLISHER_FEEDS` optionally
overrides the publisher inventory ported from Finespresso Admin.

## Verification and monitoring

After migration 34, run the targeted resumable backfill to classify historical rows
without waiting behind unrelated incomplete enrichment:

```bash
python -m news_scheduler.worker --mode company-backfill --batch-size 25 --shard-index 0 --shard-count 1
```

It has its own `news-company-backfill` checkpoint. Open
`/research/news-scheduler` to filter articles by public/private issuer and see worker
state, coverage, enriched/retryable/pending counts, prediction/event totals, fully
enriched articles, and durable worker activity. Open
`/monitoring/data-health` as an administrator for backfill completion and sanitized
errors. Use `/press` to filter enriched results. Coolify logs emit `article_inserted`,
`article_saved_partial`, and `cycle_completed` events.

An incomplete article does not stop a realtime cycle. The worker retains it, continues
with later articles, and remains `running`. Backfill scans every incomplete news row
regardless of its current event label and retries it in bounded, resumable passes.
Stopping or redeploying is safe, and realtime inserts are idempotent by publisher and
source link.

Each completed cycle also emits `publisher_cycle_summary` with attempted, enriched,
partial, and failed counts per publisher job. These counts contain no article text or
credentials and make publisher starvation or feed failures visible in Coolify logs.

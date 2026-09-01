# Hermes Agent on AlpaTrade

This runbook is the permanent setup, deployment, verification, and recovery
guide for the Nous Hermes Agent integration.

## Service roles: do not confuse these containers

| Service | Responsibility | Sensitive access |
|---|---|---|
| `hermes` | Nous model gateway, memory, skills, and free-form `/hermes` reasoning on private port 8642 | Model-provider key and dedicated restricted broker key only |
| `hermes-jobs` | AlpaTrade-owned durable executor for backtests, paper sessions, portfolio monitoring, advice persistence, and notifications | Database, encrypted per-user Alpaca paper credentials, and Postmark |
| `agui` | Authenticated browser chat, history, voice, deterministic Hermes command routing, and in-app messages | User session, database, and internal Hermes gateway key |
| `api` | Restricted `/v2/hermes/*` broker that validates the short-lived user delegation and enforces ownership | Database and encrypted account credentials |

The `hermes` model container does **not** run the paper loop and does not receive
`DATABASE_URL`, Alpaca keys, `JWT_SECRET`, or the general API service key.
`hermes-jobs` is not a second Hermes model: it is the trusted AlpaTrade worker
that executes already-authorized paper tasks and writes their results. The
normal DeepAgents/LangGraph runtime is separate and remains unchanged.

## Complete installation checklist

### 1. Configure Coolify variables

Set these on the AlpaTrade Compose resource, using secret values from your own
secret manager. Never put their values in Git or a PR:

```text
HERMES_API_SERVER_KEY     required; random 64-character internal key
HERMES_IMAGE_TAG          optional; defaults to the reviewed pinned image
HERMES_API_MODEL          optional gateway model label
XAI_API_KEY               required when xAI is the selected provider
DATABASE_URL              used by api/agui/hermes-jobs, never by hermes
ENCRYPTION_KEY            decrypts owned Alpaca credentials in trusted services
JWT_SECRET                used by api/agui, never by hermes
POSTMARK_API_KEY          required for email delivery
FROM_EMAIL                verified Postmark sender
```

Keep the existing Alpaca paper variables and linked per-user account setup. Do
not expose port 8642 publicly.

### 2. Deploy the branch

In Coolify, select `feat/hermes-agent-phase-1` as the Git source branch and
deploy the complete Compose resource. Confirm these services are healthy:

```text
hermes
api
agui
hermes-jobs
paper-strategy
```

### 3. Configure Hermes once

Open the `hermes` container terminal:

```bash
hermes setup
```

Choose `Full Setup`, `xAI Grok`, `xAI` API-key authentication, keep the detected
key, keep `https://api.x.ai/v1`, select the desired Grok model, and keep the
local terminal backend. Here, local means inside the isolated Coolify container.
Select no messaging gateway. Enable Terminal & Processes for the restricted
AlpaTrade skill; keep File Operations, Code Execution, Cron, Computer Use, and
Task Delegation disabled. Configuration persists in `/opt/data` and normal
redeploys do not require another wizard run.

### 4. Apply database migrations

Open the newly deployed `api` container terminal and run each missing migration
in numeric order. They are idempotent:

```bash
cd /app
python run_migration.py sql/18_hermes_agent_attribution.sql
python run_migration.py sql/19_hermes_jobs.sql
python run_migration.py sql/20_hermes_paper_controls.sql
python run_migration.py sql/21_hermes_portfolio_advice.sql
```

Migration 21 creates only `alpatrade.hermes_advice`. None of these commands
grants Hermes direct SQL access or modifies another PostgreSQL schema.

### 5. Restart trusted application services

Restart or redeploy `api`, `agui`, and `hermes-jobs` after migrations. Preserve
the `hermes-data` volume. A continuous paper job may briefly show `running`
while its old worker heartbeat becomes stale; it is safely requeued and broker
positions/orders are reconciled before execution continues.

### 6. Verify and test end to end

From the `agui` terminal:

```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://hermes:8642/health', timeout=10).read().decode())"
```

Then sign in to AlpaTrade and run these one at a time:

```text
/hermes help
/hermes run a buy_the_dip backtest for AAPL, MSFT, GOOGL, AMZN, META, TSLA and NVDA over 3 months and optimize Sharpe
/hermes show my running jobs
/hermes show my recent jobs
/hermes show my latest backtest result
/hermes construct an optimal portfolio from my best completed candidate
/hermes start my best candidate in continuous paper trading, email daily reports, and notify me both
/hermes analyze my running paper job
/hermes notify me both in app and email for paper job <paper-job-id>
/hermes show my recent advice
```

Expected behavior: backtest and paper starts return immediately; completion and
advice messages appear in the originating saved chat; refreshing or reopening
the thread retains them; the paper job remains active when the page closes.
The quick-start commands automatically select the best completed candidate or
latest applicable owned paper job. Use an explicit ID only when selecting one
specific job among several. A **job ID** identifies the background task, a
**run ID** identifies its stored trading/backtest record, and a **candidate ID**
identifies the winning parameters saved by a completed backtest.

These no-ID controls target the latest applicable owned paper job:

```text
/hermes pause my running paper job
/hermes resume my paused paper job
/hermes stop my running paper job
```

Use these explicit controls when you copied a particular paper job ID:

```text
/hermes pause paper job <paper-job-id>
/hermes resume paper job <paper-job-id>
/hermes stop paper job <paper-job-id>
```

### Clickable commands, clarification, and approval

Every command above can be typed, pasted, or selected from the left-side
**Agents → Hermes** menu. Hermes responses also show contextual **Suggested
follow-ups**. Selecting one fills the composer; it does not send automatically,
so the user can review or edit it first. Follow-ups are stored with the saved
message and remain available after refresh or reopening the chat.

Hermes does not guess missing details for an actionable request. For example,
`/hermes run a backtest` asks for strategy, symbols, and lookback instead of
silently using defaults. `/hermes start paper trading` asks which approved
candidate to use. A request to change running parameters explains that the
safe workflow is a new backtest and candidate approval; it never mutates a
running strategy in place.

Recommended team demonstration:

```text
/hermes run a 6-month buy_the_dip backtest for SPY, QQQ, IWM, DIA, XLK, XLF and XLV and optimize Sharpe
/hermes show my running jobs
/hermes show my latest backtest result
/hermes construct an optimal portfolio from my best completed candidate
/hermes start my best eligible candidate in continuous paper trading, email daily reports, and notify me both
/hermes analyze my running paper job
/hermes pause my running paper job
/hermes resume my paused paper job
/hermes stop my running paper job
```

Parameter updates follow the same approval boundary: run a new backtest with
the requested symbols/period or grid, inspect its validation and benchmark,
then explicitly promote the new eligible candidate. The old paper job remains
unchanged until the user stops it and approves the replacement.

Candidates created by an older worker that show fewer completed robustness
windows than requested are displayed as **blocked** and cannot be promoted.
Run a fresh backtest after deployment to create a fully validated candidate.

Do not run `stop` during initial continuous-operation testing unless you intend
to terminate that job.

## What is saved and where

All application records are in the `alpatrade` schema and carry the authenticated
`user_id`; account-bound records also carry `account_id`:

| Data | Table/location |
|---|---|
| Saved browser threads and messages | `alpatrade.chat_conversations`, `alpatrade.chat_messages` |
| Backtest and paper job status/config/results | `alpatrade.hermes_jobs` |
| Optimized strategy parameters and metrics | `alpatrade.strategy_candidates` |
| Backtest/paper run records | `alpatrade.runs` and existing trade/result tables |
| Portfolio, entry, exit, hold, and risk advice | `alpatrade.hermes_advice` |
| Hermes model profile, memory, sessions, and skills | `hermes-data` volume mounted at `/opt/data` |

Email addresses are resolved server-side from the authenticated login and are
not copied into Hermes job configuration. Advice is saved before delivery.
In-app alerts are saved into the originating owned chat; email alerts use only
that login email. `both` enables both channels. Daily-email enablement remains a
separate setting from immediate advice delivery.

## Command reference

```text
/hermes help
/hermes show my recent jobs
/hermes show my latest backtest result
/hermes construct an optimal portfolio from my best completed candidate
/hermes start my best candidate in continuous paper trading, email daily reports, and notify me both
/hermes analyze my running paper job
/hermes pause my running paper job
/hermes resume my paused paper job
/hermes stop my running paper job
/hermes show my recent advice
/hermes show the result of backtest <job-or-run-id>
/hermes construct an optimal portfolio from candidate <candidate-id>
/hermes start candidate <candidate-id> in continuous paper trading
/hermes enable daily email reports for paper job <job-id>
/hermes disable daily email reports for paper job <job-id>
/hermes notify me in app for paper job <job-id>
/hermes notify me by email for paper job <job-id>
/hermes notify me both in app and email for paper job <job-id>
/hermes pause paper job <job-id>
/hermes resume paper job <job-id>
/hermes stop paper job <job-id>
```

Portfolio construction attempts inverse 120-day volatility weighting while
respecting the candidate position limit and a 25% per-symbol cap. If complete
market history is unavailable, the saved recommendation explicitly reports a
capped equal-weight fallback. Monitoring refreshes approximately every 15
minutes during market operation and suppresses identical alerts for six hours.
It reports strategy-confirmed paper entries, exits, near-exit thresholds, and
hold observations. Advice never creates an extra order, and no Hermes live-order
route exists.

## Architecture and safety boundary

Hermes runs as a separate service in the AlpaTrade Coolify Compose resource.
The browser never calls Hermes directly:

```text
AlpaTrade /app chat -> agui -> http://hermes:8642/v1 -> Hermes Agent
```

Port 8642 stays private to the Compose network and requires bearer-token
authentication. Hermes stores its profile, sessions, memory, and skills in the
`hermes-data` volume at `/opt/data`. Never connect two Hermes containers to this
same volume.

Hermes receives no database credentials, Alpaca credentials, or unrestricted
AlpaTrade execution access. Phase 2 adds a dedicated API broker for scoped
backtests, optimization candidates, run inspection, and paper trading.
Autonomous live trading remains unavailable.

## The two required keys

### `HERMES_API_SERVER_KEY`

This is an internal password shared only by AlpaTrade and its Hermes container.
It does not come from a website. Generate it on your own computer in PowerShell,
Command Prompt, or another trusted terminal:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

The command prints one random 64-character value. Copy it directly into the
AlpaTrade Coolify resource as `HERMES_API_SERVER_KEY`. Do not place it in Git,
chat, screenshots, documentation, or a committed `.env` file. You can generate
a new value at any time, but both the `agui` and `hermes` services must receive
the same value, so redeploy the whole resource after rotating it.

### Model-provider key

Hermes also needs one model provider. AlpaTrade supports forwarding
`XAI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY`.

For Grok, create an inference API key from the API Keys page in the xAI Console.
The full value is shown only when created, so store it immediately in Coolify as
`XAI_API_KEY`. If AlpaTrade already uses Grok successfully, this variable may
already exist and does not need to be duplicated.

## First deployment in Coolify

1. Merge the reviewed Hermes branch into `main`, or deploy the feature branch in
   a separate staging resource first.
2. Open **Coolify -> AlpaTrade resource -> Environment Variables**.
3. Add `HERMES_API_SERVER_KEY` and ensure one model-provider key is present.
4. Keep port 8642 private. Do not assign it a public domain.
5. Redeploy the complete Compose resource.
6. Confirm that the `hermes` service and `hermes-data` volume were created.

The image is pinned by `HERMES_IMAGE_TAG`; upgrades must be reviewed and tested
before changing that tag.

## One-time profile setup

Open **Coolify -> AlpaTrade -> hermes service -> Terminal** and run:

```bash
hermes setup
```

If the executable is not on `PATH`, run:

```bash
/opt/hermes/.venv/bin/hermes setup
```

Choose the same provider configured in Coolify and select the intended model.
The wizard writes the profile to `/opt/data`, so it survives normal redeploys.
Restart the Hermes service afterward.

### Recommended Phase 1 wizard choices

Run the wizard once:

```bash
hermes setup
```

Use these selections for the minimum-privilege Phase 1 configuration:

1. **Setup mode:** `Full Setup`.
2. **Provider:** `xAI Grok`, followed by `xAI` (API key), not SuperGrok OAuth.
3. **Existing xAI key:** `Keep` when the key from Coolify is detected.
4. **Base URL:** press Enter to retain `https://api.x.ai/v1`.
5. **Model:** `grok-build-0.1` for the documented lowest token price among
   the listed general/code models. A stronger model can be selected later with
   `hermes setup model`.
6. **Terminal backend:** `Keep current (local)`. In this deployment, local means
   inside the isolated Hermes Coolify container, not the operator's computer.
7. **Messaging platforms:** select nothing and press Enter. Telegram, WhatsApp,
   or another platform can be configured later with `hermes setup gateway`.
8. **Tools to keep enabled:** Web Search & Scraping, Vision/Image Analysis,
   Skills, Task Planning, Memory, Session Search, and Clarifying Questions.
9. **Tools to disable for Phase 1:** Browser Automation, Terminal & Processes,
   File Operations, Code Execution, Image Generation, Text-to-Speech, Task
   Delegation, Cron Jobs, and Computer Use. Restricted execution capabilities
   can be reviewed when scoped AlpaTrade API tools are added in Phase 2.
10. **Browser provider:** `Skip`.
11. **Image provider:** `Skip`.
12. **Text-to-speech provider:** `Skip`.
13. **Search provider:** `DuckDuckGo (ddgs)` for free, keyless search.

For Phase 2, rerun `hermes setup tools` once and enable **Terminal & Processes**.
It is required only so the read-only mounted AlpaTrade skill can call the
restricted HTTP broker with `curl`. Keep File Operations, Code Execution, Cron,
Computer Use, and Task Delegation disabled. Terminal runs inside the isolated
Hermes container, not on the operator's computer.

Gateway requests cannot display Hermes's interactive terminal approval modal.
The Compose service therefore sets `HERMES_EXEC_ASK=false` and caps tool loops
at 20 iterations. This is acceptable only because the Hermes container has no
database URL, Alpaca credentials, JWT secret, or general AlpaTrade service key;
its mounted skill is instructed to use one scoped internal broker command.

After the wizard reports **Setup Complete**, the expected locations are:

```text
/opt/data/config.yaml
/opt/data/.env
/opt/data/cron/
/opt/data/sessions/
/opt/data/logs/
```

Do not display or copy the contents of `/opt/data/.env` into logs, issues, pull
requests, or chat.

`hermes gateway setup` is unnecessary for AlpaTrade web chat. Run it only when
deliberately adding Telegram, Discord, or another messaging platform, and always
configure a platform allowlist.

## Verification

From the Coolify terminal of the `agui` service, verify private connectivity:

```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://hermes:8642/health').read().decode())"
```

Then sign in to AlpaTrade and send:

```text
/hermes hello, identify yourself
```

The route label should change to **Hermes**. Send an ordinary unprefixed message
next; it should return to the user's saved default runtime. Equivalent
one-message overrides are `/deepagents` and `/langgraph`.

If Hermes fails before returning output, AlpaTrade automatically routes the
message to DeepAgents and labels the fallback in chat.

## Phase 2 database and broker deployment

The order matters because the updated application writes the new attribution
columns. From the repository branch, apply the idempotent migration first:

```bash
python run_migration.py sql/18_hermes_agent_attribution.sql
```

Then redeploy the complete Coolify Compose resource. No new secret is required:
the existing `HERMES_API_SERVER_KEY` is also injected under the broker-specific
name into only the `hermes` and `api` services. Never add `DATABASE_URL`,
`API_SERVICE_KEY`, `JWT_SECRET`, or Alpaca keys to the Hermes service.

The web app creates a thirty-minute delegation for the logged-in user on each
`/hermes` request. The API accepts it only together with the dedicated broker
key and only on `/v2/hermes/*`. Every query is explicitly scoped to
`alpatrade.*` and the delegated `user_id`; Hermes cannot issue SQL or access
another schema.

After redeploying, run `hermes setup tools` in the Hermes terminal, enable
**Terminal & Processes**, and keep the other execution tools disabled. Test:

```text
/hermes backtest AAPL and MSFT for 3 months with buy_the_dip; maximize Sharpe
```

Hermes should immediately return `job_id`, `run_id`, and `status=queued`. When
the saved chat receives the completion message, copy its `candidate_id` and test:

```text
/hermes start candidate <candidate_id> in paper trading for 1 hour
```

This can start paper trading only. There is deliberately no Hermes live-order
route. Candidates are saved in `alpatrade.strategy_candidates` under the
logged-in `user_id` and optional `account_id`, with `agent_name=Hermes` and
`agent_framework=hermes`. Candidate reads join that ID to
`alpatrade.users.display_name`, so results show the login owner without copying
identity data into every candidate row.

## Chat history and long-running feedback

The `/app` chat saves user and assistant messages in
`alpatrade.chat_conversations` and `alpatrade.chat_messages`, keyed by the
logged-in `user_id`. The **Chats** sidebar loads only that user's threads and
supports resume and delete. **New chat** creates a new browser thread and a new
Hermes gateway session.

While Hermes is preparing a request, AlpaTrade emits progress heartbeats with
elapsed time and tool status. Long backtests and paper sessions leave the chat
stream after queue acknowledgement and continue in the dedicated worker. These
are operational updates, not private model chain-of-thought. Browser history is
not resent to Hermes because the gateway already persists its thread; avoiding
that duplication prevents premature context compression.

If a broker call reports an expired delegation, start a new chat and retry once.
Each message now receives a fresh thirty-minute delegation. Repeated expiry or
`pending_approval` logs indicate that the latest Compose configuration has not
been deployed.

## Asynchronous backtest and paper jobs

Apply the durable jobs migration before deploying version 0.11.0:

```bash
python run_migration.py sql/19_hermes_jobs.sql
```

Redeploy the complete Compose resource so the `hermes-jobs` service is created.
Hermes backtest and paper endpoints now return immediately with `job_id`,
`run_id`, and `status=queued`. The AlpaTrade-owned worker—not the Hermes model
container—claims the row, executes under its signed `user_id` and optional
`account_id`, and records progress in `alpatrade.hermes_jobs`.

The AlpaTrade chat recognizes `/hermes` backtest requests before invoking the
remote model and queues them deterministically. This prevents model planning,
tool approvals, or context compression from delaying the acknowledgement.
Ordinary `/hermes` questions still use the remote Hermes model.

Successful backtests create an owned `strategy_candidates` row and append the
metrics and `candidate_id` to the originating chat. Paper jobs load only an
owned candidate and require an account linked to the same user. Both continue
when the browser closes. An open chat synchronizes saved messages every five
seconds, while `/hermes show my running jobs` reads `/v2/hermes/jobs`.

Backtests interrupted by a worker restart are safe to requeue. Finite paper
sessions are deliberately marked failed after an interrupted worker heartbeat.
Only paper jobs explicitly started as continuous are requeued; the paper agent
resynchronizes broker orders and positions before continuing. No live execution
route exists.

## Paper controls, reports, and voice

Apply the paper-control migration before deploying version 0.12.0:

```bash
python run_migration.py sql/20_hermes_paper_controls.sql
```

Use an owned candidate ID returned by a completed Hermes backtest:

```text
/hermes start candidate <candidate-id> in continuous paper trading and email daily reports
/hermes show my recent jobs
/hermes pause paper job <job-id>
/hermes resume paper job <job-id>
/hermes stop paper job <job-id>
/hermes enable daily email reports for paper job <job-id>
/hermes disable daily email reports for paper job <job-id>
/hermes help
/hermes construct an optimal portfolio from candidate <candidate-id>
/hermes show my recent advice
/hermes notify me in app for paper job <job-id>
/hermes notify me by email for paper job <job-id>
/hermes notify me both in app and email for paper job <job-id>
/hermes analyze paper job <job-id>
/hermes show result for backtest job <job-id>
/hermes send a test notification for paper job <job-id>
/hermes send a test notification both in app and email for paper job <job-id>
/hermes show my notification history
```

Apply `sql/21_hermes_portfolio_advice.sql` before using portfolio advice. It creates
only `alpatrade.hermes_advice`. Recommendations are scoped by `user_id`, account,
candidate, paper job, and chat thread. The paper worker reviews positions every 15
minutes by default, suppresses identical alerts for six hours, and saves advice
before attempting delivery. `in_app` writes to the originating saved chat; `email`
uses the account login email; `both` does both. Daily P&L email includes recent
Hermes advice. Advice never submits an additional order and all execution remains
under the already approved paper strategy.

Hermes immediate alerts identify the confirmed paper event, quantity, price,
approved threshold, P&L when an exit closes, and the reason for the decision.
An entry is informational rather than a profit signal. Exit gains render green,
losses render red, and watch/hold events render amber.

Hermes is included in the consolidated AlpaTrade daily report; it does not send
a second Hermes-only daily digest. Immediate opt-in entry/exit alerts remain
separate. The consolidated report derives realized P&L from the owned paper
run's persisted trades, groups
repeated entry fills, and labels broker positions/unrealized P&L as account-wide
because other strategies can share the linked paper account. It never adds
account-wide unrealized P&L to run-only realized P&L. Hermes analysis includes:

- **WAITING**: no completed exits exist yet; keep collecting paper evidence.
- **GREEN**: profitable closed activity without stop-loss exits; keep the
  approved configuration while monitoring consistency.
- **AMBER**: insufficient or mixed closed activity; inspect before changing it.
- **RED**: a loss, repeated stop exits/fills, or overlapping active account runs;
  pause and diagnose before another optimization.

Use `/hermes analyze paper job <job-id>` before acting on a report. The response
is scoped to the signed-in owner and returns supported follow-up commands. It
does not pause, optimize, or change a running paper strategy automatically.

## Conservative research and paper promotion

Hermes backtests use stricter assumptions than the legacy/default agent path:
five basis points of adverse slippage on entries and exits, FINRA/CAT fees,
stop-loss-first resolution when a daily bar touches both exit thresholds, and
risk statistics calculated from end-of-day portfolio equity. The saved result
records the methodology, training dates, validation dates, and both metric sets.

The first 70% of the requested period selects parameters; the final 30% is held
out. Hermes also reports SPY buy-and-hold return, excess return, and three
non-overlapping robustness windows inside that holdout. A candidate is
paper-eligible only when
validation has at least 20 closed trades, positive return, Sharpe of at least
0.50, maximum drawdown no greater than 10%, positive top-training stability,
and positive return across a majority of the robustness windows.
Candidates created before this evidence was introduced are not promotable.
These gates reduce false confidence but do not guarantee future profit.

New Hermes paper jobs enable a drift guard. It waits for at least 20 closed
trades across at least five trading days, compares daily paper Sharpe with the
candidate's held-out Sharpe, and pauses
the job when paper Sharpe falls below 50% of that reference. The pause and its
reason are delivered through the selected advice channels; resuming remains an
explicit user action. Daily Hermes reports also verify that account-wide broker
quantities cover the run-owned open DB quantities and turn red on a shortfall;
extra broker quantity can belong to another strategy and is not treated as an error.

Notification tests create an owner-scoped audit record and exercise only the
requested delivery channel. They never place an order or change a strategy.
Notification history reports whether each saved Hermes event reached in-app,
email, both, or neither.

Daily reports go only to the authenticated account's login email. The recipient
is resolved server-side and is never accepted from chat text. Controls update
only paper jobs belonging to the same `user_id`; live trading is not exposed.

Voice advertises the same paper-only Hermes dispatcher as a realtime function
tool. The WebSocket requires a signed-in browser session, uses that user's linked
Alpaca paper account for positions, and saves successful Hermes voice commands
to the active owned chat.

## Moving from the feature branch to `main`

After the feature-branch deployment passes its health and chat checks:

1. Merge the reviewed pull request into `main`.
2. Change the existing AlpaTrade Coolify resource's Git source branch from
   `feat/hermes-agent-phase-1` back to `main`.
3. Redeploy the same Coolify resource.
4. Do not delete, rename, or recreate the `hermes-data` volume.
5. Repeat the health check and one `/hermes` chat message.

The setup wizard does **not** need to be run again. Its configuration survives
because both branch deployments use the same `/opt/data` volume. Rerun
`hermes setup` only when deliberately changing the provider, model, tools, or
messaging configuration, or when the volume has been lost.

## Troubleshooting

- **`HERMES_API_SERVER_KEY is not configured`**: add the variable to Coolify and
  redeploy the whole resource.
- **HTTP 401/403**: ensure `agui` and `hermes` receive the same internal key.
- **Connection refused or DNS failure**: inspect the Hermes container health and
  confirm the internal URL is `http://hermes:8642/v1`.
- **No model/provider configured**: rerun `hermes setup` and confirm the selected
  provider key exists in Coolify.
- **Hermes forgets its profile after redeploy**: verify `hermes-data` is mounted
  at `/opt/data` and was not deleted or replaced.
- **Partial response followed by failure**: inspect Hermes logs; automatic
  fallback occurs only before Hermes has emitted content, preventing two agents
  from answering the same message.

Never paste secret values into an issue, pull request, chat, or log excerpt.

## Rollback and upgrade

To disable Hermes without affecting normal chat, remove or scale down the
`hermes` service; DeepAgents remains the application default. Preserve the
`hermes-data` volume if the agent may be restored later.

Before upgrading Hermes, back up the volume, change `HERMES_IMAGE_TAG` to a
reviewed release, redeploy once, and repeat the health and `/hermes` checks.

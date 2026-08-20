# Hermes Agent on AlpaTrade

This runbook is the permanent setup, deployment, verification, and recovery
guide for the Nous Hermes Agent integration.

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

The web app creates a ten-minute delegation for the logged-in user on each
`/hermes` request. The API accepts it only together with the dedicated broker
key and only on `/v2/hermes/*`. Every query is explicitly scoped to
`alpatrade.*` and the delegated `user_id`; Hermes cannot issue SQL or access
another schema.

After redeploying, run `hermes setup tools` in the Hermes terminal, enable
**Terminal & Processes**, and keep the other execution tools disabled. Test:

```text
/hermes backtest AAPL and MSFT for 3 months with buy_the_dip; maximize Sharpe
```

Hermes should return a `run_id`, best metrics, and `candidate_id`. Then test:

```text
/hermes start candidate <candidate_id> in paper trading for 1 hour
```

This can start paper trading only. There is deliberately no Hermes live-order
route. Candidates are saved in `alpatrade.strategy_candidates` under the
logged-in `user_id` and optional `account_id`, with `agent_name=Hermes` and
`agent_framework=hermes`. Candidate reads join that ID to
`alpatrade.users.display_name`, so results show the login owner without copying
identity data into every candidate row.

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

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

Phase 1 provides chat routing only. Hermes receives no database credentials,
Alpaca credentials, or unrestricted AlpaTrade execution access. Scoped
backtest, optimization, and paper-trading tools are added in Phase 2. Autonomous
live trading remains unavailable.

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

---
name: coolify-deploy
description: Trigger or inspect a Coolify deployment for AlpaTrade via the Coolify API. Use when the user asks to deploy/redeploy/ship, or to check deploy status.
---

# Coolify deploy

Trigger and inspect deployments on the user's Coolify instance via its REST API,
using a Coolify API token (Bearer). No password is handled.

## Safety

- Deploying is an **outward, production-affecting action**. Confirm with the user
  before triggering unless they've just asked you to deploy/ship/redeploy.
- Never print, commit, or log the API token. It lives only in the environment.

## Setup (one-time)

In Coolify: **Keys & Tokens → API tokens** → create a token with deploy permission.
Add to `.env` (gitignored — never commit values):

```
COOLIFY_URL=https://coolify.your-host.tld
COOLIFY_API_TOKEN=...
COOLIFY_APP_UUID=...        # optional default; get it from `list`
```

## Usage

```bash
# find the app + its uuid
python scripts/coolify_deploy.py list

# deploy by name or uuid (force rebuild). The prod web app is named
# `predictivelabsai/alpatrade` (uuid lwgksc8kgcwc448o40c0w0k8) — NOT "agui";
# "agui" is the Dockerfile/service name (Dockerfile.agui), not the Coolify app name.
python scripts/coolify_deploy.py deploy --name predictivelabsai/alpatrade
python scripts/coolify_deploy.py deploy --uuid lwgksc8kgcwc448o40c0w0k8

# recent deployment status
python scripts/coolify_deploy.py status
```

## After deploying AlpaTrade

Verify the new build is actually live (the old image 404s these):

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://alpatrade.chat/map      # expect 200
curl -s -o /dev/null -w "%{http_code}\n" https://alpatrade.chat/settings # expect 303 (→ /signin)
curl -s -o /dev/null -w "%{http_code}\n" https://alpatrade.chat/         # expect 200
```

Then smoke-test `/`, `/map`, `/charts`, `/settings`, and chat. The prod container runs
`Dockerfile.agui` → `python main.py` → merged `app.py` (web on 5003 in prod via
`ASSETHERO_WEB_PORT`). If a deploy doesn't appear after a few minutes, check `status`
and the Coolify build logs.

**Auto-deploy on git push has NOT been firing** — pushes to `main` do not redeploy
automatically. Trigger manually with this skill after every push that needs to ship,
or fix the GitHub App webhook (see CLAUDE.md "Deployment").

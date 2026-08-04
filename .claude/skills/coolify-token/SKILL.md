---
name: coolify-token
description: Create, list or revoke Coolify API tokens by driving the Coolify UI with Playwright. Use when a Coolify deploy token is needed (e.g. wiring up GitHub Actions CD) and none exists yet.
---

# Coolify token

Mints scoped Coolify API tokens. Coolify exposes **no API for creating API tokens** —
every `/api/v1` token endpoint returns 404 — so the only way to create one is the web UI,
which this skill automates with Playwright.

Once a token exists, use the **`coolify-deploy`** skill for deploys; this skill is only
for the credential bootstrap.

## Safety

- **Creating and revoking tokens is production-affecting.** Confirm with the user before
  running unless they just asked for it. Revoking is irreversible — anything using that
  token breaks immediately.
- `--revoke` matches on a **substring** and revokes *every* token that matches. Always run
  `--list` first and confirm the exact set. A careless substring can revoke another
  team's deploy token.
- The token value is **never printed** — only a masked prefix. Pass `--github-secret` or
  `--write-env` to store it. Never echo it, commit it, or paste it into a message.
- Never write the login password into a file, skill, or commit. It lives in `.env` only.

## Setup

Credentials come from the environment (`.env` is gitignored):

```
COOLIFY_URL=https://coolify.your-host.tld   # instance that hosts the app
COOLIFY_EMAIL=...                            # UI login
COOLIFY_PASSWORD=...                         # UI login
```

Requires `playwright` (in the `e2e` extra) with Chromium installed:
`uv run playwright install chromium`.

## Pick the right instance first

**A token is only valid on the instance that minted it.** A token from another Coolify
install returns `401 Unauthenticated` for every call. This organisation runs more than
one instance, so confirm which one hosts the target app before minting:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $COOLIFY_API_TOKEN" \
  "$COOLIFY_URL/api/v1/applications/<app-uuid>"      # 200 = right instance, 401 = wrong one
```

As of 2026-08-04: **AlpaTrade lives on `coolify.finespresso.org`**, not
`coolify.predictivelabs.ai` (which hosts polytrade, rl-agent-swarm, macrohero, plai-crm,
kanvas and others). Verify rather than assuming — the two have different logins.

## Usage

```bash
# always look before creating or revoking
python scripts/coolify_mint_token.py --list

# create a deploy-scoped token and push it straight into a GitHub repo secret
python scripts/coolify_mint_token.py \
    --description "github-actions deploy" \
    --permissions read,deploy \
    --github-secret predictivelabsai/alpatrade

# target another instance, store locally instead
python scripts/coolify_mint_token.py --url https://coolify.example.tld \
    --description "local automation" --write-env

# revoke — check --list output first, this matches every token containing the string
python scripts/coolify_mint_token.py --revoke "github-actions deploy"
```

Permissions: `root`, `write`, `deploy`, `read`, `read:sensitive`. Prefer `read,deploy`
for CI — `root` grants full control of every app on the instance.
Expiry: `--expires 7|30|60|90|365|never` (default 365).
Add `--headed` to watch the browser when debugging a selector break.

## How it works (and what breaks it)

1. Logs in at `/login`, fails loudly if the page stays on `/login`.
2. Scopes to the token form on `/security/api-tokens` — the page renders many other
   hidden modals, so a bare `input[name=description]` would match the wrong form.
3. Ticks permission checkboxes by their enclosing **label text**; they carry no name or id.
4. Reads the new token from the page with the Sanctum pattern `<id>|<40+ chars>`,
   diffing against tokens already on screen.

Revoking does **not** click "Revoke token" — that only opens an Alpine modal demanding
the token's description be retyped. Instead each row's `x-data` is parsed for its
`submitAction: 'revoke(<id>)'` and the Livewire method is invoked directly
(`window.Livewire.find(componentId).call('revoke', id)`), which is both simpler and
immune to mis-targeting a re-rendered row.

If Coolify changes its UI these selectors are what will break — rerun with `--headed`
and re-derive them. Verified against **Coolify v4.1.2**.

---
name: linkedin-post
description: Post an update to LinkedIn (text, optionally with one image) via the official REST API using a member OAuth token. Use when the user asks to publish/share something on LinkedIn.
---

# LinkedIn post

Publish a post to the user's LinkedIn feed via the official REST API. Auth is a
member OAuth token — **no password or 2FA is ever entered by the assistant**; the
user completes LinkedIn's OAuth flow once (LinkedIn handles their 2FA there).

## Safety (must follow)

- Posting is a **publish action**. ALWAYS show the exact text (and image) and get an
  explicit "yes, post it" from the user in chat before running without `--dry-run`.
- Never enter the user's LinkedIn password or a 2FA code. If a token is missing,
  point the user at `scripts/linkedin_auth.py` and let them complete OAuth.
- Never print, commit, or log the access token. It lives only in the environment.

## One-time setup

1. Create a LinkedIn app at https://www.linkedin.com/developers/apps and add the
   products **"Sign In with LinkedIn using OpenID Connect"** and **"Share on
   LinkedIn"**. Scopes: `openid profile w_member_social`.
2. Add `http://localhost:8765/callback` to the app's Authorized redirect URLs.
3. Put `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and optionally
   `LINKEDIN_REDIRECT_URI` in `.env` (all gitignored).
4. Run the auth helper and follow the browser consent (user logs in + 2FA there):
   ```bash
   python scripts/linkedin_auth.py
   export LINKEDIN_ACCESS_TOKEN=<token it prints>
   ```

## Posting

Always dry-run first, show it to the user, then post on confirmation:

```bash
# 1) validate (no post)
python scripts/linkedin_post.py --text-file media/marketing/linkedin_post_final.txt --dry-run

# 2) after the user confirms — text only
python scripts/linkedin_post.py --text-file media/marketing/linkedin_post_final.txt

# with one image
python scripts/linkedin_post.py --text-file media/marketing/linkedin_post_final.txt \
    --image media/marketing/01_market_map.png

# visibility (default PUBLIC)
python scripts/linkedin_post.py --text "…" --visibility CONNECTIONS
```

Exit codes: `0` posted / dry-run OK, `2` config or usage error, `1` API error.

## Notes

- Author URN is resolved automatically from the token (`/v2/userinfo`, falling back
  to `/v2/me`).
- One image max per post (LinkedIn `feedshare-image` recipe). For multiple images or
  video, extend `scripts/linkedin_post.py`.
- Tokens expire (~60 days); re-run `linkedin_auth.py` when a call returns 401.

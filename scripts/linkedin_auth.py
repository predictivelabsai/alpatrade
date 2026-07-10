#!/usr/bin/env python3
"""One-time LinkedIn OAuth helper — get a member access token for posting.

This runs on YOUR machine and opens LinkedIn's own consent page in your browser,
where LinkedIn handles your login and 2FA. It then catches the redirect on a local
loopback port and exchanges the authorization code for an access token. The token
is printed once so you can export it — it is NOT written into the repo.

Prerequisites (in .env or the environment):
  LINKEDIN_CLIENT_ID=...        # from your LinkedIn app
  LINKEDIN_CLIENT_SECRET=...    # from your LinkedIn app
  LINKEDIN_REDIRECT_URI=http://localhost:8765/callback   # add this exact URL to
                                                         # the app's "Authorized
                                                         # redirect URLs"

Scopes requested: openid profile w_member_social (posting + author identity).

Run:  python scripts/linkedin_auth.py
Then: export LINKEDIN_ACCESS_TOKEN=<printed token>
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPES = "openid profile w_member_social"

_code_holder: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path).query
        params = dict(urllib.parse.parse_qsl(q))
        _code_holder.update(params)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in params
        msg = "Authorized — you can close this tab and return to the terminal." if ok \
            else f"Authorization failed: {params.get('error_description', params)}"
        self.wfile.write(f"<html><body style='font-family:sans-serif'>{msg}</body></html>".encode())

    def log_message(self, *a):  # silence
        return


def main() -> int:
    cid = os.getenv("LINKEDIN_CLIENT_ID")
    secret = os.getenv("LINKEDIN_CLIENT_SECRET")
    redirect = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8765/callback")
    if not cid or not secret:
        sys.exit("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET first. (exit 2)")

    parsed = urllib.parse.urlparse(redirect)
    host, port = parsed.hostname or "localhost", parsed.port or 8765

    state = os.urandom(8).hex()
    consent = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": redirect,
        "scope": SCOPES, "state": state,
    })
    print("Opening LinkedIn consent page (log in + approve there)…")
    print(consent)
    try:
        webbrowser.open(consent)
    except Exception:  # noqa: BLE001
        pass

    server = HTTPServer((host, port), _Handler)
    server.handle_request()  # blocks for the single redirect

    if _code_holder.get("state") != state:
        sys.exit("state mismatch — aborting for safety. (exit 1)")
    code = _code_holder.get("code")
    if not code:
        sys.exit(f"no code returned: {_code_holder} (exit 1)")

    tok = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect, "client_id": cid, "client_secret": secret,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    if tok.status_code != 200:
        sys.exit(f"token exchange failed: HTTP {tok.status_code} {tok.text[:200]} (exit 1)")
    data = tok.json()
    print("\n✓ Access token obtained (valid ~", data.get("expires_in", "?"), "seconds).")
    print("Keep it secret — do NOT commit it. Export it, then run scripts/linkedin_post.py:\n")
    print(f'  export LINKEDIN_ACCESS_TOKEN={data["access_token"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

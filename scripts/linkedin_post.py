#!/usr/bin/env python3
"""Post to LinkedIn via the official REST API using an OAuth access token.

No password or 2FA is handled here: you complete LinkedIn's OAuth flow once
(which is where LinkedIn does its own 2FA), obtain a member access token with the
`w_member_social` scope, and put it in the environment. This script then creates
a text post (optionally with a single image) on your behalf.

Setup (one-time):
  1. Create a LinkedIn app: https://www.linkedin.com/developers/apps
     - Add the "Sign In with LinkedIn using OpenID Connect" and "Share on
       LinkedIn" products. Request scopes: `openid profile w_member_social`.
  2. Do the OAuth 2.0 authorization-code flow to get an access token. The helper
     `scripts/linkedin_auth.py` walks you through it (prints the consent URL, then
     exchanges the code for a token). LinkedIn handles your login + 2FA there.
  3. Export the token (do NOT commit it):
        export LINKEDIN_ACCESS_TOKEN=...        # member token, w_member_social

Usage:
  python scripts/linkedin_post.py --text-file media/marketing/linkedin_post_final.txt
  python scripts/linkedin_post.py --text "Hello world" --image media/marketing/01_market_map.png
  python scripts/linkedin_post.py --text-file post.txt --dry-run     # validate only, no post

Exit codes: 0 posted (or dry-run OK), 2 config/usage error, 1 API error.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

API = "https://api.linkedin.com"
UA = {"User-Agent": "AlpaTrade-LinkedIn/1.0"}
_TIMEOUT = 30


def _token() -> str:
    tok = os.getenv("LINKEDIN_ACCESS_TOKEN")
    if not tok:
        sys.exit("LINKEDIN_ACCESS_TOKEN not set — run scripts/linkedin_auth.py first. (exit 2)")
    return tok


def _headers(token: str) -> dict:
    return {**UA, "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0"}


def author_urn(token: str) -> str:
    """Resolve the posting member's URN via OpenID userinfo (falls back to /v2/me)."""
    r = requests.get(f"{API}/v2/userinfo", headers=_headers(token), timeout=_TIMEOUT)
    if r.status_code == 200 and r.json().get("sub"):
        return f"urn:li:person:{r.json()['sub']}"
    r = requests.get(f"{API}/v2/me", headers=_headers(token), timeout=_TIMEOUT)
    r.raise_for_status()
    return f"urn:li:person:{r.json()['id']}"


def _register_and_upload_image(token: str, urn: str, image_path: Path) -> str:
    """Register an image upload, PUT the bytes, return the asset URN."""
    reg = requests.post(
        f"{API}/v2/assets?action=registerUpload",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": urn,
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent"}],
        }},
        timeout=_TIMEOUT,
    )
    reg.raise_for_status()
    val = reg.json()["value"]
    asset = val["asset"]
    upload_url = (val["uploadMechanism"]
                  ["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]
                  ["uploadUrl"])
    up = requests.put(upload_url, headers={"Authorization": f"Bearer {token}"},
                      data=image_path.read_bytes(), timeout=120)
    up.raise_for_status()
    return asset


def build_post(urn: str, text: str, asset: str | None, visibility: str) -> dict:
    share = {"shareCommentary": {"text": text},
             "shareMediaCategory": "IMAGE" if asset else "NONE"}
    if asset:
        share["media"] = [{"status": "READY", "media": asset}]
    return {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Post to LinkedIn via the REST API.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="post body text")
    src.add_argument("--text-file", help="path to a file containing the post body")
    ap.add_argument("--image", help="optional path to a single image to attach")
    ap.add_argument("--visibility", default="PUBLIC", choices=["PUBLIC", "CONNECTIONS"])
    ap.add_argument("--dry-run", action="store_true",
                    help="build and validate the request but do NOT post")
    args = ap.parse_args()

    text = Path(args.text_file).read_text().strip() if args.text_file else args.text
    if not text:
        return 2
    image_path = Path(args.image) if args.image else None
    if image_path and not image_path.exists():
        sys.exit(f"image not found: {image_path} (exit 2)")

    token = _token()
    try:
        urn = author_urn(token)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"could not resolve author (token/scope issue?): {e} (exit 1)")

    if args.dry_run:
        print("DRY RUN — would post as", urn)
        print(f"  visibility: {args.visibility}")
        print(f"  image: {image_path or '(none)'}")
        print("  text:")
        print("  " + text.replace("\n", "\n  "))
        return 0

    asset = None
    if image_path:
        asset = _register_and_upload_image(token, urn, image_path)

    body = build_post(urn, text, asset, args.visibility)
    r = requests.post(f"{API}/v2/ugcPosts",
                      headers={**_headers(token), "Content-Type": "application/json"},
                      json=body, timeout=_TIMEOUT)
    if r.status_code not in (200, 201):
        sys.exit(f"post failed: HTTP {r.status_code} {r.text[:300]} (exit 1)")
    post_id = r.headers.get("x-restli-id") or r.json().get("id", "")
    print(f"Posted ✓  {post_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

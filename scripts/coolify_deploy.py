#!/usr/bin/env python3
"""Trigger / inspect Coolify deployments via the Coolify REST API.

Auth is a Coolify API token (Bearer) — created in Coolify → Keys & Tokens → API
tokens. No password is handled here.

Env (add to .env; never commit values):
  COOLIFY_URL=https://coolify.your-host.tld     # base URL of your Coolify instance
  COOLIFY_API_TOKEN=...                          # API token with deploy permission
  COOLIFY_APP_UUID=...                           # (optional) default app to deploy

Usage:
  python scripts/coolify_deploy.py list                     # list apps (name, uuid, fqdn, status)
  python scripts/coolify_deploy.py deploy --name agui       # deploy by app name
  python scripts/coolify_deploy.py deploy --uuid <uuid>     # deploy by uuid
  python scripts/coolify_deploy.py deploy                   # deploy COOLIFY_APP_UUID
  python scripts/coolify_deploy.py status                   # recent deployments

Exit: 0 ok, 2 config/usage error, 1 API error.
"""
from __future__ import annotations

import argparse
import os
import sys

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

_TIMEOUT = 30


def _cfg():
    base = (os.getenv("COOLIFY_URL") or "").rstrip("/")
    token = os.getenv("COOLIFY_API_TOKEN")
    if not base or not token:
        sys.exit("Set COOLIFY_URL and COOLIFY_API_TOKEN first (see script header). (exit 2)")
    return base, {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _apps(base, headers) -> list[dict]:
    r = requests.get(f"{base}/api/v1/applications", headers=headers, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def _resolve_uuid(base, headers, name: str | None, uuid: str | None) -> str:
    if uuid:
        return uuid
    if not name:
        env_uuid = os.getenv("COOLIFY_APP_UUID")
        if env_uuid:
            return env_uuid
        sys.exit("Provide --uuid, --name, or set COOLIFY_APP_UUID. (exit 2)")
    for a in _apps(base, headers):
        if (a.get("name") or "").lower() == name.lower():
            return a.get("uuid")
    sys.exit(f"No app named {name!r} found (try `list`). (exit 2)")


def cmd_list(base, headers):
    apps = _apps(base, headers)
    if not apps:
        print("(no applications returned)")
        return 0
    for a in apps:
        print(f"  {a.get('name',''):<24} {a.get('uuid',''):<26} "
              f"{a.get('fqdn') or a.get('status',''):<40} {a.get('status','')}")
    return 0


def cmd_deploy(base, headers, name, uuid, force):
    target = _resolve_uuid(base, headers, name, uuid)
    # Canonical Coolify trigger: GET /api/v1/deploy?uuid=...&force=...
    r = requests.get(f"{base}/api/v1/deploy",
                     headers=headers, params={"uuid": target, "force": str(force).lower()},
                     timeout=_TIMEOUT)
    if r.status_code >= 400:
        # Some instances expose POST /api/v1/deploy with a JSON body.
        r = requests.post(f"{base}/api/v1/deploy", headers=headers,
                          json={"uuid": target, "force": force}, timeout=_TIMEOUT)
    if r.status_code >= 400:
        sys.exit(f"deploy failed: HTTP {r.status_code} {r.text[:300]} (exit 1)")
    print(f"Deploy triggered for {target}: {r.text[:200]}")
    return 0


def cmd_status(base, headers):
    r = requests.get(f"{base}/api/v1/deployments", headers=headers, timeout=_TIMEOUT)
    if r.status_code >= 400:
        sys.exit(f"status failed: HTTP {r.status_code} {r.text[:200]} (exit 1)")
    data = r.json()
    rows = data if isinstance(data, list) else data.get("data", [])
    for d in rows[:10]:
        print(f"  {d.get('application_name',''):<24} {d.get('status',''):<12} "
              f"{d.get('created_at','')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Coolify deploy/inspect")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("deploy")
    d.add_argument("--name")
    d.add_argument("--uuid")
    d.add_argument("--force", action="store_true", default=True)
    sub.add_parser("status")
    args = ap.parse_args()

    base, headers = _cfg()
    try:
        if args.cmd == "list":
            return cmd_list(base, headers)
        if args.cmd == "deploy":
            return cmd_deploy(base, headers, args.name, args.uuid, args.force)
        if args.cmd == "status":
            return cmd_status(base, headers)
    except requests.RequestException as e:
        sys.exit(f"Coolify API error: {e} (exit 1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

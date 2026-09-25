#!/usr/bin/env python
"""Link an Alpaca LIVE account to an AlpaTrade user, READ-ONLY (operator CLI).

Reads ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY / ALPACA_LIVE_ACCOUNT from the
local .env (git-ignored), verifies with a single GET /v2/account that the keys
belong to that account number, then Fernet-encrypts them with the app's
ENCRYPTION_KEY (engine.auth.encrypt_key) and upserts a row into
alpatrade.user_live_broker_accounts for the given user. The row is shown on the
GET-only /live/account page and is invisible to every paper/trading path.

Never prints key material.

    python scripts/link_live_account.py --email you@example.com            # verify + link
    python scripts/link_live_account.py --email you@example.com --check    # verify only
    python scripts/link_live_account.py --email you@example.com --unlink   # deactivate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values, load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--email", required=True, help="AlpaTrade login that may see the account")
    ap.add_argument("--label", default="Alpaca live")
    ap.add_argument("--check", action="store_true", help="verify keys only; write nothing")
    ap.add_argument("--unlink", action="store_true", help="deactivate the link")
    args = ap.parse_args()

    env = dotenv_values(ROOT / ".env")
    key = (env.get("ALPACA_LIVE_API_KEY") or "").strip()
    secret = (env.get("ALPACA_LIVE_SECRET_KEY") or "").strip()
    acct = (env.get("ALPACA_LIVE_ACCOUNT") or "").strip()

    from engine.auth import get_user_by_email
    user = get_user_by_email(args.email.strip().lower())
    if not user:
        print(f"No AlpaTrade user with email {args.email}", file=sys.stderr)
        return 2
    uid = str(user["user_id"])

    if args.unlink:
        from sqlalchemy import text

        from engine.db.pool import DatabasePool
        from engine.live_accounts import TABLE
        with DatabasePool().get_session() as s:
            n = s.execute(text(f"UPDATE {TABLE} SET is_active = FALSE, updated_at = NOW() "
                               "WHERE user_id = :u AND account_number = :a"),
                          {"u": uid, "a": acct}).rowcount
        print(f"Deactivated {n} live link(s) for {args.email} / {acct}")
        return 0

    if not (key and secret and acct):
        print("ALPACA_LIVE_API_KEY, ALPACA_LIVE_SECRET_KEY and ALPACA_LIVE_ACCOUNT must be set "
              "in .env", file=sys.stderr)
        return 2

    from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient, LiveReadOnlyError
    try:
        account = LiveReadOnlyClient(key, secret, expected_account_number=acct).get_account()
    except LiveReadOnlyError as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified live account {account.get('account_number')} "
          f"(status {account.get('status')}) for user {args.email} ({uid})")
    if args.check:
        return 0

    from engine.live_accounts import list_live_accounts, store_live_account
    store_live_account(uid, acct, key, secret, label=args.label)
    for row in list_live_accounts(uid):
        print(f"Linked (read-only): {row['account_number']} '{row['label']}' key {row['api_key_hint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

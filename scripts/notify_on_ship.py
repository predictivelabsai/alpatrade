#!/usr/bin/env python3
"""Watch prod until the new AlpaTrade build is live, then email a heads-up.

"Shipped" = the new merged app is serving on alpatrade.chat, detected by the new
route /map returning 200 (it 404s on the old image). Polls until live or timeout,
then sends one email via the repo's Postmark util (utils.email_util.send_email_to).

Usage:
  python scripts/notify_on_ship.py --to oleg.kim@gmail.com
  python scripts/notify_on_ship.py --to oleg.kim@gmail.com --dry-run   # no email, just check
Env: POSTMARK_API_KEY, FROM_EMAIL (already in .env).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

SHIP_URLS = ["https://alpatrade.chat/map", "https://alpatrade.chat/settings"]

SUBJECT = "AlpaTrade just shipped 🟢"
BODY_HTML = """
<div style="font-family:Inter,Arial,sans-serif;color:#14231B;line-height:1.5">
  <p>Hi Oleg,</p>
  <p><b>AlpaTrade is live</b> — <a href="https://alpatrade.chat">alpatrade.chat</a>.</p>
  <p>It's a chat-first "personal trading floor": connect your own Alpaca keys
  (paper or live) and just ask. New in this release:</p>
  <ul>
    <li>🗺 finviz-style <b>market map</b> of the S&amp;P, plus candlestick &amp; multi-ticker compare charts</li>
    <li>🎙️ <b>voice mode</b> — talk to the agent, hear your positions back</li>
    <li>🔑 <b>bring-your-own-keys</b> Settings (encrypted at rest) + provider config</li>
    <li>📰 live news via Tavily</li>
  </ul>
  <p>Would love your feedback.</p>
  <p style="color:#7A867E;font-size:12px">Not financial advice; AlpaTrade holds no
  customer funds — it's a UI to your own brokerage account.</p>
  <p>— Julian</p>
</div>
"""


def is_shipped(timeout: int = 15) -> bool:
    for url in SHIP_URLS:
        try:
            if requests.get(url, timeout=timeout, allow_redirects=True).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="recipient email")
    ap.add_argument("--interval", type=int, default=60, help="poll seconds")
    ap.add_argument("--max-hours", type=float, default=24.0, help="give up after N hours")
    ap.add_argument("--dry-run", action="store_true", help="check once, don't email")
    args = ap.parse_args()

    if args.dry_run:
        print("shipped" if is_shipped() else "not shipped yet")
        return 0

    deadline = time.time() + args.max_hours * 3600
    while time.time() < deadline:
        if is_shipped():
            from utils.email_util import send_email_to
            ok = send_email_to(args.to, SUBJECT, BODY_HTML)
            print(f"SHIPPED — email to {args.to}: {'sent' if ok else 'FAILED (check Postmark env)'}")
            return 0 if ok else 1
        time.sleep(args.interval)
    print(f"gave up after {args.max_hours}h — not shipped, no email sent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

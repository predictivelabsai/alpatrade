#!/usr/bin/env python3
"""Regenerate the landing-page Hedge Funds snapshot from the real signed-in page.

The public home page shows a static screenshot of ``/hedge-funds`` (which itself
requires sign-in). This captures it from a LOCAL app instance using the dev-login
bypass (``ALPATRADE_DEV_LOGIN=1``, loopback only — never enabled in prod):

    ALPATRADE_DEV_LOGIN=1 ASSETHERO_WEB_PORT=5137 python app.py &
    python scripts/hedge_funds_snapshot.py --base http://localhost:5137 --email you@example.com

Writes ``static/landing/hedge-funds-desktop.png`` (content pane only — the app
sidebar is cropped out so no account details appear) and
``static/landing/hedge-funds-mobile.png`` (414px phone rendering).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "landing"
# (file, viewport w, viewport h, clip-from-.hfpage-left?, clip height css px, output width px)
SHOTS = [
    ("hedge-funds-desktop.png", 1440, 1000, True, 700, 1600),
    ("hedge-funds-mobile.png", 414, 900, False, 600, 800),
]


async def capture(base: str, email: str) -> list[str]:
    from playwright.async_api import async_playwright
    done = []
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for name, vw, vh, crop_sidebar, clip_h, out_w in SHOTS:
            # First pass at DPR 1 to find the content pane's left edge.
            ctx = await browser.new_context(viewport={"width": vw, "height": vh})
            page = await ctx.new_page()
            await page.goto(f"{base}/dev/login?email={email}&next=/hedge-funds",
                            wait_until="networkidle", timeout=120_000)
            if not page.url.rstrip("/").endswith("/hedge-funds"):
                raise SystemExit(f"not signed in (landed on {page.url}) — is ALPATRADE_DEV_LOGIN=1 set?")
            left = await page.evaluate(
                "document.querySelector('.page-pane').getBoundingClientRect().left") if crop_sidebar else 0
            await ctx.close()
            width = vw - left
            ctx = await browser.new_context(viewport={"width": vw, "height": vh},
                                            device_scale_factor=out_w / width)
            page = await ctx.new_page()
            await page.goto(f"{base}/dev/login?email={email}&next=/hedge-funds",
                            wait_until="networkidle", timeout=120_000)
            await page.wait_for_timeout(3000)
            path = OUT / name
            await page.screenshot(path=str(path), clip={"x": left, "y": 0, "width": width, "height": clip_h})
            done.append(str(path))
            await ctx.close()
        await browser.close()
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://localhost:5137")
    ap.add_argument("--email", required=True, help="existing user to sign in as (dev login)")
    a = ap.parse_args()
    for path in asyncio.run(capture(a.base.rstrip("/"), a.email)):
        print(path)


if __name__ == "__main__":
    main()

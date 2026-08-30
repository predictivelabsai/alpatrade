"""Playwright audit driver: drives the local app as a signed-in user.

Usage:
    uv run --extra e2e python scripts/ui_audit.py

Injects the session cookie obtained by scripts (curl) rather than registering
again. Captures screenshots to artifacts/audit/ and prints console/page errors.
"""
from __future__ import annotations

import sys
from pathlib import Path

import os

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "artifacts" / "audit"
COOKIES = Path(os.environ.get("AT_COOKIES", r"C:\Users\Joosep\AppData\Local\Temp\at_cookies.txt"))
BASE = "http://localhost:5001"


def session_cookie() -> str:
    for line in COOKIES.read_text().splitlines():
        if "localhost" in line and "session_" in line:
            return line.split("\t")[-1]
    raise RuntimeError(f"no session_ cookie in {COOKIES}")


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    cookie = session_cookie()
    issues: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "session_", "value": cookie, "url": BASE,
                          "httpOnly": True, "sameSite": "Lax"}])
        page = ctx.new_page()
        page.on("console", lambda m: issues.append(
            f"console.error: {m.text} ({m.location.get('url', '')}"
            f":{m.location.get('lineNumber', '')})")
            if m.type == "error" else None)
        page.on("pageerror", lambda e: issues.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: issues.append(
            f"requestfailed: {r.url} ({r.failure})"))
        page.on("response", lambda r: issues.append(f"HTTP {r.status}: {r.url}")
                if r.status >= 400 else None)

        # -- chat ------------------------------------------------------------
        page.goto(f"{BASE}/app", wait_until="networkidle")
        page.screenshot(path=SHOTS / "01-chat-initial.png")

        page.fill("#chat-input", "What is the current price of AAPL? Keep it brief.")
        page.screenshot(path=SHOTS / "02-chat-typed.png")
        page.click("#send-btn")
        page.wait_for_timeout(2500)
        page.screenshot(path=SHOTS / "03-chat-progress.png")
        # SSE stream: done when the send button re-enables; give the model 120s.
        try:
            page.wait_for_function(
                "!document.querySelector('#send-btn').disabled",
                timeout=120_000)
        except Exception as e:
            issues.append(f"chat: send button still disabled after 120s ({e})")
        page.wait_for_timeout(1500)
        page.screenshot(path=SHOTS / "04-chat-response.png", full_page=False)
        page.screenshot(path=SHOTS / "05-chat-response-full.png", full_page=True)
        print("---- assistant text ----")
        text = page.eval_on_selector_all(
            ".msg-bubble", "els => els.map(e => e.innerText)")
        for t in text[-2:]:
            print(repr(t[:800]))

        # -- pages with anomalies ----------------------------------------------
        for route, name in [("/pnl", "pnl"), ("/news", "news"),
                            ("/charts/compare", "compare")]:
            page.goto(f"{BASE}{route}", wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(path=SHOTS / f"10-{name}.png", full_page=True)
            print(f"{route}: title={page.title()!r} url={page.url}")

        browser.close()
    print("---- issues ----")
    seen = set()
    for i in issues:
        if i not in seen:
            seen.add(i)
            print(i)
    if not issues:
        print("(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
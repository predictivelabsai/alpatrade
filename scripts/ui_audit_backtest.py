"""Drive a real backtest through the chat SSE pipeline (Part 3 audit)."""
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "artifacts" / "audit"
BASE = "http://localhost:5001"
COOKIE = Path(os.environ.get(
    "AT_COOKIES", r"C:\Users\Joosep\AppData\Local\Temp\at_cookies.txt"))


def cookie() -> str:
    for line in COOKIE.read_text().splitlines():
        if "localhost" in line and "session_" in line:
            return line.split("\t")[-1]
    raise RuntimeError("no session cookie")


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "session_", "value": cookie(), "url": BASE,
                          "httpOnly": True, "sameSite": "Lax"}])
        page = ctx.new_page()
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        page.on("response", lambda r: errs.append(f"HTTP{r.status} {r.url}")
                if r.status >= 400 else None)

        page.goto(f"{BASE}/app", wait_until="networkidle")
        page.fill("#chat-input", "agent:backtest AAPL lookback:1m")
        page.click("#send-btn")
        # Backtests run to completion before streaming; allow 5 minutes.
        try:
            page.wait_for_function(
                "!document.querySelector('#send-btn').disabled", timeout=300_000)
        except Exception as e:
            errs.append(f"chat: send button still disabled after 300s ({e})")
        page.wait_for_timeout(1500)
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=SHOTS / "40-backtest-response.png", full_page=True)
        text = page.eval_on_selector_all(
            ".msg-bubble", "els => els.map(e => e.innerText)")
        print("---- assistant reply ----")
        for t in text[-2:]:
            print(t[:2000])
            print("~~~~~~~~")
        print("---- errors ----")
        print("\n".join(errs) or "(none)")
        browser.close()


if __name__ == "__main__":
    main()
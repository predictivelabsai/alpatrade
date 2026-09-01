"""Verify positional-ticker fix: `agent:backtest AAPL lookback:1m` runs 1 symbol."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).resolve().parents[1] / "artifacts" / "audit"
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
        page.goto(f"{BASE}/app?new=1&x=argfix", wait_until="networkidle")
        page.fill("#chat-input", "agent:backtest AAPL lookback:1m")
        page.click("#send-btn")
        page.wait_for_function(
            "!document.querySelector('#send-btn').disabled", timeout=300_000)
        page.wait_for_timeout(1500)
        text = page.eval_on_selector_all(
            ".msg-bubble", "els => els.map(e => e.innerText)")
        print("---- reply head ----")
        print(text[-1][:600] if text else "(no reply)")
        browser.close()


if __name__ == "__main__":
    main()
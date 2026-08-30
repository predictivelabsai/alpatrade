"""Sweep every page, print pageerrors with stack + 4xx/5xx + console errors."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5001"
COOKIE = Path(os.environ.get(
    "AT_COOKIES", r"C:\Users\Joosep\AppData\Local\Temp\at_cookies.txt"))
ROUTES = ["/dashboard", "/app", "/news", "/charts", "/charts/compare", "/map",
          "/pnl", "/profile", "/settings", "/guide", "/research/premarket",
          "/research/history", "/research/models", "/research/news",
          "/research/timing", "/market-intel", "/hedge-funds", "/filings",
          "/index-options", "/ipo-map", "/ipo-pipeline", "/premarket", "/press",
          "/developers", "/platform"]


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
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"PAGEERROR {e}\n{e.stack}\n---"))
        page.on("console", lambda m: errors.append(
            f"console.error {m.text} @ {m.location.get('url')}:{m.location.get('lineNumber')}")
            if m.type == "error" else None)
        page.on("response", lambda r: errors.append(f"HTTP{r.status} {r.url}")
                if r.status >= 400 else None)
        for route in ROUTES:
            errors.clear()
            try:
                page.goto(f"{BASE}{route}", wait_until="networkidle",
                          timeout=45_000)
                page.wait_for_timeout(800)
                title = page.title()
            except Exception as e:
                errors.append(f"navigation: {e}")
                title = "<nav failed>"
            if errors:
                print(f"### {route} (title={title!r})")
                for e in errors:
                    print("   ", e)
            else:
                print(f"OK {route} (title={title!r})")
        browser.close()


if __name__ == "__main__":
    main()
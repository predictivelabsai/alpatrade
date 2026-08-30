"""Part 4 audit: research / public-markets pages + slow-route timing sweep.

Times every page load (networkidle), captures JS/console/HTTP errors, and
screenshots the research & public-markets surfaces.
"""
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "artifacts" / "audit"
BASE = "http://localhost:5001"
COOKIE = Path(os.environ.get(
    "AT_COOKIES", r"C:\Users\Joosep\AppData\Local\Temp\at_cookies.txt"))

# (route, screenshot-or-empty)
ROUTES = [
    ("/research", "60-research.png"),
    ("/research/premarket", "61-premarket.png"),
    ("/research/history", None),
    ("/research/models", "62-research-models.png"),
    ("/research/news", None),
    ("/research/timing", None),
    ("/market-intel", "63-market-intel.png"),
    ("/hedge-funds", "64-hedge-funds.png"),
    ("/filings", "65-filings.png"),
    ("/index-options", "66-index-options.png"),
    ("/ipo-map", "67-ipo-map.png"),
    ("/ipo-pipeline", None),
    ("/premarket", "68-premarket.png"),
    ("/press", "69-press.png"),
    ("/spacs", "70-spacs.png"),
    ("/monitoring/pipeline", "71-monitoring.png"),
    ("/positions", None),
    ("/news", None),
    ("/charts", None),
    ("/charts/compare", None),
    ("/map", None),
]


def cookie() -> str:
    for line in COOKIE.read_text().splitlines():
        if "localhost" in line and "session_" in line:
            return line.split("\t")[-1]
    raise RuntimeError("no session cookie")


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "session_", "value": cookie(), "url": BASE,
                          "httpOnly": True, "sameSite": "Lax"}])
        page = ctx.new_page()
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        page.on("console", lambda m: errs.append(f"console.error {m.text}")
                if m.type == "error" else None)
        page.on("response", lambda r: errs.append(f"HTTP{r.status} {r.url}")
                if r.status >= 400 else None)

        for route, shot in sorted(ROUTES, reverse=True):
            errs.clear()
            t0 = time.perf_counter()
            try:
                page.goto(f"{BASE}{route}", wait_until="networkidle",
                          timeout=60_000)
                page.wait_for_timeout(600)
                dt = time.perf_counter() - t0
                title = page.title()
            except Exception as e:
                print(f"SLOW/FAIL {route}: {e}")
                continue
            flag = " <<< SLOW" if dt > 5 else ""
            print(f"{dt:6.2f}s  {route}  (title={title!r}){flag}")
            if errs:
                print("   errors:")
                for e in sorted(set(errs)):
                    print("    ", e)
            if shot and not errs:
                page.screenshot(path=SHOTS / shot)
        browser.close()


if __name__ == "__main__":
    main()
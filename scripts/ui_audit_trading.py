"""Part 2 audit: trading surfaces — keys round-trip, positions, paper order, dashboard.

Reads ALPACA_PAPER_* from .env at runtime and posts them through the real
/profile/keys endpoint. Key values are never printed or logged.
"""
import os
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


def env_key() -> tuple[str, str]:
    vals = {}
    for line in (ROOT / ".env").read_text().splitlines():
        for name in ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"):
            if line.startswith(name + "="):
                vals[name] = line.split("=", 1)[1].strip().strip('"')
    return vals.get("ALPACA_PAPER_API_KEY", ""), vals.get("ALPACA_PAPER_SECRET_KEY", "")


def attach_keys() -> str:
    import subprocess
    import urllib.request

    api, sec = env_key()
    assert api and sec, "no paper keys in .env"
    data = urlencode = b"account_name=Audit+Test+Account"
    from urllib.parse import urlencode
    req = urllib.request.Request(
        f"{BASE}/profile/keys",
        data=urlencode({"api_key": api, "secret_key": sec,
                        "account_name": "Audit Test Account"}).encode(),
        headers={"Cookie": f"session_={cookie()}"},
        method="POST")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req)
        return f"profile/keys -> {resp.status}"
    except urllib.error.HTTPError as e:
        return f"profile/keys -> {e.code} Location: {e.headers.get('Location', '')}"


def chat(page, msg: str, timeout: int = 180_000) -> None:
    page.fill("#chat-input", msg)
    page.click("#send-btn")
    page.wait_for_function(
        "!document.querySelector('#send-btn').disabled", timeout=timeout)
    page.wait_for_timeout(1200)


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    print(attach_keys())
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

        page.goto(f"{BASE}/app?new=1&x=part2", wait_until="networkidle")

        chat(page, "Show me my positions")
        page.screenshot(path=SHOTS / "50-positions.png")
        text = page.eval_on_selector_all(
            ".msg-bubble", "els => els.map(e => e.innerText)")
        print("== positions reply ==", "\n", text[-1][:400])

        chat(page, "accounts")
        text = page.eval_on_selector_all(
            ".msg-bubble", "els => els.map(e => e.innerText)")
        print("== accounts reply ==", "\n", text[-1][:400])

        # paper order through the tool path (Alpaca paper API)
        chat(page, "Buy 1 share of TSLA at market", timeout=180_000)
        page.screenshot(path=SHOTS / "51-paper-order.png")
        text = page.eval_on_selector_all(
            ".msg-bubble", "els => els.map(e => e.innerText)")
        print("== order reply ==", "\n", text[-1][:600])

        # dashboard + pnl should now render with data
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=SHOTS / "52-dashboard-with-data.png", full_page=True)
        print("dashboard URL:", page.url, "title:", page.title())
        plot = page.locator("#equity-chart.js-plotly-plot").count()
        print("equity plot rendered:", plot == 1)

        page.goto(f"{BASE}/pnl", wait_until="networkidle")
        page.wait_for_timeout(800)
        print("pnl URL:", page.url, "title:", page.title())
        page.screenshot(path=SHOTS / "53-pnl.png", full_page=True)

        print("== errors ==")
        print("\n".join(sorted(set(errs))) or "(none)")
        browser.close()


if __name__ == "__main__":
    main()
"""End-to-end test of the assisted Alpaca connect flow (engine.alpaca_connect).

Drives the same step()/poll() the chat uses, against real app.alpaca.markets.

  ALPACA_LOGIN_PASSWORD=... python scripts/alpaca_connect_e2e.py \
      --alpatrade-user julian.kaljuvee@gmail.com --alpaca-email you@x.com \
      --otp-file /tmp/alpaca_otp [--live] [--headed]

The password is read from $ALPACA_LOGIN_PASSWORD or a getpass prompt (never argv).
The 2FA code is read the moment it appears: from --otp-file (polled every 0.2s,
then deleted) or from stdin if no file is given. Codes expire in ~30s.
"""
import argparse
import getpass
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()
os.environ["ALPACA_CONNECT_ENABLED"] = "1"
os.environ.setdefault("ALPACA_CONNECT_OTP_WAIT", "900")
os.environ.setdefault("ALPACA_CONNECT_TTL", "1200")
from engine import alpaca_connect as ac  # noqa: E402


def read_otp(path: str | None, wait: int) -> str:
    if not path:
        return input("2FA code: ").strip()
    p = Path(path)
    print(f"[e2e] waiting up to {wait}s for the code in {p} …", flush=True)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if p.exists() and p.read_text().strip():
            code = p.read_text().strip()
            p.unlink()
            return code
        time.sleep(0.2)
    raise SystemExit("[e2e] no 2FA code arrived")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--alpatrade-user", required=True)
    a.add_argument("--alpaca-email", required=True)
    a.add_argument("--otp-file")
    a.add_argument("--otp-wait", type=int, default=600)
    a.add_argument("--live", action="store_true")
    a.add_argument("--headed", action="store_true")
    a.add_argument("--screenshots", help="TEST ONLY: dir for masked, verified user-guide screenshots")
    a.add_argument("--app-url", default="http://localhost:5077",
                   help="local AlpaTrade (ALPATRADE_DEV_LOGIN=1, ALPACA_CONNECT_ENABLED=1) for chat/Settings shots")
    o = a.parse_args()
    from engine.auth import get_user_by_email
    u = get_user_by_email(o.alpatrade_user)
    if not u:
        raise SystemExit("[e2e] AlpaTrade user not found")
    uid = str(u["user_id"])
    pw = os.environ.pop("ALPACA_LOGIN_PASSWORD", "") or getpass.getpass("Alpaca password: ")
    factory = lambda: ac.AlpacaBrowser(headless=not o.headed, screenshot_dir=o.screenshots)  # noqa: E731
    if o.screenshots:
        app_shots(o, "chat")
    say = lambda r: print("[bot]", r.replace("\n", " ")[:300], flush=True)  # noqa: E731
    r, _, _ = ac.step(uid, "connect alpaca live" if o.live else "connect alpaca", factory); say(r)
    r, f, _ = ac.step(uid, o.alpaca_email, factory); say(r)
    _, _, _ = ac.step(uid, pw, factory); pw = ""
    r, f = ac.poll(uid, 120, tick=lambda m: None); say(r)
    if f == "otp":
        print("[e2e] READY_FOR_2FA", flush=True)
        ac.SESSIONS[uid].created = time.monotonic()  # keep alive while waiting for the relay
        code = read_otp(o.otp_file, o.otp_wait)
        ac.step(uid, code, factory); code = ""
        r, f = ac.poll(uid, 180); say(r)
    if o.screenshots:
        app_shots(o, "settings")
    sys.exit(0 if r.startswith("Done") else 1)


def app_shots(o, which: str) -> None:
    """Masked screenshots of the AlpaTrade side (chat prompts; Settings Check result)."""
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(f"{o.app_url}/dev/login?email={o.alpatrade_user}&next=/app?new=1", timeout=30000)
            hide = (o.alpaca_email, o.alpatrade_user)
            if which == "chat":
                pg.wait_for_selector("#chat-input", timeout=30000)

                def send(t, wait="#chat-input"):
                    pg.fill("#chat-input", t); pg.keyboard.press("Enter"); pg.wait_for_timeout(3500)
                send("connect alpaca")
                pg.wait_for_selector("text=Heads up", timeout=30000)
                ac.masked_screenshot(pg, os.path.join(o.screenshots, "00a-chat-connect-warning.png"), hide)
                send(o.alpaca_email)
                pg.wait_for_selector("text=Alpaca password", timeout=30000)
                pg.fill("#chat-input", "not-a-real-password")  # shows the masked input box only
                ac.masked_screenshot(pg, os.path.join(o.screenshots, "00b-chat-password-prompt-masked.png"),
                                     hide + ("not-a-real-password",))
                pg.fill("#chat-input", ""); send("cancel")  # never submit the dummy
            else:
                pg.goto(f"{o.app_url}/settings", timeout=30000)
                btns = pg.locator("button.s-chkbtn")
                if btns.count():
                    btns.last.click(); pg.wait_for_timeout(5000)
                ac.masked_screenshot(pg, os.path.join(o.screenshots, "05-settings-check-result.png"), hide)
            b.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[e2e] app screenshots ({which}) skipped: {type(exc).__name__}: {str(exc)[:120]}", flush=True)


if __name__ == "__main__":
    main()

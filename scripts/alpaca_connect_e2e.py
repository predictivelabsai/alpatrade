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
    o = a.parse_args()
    from engine.auth import get_user_by_email
    u = get_user_by_email(o.alpatrade_user)
    if not u:
        raise SystemExit("[e2e] AlpaTrade user not found")
    uid = str(u["user_id"])
    pw = os.environ.pop("ALPACA_LOGIN_PASSWORD", "") or getpass.getpass("Alpaca password: ")
    factory = lambda: ac.AlpacaBrowser(headless=not o.headed)  # noqa: E731
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
    sys.exit(0 if r.startswith("Done") else 1)


if __name__ == "__main__":
    main()

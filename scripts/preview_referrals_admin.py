"""Local UI preview of /invite and /admin with fake data (no DB writes), screenshotted
by headless Playwright at 390px (mobile) and 1366px (desktop).

Usage: python scripts/preview_referrals_admin.py  → screenshots/referrals_admin/*.png
"""
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "screenshots" / "referrals_admin"
OUT.mkdir(parents=True, exist_ok=True)

import app as appmod  # noqa: E402
from engine import admin_analytics, rbac, referrals  # noqa: E402
from engine.web import ph_admin, ph_auth, ph_referrals  # noqa: E402

U = {"user_id": "00000000-0000-0000-0000-000000000001", "email": "kaljuvee@gmail.com",
     "display_name": "Julian", "is_admin": True, "email_verified_at": datetime.now(timezone.utc)}
now = datetime.now(timezone.utc)
ph_auth.current_user = lambda s: U
ph_referrals._user = lambda s: U
ph_admin._user = lambda s: U
rbac.is_admin = lambda u: True
referrals.get_or_create_code = lambda uid: "K7QX2M9P"
referrals.list_invites = lambda uid: [
    {"email": "anna@example.com", "status": "accepted", "sent_at": now - timedelta(days=2), "accepted_at": now},
    {"email": "mark@example.com", "status": "sent", "sent_at": now - timedelta(hours=3), "accepted_at": None}]
d = date.today()
admin_analytics.snapshot = lambda: {
    "total_users": 184, "new_users_7d": 23, "new_users_30d": 71, "dau": 19, "wau": 64, "mau": 121,
    "logins_7d": 142, "logins_total": 142, "activations": [("live", 6, 4), ("paper", 38, 27)],
    "referrals": [(17, 6, 9)], "referred_signups": 6, "backtests_total": 2311, "backtests_7d": 188, "teams": 2,
    "new_users_daily": [(d - timedelta(days=i), 5 - i % 4) for i in range(7)],
    "new_users_weekly": [(d - timedelta(days=7 * i + d.weekday()), 20 - i) for i in range(6)],
    "roles": [("user", 176), ("member", 6), ("admin", 2)],
    "logins_by_method_30d": [("google", 90), ("password", 48), ("register", 4)]}


def serve():
    import uvicorn
    uvicorn.run(appmod.app, host="127.0.0.1", port=5187, log_level="warning")


threading.Thread(target=serve, daemon=True).start()
time.sleep(3)
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, w, h in (("mobile", 390, 844), ("desktop", 1366, 900)):
        pg = b.new_page(viewport={"width": w, "height": h})
        for path in ("/invite", "/admin"):
            pg.goto(f"http://127.0.0.1:5187{path}", wait_until="networkidle")
            f = OUT / f"{path.strip('/')}_{name}.png"
            pg.screenshot(path=str(f), full_page=True)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            print(f, "scrollWidth", sw, "viewport", w)
    b.close()

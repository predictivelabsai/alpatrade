"""Anti-bot guard for the public auth forms (/register, /signin, /forgot).

Layers (all server-side; each fails closed for the request, never crashes it):

* **Cloudflare Turnstile** — on when ``TURNSTILE_SITE_KEY`` and
  ``TURNSTILE_SECRET_KEY`` are set, unless ``TURNSTILE_ENABLED=0``.
* **Honeypot + minimum time-to-submit** — a hidden ``website`` field must stay
  empty and the HMAC-signed render timestamp ``ft`` must be ≥ 3 s old (≤ 2 h).
* **Per-IP signup rate limit** — 3 accounts / hour and 10 / day per client IP
  (first ``x-forwarded-for`` hop). Every signup attempt is logged with IP and
  user agent in ``alpatrade.signup_attempts`` (``sql/55_signup_guard.sql``).
* **Daily admin alert** — one email to ``SIGNUP_ALERT_TO`` (fallback
  ``TO_EMAIL``) when more than ``SIGNUP_ALERT_THRESHOLD`` (20) accounts are
  created in a UTC day.
* **Cleanup** — :func:`purge_stale_accounts` deletes password accounts left
  unverified for 7 days and test-domain accounts older than 1 day; run daily by
  :func:`start_cleanup_scheduler`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fasthtml.common import Div, Input, Label, NotStr

log = logging.getLogger("engine.web.antibot")

MIN_SUBMIT_SECONDS = 3.0
MAX_FORM_AGE_SECONDS = 2 * 3600
SIGNUPS_PER_HOUR = int(os.getenv("SIGNUP_LIMIT_PER_HOUR", "3"))
SIGNUPS_PER_DAY = int(os.getenv("SIGNUP_LIMIT_PER_DAY", "10"))
UNVERIFIED_TTL_DAYS = 7
# Dedicated test domains. Tests must use TEST_EMAIL_DOMAIN; the cleanup job
# removes any account on these domains after a day.
TEST_EMAIL_DOMAIN = "alpatrade-test.invalid"
TEST_DOMAINS = (TEST_EMAIL_DOMAIN, "test.local", "example.com", "example.test", "example.org")
_SQL = Path(__file__).resolve().parents[2] / "sql" / "55_signup_guard.sql"
_ready = False
_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


# --------------------------------------------------------------------------- turnstile
def turnstile_site_key() -> str:
    return os.getenv("TURNSTILE_SITE_KEY", "").strip()


def turnstile_enabled() -> bool:
    flag = os.getenv("TURNSTILE_ENABLED", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return bool(turnstile_site_key() and os.getenv("TURNSTILE_SECRET_KEY", "").strip())


def verify_turnstile(token: str, ip: str = "") -> bool:
    """True when Turnstile is off, or Cloudflare accepts ``token``."""
    if not turnstile_enabled():
        return True
    if not token:
        return False
    data = {"secret": os.getenv("TURNSTILE_SECRET_KEY", "").strip(), "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        req = urllib.request.Request(_VERIFY_URL, data=urllib.parse.urlencode(data).encode())
        with urllib.request.urlopen(req, timeout=8) as r:
            return bool(json.load(r).get("success"))
    except Exception as exc:  # noqa: BLE001
        log.warning("turnstile verify failed: %s", type(exc).__name__)
        return False


# --------------------------------------------------------------------------- honeypot / timing
def _secret() -> bytes:
    return (os.getenv("JWT_SECRET") or os.getenv("ENCRYPTION_KEY") or "alpatrade-dev").encode()


def _sign(ts: str) -> str:
    return hmac.new(_secret(), ts.encode(), hashlib.sha256).hexdigest()[:32]


def form_token(now: float | None = None) -> str:
    ts = str(int((now if now is not None else time.time()) * 1000))
    return f"{ts}.{_sign(ts)}"


def guard_fields():
    """Hidden honeypot + signed timestamp + (optional) Turnstile widget."""
    fields = [
        Div(
            Label("Website", fr="hp-website"),
            Input(id="hp-website", name="website", type="text", value="",
                  autocomplete="off", tabindex="-1"),
            cls="hp-field", aria_hidden="true",
            style="position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden",
        ),
        Input(type="hidden", name="ft", value=form_token()),
    ]
    if turnstile_enabled():
        fields.append(NotStr(
            '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
            f'<div class="cf-turnstile" data-sitekey="{turnstile_site_key()}" '
            'data-size="flexible" style="margin:8px 0 12px"></div>'))
    return fields


def check_form(form, ip: str = "", now: float | None = None) -> str:
    """Return ``""`` if the form passes, else a reason code."""
    if (form.get("website") or "").strip():
        return "honeypot"
    tok = form.get("ft") or ""
    ts, _, sig = tok.partition(".")
    if not ts.isdigit() or not hmac.compare_digest(sig, _sign(ts)):
        return "invalid"
    age = (now if now is not None else time.time()) - int(ts) / 1000.0
    if age < MIN_SUBMIT_SECONDS:
        return "too_fast"
    if age > MAX_FORM_AGE_SECONDS:
        return "expired"
    if not verify_turnstile(form.get("cf-turnstile-response") or "", ip):
        return "captcha"
    return ""


def client_ip(request) -> str:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return ip or (request.client.host if getattr(request, "client", None) else "")


def is_test_email(email: str) -> bool:
    dom = (email or "").rsplit("@", 1)[-1].strip().lower()
    return any(dom == d or dom.endswith("." + d) for d in TEST_DOMAINS)


# --------------------------------------------------------------------------- DB helpers
def _session():
    from utils.db.db_pool import DatabasePool
    return DatabasePool().get_session()


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    from sqlalchemy import text
    with _session() as s:
        s.execute(text(_SQL.read_text()))
        s.commit()
    _ready = True


def log_attempt(ip: str, email: str, user_agent: str, outcome: str, user_id=None) -> None:
    try:
        ensure_schema()
        from sqlalchemy import text
        with _session() as s:
            s.execute(text("INSERT INTO alpatrade.signup_attempts (ip, email, user_agent, outcome, user_id) "
                           "VALUES (:ip, :e, :ua, :o, CAST(:u AS UUID))"),
                      {"ip": (ip or "")[:64] or None, "e": (email or "")[:255].lower() or None,
                       "ua": (user_agent or "")[:300] or None, "o": outcome[:32],
                       "u": str(user_id) if user_id else None})
            s.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("signup attempt log failed: %s", type(exc).__name__)


def rate_limited(ip: str) -> bool:
    """True if ``ip`` already created ≥3 accounts in the last hour or ≥10 today."""
    if not ip:
        return False
    try:
        ensure_schema()
        from sqlalchemy import text
        with _session() as s:
            h, d = s.execute(text(
                "SELECT COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour'), COUNT(*) "
                "FROM alpatrade.signup_attempts WHERE ip = :ip AND outcome = 'created' "
                "AND created_at > NOW() - INTERVAL '24 hours'"), {"ip": ip}).fetchone()
        return h >= SIGNUPS_PER_HOUR or d >= SIGNUPS_PER_DAY
    except Exception as exc:  # noqa: BLE001
        log.warning("rate limit check failed: %s", type(exc).__name__)
        return False


def maybe_alert_admin() -> bool:
    """Email the admin once per UTC day when signups exceed the threshold."""
    threshold = int(os.getenv("SIGNUP_ALERT_THRESHOLD", "20"))
    to = os.getenv("SIGNUP_ALERT_TO") or os.getenv("TO_EMAIL") or ""
    try:
        ensure_schema()
        from sqlalchemy import text
        with _session() as s:
            n = s.execute(text("SELECT COUNT(*) FROM alpatrade.users WHERE created_at >= "
                               "date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'")).scalar()
            if n <= threshold or not to:
                return False
            claimed = s.execute(text("INSERT INTO alpatrade.signup_alerts (alert_day, signups) "
                                     "VALUES ((NOW() AT TIME ZONE 'UTC')::date, :n) "
                                     "ON CONFLICT DO NOTHING RETURNING alert_day"), {"n": n}).fetchone()
            s.commit()
        if not claimed:
            return False
        from utils.email_util import send_email_to
        send_email_to(to, f"AlpaTrade: {n} signups today (threshold {threshold})",
                      f"<p>{n} AlpaTrade accounts were created today (UTC). Possible bot wave — "
                      "check /admin and alpatrade.signup_attempts.</p>")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("signup alert failed: %s", type(exc).__name__)
        return False


# --------------------------------------------------------------------------- cleanup
_STALE_WHERE = """
    u.is_admin IS NOT TRUE
    AND NOT EXISTS (SELECT 1 FROM alpatrade.user_accounts a WHERE a.user_id = u.user_id)
    AND NOT EXISTS (SELECT 1 FROM alpatrade.user_strategy_activations x WHERE x.user_id = u.user_id)
    AND NOT EXISTS (SELECT 1 FROM alpatrade.user_live_broker_accounts b WHERE b.user_id = u.user_id)
    AND NOT EXISTS (SELECT 1 FROM alpatrade.runs r WHERE r.user_id = u.user_id)
    AND NOT EXISTS (SELECT 1 FROM alpatrade.trades t WHERE t.user_id = u.user_id)
    AND (
        (u.email_verified_at IS NULL AND u.google_id IS NULL AND u.password_hash IS NOT NULL
         AND u.created_at < NOW() - make_interval(days => :ttl))
        OR (split_part(lower(u.email), '@', 2) = ANY(:test_domains)
            AND u.created_at < NOW() - INTERVAL '1 day')
    )
"""


def purge_stale_accounts(dry_run: bool = False) -> list[str]:
    """Delete stale unverified / test accounts. Returns the deleted emails.

    Accounts with broker keys, activations, runs or trades are never touched.
    Child rows with ON DELETE CASCADE go with the user; the few NO ACTION
    tables are excluded by the guards above.
    """
    from sqlalchemy import text
    params = {"ttl": UNVERIFIED_TTL_DAYS, "test_domains": list(TEST_DOMAINS)}
    with _session() as s:
        if dry_run:
            return [r[0] for r in s.execute(text(
                f"SELECT u.email FROM alpatrade.users u WHERE {_STALE_WHERE}"), params)]
        rows = s.execute(text(
            "DELETE FROM alpatrade.users WHERE user_id IN "
            f"(SELECT u.user_id FROM alpatrade.users u WHERE {_STALE_WHERE}) RETURNING email"),
            params).fetchall()
        s.commit()
    emails = [r[0] for r in rows]
    if emails:
        log.info("purged %d stale accounts", len(emails))
    return emails


_scheduler_started = False


def start_cleanup_scheduler(interval_seconds: int = 6 * 3600) -> None:
    """Run :func:`purge_stale_accounts` in a daemon thread every 6 h.

    Disabled with ``ACCOUNT_CLEANUP_ENABLED=0`` and under pytest. A Postgres
    advisory lock keeps multiple web workers from running it concurrently.
    """
    global _scheduler_started
    if _scheduler_started or os.getenv("PYTEST_CURRENT_TEST") or \
            os.getenv("ACCOUNT_CLEANUP_ENABLED", "1").lower() in ("0", "false", "no"):
        return
    _scheduler_started = True

    def _loop():
        time.sleep(120)
        while True:
            try:
                from sqlalchemy import text
                with _session() as s:
                    got = s.execute(text("SELECT pg_try_advisory_lock(551055)")).scalar()
                    try:
                        if got:
                            purge_stale_accounts()
                    finally:
                        if got:
                            s.execute(text("SELECT pg_advisory_unlock(551055)"))
            except Exception as exc:  # noqa: BLE001
                log.warning("account cleanup failed: %s", type(exc).__name__)
            time.sleep(interval_seconds)

    threading.Thread(target=_loop, name="account-cleanup", daemon=True).start()

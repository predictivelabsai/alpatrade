"""Referrals: per-user code, up to 5 invites, Postmark delivery, signup attribution.

* Each user gets a stable 8-char referral code (``users.referral_code``).
* ``/invite`` accepts up to 5 emails; invites are deduped per (referrer, email),
  capped at :data:`MAX_INVITES` per user for life (failed sends don't count),
  and a recipient is emailed at most once per :data:`RECIPIENT_COOLDOWN_H`
  hours across all referrers. Already-registered emails are skipped.
* The email is an HTML cover letter (key features, referral link + code, linked
  YouTube thumbnail) with the user guide PDF attached, sent via Postmark
  (``POSTMARK_API_KEY``, ``FROM_EMAIL``).
* ``/register?ref=CODE`` stores the code in the session; on signup the new user
  gets ``referred_by`` and matching invites flip to ``accepted``.
"""
from __future__ import annotations

import base64
import html
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("engine.referrals")

MAX_INVITES = 5
RECIPIENT_COOLDOWN_H = 24
YOUTUBE_ID = "rfbsMxSUGh4"
YOUTUBE_URL = f"https://youtu.be/{YOUTUBE_ID}"
YOUTUBE_THUMB = f"https://img.youtube.com/vi/{YOUTUBE_ID}/hqdefault.jpg"
GUIDE_PDF = Path(__file__).resolve().parents[1] / "docs" / "user_guide" / "alpatrade_user_guide.pdf"
_EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}$")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
_CODE_RE = re.compile(r"^[A-Z0-9]{6,16}$")

FEATURES = [
    ("AI trading copilot", "Ask in plain English: backtest a strategy, explain a move, or check your account."),
    ("Backtesting that holds up", "Grid-search parameters on real market data with fees, drawdown and Sharpe reported honestly."),
    ("Paper, then live", "Run strategies on your own Alpaca paper account, then go live with allocation caps and kill switches."),
    ("Strategy leaderboard", "See what's working, clone a strategy in one click and make it your own."),
    ("Daily reports", "A clear after-close P&L report for every strategy you run, in your inbox."),
    ("Market research", "News with sector impact, market map, premarket movers and hedge-fund filings."),
]


def base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "https://alpatrade.chat").rstrip("/")


def referral_link(code: str) -> str:
    return f"{base_url()}/register?ref={code}"


def new_code(n: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(n))


def clean_code(code) -> str:
    c = (code or "").strip().upper() if isinstance(code, str) else ""
    return c if _CODE_RE.match(c) else ""


def parse_emails(raw: Iterable[str] | str) -> tuple[list[str], list[str]]:
    """Split/normalise input → (valid unique lowercase emails, invalid tokens)."""
    if isinstance(raw, str):
        raw = [raw]
    tokens = [t.strip().lower() for chunk in raw for t in re.split(r"[\s,;]+", chunk or "") if t.strip()]
    good, bad, seen = [], [], set()
    for t in tokens:
        if not _EMAIL_RE.match(t) or len(t) > 254:
            bad.append(t)
        elif t not in seen:
            seen.add(t)
            good.append(t)
    return good, bad


def plan_invites(emails: list[str], *, own_email: str, already_invited: set[str],
                 used: int, registered: set[str], recently_emailed: set[str],
                 cap: int = MAX_INVITES) -> dict:
    """Pure decision: which emails to send now and why the rest are skipped."""
    send, skipped = [], []
    remaining = max(0, cap - used)
    for e in emails:
        if e == (own_email or "").lower():
            skipped.append((e, "that's you"))
        elif e in already_invited:
            skipped.append((e, "already invited"))
        elif e in registered:
            skipped.append((e, "already has an account"))
        elif e in recently_emailed:
            skipped.append((e, "invited by someone in the last 24h"))
        elif len(send) >= remaining:
            skipped.append((e, f"invite limit reached ({cap})"))
        else:
            send.append(e)
    return {"send": send, "skipped": skipped, "remaining_after": remaining - len(send)}


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def render_email(*, inviter_name: str, code: str) -> tuple[str, str, str]:
    """Return (subject, html, text)."""
    name = html.escape(inviter_name or "A friend")
    link = referral_link(code)
    feats = "".join(
        f'<tr><td style="padding:6px 0;vertical-align:top;color:#1F5D43;font-weight:700;width:18px">&#10003;</td>'
        f'<td style="padding:6px 0"><b>{html.escape(t)}</b><br>'
        f'<span style="color:#4a4a4a">{html.escape(d)}</span></td></tr>' for t, d in FEATURES)
    subject = f"{inviter_name or 'A friend'} invited you to AlpaTrade"
    body = f"""<!doctype html><html><body style="margin:0;background:#F7F6F1;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d1d1b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F7F6F1;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #e4e1d8;border-radius:12px;overflow:hidden">
<tr><td style="background:#1F5D43;color:#fff;padding:22px 28px;font-size:20px;font-weight:700">AlpaTrade</td></tr>
<tr><td style="padding:26px 28px 8px;font-size:15px;line-height:1.55">
<p style="margin:0 0 14px">Hi,</p>
<p style="margin:0 0 14px"><b>{name}</b> thinks you'd like <b>AlpaTrade</b>: an AI trading platform where you can research ideas,
backtest strategies on real data, paper-trade them and, when you're ready, run them live on your own Alpaca account.</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 6px;font-size:14px;line-height:1.45">{feats}</table>
</td></tr>
<tr><td align="center" style="padding:12px 28px 4px">
<a href="{link}" style="display:inline-block;background:#1F5D43;color:#ffffff;text-decoration:none;font-weight:700;padding:13px 26px;border-radius:8px;font-size:15px">Join AlpaTrade</a>
<p style="margin:12px 0 0;font-size:13px;color:#6c6c6c">Your referral code: <b style="letter-spacing:1px;color:#1d1d1b">{code}</b></p>
</td></tr>
<tr><td style="padding:22px 28px 6px;font-size:15px"><b>See it in 3 minutes</b></td></tr>
<tr><td style="padding:0 28px 8px"><a href="{YOUTUBE_URL}"><img src="{YOUTUBE_THUMB}" width="544" alt="Watch the AlpaTrade video on YouTube" style="width:100%;max-width:544px;height:auto;border-radius:8px;border:1px solid #e4e1d8;display:block"></a>
<p style="margin:6px 0 0;font-size:13px"><a href="{YOUTUBE_URL}" style="color:#1F5D43">&#9654; Watch on YouTube</a></p></td></tr>
<tr><td style="padding:14px 28px 24px;font-size:14px;line-height:1.5;color:#4a4a4a">The <b>AlpaTrade user guide</b> is attached (PDF): connecting Alpaca, running a backtest, activating paper and live strategies.</td></tr>
<tr><td style="padding:14px 28px;background:#F7F6F1;font-size:12px;color:#8a8a8a">You received this because {name} entered your address on AlpaTrade. We won't email you again unless you sign up.
Link not working? Paste <span style="color:#1F5D43">{html.escape(link)}</span> into your browser.</td></tr>
</table></td></tr></table></body></html>"""
    text = (f"{inviter_name or 'A friend'} invited you to AlpaTrade.\n\n"
            + "\n".join(f"- {t}: {d}" for t, d in FEATURES)
            + f"\n\nJoin: {link}\nReferral code: {code}\nVideo: {YOUTUBE_URL}\n"
              "The user guide PDF is attached.\n")
    return subject, body, text


def send_invite_email(to: str, *, inviter_name: str, code: str, http=None) -> Optional[str]:
    """Send one invite via Postmark. Returns the Postmark MessageID, or None on failure."""
    token, sender = os.getenv("POSTMARK_API_KEY"), os.getenv("FROM_EMAIL")
    if not token or not sender:
        log.warning("Postmark not configured (POSTMARK_API_KEY / FROM_EMAIL)")
        return None
    subject, body, text = render_email(inviter_name=inviter_name, code=code)
    payload = {"From": f"AlpaTrade <{sender}>" if "<" not in sender else sender, "To": to,
               "Subject": subject, "HtmlBody": body, "TextBody": text,
               "MessageStream": "outbound", "Tag": "referral-invite", "TrackOpens": True}
    if GUIDE_PDF.exists():
        payload["Attachments"] = [{"Name": "AlpaTrade-User-Guide.pdf", "ContentType": "application/pdf",
                                   "Content": base64.b64encode(GUIDE_PDF.read_bytes()).decode()}]
    if http is None:
        import requests as http  # noqa: N813
    try:
        r = http.post("https://api.postmarkapp.com/email", timeout=30, json=payload,
                      headers={"Accept": "application/json", "Content-Type": "application/json",
                               "X-Postmark-Server-Token": token})
        if r.status_code != 200:
            log.error("Postmark HTTP %s: %s", r.status_code, (r.text or "")[:200])
            return None
        return (r.json() or {}).get("MessageID") or "sent"
    except Exception as exc:  # noqa: BLE001
        log.error("Postmark send failed: %s", type(exc).__name__)
        return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _session():
    from engine.rbac import ensure_schema
    from utils.db.db_pool import DatabasePool
    ensure_schema()
    return DatabasePool().get_session()


def get_or_create_code(user_id: str) -> str:
    from sqlalchemy import text
    with _session() as s:
        row = s.execute(text("SELECT referral_code FROM alpatrade.users WHERE user_id = CAST(:u AS UUID)"),
                        {"u": str(user_id)}).fetchone()
        if row and row[0]:
            return row[0]
        for _ in range(5):
            code = new_code()
            try:
                s.execute(text("UPDATE alpatrade.users SET referral_code = :c "
                               "WHERE user_id = CAST(:u AS UUID) AND referral_code IS NULL"),
                          {"c": code, "u": str(user_id)})
                s.commit()
                break
            except Exception:  # noqa: BLE001 — unique collision, retry
                s.rollback()
        row = s.execute(text("SELECT referral_code FROM alpatrade.users WHERE user_id = CAST(:u AS UUID)"),
                        {"u": str(user_id)}).fetchone()
        return row[0]


def list_invites(user_id: str) -> list[dict]:
    from sqlalchemy import text
    with _session() as s:
        rows = s.execute(text("SELECT email, status, sent_at, accepted_at FROM alpatrade.referral_invites "
                              "WHERE referrer_id = CAST(:u AS UUID) ORDER BY sent_at DESC"),
                         {"u": str(user_id)}).fetchall()
    return [dict(email=r[0], status=r[1], sent_at=r[2], accepted_at=r[3]) for r in rows]


def invite(user: dict, raw_emails, *, sender=send_invite_email) -> dict:
    """Validate, dedupe, rate-limit and send. Returns a result summary for the page."""
    from sqlalchemy import text
    good, bad = parse_emails(raw_emails)
    good = good[:MAX_INVITES]
    uid = str(user["user_id"])
    code = get_or_create_code(uid)
    with _session() as s:
        mine = s.execute(text("SELECT email, status FROM alpatrade.referral_invites "
                              "WHERE referrer_id = CAST(:u AS UUID)"), {"u": uid}).fetchall()
        registered = {r[0] for r in s.execute(text(
            "SELECT lower(email) FROM alpatrade.users WHERE lower(email) = ANY(:e)"), {"e": good}).fetchall()} if good else set()
        recent = {r[0] for r in s.execute(text(
            "SELECT email FROM alpatrade.referral_invites WHERE email = ANY(:e) AND status <> 'failed' "
            f"AND sent_at > NOW() - INTERVAL '{RECIPIENT_COOLDOWN_H} hours'"), {"e": good}).fetchall()} if good else set()
    already = {r[0] for r in mine if r[1] != "failed"}
    used = sum(1 for r in mine if r[1] != "failed")
    plan = plan_invites(good, own_email=user.get("email", ""), already_invited=already, used=used,
                        registered=registered, recently_emailed=recent - already)
    name = user.get("display_name") or (user.get("email") or "").split("@")[0]
    sent, failed = [], []
    for e in plan["send"]:
        mid = sender(e, inviter_name=name, code=code)
        status = "sent" if mid else "failed"
        (sent if mid else failed).append(e)
        with _session() as s:
            s.execute(text("""
                INSERT INTO alpatrade.referral_invites (referrer_id, email, status, message_id, sent_at)
                VALUES (CAST(:u AS UUID), :e, :st, :m, NOW())
                ON CONFLICT (referrer_id, email) DO UPDATE
                SET status = EXCLUDED.status, message_id = EXCLUDED.message_id, sent_at = NOW()
                WHERE alpatrade.referral_invites.status = 'failed'"""),
                      {"u": uid, "e": e, "st": status, "m": (mid or "")[:80] or None})
            s.commit()
    return {"sent": sent, "failed": failed, "skipped": plan["skipped"], "invalid": bad,
            "remaining": MAX_INVITES - used - len(sent)}


def link_signup(new_user_id: str, email: str, code: str = "") -> bool:
    """Attribute a fresh signup: set referred_by from the code and accept matching invites."""
    from sqlalchemy import text
    code = clean_code(code)
    try:
        with _session() as s:
            referrer = None
            if code:
                row = s.execute(text("SELECT user_id FROM alpatrade.users WHERE referral_code = :c"),
                                {"c": code}).fetchone()
                if row and str(row[0]) != str(new_user_id):
                    referrer = str(row[0])
            if referrer is None:  # invited by email but signed up without the link
                row = s.execute(text("SELECT referrer_id FROM alpatrade.referral_invites WHERE email = :e "
                                     "AND status = 'sent' ORDER BY sent_at DESC LIMIT 1"),
                                {"e": (email or "").lower()}).fetchone()
                referrer = str(row[0]) if row else None
            if referrer is None:
                return False
            s.execute(text("UPDATE alpatrade.users SET referred_by = CAST(:r AS UUID) "
                           "WHERE user_id = CAST(:u AS UUID) AND referred_by IS NULL"),
                      {"r": referrer, "u": str(new_user_id)})
            s.execute(text("UPDATE alpatrade.referral_invites SET status = 'accepted', accepted_at = NOW(), "
                           "accepted_user_id = CAST(:u AS UUID) WHERE referrer_id = CAST(:r AS UUID) "
                           "AND email = :e AND status <> 'accepted'"),
                      {"u": str(new_user_id), "r": referrer, "e": (email or "").lower()})
            s.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — never block signup
        log.warning("referral attribution failed: %s", type(exc).__name__)
        return False

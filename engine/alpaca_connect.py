"""Chat-assisted Alpaca key connect ("connect alpaca" in /app chat).

Flow (per signed-in user, in memory only):
  trigger -> warn (regenerating invalidates old keys) -> ask Alpaca email ->
  ask password (masked) -> headless login -> ask authenticator 2FA code (masked) ->
  open paper (and optionally live) dashboard -> regenerate/create key pair ->
  validate with the existing read-only GET /v2/account -> save via the existing
  encrypted paths (engine.auth.store_alpaca_keys / engine.live_accounts.store_live_account)
  -> run the existing Check (engine.key_check.check).

Security:
  * Gated by ALPACA_CONNECT_ENABLED (default off).
  * The Alpaca password and 2FA code are never logged, never written to the chat
    transcript or DB; they live on the session object only until used, then wiped.
  * Every step has a timeout; sessions expire after SESSION_TTL seconds.
  * No screenshots/HTML dumps are taken (they could contain the secret).
"""
from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

LOGIN_URL = "https://app.alpaca.markets/account/login"
PAPER_URL = "https://app.alpaca.markets/paper/dashboard/overview"
LIVE_URL = "https://app.alpaca.markets/brokerage/dashboard/overview"
SESSION_TTL = int(os.getenv("ALPACA_CONNECT_TTL", "300"))
STEP_TIMEOUT_MS = int(os.getenv("ALPACA_CONNECT_STEP_TIMEOUT_MS", "30000"))
OTP_WAIT = int(os.getenv("ALPACA_CONNECT_OTP_WAIT", "180"))  # e2e script raises this

TRIGGER = re.compile(r"^\s*(/alpaca[-_ ]?connect\b.*|(please\s+)?(help\s+me\s+)?connect\s+(my\s+)?alpaca\b.*)$", re.I)
CANCEL = re.compile(r"^\s*(cancel|stop|abort|/cancel)\s*$", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OTP = re.compile(r"^\d{6,8}$")
PAPER_KEY = re.compile(r"\bPK[A-Z0-9]{14,30}\b")
LIVE_KEY = re.compile(r"\bAK[A-Z0-9]{14,30}\b")
SECRET = re.compile(r"\b[A-Za-z0-9/+]{36,48}\b")

WARNING = ("**Heads up:** connecting this way logs into Alpaca for you and **regenerates** your API "
           "keys. Your OLD keys stop working immediately — anything else using them (other apps, "
           "scripts) will break. Your Alpaca password and 2FA code are used once, kept in memory "
           "only, never saved or logged, and wiped when we're done. Type `cancel` at any time.")


def enabled() -> bool:
    return os.getenv("ALPACA_CONNECT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


class ConnectError(Exception):
    """User-facing error (message is safe to show)."""


@dataclass
class Session:
    user_id: str
    want_live: bool = False
    state: str = "await_email"   # await_email, await_password, logging_in, await_otp, working, done, error
    email: str = ""
    _password: str = field(default="", repr=False)
    otp_q: "queue.Queue[str]" = field(default_factory=queue.Queue, repr=False)
    progress: str = ""
    result: str = ""
    created: float = field(default_factory=time.monotonic)
    thread: Optional[threading.Thread] = None

    def wipe(self) -> None:
        self._password = ""
        try:
            while True:
                self.otp_q.get_nowait()
        except queue.Empty:
            pass

    def expired(self) -> bool:
        return time.monotonic() - self.created > SESSION_TTL


SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


def active(user_id: str) -> Optional[Session]:
    s = SESSIONS.get(user_id)
    if s and s.expired() and s.state not in ("working",):
        s.wipe()
        SESSIONS.pop(user_id, None)
        return None
    return s


def wants(user_id: str, msg: str) -> bool:
    """True when this chat message belongs to the connect flow (so it must NOT be persisted)."""
    if not enabled() or not user_id:
        return False
    return bool(active(user_id)) or bool(TRIGGER.match(msg or ""))


# ---------------------------------------------------------------------------
# Browser driver (Playwright, sync, runs in a worker thread)
# ---------------------------------------------------------------------------

def _first(page, selectors: list[str], timeout: int = STEP_TIMEOUT_MS):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.4)
    return None


def extract_pair(texts: list[str], live: bool) -> Optional[tuple[str, str]]:
    """Find (key_id, secret) in visible texts / input values of the 'new keys' dialog."""
    kre = LIVE_KEY if live else PAPER_KEY
    key = secret = None
    for t in texts:
        if not key:
            m = kre.search(t or "")
            key = m.group(0) if m else None
    for t in texts:
        for m in SECRET.finditer(t or ""):
            v = m.group(0)
            if v != key and not kre.fullmatch(v) and re.search(r"[a-z]", v) and re.search(r"\d", v):
                secret = v
                break
        if secret:
            break
    return (key, secret) if key and secret else None


class AlpacaBrowser:
    """Thin wrapper so tests can substitute a fake driver."""

    def __init__(self, headless: bool = True):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self.page = self._browser.new_page()
        self.page.set_default_timeout(STEP_TIMEOUT_MS)

    def close(self):
        for f in (self._browser.close, self._pw.stop):
            try:
                f()
            except Exception:  # noqa: BLE001
                pass

    def login(self, email: str, password: str) -> str:
        """Returns 'otp' when a 2FA prompt is shown, 'ok' when already in."""
        p = self.page
        try:
            p.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            raise ConnectError("Couldn't reach app.alpaca.markets from our server (timeout or blocked "
                               "network). Please add your keys manually in Settings > Integrations.") from exc
        btn = _first(p, ["#rcc-confirm-button"], 3000)
        if btn:
            btn.click()
        e = _first(p, ["input[name=email]", "input[type=email]"])
        if not e:
            raise ConnectError("Alpaca's login page didn't load as expected (possibly blocked or changed).")
        e.fill(email)
        p.locator("input[name=password], input[type=password]").first.fill(password)
        p.get_by_role("button", name=re.compile("continue|log ?in|sign ?in", re.I)).first.click()
        deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            body = (p.inner_text("body") or "").lower()
            if _otp_inputs(p):
                return "otp"
            if "dashboard" in p.url:
                return "ok"
            if re.search(r"incorrect|invalid (email|password|username)|wrong password", body):
                raise ConnectError("Alpaca rejected that email/password.")
            if re.search(r"captcha|verify you are human|access denied|unusual activity", body):
                raise ConnectError("Alpaca blocked the automated login (captcha / bot check). "
                                   "Please add your keys manually in Settings > Integrations.")
            time.sleep(0.5)
        raise ConnectError("Timed out waiting for Alpaca after login.")

    def submit_otp(self, code: str) -> None:
        p = self.page
        boxes = _otp_inputs(p)
        if not boxes:
            raise ConnectError("The 2FA prompt disappeared — please start again.")
        if len(boxes) >= len(code):
            for b, ch in zip(boxes, code):
                b.fill(ch)
        else:
            boxes[0].fill(code)
        btn = _first(p, ["button[type=submit]", "button:has-text('Verify')", "button:has-text('Continue')",
                         "button:has-text('Submit')"], 3000)
        if btn:
            try:
                btn.click()
            except Exception:  # noqa: BLE001
                pass
        deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            if "dashboard" in p.url and not _otp_inputs(p):
                return
            body = (p.inner_text("body") or "").lower()
            if re.search(r"invalid (code|token|otp)|incorrect code|code (is )?(invalid|expired)", body):
                raise ConnectError("Alpaca rejected the 2FA code (wrong or expired).")
            time.sleep(0.5)
        raise ConnectError("Timed out after submitting the 2FA code.")

    def regenerate(self, live: bool) -> tuple[str, str]:
        p = self.page
        p.goto(LIVE_URL if live else PAPER_URL, wait_until="domcontentloaded", timeout=45000)
        btn = _first(p, ["button:has-text('Regenerate')", "button:has-text('Generate New Key')",
                         "button:has-text('Generate')", "button:has-text('Create New Key')",
                         "text=View API Keys", "button:has-text('View')"])
        if not btn:
            raise ConnectError("Couldn't find the API keys panel on Alpaca's dashboard.")
        btn.click()
        # Some UIs open a panel first, then need Regenerate; some ask for confirmation.
        for sel in ["button:has-text('Regenerate')", "button:has-text('Generate New Key')",
                    "button:has-text('Confirm')", "button:has-text('Yes')"]:
            b = _first(p, [sel], 2500)
            if b:
                try:
                    b.click()
                except Exception:  # noqa: BLE001
                    pass
        deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            texts = [p.inner_text("body") or ""]
            texts += p.locator("input").evaluate_all("els => els.map(e => e.value || '')")
            pair = extract_pair(texts, live)
            if pair:
                return pair
            time.sleep(0.5)
        raise ConnectError("Alpaca didn't show a new key/secret pair (UI may have changed).")


def _otp_inputs(page) -> list:
    sels = ["input[autocomplete=one-time-code]", "input[name*=code i]", "input[name*=otp i]",
            "input[name*=token i]", "input[inputmode=numeric]", "input[maxlength='1']",
            "input[maxlength='6']"]
    out = []
    for sel in sels:
        try:
            loc = page.locator(sel)
            out = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]
        except Exception:  # noqa: BLE001
            out = []
        if out:
            return out
    return []


# ---------------------------------------------------------------------------
# Saving through the existing encrypted + validated paths
# ---------------------------------------------------------------------------

def save_pair(user_id: str, key: str, secret: str, live: bool) -> str:
    from engine import live_accounts as la
    if live:
        info = la.validate_live_keys(key, secret)
        la.store_live_account(user_id, info["account_number"], key, secret, label="Alpaca live (auto-connect)")
        ref, mode = info["account_number"], "live"
    else:
        from engine import auth
        la.validate_paper_keys(key, secret)
        existing = [a for a in auth.get_user_accounts(user_id)
                    if (a.get("account_name") or "").startswith("Alpaca Paper (auto-connect)")]
        ref = auth.store_alpaca_keys(user_id, key, secret, "Alpaca Paper (auto-connect)",
                                     account_id=str(existing[0]["account_id"]) if existing else None)
        mode = "paper"
    try:
        from engine import key_check
        res = key_check.check(mode, user_id, ref)
        status = "OK" if res.get("ok") else f"check failed: {res.get('text')}"
    except Exception as exc:  # noqa: BLE001
        status = f"saved; Check unavailable ({type(exc).__name__})"
    hint = key[:4] + "…" + key[-4:]
    return f"{'Live' if live else 'Paper'} keys {hint} saved — {status}"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _worker(s: Session, browser_factory: Callable[[], AlpacaBrowser], saver=save_pair) -> None:
    br = None
    try:
        s.progress = "Opening Alpaca login…"
        br = browser_factory()
        pw, s._password = s._password, ""
        try:
            outcome = br.login(s.email, pw)
        finally:
            pw = ""  # noqa: F841 — drop our reference immediately
        if outcome == "otp":
            s.state, s.progress = "await_otp", "Waiting for your 2FA code…"
            try:
                code = s.otp_q.get(timeout=OTP_WAIT)
            except queue.Empty:
                raise ConnectError("Timed out waiting for the 2FA code. Start again with `connect alpaca`.")
            if code == "__cancel__":
                raise ConnectError("Cancelled.")
            s.state, s.progress = "working", "Submitting 2FA code…"
            try:
                br.submit_otp(code)
            finally:
                code = ""  # noqa: F841
        s.state = "working"
        lines = []
        for live in ([False, True] if s.want_live else [False]):
            s.progress = f"Regenerating {'live' if live else 'paper'} API keys…"
            key, secret = br.regenerate(live)
            s.progress = "Validating and saving keys…"
            lines.append(saver(s.user_id, key, secret, live))
            key = secret = ""  # noqa: F841
        s.result, s.state = "\n".join(f"- {l}" for l in lines), "done"
    except ConnectError as exc:
        s.result, s.state = str(exc), "error"
    except Exception as exc:  # noqa: BLE001
        log.warning("alpaca_connect failed: %s", type(exc).__name__)  # never log values
        s.result, s.state = f"Something went wrong talking to Alpaca ({type(exc).__name__}). Your keys were not changed in AlpaTrade.", "error"
    finally:
        s.wipe()
        if br:
            br.close()


# ---------------------------------------------------------------------------
# Chat step handler: returns (reply_markdown, secret_field_or_None, wait_for)
# wait_for: None, or a set of states the caller should poll for before replying again.
# ---------------------------------------------------------------------------

def step(user_id: str, msg: str, browser_factory: Optional[Callable[[], AlpacaBrowser]] = None,
         saver=None) -> tuple[str, Optional[str], bool]:
    """Advance the flow. Returns (reply, secret_prompt_field, needs_wait)."""
    text = (msg or "").strip()
    browser_factory = browser_factory or (lambda: AlpacaBrowser())
    saver = saver or save_pair
    with _LOCK:
        s = active(user_id)
        if s and CANCEL.match(text):
            s.wipe()
            s.otp_q.put("__cancel__") if s.state == "await_otp" else None
            SESSIONS.pop(user_id, None)
            return "Cancelled. Nothing was changed.", None, False
        if not s or (TRIGGER.match(text) and s.state in ("done", "error")):
            s = Session(user_id=user_id, want_live=bool(re.search(r"\blive\b", text, re.I)))
            SESSIONS[user_id] = s
            return (WARNING + f"\n\nThis will set up your **paper**{' and **live**' if s.want_live else ''} keys. "
                    "What's the **email** you use to log into Alpaca?"), None, False
        if s.state == "await_email":
            if not EMAIL.match(text):
                return "That doesn't look like an email address. What's your Alpaca login email?", None, False
            s.email, s.state = text, "await_password"
            return "Thanks. Now enter your **Alpaca password** (hidden; used once, never saved).", "password", False
        if s.state == "await_password":
            if not text:
                return "Please enter your Alpaca password.", "password", False
            s._password, s.state = text, "logging_in"
            s.thread = threading.Thread(target=_worker, args=(s, browser_factory, saver), daemon=True)
            s.thread.start()
            return "", None, True
        if s.state == "await_otp":
            if not OTP.match(text.replace(" ", "")):
                return "Enter the 6-digit code from your **authenticator app**.", "otp", False
            s.otp_q.put(text.replace(" ", ""))
            s.state = "working"
            return "", None, True
        if s.state in ("logging_in", "working"):
            return "Still working on it — " + (s.progress or "please wait…"), None, True
    return "", None, True


def poll(user_id: str, timeout: float = 120.0, tick: Callable[[str], None] = lambda _m: None):
    """Block until the session needs input or finishes. Returns (reply, secret_field)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = SESSIONS.get(user_id)
        if not s:
            return "The connect session ended.", None
        if s.state == "await_otp":
            return ("Logged in. Enter the **6-digit 2FA code** from your authenticator app "
                    "(hidden; codes expire in ~30s, so enter it right away)."), "otp"
        if s.state == "done":
            SESSIONS.pop(user_id, None)
            return "Done! Alpaca is connected.\n\n" + s.result + "\n\nYour old keys are no longer valid.", None
        if s.state == "error":
            SESSIONS.pop(user_id, None)
            return "Couldn't connect Alpaca: " + s.result, None
        tick(s.progress)
        time.sleep(0.5)
    return "Still working — send any message to check progress.", None

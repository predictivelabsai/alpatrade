"""Authentication + profile for the merged AlpaTrade app (PEHero skin).

This is the ``ph_auth`` feature module. It ports the FULL auth flow from the
legacy ``web_app.py`` into the parchment/forest house style, rendering every
page through :func:`engine.web.ph_layout.auth_shell`.

Public surface
--------------
* ``register(app, rt)`` — adds all auth/profile routes and returns the list of
  registered route paths (see the contract in ``engine/web/ph_layout.py``).
* ``current_user(session)`` — resolve the signed-in user dict from the session,
  or ``None``. The session stores only ``session['user_id']``; the full user
  record is fetched fresh via :func:`engine.auth.get_user_by_id`.

Routes registered
-----------------
* ``/signin``            GET (form) + POST (email/password via ``authenticate``)
* ``/register``          GET (form) + POST (via ``create_user``)
* ``/forgot``            GET (form) + POST (email a reset token)
* ``/reset``             GET (form, ``?token=``) + POST (set new password)
* ``/logout``            GET (clears the session)
* ``/login``             GET (Google OAuth start, or stub → ``/signin``)
* ``/auth/callback``     GET (Google OAuth callback)
* ``/profile``           GET (user + linked Alpaca accounts)
* ``/profile/keys``      POST (add a per-user Alpaca key pair)
* ``/profile/keys/remove`` POST (deactivate an Alpaca account)
"""
from __future__ import annotations

import logging
import os

from fasthtml.common import (
    A, Button, Code, Div, Form, H2, H3, Input, Label, NotStr, P, Span, Table,
    Tbody, Td, Th, Thead, Tr,
)
from starlette.responses import RedirectResponse

from engine.auth import (
    authenticate,
    create_password_reset_token,
    create_user,
    get_user_accounts,
    get_user_by_email,
    get_user_by_google_id,
    get_user_by_id,
    link_google_id,
    store_alpaca_keys,
    update_password,
    verify_and_consume_reset_token,
)
from engine.web.ph_layout import auth_shell

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- oauth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
_oauth_enabled = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_authlib_oauth = None
if _oauth_enabled:
    from authlib.integrations.starlette_client import OAuth as AuthlibOAuth

    _authlib_oauth = AuthlibOAuth()
    _authlib_oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

# Google "G" mark (inline so the CSP-free static skin needs no extra asset).
_GOOGLE_SVG = (
    '<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 '
    '2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>'
    '<path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 '
    '0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>'
    '<path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 '
    '8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/>'
    '<path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 '
    '8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/></svg>'
)


# ---------------------------------------------------------------------------
# Session + user helpers
# ---------------------------------------------------------------------------
def current_user(session):
    """Resolve the signed-in user dict from ``session['user_id']`` (or None)."""
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


def _session_login(session, user: dict) -> None:
    """Persist the login. Only the id is stored; the record is re-fetched."""
    session["user_id"] = user["user_id"]


# ---------------------------------------------------------------------------
# Skin fragments
# ---------------------------------------------------------------------------
def _google_btn(label: str):
    return A(
        Span(NotStr(_GOOGLE_SVG), cls="google-btn-icon"),
        Span(label, cls="google-btn-text"),
        href="/login", cls="google-btn",
    )


def _or_divider():
    return Div(
        Div(cls="google-divider-line"),
        Span("or", cls="google-divider-text"),
        Div(cls="google-divider-line"),
        cls="google-divider",
    )


def _notice(error: str = "", msg: str = ""):
    parts = []
    if msg:
        parts.append(P(msg, cls="auth-success"))
    if error:
        parts.append(P(error, cls="auth-error"))
    return parts


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------
def _signin_page(email: str = "", error: str = "", msg: str = ""):
    blocks = [H2("Welcome back"), *_notice(error, msg)]
    if _oauth_enabled:
        blocks.append(_google_btn("Continue with Google"))
        blocks.append(_or_divider())
    blocks.append(Form(
        Label("Email"),
        Input(name="email", type="email", value=email, required=True, autofocus=True),
        Label("Password"),
        Input(name="password", type="password", required=True),
        Button("Log in", type="submit", cls="auth-primary-btn", style="width:100%"),
        method="post", action="/signin",
    ))
    blocks.append(A("Forgot password?", href="/forgot", cls="forgot-link"))
    blocks.append(P("Don't have an account? ", A("Sign up", href="/register"),
                    cls="forgot-link"))
    return auth_shell(*blocks, title="AlpaTrade · Sign in")


def _register_page(email: str = "", error: str = ""):
    blocks = [H2("Create your account"), *_notice(error)]
    if _oauth_enabled:
        blocks.append(_google_btn("Sign up with Google"))
        blocks.append(_or_divider())
    blocks.append(Form(
        Label("Display name"),
        Input(name="display_name", type="text", placeholder="Optional"),
        Label("Email"),
        Input(name="email", type="email", value=email, required=True),
        Label("Password"),
        Input(name="password", type="password", minlength="8",
              placeholder="At least 8 characters", required=True),
        Button("Create account", type="submit", cls="auth-primary-btn", style="width:100%"),
        method="post", action="/register",
    ))
    blocks.append(P("Already have an account? ", A("Log in", href="/signin"),
                    cls="forgot-link"))
    return auth_shell(*blocks, title="AlpaTrade · Register")


def _forgot_page(error: str = "", msg: str = ""):
    blocks = [
        H2("Reset your password"),
        P("Enter your email and we'll send you a reset link.", cls="signin-sub"),
        *_notice(error, msg),
        Form(
            Label("Email"),
            Input(name="email", type="email", required=True, autofocus=True),
            Button("Send reset link", type="submit", cls="auth-primary-btn", style="width:100%"),
            method="post", action="/forgot",
        ),
        A("Back to sign in", href="/signin", cls="forgot-link"),
    ]
    return auth_shell(*blocks, title="AlpaTrade · Forgot password")


def _reset_page(token: str, error: str = ""):
    blocks = [
        H2("Set a new password"),
        *_notice(error),
        Form(
            Input(name="token", type="hidden", value=token),
            Label("New password"),
            Input(name="password", type="password", minlength="8",
                  placeholder="At least 8 characters", required=True, autofocus=True),
            Label("Confirm password"),
            Input(name="confirm_password", type="password", minlength="8", required=True),
            Button("Reset password", type="submit", cls="auth-primary-btn", style="width:100%"),
            method="post", action="/reset",
        ),
    ]
    return auth_shell(*blocks, title="AlpaTrade · Reset password")


def _profile_page(user: dict, accounts: list, msg: str = ""):
    account_count = len(accounts)
    status = (
        Span(f"{account_count} account{'s' if account_count != 1 else ''}",
             cls="key-status configured")
        if account_count
        else Span("Not configured", cls="key-status not-configured")
    )

    blocks = [
        H2("Profile"),
        *_notice(msg=msg),
        Div(
            P(NotStr(f"<b>Email:</b> {user.get('email', '')}")),
            P(NotStr(f"<b>Display name:</b> {user.get('display_name') or '—'}")),
            P(NotStr("<b>Alpaca accounts:</b> "), status),
            cls="profile-info",
        ),
    ]

    if accounts:
        rows = []
        for i, acct in enumerate(accounts, 1):
            rows.append(Tr(
                Td(str(i)),
                Td(acct.get("account_name") or "—"),
                Td(Code(acct.get("api_key_hint", "****"))),
                Td(Form(
                    Input(name="account_id", type="hidden", value=acct["account_id"]),
                    Button("Remove", type="submit", cls="auth-cancel-btn"),
                    method="post", action="/profile/keys/remove",
                )),
            ))
        blocks.append(H3("Linked Alpaca accounts"))
        blocks.append(Table(
            Thead(Tr(Th("#"), Th("Name"), Th("API key"), Th(""))),
            Tbody(*rows),
            cls="accounts-table",
        ))

    blocks.append(H3("Add Alpaca account"))
    blocks.append(Form(
        Div(Label("Account name"),
            Input(name="account_name", type="text", placeholder="Default Account"),
            cls="keys-row"),
        Div(Label("Alpaca Paper API key"),
            Input(name="api_key", type="password", required=True),
            cls="keys-row"),
        Div(Label("Alpaca Paper secret key"),
            Input(name="secret_key", type="password", required=True),
            cls="keys-row"),
        P("Keys are Fernet-encrypted at rest.", cls="keys-hint"),
        Button("Save keys", type="submit", cls="auth-primary-btn"),
        method="post", action="/profile/keys", cls="keys-form",
    ))
    blocks.append(P(A("← Back to app", href="/"), cls="forgot-link"))
    return auth_shell(*blocks, title="AlpaTrade · Profile")


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------
def register(app, rt):
    """Add auth + profile routes to the app; return the registered paths."""

    # ---- sign in ----------------------------------------------------------
    @rt("/signin", methods=["GET"])
    def signin_get(session, error: str = "", msg: str = ""):
        if current_user(session):
            return RedirectResponse("/", status_code=303)
        return _signin_page(error=error, msg=msg)

    @app.post("/signin")
    async def signin_post(session, request):
        form = await request.form()
        email = (form.get("email") or "").strip()
        pw = form.get("password") or ""
        try:
            user = authenticate(email, pw)
        except Exception:  # noqa: BLE001
            user = None
        if not user:
            return _signin_page(email=email, error="Invalid email or password.")
        _session_login(session, user)
        return RedirectResponse("/", status_code=303)

    # ---- register ---------------------------------------------------------
    @rt("/register", methods=["GET"])
    def register_get(session, error: str = ""):
        if current_user(session):
            return RedirectResponse("/", status_code=303)
        return _register_page(error=error)

    @app.post("/register")
    async def register_post(session, request):
        form = await request.form()
        email = (form.get("email") or "").strip()
        pw = form.get("password") or ""
        dn = (form.get("display_name") or "").strip() or None
        if not email or not pw:
            return _register_page(email=email, error="Email and password are required.")
        if len(pw) < 8:
            return _register_page(email=email, error="Password must be at least 8 characters.")
        try:
            if get_user_by_email(email):
                return _register_page(email=email, error="That email is already registered.")
            user = create_user(email=email, password=pw, display_name=dn)
        except Exception as e:  # noqa: BLE001
            logger.error("register failed: %s", e)
            return _register_page(email=email, error="Could not create account. Please try again.")
        if not user:
            return _register_page(email=email, error="Could not create account. Please try again.")
        _session_login(session, user)
        return RedirectResponse("/", status_code=303)

    # ---- forgot password --------------------------------------------------
    @rt("/forgot", methods=["GET"])
    def forgot_get(session, error: str = "", msg: str = ""):
        if current_user(session):
            return RedirectResponse("/", status_code=303)
        return _forgot_page(error=error, msg=msg)

    @app.post("/forgot")
    async def forgot_post(request):
        form = await request.form()
        email = (form.get("email") or "").strip()
        if email:
            try:
                token = create_password_reset_token(email)
                if token:
                    from utils.email_util import send_email_to
                    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
                    host = request.headers.get("host", request.url.netloc)
                    reset_url = f"{scheme}://{host}/reset?token={token}"
                    body_html = (
                        '<div style="font-family:-apple-system,sans-serif;max-width:500px;margin:0 auto">'
                        "<h2>Reset your password</h2>"
                        "<p>You requested a password reset for your AlpaTrade account.</p>"
                        f'<p><a href="{reset_url}" style="display:inline-block;padding:12px 24px;'
                        'background:#1F5D43;color:#fff;text-decoration:none;border-radius:6px">'
                        "Reset password</a></p>"
                        '<p style="color:#6c757d;font-size:13px">This link expires in 1 hour. '
                        "If you didn't request this, ignore this email.</p></div>"
                    )
                    send_email_to(email, "AlpaTrade — Password Reset", body_html)
            except Exception as e:  # noqa: BLE001
                logger.error("forgot-password send failed: %s", e)
        # Always report success to avoid email enumeration.
        return RedirectResponse(
            "/forgot?msg=If+that+email+is+registered+you+will+receive+a+reset+link",
            status_code=303,
        )

    # ---- reset password ---------------------------------------------------
    @rt("/reset", methods=["GET"])
    def reset_get(token: str = "", error: str = ""):
        if not token:
            return RedirectResponse("/forgot", status_code=303)
        return _reset_page(token, error=error)

    @app.post("/reset")
    async def reset_post(request):
        form = await request.form()
        token = form.get("token") or ""
        pw = form.get("password") or ""
        confirm = form.get("confirm_password") or ""
        if not token:
            return RedirectResponse("/forgot", status_code=303)
        if len(pw) < 8:
            return RedirectResponse(
                f"/reset?token={token}&error=Password+must+be+at+least+8+characters",
                status_code=303)
        if pw != confirm:
            return RedirectResponse(
                f"/reset?token={token}&error=Passwords+do+not+match", status_code=303)
        try:
            user = verify_and_consume_reset_token(token)
            if not user:
                return RedirectResponse(
                    "/forgot?error=Reset+link+is+invalid+or+expired", status_code=303)
            update_password(user["user_id"], pw)
        except Exception as e:  # noqa: BLE001
            logger.error("reset-password failed: %s", e)
            return RedirectResponse(
                "/forgot?error=Reset+link+is+invalid+or+expired", status_code=303)
        return RedirectResponse(
            "/signin?msg=Password+reset+successful.+Please+log+in.", status_code=303)

    # ---- logout -----------------------------------------------------------
    @rt("/logout")
    def logout(session):
        session.pop("user_id", None)
        return RedirectResponse("/", status_code=303)

    # ---- Google OAuth -----------------------------------------------------
    if _oauth_enabled:
        @rt("/login")
        async def google_login(request):
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("host", request.url.netloc)
            redirect_uri = f"{scheme}://{host}/auth/callback"
            return await _authlib_oauth.google.authorize_redirect(request, redirect_uri)

        @rt("/auth/callback")
        async def auth_callback(request, session):
            try:
                token = await _authlib_oauth.google.authorize_access_token(request)
            except Exception as e:  # noqa: BLE001
                logger.error("OAuth token exchange failed: %s", e)
                return RedirectResponse("/signin?error=Google+login+failed", status_code=303)
            userinfo = token.get("userinfo") or await _authlib_oauth.google.userinfo(token=token)
            google_id = userinfo.get("sub", "")
            email = userinfo.get("email", "")
            name = userinfo.get("name", "")
            if not email:
                return RedirectResponse(
                    "/signin?error=Google+did+not+provide+email", status_code=303)
            user = get_user_by_google_id(google_id) if google_id else None
            if not user:
                user = get_user_by_email(email)
                if user and google_id:
                    link_google_id(email, google_id)
                elif not user:
                    user = create_user(email=email, google_id=google_id, display_name=name)
            if not user:
                return RedirectResponse("/signin?error=Could+not+create+account", status_code=303)
            _session_login(session, user)
            return RedirectResponse("/", status_code=303)
    else:
        @rt("/login")
        def google_login_stub():
            return RedirectResponse("/signin", status_code=303)

    # ---- profile ----------------------------------------------------------
    @rt("/profile", methods=["GET"])
    def profile_get(session, msg: str = ""):
        user = current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        try:
            accounts = get_user_accounts(user["user_id"])
        except Exception:  # noqa: BLE001
            accounts = []
        return _profile_page(user, accounts, msg=msg)

    @app.post("/profile/keys")
    async def profile_keys(session, request):
        user = current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        api_key = (form.get("api_key") or "").strip()
        secret_key = (form.get("secret_key") or "").strip()
        account_name = (form.get("account_name") or "").strip() or "Default Account"
        if not api_key or not secret_key:
            return RedirectResponse("/profile?msg=Both+keys+are+required", status_code=303)
        try:
            store_alpaca_keys(user["user_id"], api_key, secret_key, account_name=account_name)
            return RedirectResponse("/profile?msg=Alpaca+keys+saved+successfully", status_code=303)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to store Alpaca keys: %s", e)
            return RedirectResponse("/profile?msg=Error+saving+keys", status_code=303)

    @app.post("/profile/keys/remove")
    async def profile_keys_remove(session, request):
        user = current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        account_id = (form.get("account_id") or "").strip()
        if not account_id:
            return RedirectResponse("/profile", status_code=303)
        try:
            from sqlalchemy import text

            from utils.db.db_pool import DatabasePool
            pool = DatabasePool()
            with pool.get_session() as db:
                db.execute(
                    text("""
                        UPDATE alpatrade.user_accounts
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE account_id = :account_id AND user_id = :user_id
                    """),
                    {"account_id": account_id, "user_id": user["user_id"]},
                )
            return RedirectResponse("/profile?msg=Account+removed", status_code=303)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to remove account: %s", e)
            return RedirectResponse("/profile?msg=Error+removing+account", status_code=303)

    return [
        "/signin", "/register", "/forgot", "/reset", "/logout",
        "/login", "/auth/callback", "/profile", "/profile/keys",
        "/profile/keys/remove",
    ]

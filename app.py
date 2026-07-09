"""assethero unified web app (Phase 1) — port 5001.

One FastHTML entry point: the shared house-style 3-pane shell + asset-class switcher,
root authentication, and the equities vertical mounted under /equities/*. The other
verticals (crypto, fx, prediction, research) are stubs until their merge phases.

Run:  ASSETHERO_WEB_PORT=5001 python app.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fasthtml.common import (  # noqa: E402
    A, Button, Div, Form, H2, Input, Label, P, serve, fast_app, NotStr,
)
from starlette.responses import RedirectResponse  # noqa: E402

from engine.auth import (  # noqa: E402
    authenticate, create_user, get_user_by_id, get_user_by_email, get_user_accounts,
    get_user_by_google_id, link_google_id,
)
from engine.web.layout import auth_page, page  # noqa: E402
from engine.web import landing  # noqa: E402
import verticals.equities.routes as equities  # noqa: E402

app, rt = fast_app(pico=False)

# --------------------------------------------------------------------------- oauth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
_oauth_enabled = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_authlib_oauth = None
if _oauth_enabled:
    from authlib.integrations.starlette_client import OAuth as AuthlibOAuth  # noqa: E402

    _authlib_oauth = AuthlibOAuth()
    _authlib_oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


_GOOGLE_SVG = ('<svg width="18" height="18" viewBox="0 0 18 18" style="display:inline-block;'
               'vertical-align:middle;margin-right:8px"><path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 '
               '1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/><path '
               'd="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 '
               '8.997 0 009 18z" fill="#34A853"/><path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 '
               '8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/><path d="M9 3.58c1.321 0 2.508.454 '
               '3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" '
               'fill="#EA4335"/></svg>')


def _google_btn(label):
    return A(NotStr(_GOOGLE_SVG), label, href="/login", cls="btn ghost",
             style="width:100%;display:flex;align-items:center;justify-content:center;text-decoration:none")


def current_user(session):
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- auth
def _or_divider():
    return Div("or", cls="muted", style="text-align:center;margin:.9rem 0;font-size:.8rem")


def _signin_form(error=None, email=""):
    rows = [
        Div(Label("Email"), Input(name="email", type="email", value=email), cls="formrow"),
        Div(Label("Password"), Input(name="password", type="password"), cls="formrow"),
        Button("Log in", cls="btn", type="submit", style="width:100%"),
    ]
    blocks = []
    if error:
        blocks.append(Div(error, cls="notice err"))
    if _oauth_enabled:
        blocks.append(_google_btn("Continue with Google"))
        blocks.append(_or_divider())
    blocks.append(Form(*rows, method="post", action="/signin"))
    blocks.append(P(A("Create an account", href="/register"), cls="muted",
                    style="text-align:center;margin-top:1rem"))
    return auth_page(*blocks, title="AlpaTrade · Sign in")


def _register_form(error=None, email=""):
    rows = [
        Div(Label("Display name"), Input(name="display_name"), cls="formrow"),
        Div(Label("Email"), Input(name="email", type="email", value=email), cls="formrow"),
        Div(Label("Password"), Input(name="password", type="password"), cls="formrow"),
        Button("Create account", cls="btn", type="submit", style="width:100%"),
    ]
    blocks = []
    if error:
        blocks.append(Div(error, cls="notice err"))
    if _oauth_enabled:
        blocks.append(_google_btn("Sign up with Google"))
        blocks.append(_or_divider())
    blocks.append(Form(*rows, method="post", action="/register"))
    blocks.append(P(A("Back to sign in", href="/signin"), cls="muted",
                    style="text-align:center;margin-top:1rem"))
    return auth_page(*blocks, title="AlpaTrade · Register")


@rt("/signin", methods=["GET"])
def signin_get(session):
    if current_user(session):
        return RedirectResponse("/equities", status_code=303)
    return _signin_form()


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
        return _signin_form(error="Invalid email or password.", email=email)
    session["user_id"] = user["user_id"]
    return RedirectResponse("/equities", status_code=303)


@rt("/register", methods=["GET"])
def register_get(session):
    if current_user(session):
        return RedirectResponse("/equities", status_code=303)
    return _register_form()


@app.post("/register")
async def register_post(session, request):
    form = await request.form()
    email = (form.get("email") or "").strip()
    pw = form.get("password") or ""
    dn = (form.get("display_name") or "").strip() or None
    if not email or not pw:
        return _register_form(error="Email and password are required.", email=email)
    try:
        if get_user_by_email(email):
            return _register_form(error="That email is already registered.", email=email)
        user = create_user(email=email, password=pw, display_name=dn)
    except Exception as e:  # noqa: BLE001
        return _register_form(error=f"Could not create account: {e}", email=email)
    session["user_id"] = user["user_id"]
    return RedirectResponse("/equities", status_code=303)


@rt("/logout")
def logout(session):
    session.pop("user_id", None)
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------- google oauth
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
        except Exception:  # noqa: BLE001
            return RedirectResponse("/signin?error=google", status_code=303)
        userinfo = token.get("userinfo") or await _authlib_oauth.google.userinfo(token=token)
        google_id = userinfo.get("sub", "")
        email = userinfo.get("email", "")
        name = userinfo.get("name", "")
        if not email:
            return RedirectResponse("/signin?error=google", status_code=303)
        user = get_user_by_google_id(google_id) if google_id else None
        if not user:
            user = get_user_by_email(email)
            if user and google_id:
                link_google_id(email, google_id)
            elif not user:
                user = create_user(email=email, google_id=google_id, display_name=name)
        if not user:
            return RedirectResponse("/signin?error=google", status_code=303)
        session["user_id"] = user["user_id"]
        return RedirectResponse("/equities", status_code=303)
else:
    @rt("/login")
    def google_login_stub():
        return RedirectResponse("/signin", status_code=303)


# --------------------------------------------------------------------- marketing
@rt("/")
def root(session):
    if current_user(session):
        return RedirectResponse("/equities", status_code=303)
    return landing.home_page()


@rt("/platform")
def platform_page():
    return landing.platform_page()


@rt("/agents")
def agents_page():
    return landing.agents_page()


@rt("/pricing")
def pricing_page():
    return landing.pricing_page()


@rt("/profile")
def profile(session):
    user = current_user(session)
    if not user:
        return RedirectResponse("/signin", status_code=303)
    try:
        accounts = get_user_accounts(user["user_id"])
    except Exception:  # noqa: BLE001
        accounts = []
    nav = [("Dashboard", "/equities"), ("Profile", "/profile")]
    body = [
        H2("Profile"),
        Div(
            P(NotStr(f"<b>Email:</b> {user.get('email', '')}")),
            P(NotStr(f"<b>Name:</b> {user.get('display_name') or '—'}")),
            P(NotStr(f"<b>Linked Alpaca accounts:</b> {len(accounts)}")),
            cls="card",
        ),
    ]
    return page("equities", nav, *body, user=user, active_nav="/profile",
                title="AlpaTrade · Profile")


# ----------------------------------------------------------------- vertical stubs
def _stub(vertical, label, session):
    user = current_user(session)
    if not user:
        return RedirectResponse("/signin", status_code=303)
    body = [
        H2(label),
        Div(P(f"The {label} vertical is coming in a later phase of the assethero merge."),
            P("Equities is live now — use the switcher above.", cls="muted"),
            cls="card"),
    ]
    return page(vertical, [("Overview", f"/{vertical}")], *body, user=user,
                title=f"AlpaTrade · {label}")


def _make_stub(vertical, label):
    def handler(session):
        return _stub(vertical, label, session)
    return handler


for _v, _l in [("crypto", "Crypto"), ("fx", "FX / Macro"),
               ("prediction", "Prediction"), ("research", "Research")]:
    rt(f"/{_v}")(_make_stub(_v, _l))


# --------------------------------------------------------------- equities vertical
equities.register(app, rt, current_user)


if __name__ == "__main__":
    serve(port=int(os.getenv("ASSETHERO_WEB_PORT", "5001")))

"""
AlpaTrade AG-UI — 3-pane chat interface powered by pydantic-ai + AG-UI protocol.

Left pane:  Auth / settings / navigation
Center:     Chat (WebSocket streaming)
Right:      Thinking trace / artifact canvas (toggled)

Launch:  python agui_app.py          # port 5003
         uvicorn agui_app:app --port 5003 --reload
"""

import os
import sys
import uuid as _uuid
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.ui import StateDeps
from fasthtml.common import *

from utils.agui import setup_agui, get_chat_styles

# ---------------------------------------------------------------------------
# pydantic-ai Agent
# ---------------------------------------------------------------------------

class AlpaTradeState(BaseModel):
    """Shared state between UI and agent — rendered in right pane."""
    last_action: str = ""

    def __ft__(self):
        if not self.last_action:
            return Div()
        return Div(
            Div(self.last_action, cls="state-value"),
            id="agui-state",
            hx_swap_oob="innerHTML",
        )


agent = Agent(
    "xai:grok-3-mini",
    name="AlpaTrade",
    instructions=(
        "You are AlpaTrade, an AI trading assistant. "
        "You help users with stock research, backtesting strategies, "
        "paper trading, and portfolio management. "
        "Be concise and use markdown formatting. "
        "When users type CLI-style commands like 'agent:backtest lookback:1m' "
        "or 'price AAPL', help them understand how to use those in the full AlpaTrade CLI. "
        "For now, answer questions about trading, stocks, and market analysis."
    ),
)


# ---------------------------------------------------------------------------
# FastHTML app
# ---------------------------------------------------------------------------

app, rt = fast_app(
    exts="ws",
    secret_key=os.getenv("JWT_SECRET", os.urandom(32).hex()),
    hdrs=[
        Script(src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"),
        Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js"),
    ],
)

agui = setup_agui(app, agent, AlpaTradeState(), AlpaTradeState)


# ---------------------------------------------------------------------------
# CSS — 3-pane layout
# ---------------------------------------------------------------------------

LAYOUT_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace;
  background: #0f172a;
  color: #e2e8f0;
  height: 100vh;
  overflow: hidden;
}

/* === 3-Pane Grid === */
.app-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100vh;
  transition: grid-template-columns 0.3s ease;
}

.app-layout .right-pane {
  display: none;
}

.app-layout.right-open {
  grid-template-columns: 260px 1fr 380px;
}

.app-layout.right-open .right-pane {
  display: flex;
}

/* === Left Pane (Sidebar) === */
.left-pane {
  background: #1e293b;
  border-right: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 1rem;
  gap: 1.25rem;
}

.brand {
  font-size: 1.25rem;
  font-weight: 700;
  color: #f1f5f9;
  text-decoration: none;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #334155;
}

.brand:hover { color: #3b82f6; }

.sidebar-section { display: flex; flex-direction: column; gap: 0.5rem; }

.sidebar-section h4 {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.sidebar-section a {
  color: #94a3b8;
  text-decoration: none;
  font-size: 0.85rem;
  padding: 0.35rem 0.5rem;
  border-radius: 0.375rem;
  transition: all 0.15s;
}

.sidebar-section a:hover {
  background: #334155;
  color: #f1f5f9;
}

.sidebar-section a.active {
  background: #3b82f6;
  color: white;
}

/* Auth forms in sidebar */
.sidebar-auth { display: flex; flex-direction: column; gap: 0.75rem; }

.sidebar-auth input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 0.375rem;
  color: #e2e8f0;
  font-family: inherit;
  font-size: 0.8rem;
}

.sidebar-auth input:focus {
  outline: none;
  border-color: #3b82f6;
}

.sidebar-auth button {
  width: 100%;
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}

.sidebar-auth button:hover { background: #2563eb; }

.alt-link { font-size: 0.75rem; color: #64748b; }
.alt-link a { color: #3b82f6; }

.error-msg { color: #f87171; font-size: 0.8rem; }
.success-msg { color: #4ade80; font-size: 0.8rem; }

.user-info {
  background: #0f172a;
  border-radius: 0.5rem;
  padding: 0.75rem;
  font-size: 0.8rem;
}

.user-info .name { font-weight: 600; color: #f1f5f9; }
.user-info .email { color: #64748b; font-size: 0.75rem; }

.key-status {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.7rem;
  font-weight: 500;
}
.key-status.configured { background: #065f46; color: #6ee7b7; }
.key-status.not-configured { background: #7f1d1d; color: #fca5a5; }

.keys-form input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 0.375rem;
  color: #e2e8f0;
  font-family: inherit;
  font-size: 0.8rem;
  margin-bottom: 0.5rem;
}

.keys-form input:focus { outline: none; border-color: #3b82f6; }

.keys-form button {
  width: 100%;
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.8rem;
}

/* Logout */
.logout-btn {
  display: block;
  padding: 0.35rem 0.5rem;
  color: #f87171;
  text-decoration: none;
  font-size: 0.85rem;
  border-radius: 0.375rem;
}
.logout-btn:hover { background: #7f1d1d33; }

/* === Center Pane (Chat) === */
.center-pane {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0f172a;
  overflow: hidden;
}

.center-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #334155;
  min-height: 3rem;
}

.center-header h2 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #f1f5f9;
}

.toggle-trace-btn {
  padding: 0.3rem 0.7rem;
  background: #334155;
  color: #94a3b8;
  border: 1px solid #475569;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}

.toggle-trace-btn:hover { background: #475569; color: #f1f5f9; }

.center-chat {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.center-chat > div {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* Override agui chat styles for dark theme */
.center-chat .chat-container {
  height: 100%;
  flex: 1;
  border: none;
  border-radius: 0;
  background: #0f172a;
  display: flex;
  flex-direction: column;
}

.center-chat .chat-messages {
  background: #0f172a;
  flex: 1;
}

.center-chat .chat-input {
  background: #1e293b;
  border-top: 1px solid #334155;
}

.center-chat .chat-input-field {
  background: #0f172a;
  border-color: #334155;
  color: #e2e8f0;
}

.center-chat .chat-input-field:focus {
  border-color: #3b82f6;
}

.center-chat .chat-message.chat-assistant .chat-message-content {
  background: #1e293b;
  color: #e2e8f0;
}

.center-chat .chat-message.chat-user .chat-message-content {
  background: #3b82f6;
  color: white;
}

.center-chat .chat-message.chat-tool .chat-message-content {
  background: #334155;
  color: #94a3b8;
}

.center-chat .chat-messages:empty::before {
  content: "Ask anything about stocks, trading, or type a CLI command...";
  color: #475569;
}

/* === Right Pane (Trace / Artifacts) === */
.right-pane {
  background: #1e293b;
  border-left: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.right-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #334155;
}

.right-header h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: #f1f5f9;
}

.close-trace-btn {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.2rem;
}
.close-trace-btn:hover { color: #f1f5f9; }

.right-tabs {
  display: flex;
  border-bottom: 1px solid #334155;
}

.right-tab {
  flex: 1;
  padding: 0.5rem;
  text-align: center;
  font-size: 0.75rem;
  color: #64748b;
  cursor: pointer;
  border: none;
  background: none;
  font-family: inherit;
}

.right-tab:hover { color: #94a3b8; }
.right-tab.active { color: #3b82f6; border-bottom: 2px solid #3b82f6; }

.right-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

#trace-content {
  font-size: 0.8rem;
  color: #94a3b8;
}

#artifact-content {
  display: none;
}

/* === Query Badge === */
.query-badge {
  font-size: 0.7rem;
  color: #64748b;
  padding: 0.2rem 0.5rem;
}

/* === Responsive === */
@media (max-width: 768px) {
  .app-layout {
    grid-template-columns: 1fr !important;
  }
  .left-pane { display: none; }
  .right-pane { display: none; }
}
"""


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

FREE_QUERY_LIMIT = 50


def _session_login(session, user: Dict):
    display = user.get("display_name") or ""
    if display.startswith("$2") or not display.strip():
        display = user.get("email", "user").split("@")[0]
    session["user"] = {
        "user_id": str(user["user_id"]),
        "email": user["email"],
        "display_name": display,
    }
    session["query_count"] = 0


# ---------------------------------------------------------------------------
# Left pane builder
# ---------------------------------------------------------------------------

def _left_pane(session):
    """Build the left sidebar: auth + navigation + status."""
    user = session.get("user")

    sections = [A("AlpaTrade", href="/", cls="brand")]

    # Auth section
    if user:
        name = user.get("display_name") or user.get("email", "user")
        email = user.get("email", "")

        # Check Alpaca key status
        keys_configured = False
        try:
            from utils.auth import get_alpaca_keys
            keys = get_alpaca_keys(user["user_id"])
            keys_configured = keys is not None
        except Exception:
            pass

        key_badge = (
            Span("Keys OK", cls="key-status configured")
            if keys_configured
            else Span("No keys", cls="key-status not-configured")
        )

        sections.append(
            Div(
                Div(
                    Div(name, cls="name"),
                    Div(email, cls="email"),
                    Div(key_badge, style="margin-top: 0.5rem;"),
                    cls="user-info",
                ),
                cls="sidebar-section",
            )
        )
    else:
        sections.append(
            Div(
                H4("Account"),
                Div(
                    id="auth-forms",
                    hx_get="/agui-auth/login-form",
                    hx_trigger="load",
                    hx_swap="innerHTML",
                ),
                cls="sidebar-section",
            )
        )

    # Navigation
    nav_links = [
        A("Home", href="/"),
        A("Guide", href="/guide", target="_blank"),
        A("Dashboard", href="https://alpatrade.dev", target="_blank"),
        A("Screenshots", href="/screenshots", target="_blank"),
    ]
    if user:
        nav_links.append(A("Profile", href="/profile"))
        nav_links.append(A("Logout", href="/logout", cls="logout-btn"))

    sections.append(Div(H4("Navigation"), *nav_links, cls="sidebar-section"))

    # Query status
    if not user:
        count = session.get("query_count", 0)
        remaining = max(0, FREE_QUERY_LIMIT - count)
        sections.append(
            Div(
                H4("Status"),
                Span(f"{remaining}/{FREE_QUERY_LIMIT} free queries", cls="query-badge"),
                cls="sidebar-section",
            )
        )

    return Div(*sections, cls="left-pane", id="left-pane")


# ---------------------------------------------------------------------------
# Right pane builder
# ---------------------------------------------------------------------------

def _right_pane():
    """Build the right pane: thinking trace + artifacts."""
    return Div(
        Div(
            H3("Trace"),
            Button("x", cls="close-trace-btn", onclick="toggleRightPane()"),
            cls="right-header",
        ),
        Div(
            Button("Thinking", cls="right-tab active", onclick="showTab('trace')"),
            Button("Artifacts", cls="right-tab", onclick="showTab('artifact')"),
            cls="right-tabs",
        ),
        Div(
            Div(
                Div("Tool calls and reasoning will appear here during agent runs.",
                    style="color: #475569; font-style: italic;"),
                id="trace-content",
            ),
            Div(id="artifact-content"),
            cls="right-content",
        ),
        cls="right-pane",
    )


# ---------------------------------------------------------------------------
# Layout JS
# ---------------------------------------------------------------------------

LAYOUT_JS = """
function toggleRightPane() {
    var layout = document.querySelector('.app-layout');
    layout.classList.toggle('right-open');
}

function showTab(tab) {
    var trace = document.getElementById('trace-content');
    var artifact = document.getElementById('artifact-content');
    var tabs = document.querySelectorAll('.right-tab');

    tabs.forEach(function(t) { t.classList.remove('active'); });

    if (tab === 'trace') {
        trace.style.display = 'block';
        artifact.style.display = 'none';
        tabs[0].classList.add('active');
    } else {
        trace.style.display = 'none';
        artifact.style.display = 'block';
        tabs[1].classList.add('active');
    }
}
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@rt("/")
def get(session):
    thread_id = session.get("thread_id")
    if not thread_id:
        thread_id = str(_uuid.uuid4())
        session["thread_id"] = thread_id

    return (
        Title("AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            _left_pane(session),
            Div(
                Div(
                    H2("AlpaTrade Chat"),
                    Button(
                        "Trace",
                        cls="toggle-trace-btn",
                        onclick="toggleRightPane()",
                    ),
                    cls="center-header",
                ),
                Div(agui.chat(thread_id), cls="center-chat"),
                cls="center-pane",
            ),
            _right_pane(),
            cls="app-layout",
        ),
        Script(LAYOUT_JS),
    )


# ---------------------------------------------------------------------------
# Auth routes (sidebar-based, return HTML fragments)
# ---------------------------------------------------------------------------

@rt("/agui-auth/login-form")
def login_form_fragment():
    """Return the login form for the sidebar."""
    return Div(
        Form(
            Input(type="email", name="email", placeholder="Email", required=True),
            Input(type="password", name="password", placeholder="Password", required=True),
            Button("Login", type="submit"),
            hx_post="/agui-auth/login",
            hx_target="#auth-forms",
            hx_swap="innerHTML",
            cls="sidebar-auth",
        ),
        Div(
            "No account? ",
            A("Sign up", href="#", hx_get="/agui-auth/register-form",
              hx_target="#auth-forms", hx_swap="innerHTML"),
            cls="alt-link",
        ),
    )


@rt("/agui-auth/register-form")
def register_form_fragment():
    """Return the register form for the sidebar."""
    return Div(
        Form(
            Input(type="email", name="email", placeholder="Email", required=True),
            Input(type="password", name="password", placeholder="Password (min 8 chars)",
                  required=True, minlength="8"),
            Input(type="text", name="display_name", placeholder="Display name (optional)"),
            Button("Create Account", type="submit"),
            hx_post="/agui-auth/register",
            hx_target="#auth-forms",
            hx_swap="innerHTML",
            cls="sidebar-auth",
        ),
        Div(
            "Have an account? ",
            A("Login", href="#", hx_get="/agui-auth/login-form",
              hx_target="#auth-forms", hx_swap="innerHTML"),
            cls="alt-link",
        ),
    )


@rt("/agui-auth/login")
def auth_login(session, email: str = "", password: str = ""):
    if not email or not password:
        return Div(P("Email and password required.", cls="error-msg"),
                   login_form_fragment())
    from utils.auth import authenticate
    user = authenticate(email, password)
    if not user:
        return Div(P("Invalid email or password.", cls="error-msg"),
                   login_form_fragment())
    _session_login(session, user)
    # Refresh the whole page to update sidebar
    return Div(
        P("Logged in!", cls="success-msg"),
        Script("setTimeout(function(){ window.location.reload(); }, 500);"),
    )


@rt("/agui-auth/register")
def auth_register(session, email: str = "", password: str = "", display_name: str = ""):
    if not email or not password:
        return Div(P("Email and password required.", cls="error-msg"),
                   register_form_fragment())
    if len(password) < 8:
        return Div(P("Password must be at least 8 characters.", cls="error-msg"),
                   register_form_fragment())
    from utils.auth import create_user
    user = create_user(email=email, password=password, display_name=display_name or None)
    if not user:
        return Div(P("Email already registered.", cls="error-msg"),
                   register_form_fragment())
    _session_login(session, user)
    return Div(
        P("Account created!", cls="success-msg"),
        Script("setTimeout(function(){ window.location.reload(); }, 500);"),
    )


@rt("/logout")
def logout(session):
    session.clear()
    return RedirectResponse("/", status_code=307)


@rt("/profile")
def profile(session, msg: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")

    keys_configured = False
    try:
        from utils.auth import get_alpaca_keys
        keys = get_alpaca_keys(user["user_id"])
        keys_configured = keys is not None
    except Exception:
        pass

    key_badge = (
        Span("Configured", cls="key-status configured")
        if keys_configured
        else Span("Not configured", cls="key-status not-configured")
    )

    return (
        Title("Profile — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("AlpaTrade", href="/", cls="brand"),
                Div(
                    H4("Profile"),
                    Div(
                        Div(user.get("display_name", ""), cls="name"),
                        Div(user.get("email", ""), cls="email"),
                        Div(key_badge, style="margin-top: 0.5rem;"),
                        cls="user-info",
                    ),
                    cls="sidebar-section",
                ),
                Div(
                    H4("Alpaca Paper Keys"),
                    P("Encrypted at rest. Used for paper trading.",
                      style="color: #64748b; font-size: 0.75rem; margin-bottom: 0.5rem;"),
                    Form(
                        Input(type="password", name="api_key",
                              placeholder="Alpaca Paper API Key", required=True),
                        Input(type="password", name="secret_key",
                              placeholder="Alpaca Paper Secret Key", required=True),
                        Button("Save Keys", type="submit"),
                        method="post", action="/profile/keys",
                        cls="keys-form",
                    ),
                    P(msg, cls="success-msg") if msg else "",
                    cls="sidebar-section",
                ),
                Div(
                    A("Back to Chat", href="/"),
                    A("Logout", href="/logout", cls="logout-btn"),
                    cls="sidebar-section",
                ),
                cls="left-pane",
                style="max-width: 400px; margin: 2rem auto; height: auto;",
            ),
            style="display: flex; justify-content: center; min-height: 100vh; background: #0f172a;",
        ),
    )


@rt("/profile/keys")
def profile_keys(session, api_key: str = "", secret_key: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not api_key or not secret_key:
        return RedirectResponse("/profile?msg=Both+keys+required")
    from utils.auth import store_alpaca_keys
    store_alpaca_keys(user["user_id"], api_key, secret_key)
    return RedirectResponse("/profile?msg=Keys+saved+successfully", status_code=303)


# ---------------------------------------------------------------------------
# Static content routes (open in new tabs from sidebar)
# ---------------------------------------------------------------------------

@rt("/guide")
def guide(session):
    """Minimal guide redirect — full guide lives on web_app.py."""
    return (
        Title("Guide — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("AlpaTrade", href="/", cls="brand"),
                Div(
                    H4("Quick Reference"),
                    P("Full guide available at ",
                      A("alpatrade.chat/guide", href="https://alpatrade.chat/guide",
                        target="_blank"),
                      style="font-size: 0.85rem; color: #94a3b8;"),
                    cls="sidebar-section",
                ),
                Div(
                    H4("Common Commands"),
                    P("agent:backtest lookback:1m", style="font-size: 0.8rem;"),
                    P("agent:paper duration:7d", style="font-size: 0.8rem;"),
                    P("price AAPL", style="font-size: 0.8rem;"),
                    P("news TSLA", style="font-size: 0.8rem;"),
                    P("trades / runs / status", style="font-size: 0.8rem;"),
                    cls="sidebar-section",
                ),
                Div(A("Back to Chat", href="/"), cls="sidebar-section"),
                cls="left-pane",
                style="max-width: 400px; margin: 2rem auto; height: auto;",
            ),
            style="display: flex; justify-content: center; min-height: 100vh; background: #0f172a;",
        ),
    )


@rt("/screenshots")
def screenshots():
    """Redirect to main app screenshots."""
    return RedirectResponse("https://alpatrade.chat/screenshots", status_code=307)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agui_app:app",
        host="0.0.0.0",
        port=5003,
        reload=True,
    )

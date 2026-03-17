"""FastHTML web shell for AlpaTrade — browser-based CLI."""
import asyncio
import collections
import logging
import os
import sys
import time
import threading
import uuid as _uuid
from pathlib import Path
from typing import Dict, Optional

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv
from fasthtml.common import *
from tui.command_processor import CommandProcessor
from tui.strategy_cli import StrategyCLI

load_dotenv()


# ---------------------------------------------------------------------------
# Log capture handler — thread-safe, stores lines in a bounded deque
# ---------------------------------------------------------------------------

class LogCapture(logging.Handler):
    """Captures log records into a deque for streaming to the browser."""

    def __init__(self, maxlen=500):
        super().__init__()
        self.lines = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._lock:
                self.lines.append(msg)
        except Exception:
            self.handleError(record)

    def get_lines(self):
        with self._lock:
            return list(self.lines)

    def clear(self):
        with self._lock:
            self.lines.clear()


# ---------------------------------------------------------------------------
# Per-user session state (replaces global cli singleton)
# ---------------------------------------------------------------------------

class UserSessionState:
    """Holds all per-user mutable state for the web UI."""

    SESSION_TTL = 7200  # 2 hours

    def __init__(self):
        self.cli = StrategyCLI()
        self.cli._log_capture = LogCapture()
        self.cli._cmd_task = None
        self.cli._cmd_result = None
        self.cli._last_chart_json = None
        self.cli._cmd_286_html = None
        self.cli._chat_events = collections.deque(maxlen=200)
        self.cli._chat_task = None
        self.cli._chat_done = False
        self.cli._chat_final = ""
        self.cli._chat_286_html = None
        self.last_accessed = time.time()
        self.user_id: Optional[str] = None  # set after login


_user_sessions: Dict[str, UserSessionState] = {}
_SESSION_CLEANUP_INTERVAL = 600  # seconds


def _get_user_session(session) -> UserSessionState:
    """Get or create a UserSessionState for this browser session."""
    sid = session.get("session_id")
    if not sid:
        sid = str(_uuid.uuid4())
        session["session_id"] = sid

    if sid not in _user_sessions:
        _user_sessions[sid] = UserSessionState()

    uss = _user_sessions[sid]
    uss.last_accessed = time.time()

    # Sync user_id from session auth
    user = session.get("user")
    if user:
        uss.user_id = user.get("user_id")
    else:
        uss.user_id = None

    return uss


def _evict_stale_sessions():
    """Remove sessions that haven't been accessed in TTL seconds."""
    now = time.time()
    stale = [
        sid for sid, uss in _user_sessions.items()
        if now - uss.last_accessed > UserSessionState.SESSION_TTL
    ]
    for sid in stale:
        del _user_sessions[sid]

# Commands that trigger background streaming
_STREAMING_COMMANDS = {"agent:backtest", "agent:paper", "agent:full", "agent:validate", "agent:reconcile"}

# Structured command prefixes — anything not matching these is free-form chat
_STRUCTURED_PREFIXES = {
    "news", "price", "profile", "financials", "analysts", "valuation", "movers",
    "trades", "runs", "agent:backtest", "agent:paper", "agent:full", "agent:validate",
    "agent:reconcile", "agent:status", "agent:stop", "agent:report", "agent:top",
    "agent:runs", "agent:trades", "agent:logs",
    "alpaca:backtest",
    "help", "h", "?", "guide", "status", "clear", "cls", "exit", "quit", "q",
}

# Broker-related keywords (mirrors CommandProcessor._BROKER_KEYWORDS)
_BROKER_KEYWORDS = {
    "buy", "sell", "order", "orders", "position", "positions",
    "holdings", "holding", "portfolio", "account", "balance",
    "buying power", "equity", "assets", "tradable",
}


def _is_structured_command(cmd_lower: str) -> bool:
    """Return True if the input matches a known structured command prefix."""
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    # Check exact match (e.g. "trades", "runs", "help")
    if first_word in _STRUCTURED_PREFIXES:
        return True
    # Check colon prefix (e.g. "news:TSLA" → "news")
    base = first_word.split(":")[0]
    if base in _STRUCTURED_PREFIXES:
        return True
    return False


def _is_broker_query(text: str) -> bool:
    """Return True if the input looks like a broker / trading interaction."""
    lower = text.lower()
    return any(kw in lower for kw in _BROKER_KEYWORDS)

# ---------------------------------------------------------------------------
# Google OAuth setup via authlib (optional — gracefully skip if no creds)
# ---------------------------------------------------------------------------

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

FREE_QUERY_LIMIT = 50
# Commands that don't count toward the free query limit
_FREE_COMMANDS = {"help", "h", "?", "guide", "clear", "cls", "exit", "quit", "q", "status"}

# ---------------------------------------------------------------------------
# Custom CSS & JS
# ---------------------------------------------------------------------------

_theme = Script("document.documentElement.dataset.theme='dark';")

_css = Style("""
body { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; }
main { max-width: 960px; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; height: 95vh; }
#output { flex: 1; overflow-y: auto; }
.cmd-entry { border-bottom: 1px solid var(--pico-muted-border-color); padding: 0.75rem 0; }
.cmd-echo { color: var(--pico-muted-color); font-size: 0.85em; margin-bottom: 0.25rem; }
.cmd-echo b { color: var(--pico-primary); }
#cmd-form { display: flex; gap: 0.5rem; padding-top: 0.5rem; border-top: 1px solid var(--pico-muted-border-color); }
#cmd-form input { flex: 1; margin-bottom: 0; }
#cmd-form button { width: auto; margin-bottom: 0; }
.help-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1.5rem; font-size: 0.85em; }
@media (max-width: 768px) { .help-grid { grid-template-columns: 1fr; } }
.help-grid h4 { color: var(--pico-primary); margin: 0.8rem 0 0.3rem; font-size: 0.95em; }
.help-grid h4:first-child { margin-top: 0; }
.help-grid dl { margin: 0; }
.help-grid dt { color: #e2c07b; font-size: 0.9em; margin-top: 0.3rem; }
.help-grid dd { color: var(--pico-muted-color); margin: 0 0 0 0.5rem; font-size: 0.85em; }
.htmx-request .htmx-indicator { display: inline; }
.htmx-indicator { display: none; }

/* Nav bar */
nav.top-nav { display: flex; align-items: center; justify-content: space-between;
              padding: 0.5rem 0; margin-bottom: 0.5rem;
              border-bottom: 1px solid var(--pico-muted-border-color); }
nav.top-nav .nav-brand { font-weight: bold; font-size: 1.1em; color: var(--pico-primary); text-decoration: none; }
nav.top-nav .nav-links { display: flex; gap: 1rem; align-items: center; font-size: 0.85em; }
nav.top-nav .nav-links a { color: var(--pico-muted-color); text-decoration: none; }
nav.top-nav .nav-links a:hover { color: var(--pico-primary); }

/* Query badge */
.query-badge { font-size: 0.75em; color: var(--pico-muted-color);
               background: var(--pico-card-background-color); padding: 0.15rem 0.5rem;
               border-radius: 0.25rem; border: 1px solid var(--pico-muted-border-color); }

/* Sign-in prompt */
.signin-card { text-align: center; padding: 2rem; margin: 1rem 0;
               border: 1px solid var(--pico-muted-border-color); border-radius: 0.5rem;
               background: var(--pico-card-background-color); }
.signin-card h4 { margin-bottom: 0.5rem; }
.signin-card p { color: var(--pico-muted-color); margin-bottom: 1rem; }
.signin-card a { display: inline-block; padding: 0.5rem 1.5rem;
                 background: var(--pico-primary); color: #fff; border-radius: 0.25rem;
                 text-decoration: none; font-weight: 600; }

/* Screenshot gallery */
.screenshot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-top: 1rem; }
@media (max-width: 768px) { .screenshot-grid { grid-template-columns: 1fr; } }
.screenshot-grid figure { margin: 0; }
.screenshot-grid img { width: 100%; border-radius: 0.5rem; border: 1px solid var(--pico-muted-border-color); }
.screenshot-grid figcaption { color: var(--pico-muted-color); font-size: 0.85em; margin-top: 0.3rem; text-align: center; }

/* Download page */
.dl-page { max-width: 700px; margin: 0 auto; }
.dl-page pre { position: relative; }
.copy-btn { position: absolute; top: 0.5rem; right: 0.5rem; background: var(--pico-primary);
            color: #fff; border: none; padding: 0.25rem 0.75rem; border-radius: 0.25rem;
            cursor: pointer; font-size: 0.8em; }
.copy-btn:hover { opacity: 0.85; }

/* Log console for streaming agent output */
.log-console { max-height: 400px; overflow-y: auto; background: #1a1a2e;
               border-radius: 0.5rem; padding: 0.5rem; margin-top: 0.5rem; }
.log-pre { color: #8b949e; font-size: 0.8em; margin: 0; white-space: pre-wrap; word-break: break-word; }
.backtest-chart { margin-top: 1rem; border-radius: 0.5rem; }

/* Auth forms — card layout with logo */
.auth-wrapper { display: flex; flex-direction: column; align-items: center;
                justify-content: center; min-height: 85vh; padding: 1rem; }
.auth-logo { text-align: center; margin-bottom: 1.5rem; }
.auth-logo .logo-icon { font-size: 2.8rem; display: block; margin-bottom: 0.4rem; }
.auth-logo .logo-text { font-size: 1.6rem; font-weight: 700; color: var(--pico-primary);
                         letter-spacing: -0.02em; }
.auth-logo .logo-tagline { font-size: 0.8rem; color: var(--pico-muted-color); margin-top: 0.2rem; }
.auth-card { width: 100%; max-width: 420px; background: var(--pico-card-background-color);
             border: 1px solid var(--pico-muted-border-color); border-radius: 12px;
             padding: 2rem; box-shadow: 0 4px 24px rgba(0,0,0,0.2); }
.auth-card h2 { text-align: center; margin-bottom: 1.5rem; font-size: 1.3rem; }
.auth-card form { display: flex; flex-direction: column; gap: 0.75rem; }
.auth-card input { width: 100%; }
.auth-card button[type=submit] { width: 100%; margin-top: 0.5rem; padding: 0.65rem;
                                  font-weight: 600; border-radius: 8px; }
.auth-card .alt-link { text-align: center; margin-top: 1rem; font-size: 0.85em;
                        color: var(--pico-muted-color); }
.auth-card .alt-link a { color: var(--pico-primary); }
.auth-card .error-msg { color: #e06c75; font-size: 0.85em; text-align: center;
                         margin-bottom: 0.5rem; background: rgba(224,108,117,0.08);
                         padding: 0.5rem; border-radius: 6px; }
.auth-card .success-msg { color: #2ea043; font-size: 0.85em; text-align: center;
                           margin-bottom: 0.5rem; background: rgba(46,160,67,0.08);
                           padding: 0.5rem; border-radius: 6px; }
.auth-card .divider { text-align: center; color: var(--pico-muted-color); margin: 1rem 0;
                       font-size: 0.85em; position: relative; }
.auth-card .divider::before, .auth-card .divider::after {
    content: ""; position: absolute; top: 50%; width: 40%; height: 1px;
    background: var(--pico-muted-border-color); }
.auth-card .divider::before { left: 0; }
.auth-card .divider::after { right: 0; }
.auth-card .google-btn { background: #4285f4; color: #fff; text-align: center;
                          text-decoration: none; display: flex; align-items: center;
                          justify-content: center; gap: 0.5rem; padding: 0.6rem;
                          border-radius: 8px; font-weight: 600; font-size: 0.9rem; }
.auth-card .google-btn:hover { background: #3367d6; color: #fff; }
.auth-card .google-btn svg { flex-shrink: 0; }
.auth-footer { text-align: center; margin-top: 2rem; font-size: 0.75em;
               color: var(--pico-muted-color); }
.auth-footer a { color: var(--pico-muted-color); }
/* Password field with eye toggle */
.pw-wrap { position: relative; }
.pw-wrap input { width: 100%; padding-right: 2.8rem; }
.pw-toggle { position: absolute; right: 0.6rem; top: 50%; transform: translateY(-50%);
             background: none; border: none; cursor: pointer; padding: 0.25rem;
             color: var(--pico-muted-color); line-height: 1; }
.pw-toggle:hover { color: var(--pico-primary); }
.pw-toggle svg { width: 20px; height: 20px; display: block; }

/* Profile page */
.profile-page { max-width: 600px; margin: 2rem auto; }
.profile-page .info-grid { display: grid; grid-template-columns: auto 1fr; gap: 0.5rem 1rem;
                            font-size: 0.9em; margin-bottom: 1.5rem; }
.profile-page .info-grid dt { color: var(--pico-muted-color); }
.profile-page .info-grid dd { margin: 0; }
.profile-page .keys-form { display: flex; flex-direction: column; gap: 0.75rem; }
.profile-page .keys-form input { width: 100%; }
.profile-page .keys-form button { width: auto; align-self: flex-start; }
.profile-page .key-status { font-size: 0.85em; padding: 0.3rem 0.6rem; border-radius: 0.25rem; }
.profile-page .key-status.configured { color: #2ea043; background: rgba(46, 160, 67, 0.1); }
.profile-page .key-status.not-configured { color: #e06c75; background: rgba(224, 108, 117, 0.1); }
.profile-page .accounts-table { width: 100%; font-size: 0.85em; margin-bottom: 1.5rem; }
.profile-page .accounts-table th { text-align: left; padding: 0.5rem; border-bottom: 1px solid var(--pico-muted-border-color); }
.profile-page .accounts-table td { padding: 0.5rem; border-bottom: 1px solid rgba(128,128,128,0.15); }
.profile-page .btn-sm { padding: 0.25rem 0.6rem; font-size: 0.75em; }
.profile-page .btn-danger { background: #e06c75; border-color: #e06c75; color: #fff; }
.profile-page .btn-danger:hover { background: #c95a63; }

/* User guide page */
.guide { max-width: 760px; margin: 0 auto; font-size: 0.9em; line-height: 1.6; }
.guide h2 { margin-top: 2rem; border-bottom: 1px solid var(--pico-muted-border-color); padding-bottom: 0.3rem; }
.guide h3 { margin-top: 1.5rem; color: var(--pico-primary); }
.guide code { background: var(--pico-card-background-color); padding: 0.1em 0.35em; border-radius: 0.2rem; font-size: 0.9em; }
.guide pre { background: #1a1a2e; padding: 0.75rem; border-radius: 0.5rem; overflow-x: auto; }
.guide pre code { background: none; padding: 0; font-size: 0.85em; color: #8b949e; }
.guide table { font-size: 0.85em; margin: 0.5rem 0 1rem; }
.guide .toc { background: var(--pico-card-background-color); padding: 1rem 1.5rem; border-radius: 0.5rem;
              border: 1px solid var(--pico-muted-border-color); margin-bottom: 1.5rem; }
.guide .toc ul { margin: 0.3rem 0 0 1rem; padding: 0; }
.guide .toc li { margin: 0.2rem 0; }
.guide .toc a { color: var(--pico-primary); text-decoration: none; font-size: 0.9em; }
.guide .toc a:hover { text-decoration: underline; }
.guide .param-grid { background: var(--pico-card-background-color); padding: 0.75rem 1rem; border-radius: 0.5rem;
                     border-left: 3px solid var(--pico-primary); margin: 0.5rem 0 1rem; }
.guide .tip { background: rgba(46, 160, 67, 0.1); padding: 0.5rem 1rem; border-radius: 0.5rem;
              border-left: 3px solid #2ea043; margin: 0.5rem 0; }
.guide .tip::before { content: "Tip: "; font-weight: bold; color: #2ea043; }
""")

_js = Script("""
document.addEventListener('htmx:afterSettle', function() {
    var out = document.getElementById('output');
    if (out) out.scrollTop = out.scrollHeight;
});
document.addEventListener('htmx:afterRequest', function(evt) {
    if (evt.detail.elt && evt.detail.elt.id === 'cmd-form') {
        evt.detail.elt.reset();
        evt.detail.elt.querySelector('input').focus();
    }
});
// Extend HTMX timeout for long-running commands (backtests)
document.addEventListener('htmx:configRequest', function(evt) {
    evt.detail.timeout = 300000;  // 5 minutes
});
// Auto-scroll log console and chat console when new content arrives
document.addEventListener('htmx:afterSwap', function(evt) {
    var lc = document.getElementById('log-console');
    if (lc) lc.scrollTop = lc.scrollHeight;
    var cc = document.getElementById('chat-console');
    if (cc) cc.scrollTop = cc.scrollHeight;
});
// Password eye toggle
document.addEventListener('click', function(e) {
    var btn = e.target.closest('.pw-toggle');
    if (!btn) return;
    var wrap = btn.closest('.pw-wrap');
    var inp = wrap.querySelector('input');
    var isHidden = inp.type === 'password';
    inp.type = isHidden ? 'text' : 'password';
    btn.querySelector('.eye-open').style.display = isHidden ? 'none' : 'block';
    btn.querySelector('.eye-closed').style.display = isHidden ? 'block' : 'none';
});
""")

_plotly_cdn = Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js")

app, rt = fast_app(hdrs=[_theme, MarkdownJS(), _css, _js, _plotly_cdn])

# ---------------------------------------------------------------------------
# Help — 3-column HTML grid (mirrors Rich CLI help layout)
# ---------------------------------------------------------------------------


def _help_html():
    """Return a 3-column help grid as FastHTML components."""

    def _section(title, items):
        """Build an h4 + dl for a help section."""
        dl_items = []
        for cmd, desc in items:
            dl_items.append(Dt(cmd))
            dl_items.append(Dd(desc))
        return (H4(title), Dl(*dl_items))

    # Column 1: Backtest, Validate, Reconcile
    col1 = Div(
        *_section("Backtest", [
            ("agent:backtest lookback:1m", "1-month backtest"),
            ("  symbols:AAPL,TSLA", "custom symbols"),
            ("  hours:extended", "pre/after-market"),
            ("  intraday_exit:true", "5-min TP/SL bars"),
            ("  pdt:false", "disable PDT rule"),
        ]),
        *_section("Validate", [
            ("agent:validate run-id:<uuid>", "validate a run"),
            ("  source:paper_trade", "validate paper trades"),
        ]),
        *_section("Reconcile", [
            ("agent:reconcile", "DB vs Alpaca (7d)"),
            ("  window:14d", "custom window"),
        ]),
    )

    # Column 2: Paper Trade, Full Cycle, Query & Monitor
    col2 = Div(
        *_section("Paper Trade", [
            ("agent:paper duration:7d", "run in background"),
            ("  symbols:AAPL,MSFT poll:60", "custom config"),
            ("  hours:extended", "extended hours"),
            ("  email:false", "disable email reports"),
            ("  pdt:false", "disable PDT rule"),
        ]),
        *_section("Full Cycle", [
            ("agent:full lookback:1m duration:1m", "BT > Val > PT > Val"),
            ("  hours:extended", "extended hours"),
        ]),
        *_section("Query & Monitor", [
            ("trades / runs", "DB tables"),
            ("agent:report", "performance summary"),
            ("  type:backtest run-id:<uuid>", "filter / detail"),
            ("  strategy:btd", "filter by slug prefix"),
            ("agent:top", "rank strategies by Avg Annual Return"),
            ("  strategy:btd", "filter by slug prefix"),
            ("agent:status", "agent states"),
            ("agent:stop", "stop background task"),
        ]),
    )

    # Column 3: Research & Options
    col3 = Div(
        *_section("Research", [
            ("news:TSLA", "company news"),
            ("  provider:xai|tavily", "force news provider"),
            ("profile:TSLA", "company profile"),
            ("financials:AAPL", "income & balance sheet"),
            ("price:TSLA", "quote & technicals"),
            ("movers", "top gainers & losers"),
            ("analysts:AAPL", "ratings & targets"),
            ("valuation:AAPL,MSFT", "valuation comparison"),
        ]),
        *_section("Accounts", [
            ("accounts", "list linked accounts"),
            ("account:add <KEY> <SECRET>", "add Alpaca account"),
            ("account:switch <id|name>", "change active account"),
        ]),
        *_section("Options", [
            ("hours:extended", "4AM-8PM ET"),
            ("intraday_exit:true", "5-min bar exits"),
            ("pdt:false", "disable PDT (>$25k)"),
        ]),
        *_section("General", [
            ("help / guide / status / clear", ""),
        ]),
    )

    return Div(
        H3("AlpaTrade — Command Reference"),
        Div(col1, col2, col3, cls="help-grid"),
    )


# ---------------------------------------------------------------------------
# Nav bar helper
# ---------------------------------------------------------------------------

def _nav(session):
    """Build the top navigation bar."""
    user = session.get("user") if session else None
    links = [
        A("Home", href="/"),
        A("Guide", href="/guide"),
        A("Dashboard", href="https://alpatrade.dev", target="_blank"),
        A("Download", href="/download"),
        A("Screenshots", href="/screenshots"),
    ]
    if user:
        name = user.get("display_name") or user.get("email", "user")
        links.append(A(name, href="/profile", style="color: var(--pico-color); font-weight: 600;"))
        
        from utils.auth import get_user_accounts
        accounts = get_user_accounts(user["user_id"])
        if accounts:
            uss = _get_user_session(session) if session else None
            active_id = uss.cli.account_id if uss else None
            if not active_id and accounts:
                active_id = accounts[0]["account_id"]
                if uss:
                    uss.cli.account_id = active_id
                
            opts = []
            for acc in accounts:
                selected = str(acc["account_id"]) == str(active_id)
                opts.append(Option(acc["account_name"], value=str(acc["account_id"]), selected=selected))
            
            sel = Select(*opts, 
                         name="account_id", 
                         hx_post="/set_account", 
                         hx_swap="none", 
                         style="width: 150px; padding: 0.2rem 0.5rem; margin: 0; font-size: 0.85em; display: inline-block;")
            links.append(sel)

        links.append(A("Logout", href="/logout"))
    else:
        links.append(A("Sign up", href="/register"))
        links.append(A("Login", href="/signin"))
    return Nav(
        A("AlpaTrade", href="/", cls="nav-brand"),
        Div(*links, cls="nav-links"),
        cls="top-nav",
    )


def _query_badge(session):
    """Show remaining free queries for anonymous users."""
    user = session.get("user") if session else None
    if user:
        return ""
    count = session.get("query_count", 0) if session else 0
    remaining = max(0, FREE_QUERY_LIMIT - count)
    return Span(f"{remaining} free queries remaining", cls="query-badge")


def _signin_prompt():
    """Card shown when free query limit is reached."""
    parts = [
        H4("Free query limit reached"),
        P(f"You've used all {FREE_QUERY_LIMIT} free queries."),
        P("Login or create an account for unlimited access."),
        A("Login", href="/signin", style="margin-right: 1rem;"),
        A("Sign up", href="/register"),
    ]
    return Div(*parts, cls="signin-card")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@rt("/")
def get(session):
    return (
        Title("AlpaTrade"),
        Main(
            _nav(session),
            Div(
                _query_badge(session),
                style="text-align: right; margin-bottom: 0.5rem;",
            ),
            Div(_help_html(), id="output"),
            Form(
                Input(type="text", name="command",
                      placeholder="agent:backtest lookback:1m — or ask anything about a ticker",
                      autofocus=True, autocomplete="off"),
                Button("Run", type="submit"),
                Span(" Running...", cls="htmx-indicator",
                     style="color: var(--pico-muted-color); font-size: 0.85em;"),
                id="cmd-form",
                hx_post="/cmd", hx_target="#output", hx_swap="beforeend",
                hx_indicator=".htmx-indicator",
            ),
        ),
    )


@rt("/cmd")
async def post(command: str, session):
    cmd_lower = command.strip().lower()

    if not command.strip():
        return ""

    # Special web-only handling
    if cmd_lower in ("exit", "quit", "q"):
        result_md = "Close the browser tab to end this session."
    elif cmd_lower in ("clear", "cls"):
        return Div(id="output", hx_swap_oob="innerHTML")
    elif cmd_lower in ("help", "h", "?"):
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            _help_html(),
            cls="cmd-entry",
        )
    elif cmd_lower == "guide":
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            P("Opening ", A("User Guide", href="/guide", target="_blank",
              style="color: var(--pico-primary); font-weight: bold;"),
              " — complete reference for all commands."),
            cls="cmd-entry",
        )
    else:
        # Rate-limit check for anonymous users
        user = session.get("user")
        if not user:
            # Only count non-free commands
            first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
            if first_word not in _FREE_COMMANDS:
                count = session.get("query_count", 0)
                if count >= FREE_QUERY_LIMIT:
                    return Div(
                        P(B(f"> {command}"), cls="cmd-echo"),
                        _signin_prompt(),
                        cls="cmd-entry",
                    )
                session["query_count"] = count + 1

        uss = _get_user_session(session)

        # ---- Account management commands (web-specific rendering) ----
        if cmd_lower == "accounts":
            return _web_show_accounts(command, uss)

        if cmd_lower.startswith("account:add"):
            return _web_account_add(command, uss)

        if cmd_lower.startswith("account:switch"):
            return _web_account_switch(command, uss)

        # Check if this is a long-running agent command
        first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
        if first_word in _STREAMING_COMMANDS:
            return _start_streaming_command(command, uss)

        # Free-form chat — route to streaming chat console
        if not _is_structured_command(cmd_lower):
            return _start_chat_stream(command, uss)

        processor = CommandProcessor(uss.cli, user_id=uss.user_id)
        result_md = await processor.process_command(command) or ""

    return Div(
        P(B(f"> {command}"), cls="cmd-echo"),
        Div(result_md, cls="marked"),
        cls="cmd-entry",
    )


# ---------------------------------------------------------------------------
# Streaming log console for long-running commands
# ---------------------------------------------------------------------------


def _start_streaming_command(command: str, uss: UserSessionState):
    """Launch a long-running command as a background task and return log console HTML."""
    cli = uss.cli

    # Cancel any existing running command task
    if cli._cmd_task and not cli._cmd_task.done():
        cli._cmd_task.cancel()

    # Reset state
    cli._log_capture.clear()
    cli._cmd_result = None
    cli._cmd_286_html = None

    # Attach log handler to root logger
    root_logger = logging.getLogger()
    # Remove old capture handler if still attached
    root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, LogCapture)]
    root_logger.addHandler(cli._log_capture)
    if root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    async def _run():
        try:
            processor = CommandProcessor(cli, user_id=uss.user_id)
            result = await processor.process_command(command) or ""
            cli._cmd_result = result
        except Exception as e:
            cli._cmd_result = f"# Error\n\n```\n{e}\n```"
        finally:
            # Remove log handler
            logging.getLogger().handlers = [
                h for h in logging.getLogger().handlers if not isinstance(h, LogCapture)
            ]

    cli._cmd_task = asyncio.create_task(_run())

    return Div(
        P(B(f"> {command}"), cls="cmd-echo"),
        Div(
            Button("Stop", hx_post="/stop_cmd", hx_target="#output", hx_swap="beforeend",
                   cls="copy-btn", style="background:#dc3545;"),
            Pre(Code("Starting...", id="log-output-code"), cls="log-pre"),
            cls="log-console", id="log-console",
            hx_ext="sse", sse_connect="/stream_logs", sse_swap="logMsg",
        ),
        cls="cmd-entry",
    )


# ---------------------------------------------------------------------------
# Web-specific account management helpers
# ---------------------------------------------------------------------------


def _web_show_accounts(command: str, uss):
    """Render the user's accounts as an HTML table."""
    from utils.auth import get_user_accounts
    if not uss or not uss.user_id:
        return Div(P(B(f"> {command}"), cls="cmd-echo"), P("Not logged in."), cls="cmd-entry")

    accounts = get_user_accounts(uss.user_id)
    if not accounts:
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            P("No accounts found. Use ", Code("account:add <API_KEY> <SECRET_KEY>"), " to add one."),
            cls="cmd-entry",
        )

    active_id = uss.cli.account_id
    rows = []
    for i, acc in enumerate(accounts, 1):
        is_current = str(acc["account_id"]) == str(active_id)
        marker = " ◀" if is_current else ""
        rows.append(Tr(
            Td(str(i)),
            Td(B(acc["account_name"] + marker) if is_current else acc["account_name"]),
            Td(Code(acc.get("api_key_hint", "****"))),
            Td("✓"),
        ))

    tbl = Table(
        Thead(Tr(Th("#"), Th("Name"), Th("API Key"), Th("Active"))),
        Tbody(*rows),
        style="width:100%; margin:0.5rem 0;",
    )
    return Div(
        P(B(f"> {command}"), cls="cmd-echo"),
        tbl,
        P(Code("account:switch 1"), " or ", Code("account:switch <name>"), style="color:gray; font-size:0.85em;"),
        cls="cmd-entry",
    )


def _web_account_add(command: str, uss):
    """Add a new Alpaca account from the web terminal."""
    if not uss or not uss.user_id:
        return Div(P(B(f"> {command}"), cls="cmd-echo"), P("Not logged in."), cls="cmd-entry")

    parts = command.split()
    if len(parts) < 3:
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            P("Usage: ", Code("account:add <API_KEY> <SECRET_KEY>")),
            P("Example: ", Code("account:add PKXXXXXXXX ECpXXXXXXXX"), style="color:gray; font-size:0.85em;"),
            cls="cmd-entry",
        )

    api_key = parts[1].strip()
    sec_key = parts[2].strip()

    # Auto-detect account name from Alpaca
    acc_name = f"Account ({api_key[:6]}...)"
    status_msgs = []
    try:
        from utils.alpaca_util import AlpacaAPI
        client = AlpacaAPI(api_key=api_key, secret_key=sec_key, paper=True)
        acct_info = client.get_account()
        if "error" not in acct_info:
            acct_num = acct_info.get("account_number", "")
            acc_name = f"Paper-{acct_num}" if acct_num else acc_name
            status_msgs.append(P(f"✓ Alpaca verified: {acc_name}", style="color:green;"))
        else:
            status_msgs.append(P(f"⚠ Could not verify: {acct_info['error']}", style="color:orange;"))
    except Exception as e:
        status_msgs.append(P(f"⚠ Could not verify: {e}", style="color:orange;"))

    from utils.auth import store_alpaca_keys
    try:
        new_id = store_alpaca_keys(uss.user_id, api_key, sec_key, account_name=acc_name)
        uss.cli.account_id = new_id
        uss.cli._orch = None
        status_msgs.append(P(f"✓ Account '{acc_name}' saved and activated!", style="color:green; font-weight:bold;"))
        status_msgs.append(P(f"ID: {new_id}", style="color:gray; font-size:0.85em;"))
    except Exception as e:
        status_msgs.append(P(f"✗ Failed: {e}", style="color:red;"))

    return Div(P(B(f"> {command}"), cls="cmd-echo"), *status_msgs, cls="cmd-entry")


def _web_account_switch(command: str, uss):
    """Switch account by number, name, or key prefix."""
    from utils.auth import get_user_accounts
    if not uss or not uss.user_id:
        return Div(P(B(f"> {command}"), cls="cmd-echo"), P("Not logged in."), cls="cmd-entry")

    query = command.split(maxsplit=1)[1].strip() if len(command.split(maxsplit=1)) > 1 else ""
    if not query:
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            P("Usage: ", Code("account:switch <number|name|key-prefix>")),
            cls="cmd-entry",
        )

    accounts = get_user_accounts(uss.user_id)
    if not accounts:
        return Div(P(B(f"> {command}"), cls="cmd-echo"), P("No accounts. Use account:add first."), cls="cmd-entry")

    matched = None
    # Try row number
    try:
        idx = int(query) - 1
        if 0 <= idx < len(accounts):
            matched = accounts[idx]
    except ValueError:
        pass
    # Try name
    if not matched:
        q = query.lower()
        for acc in accounts:
            if q in acc["account_name"].lower():
                matched = acc
                break
    # Try API key prefix
    if not matched:
        q = query.upper()
        for acc in accounts:
            if acc.get("api_key_hint", "").upper().startswith(q[:6]):
                matched = acc
                break
    # Try UUID
    if not matched:
        for acc in accounts:
            if acc["account_id"].startswith(query):
                matched = acc
                break

    if matched:
        uss.cli.account_id = matched["account_id"]
        uss.cli._orch = None
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            P(f"✓ Switched to: {matched['account_name']} ({matched['api_key_hint']})", style="color:green; font-weight:bold;"),
            cls="cmd-entry",
        )
    else:
        return Div(
            P(B(f"> {command}"), cls="cmd-echo"),
            P(f"✗ No account matches '{query}'. Type ", Code("accounts"), " to see the list.", style="color:red;"),
            cls="cmd-entry",
        )
@rt("/set_account")
def post(account_id: str, session):
    """Switch active account via HTMX dropdown."""
    uss = _get_user_session(session)
    if uss:
        uss.cli.account_id = account_id
        uss.cli._orch = None  # Force fresh orchestrator on next command
    return ""


@rt("/stream_logs")
def logs_get(session):
    """Return current log lines; HTTP 286 stops HTMX polling when done."""
    uss = _get_user_session(session)
    cli = uss.cli

    lines = cli._log_capture.get_lines()
    log_text = "\n".join(lines) if lines else "Waiting for output..."

    task = cli._cmd_task
    bg_task = cli._bg_task  # paper trade background task

    # Command processor task finished?
    cmd_done = task is None or task.done()
    # Paper trade still running in background?
    bg_running = bg_task is not None and not bg_task.done()

    if cmd_done and not bg_running and cli._cmd_result is not None:
        # Command fully complete — return result and stop polling (HTTP 286)
        chart_html = None
        chart_json = getattr(cli, '_last_chart_json', None)
        if chart_json:
            import json
            chart_data = json.loads(chart_json)
            data_js = json.dumps(chart_data.get("data", []))
            layout_js = json.dumps(chart_data.get("layout", {}))
            chart_html = NotStr(
                f'<div id="backtest-chart" class="backtest-chart"></div>'
                f'<script>Plotly.newPlot("backtest-chart", {data_js}, {layout_js}, '
                f'{{"responsive": true}});</script>'
            )
            cli._last_chart_json = None

        parts = [
            Pre(log_text, cls="log-pre"),
            Hr(),
            Div(cli._cmd_result, cls="marked"),
        ]
        if chart_html:
            parts.append(chart_html)
        result_html = Div(*parts)
        cli._cmd_result = None  # clear for next run
        # Cache the 286 HTML so racing HTMX requests also get 286
        cli._cmd_286_html = to_xml(result_html)
        return Response(
            cli._cmd_286_html,
            status_code=286,
            headers={"Content-Type": "text/html"},
        )

    # Handle HTMX race: if a 286 was just sent but a concurrent poll arrives,
    # replay the cached 286 to prevent overwriting results with plain logs
    if cmd_done and not bg_running and cli._cmd_286_html is not None:
        html = cli._cmd_286_html
        cli._cmd_286_html = None  # clear after one replay
        return Response(html, status_code=286, headers={"Content-Type": "text/html"})

    # Still running — return log lines
    return Pre(log_text, cls="log-pre")


# ---------------------------------------------------------------------------
# Streaming chat console for free-form AI queries
# ---------------------------------------------------------------------------


def _start_chat_stream(command: str, uss: UserSessionState):
    """Launch a chat agent query with streaming trace console."""
    import uuid
    cli = uss.cli

    # Cancel any existing chat task
    if cli._chat_task and not cli._chat_task.done():
        cli._chat_task.cancel()

    # Reset state
    cli._chat_events.clear()
    cli._chat_done = False
    cli._chat_final = ""
    cli._chat_286_html = None

    is_broker = _is_broker_query(command)

    # Ensure thread IDs exist
    if not hasattr(cli, '_broker_thread_id'):
        cli._broker_thread_id = str(uuid.uuid4())
    if not hasattr(cli, '_research_thread_id'):
        cli._research_thread_id = str(uuid.uuid4())

    # Resolve per-user Alpaca keys for broker queries
    alpaca_keys = None
    if is_broker and uss.user_id:
        try:
            from utils.auth import get_alpaca_keys
            alpaca_keys = get_alpaca_keys(uss.user_id)
        except Exception:
            pass

    async def _run():
        try:
            if is_broker:
                from utils.alpaca_agent import async_stream_response
                thread_id = cli._broker_thread_id
            else:
                from utils.research_agent import async_stream_response
                thread_id = cli._research_thread_id

            kwargs = {"alpaca_keys": alpaca_keys} if is_broker and alpaca_keys else {}
            async for event in async_stream_response(command, thread_id, **kwargs):
                cli._chat_events.append(event)
                if event["type"] == "done":
                    cli._chat_final = event["content"]

        except Exception as e:
            cli._chat_events.append({"type": "error", "content": str(e)})
        finally:
            cli._chat_done = True

    cli._chat_task = asyncio.create_task(_run())

    agent_label = "broker" if is_broker else "research"
    return Div(
        P(B(f"> {command}"), cls="cmd-echo"),
        Div(
            Pre(f"Asking {agent_label} agent...", cls="log-pre"),
            id="chat-console", cls="log-console",
            hx_get="/chat-stream", hx_trigger="every 500ms", hx_swap="innerHTML",
        ),
        cls="cmd-entry",
    )


@rt("/chat-stream")
def chat_stream_get(session):
    """Return streaming chat trace; HTTP 286 stops HTMX polling when done."""
    uss = _get_user_session(session)
    cli = uss.cli
    events = list(cli._chat_events)
    lines = []
    for ev in events:
        if ev["type"] == "tool_call":
            lines.append(f">> Calling {ev['tool']}...")
        elif ev["type"] == "tool_result":
            lines.append(f"<< {ev['tool']} returned data")
        elif ev["type"] == "error":
            lines.append(f"!! Error: {ev['content']}")
        # tokens accumulate in final content, not shown in trace

    trace_text = "\n".join(lines) if lines else "Thinking..."

    if cli._chat_done:
        # Build final response with trace + rendered markdown
        parts = []
        if lines:
            parts.append(Pre("\n".join(lines), cls="log-pre"))
            parts.append(Hr())
        parts.append(Div(cli._chat_final, cls="marked"))
        result_html = Div(*parts)
        cli._chat_286_html = to_xml(result_html)
        cli._chat_done = False
        cli._chat_final = ""
        return Response(cli._chat_286_html, status_code=286,
                        headers={"Content-Type": "text/html"})

    # Handle HTMX race (same pattern as /logs)
    if cli._chat_286_html is not None:
        html = cli._chat_286_html
        cli._chat_286_html = None
        return Response(html, status_code=286, headers={"Content-Type": "text/html"})

    return Pre(trace_text, cls="log-pre")


# ---------------------------------------------------------------------------
# Registration & login routes
# ---------------------------------------------------------------------------

_GOOGLE_SVG = """<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
<path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
<path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
<path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/>
<path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
</svg>"""


def _auth_layout(title: str, card_parts: list):
    """Wrap auth card content in the branded layout with logo and footer."""
    return (
        Title(f"{title} — AlpaTrade"),
        Main(
            Div(
                Div(
                    Span("AT", cls="logo-icon",
                         style="background:linear-gradient(135deg,#1976d2,#42a5f5);color:#fff;"
                               "width:56px;height:56px;border-radius:14px;display:inline-flex;"
                               "align-items:center;justify-content:center;font-weight:800;"
                               "font-size:1.4rem;letter-spacing:-0.02em;margin:0 auto;"),
                    Div("AlpaTrade", cls="logo-text"),
                    Div("Algorithmic Trading Platform", cls="logo-tagline"),
                    cls="auth-logo",
                ),
                Div(*card_parts, cls="auth-card"),
                Div(
                    f"© 2024–2026 AlpaTrade. All rights reserved.",
                    cls="auth-footer",
                ),
                cls="auth-wrapper",
            ),
            style="height: auto; padding: 0;",
        ),
    )


def _google_btn(label: str):
    """Return the Google sign-in button with the colored G icon."""
    return A(NotStr(_GOOGLE_SVG), label, href="/login", cls="google-btn")


_EYE_OPEN = '<svg class="eye-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'
_EYE_CLOSED = '<svg class="eye-closed" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'


def _pw_input(name: str = "password", placeholder: str = "Password", **kwargs):
    """Password input with eye toggle button."""
    return Div(
        Input(type="password", name=name, placeholder=placeholder, required=True, **kwargs),
        Button(NotStr(_EYE_OPEN + _EYE_CLOSED), type="button", cls="pw-toggle"),
        cls="pw-wrap",
    )


def _session_login(session, user: Dict):
    """Set session state after successful login."""
    # Only store safe fields — never password_hash or other sensitive data
    display = user.get("display_name") or ""
    # Guard: if display_name somehow contains a hash (starts with $2), fall back to email
    if display.startswith("$2") or not display.strip():
        display = user.get("email", "user").split("@")[0]
    session["user"] = {
        "user_id": str(user["user_id"]),
        "email": user["email"],
        "display_name": display,
    }
    session["query_count"] = 0


@rt("/register")
def register(session, email: str = "", password: str = "", display_name: str = "", error: str = ""):
    # Handle POST submission (form data present)
    if email and password:
        if len(password) < 8:
            return RedirectResponse("/register?error=Password+must+be+at+least+8+characters", status_code=303)
        from utils.auth import create_user
        user = create_user(email=email, password=password, display_name=display_name or None)
        if not user:
            return RedirectResponse("/register?error=Email+already+registered", status_code=303)
        _session_login(session, user)
        return RedirectResponse("/", status_code=303)

    # Show form (GET or empty POST)
    if session.get("user"):
        return RedirectResponse("/")
    parts = [H2("Create Account")]
    if error:
        parts.append(P(error, cls="error-msg"))
    if _oauth_enabled:
        parts.append(_google_btn("Sign up with Google"))
        parts.append(Div("or", cls="divider"))
    parts.append(
        Form(
            Input(type="email", name="email", placeholder="Email", required=True, autofocus=True),
            _pw_input("password", "Password (min 8 characters)", minlength="8"),
            Input(type="text", name="display_name", placeholder="Display name (optional)"),
            Button("Create Account", type="submit"),
            method="post", action="/register",
        )
    )
    parts.append(Div("Already have an account? ", A("Login", href="/signin"), cls="alt-link"))
    return _auth_layout("Register", parts)


@rt("/signin")
def signin(session, email: str = "", password: str = "", error: str = "", msg: str = ""):
    # Handle POST submission (form data present)
    if email and password:
        from utils.auth import authenticate
        user = authenticate(email, password)
        if not user:
            return RedirectResponse("/signin?error=Invalid+email+or+password", status_code=303)
        _session_login(session, user)
        return RedirectResponse("/", status_code=303)

    # Show form (GET or empty POST)
    if session.get("user"):
        return RedirectResponse("/")
    parts = [H2("Login")]
    if msg:
        parts.append(P(msg, cls="success-msg"))
    if error:
        parts.append(P(error, cls="error-msg"))
    if _oauth_enabled:
        parts.append(_google_btn("Login with Google"))
        parts.append(Div("or", cls="divider"))
    parts.append(
        Form(
            Input(type="email", name="email", placeholder="Email", required=True, autofocus=True),
            _pw_input("password", "Password"),
            Button("Login", type="submit"),
            method="post", action="/signin",
        )
    )
    parts.append(Div(A("Forgot password?", href="/forgot"), cls="alt-link"))
    parts.append(Div("Don't have an account? ", A("Sign up", href="/register"), cls="alt-link"))
    return _auth_layout("Login", parts)


@rt("/forgot")
def forgot_password(request, session, email: str = "", error: str = "", msg: str = ""):
    # Handle POST
    if email:
        from utils.auth import create_password_reset_token
        token = create_password_reset_token(email)
        if token:
            from utils.email_util import send_email_to
            # Build absolute reset URL from the incoming request
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("host", request.url.netloc)
            reset_url = f"{scheme}://{host}/reset?token={token}"
            body_html = f"""
            <div style="font-family: -apple-system, sans-serif; max-width: 500px; margin: 0 auto;">
              <h2>Reset Your Password</h2>
              <p>You requested a password reset for your AlpaTrade account.</p>
              <p><a href="{reset_url}"
                    style="display:inline-block; padding:12px 24px; background:#1976d2;
                           color:#fff; text-decoration:none; border-radius:6px;">
                Reset Password
              </a></p>
              <p style="color:#6c757d; font-size:13px;">
                This link expires in 1 hour. If you didn't request this, ignore this email.
              </p>
            </div>
            """
            send_email_to(email, "AlpaTrade — Password Reset", body_html)
        # Always show success to prevent email enumeration
        return RedirectResponse(
            "/forgot?msg=If+that+email+is+registered+you+will+receive+a+reset+link",
            status_code=303,
        )

    # Show form (GET)
    if session.get("user"):
        return RedirectResponse("/")
    parts = [H2("Forgot Password")]
    if msg:
        parts.append(P(msg, cls="success-msg"))
    if error:
        parts.append(P(error, cls="error-msg"))
    parts.append(
        P("Enter your email and we'll send you a reset link.",
          style="text-align:center; color:var(--pico-muted-color); font-size:0.85em; margin-bottom:0.5rem;"),
    )
    parts.append(
        Form(
            Input(type="email", name="email", placeholder="Enter your email", required=True, autofocus=True),
            Button("Send Reset Link", type="submit"),
            method="post", action="/forgot",
        )
    )
    parts.append(Div(A("Back to login", href="/signin"), cls="alt-link"))
    return _auth_layout("Forgot Password", parts)


@rt("/reset")
def reset_password(session, token: str = "", password: str = "", confirm_password: str = "", error: str = ""):
    # Handle POST (new password submitted)
    if token and password:
        if len(password) < 8:
            return RedirectResponse(f"/reset?token={token}&error=Password+must+be+at+least+8+characters", status_code=303)
        if password != confirm_password:
            return RedirectResponse(f"/reset?token={token}&error=Passwords+do+not+match", status_code=303)
        from utils.auth import verify_and_consume_reset_token, update_password
        user = verify_and_consume_reset_token(token)
        if not user:
            return RedirectResponse("/forgot?error=Reset+link+is+invalid+or+expired", status_code=303)
        update_password(user["user_id"], password)
        return RedirectResponse("/signin?msg=Password+reset+successful.+Please+log+in.", status_code=303)

    # Show form (GET)
    if not token:
        return RedirectResponse("/forgot")
    parts = [H2("Set New Password")]
    if error:
        parts.append(P(error, cls="error-msg"))
    parts.append(
        Form(
            Input(type="hidden", name="token", value=token),
            _pw_input("password", "New password (min 8 characters)", minlength="8", autofocus=True),
            _pw_input("confirm_password", "Confirm new password", minlength="8"),
            Button("Reset Password", type="submit"),
            method="post", action="/reset",
        )
    )
    return _auth_layout("Reset Password", parts)


@rt("/profile")
def profile(session, msg: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/signin")

    # Fetch all accounts for this user (includes keys added from CLI)
    accounts = []
    try:
        from utils.auth import get_user_accounts
        accounts = get_user_accounts(user["user_id"])
    except Exception:
        pass

    account_count = len(accounts)
    key_badge = (
        Span(f"{account_count} account{'s' if account_count != 1 else ''}", cls="key-status configured")
        if account_count > 0
        else Span("Not configured", cls="key-status not-configured")
    )

    parts = [
        H2("Profile"),
        Dl(
            Dt("Email"), Dd(user.get("email", "")),
            Dt("Display Name"), Dd(user.get("display_name", "")),
            Dt("Alpaca Accounts"), Dd(key_badge),
            cls="info-grid",
        ),
    ]

    if msg:
        parts.append(P(msg, cls="success-msg"))

    # Show existing accounts table (synced from CLI and web)
    if accounts:
        rows = []
        for i, acct in enumerate(accounts, 1):
            rows.append(Tr(
                Td(str(i)),
                Td(acct.get("account_name", "—")),
                Td(Code(acct.get("api_key_hint", "****"))),
                Td(
                    Form(
                        Input(type="hidden", name="account_id", value=acct["account_id"]),
                        Button("Remove", type="submit", cls="btn-sm btn-danger"),
                        method="post", action="/profile/keys/remove",
                    )
                ),
            ))
        parts.extend([
            H3("Your Alpaca Accounts"),
            P("Accounts added from the web or CLI appear here. Keys are encrypted at rest.",
              style="color: var(--pico-muted-color); font-size: 0.85em;"),
            Table(
                Thead(Tr(Th("#"), Th("Account Name"), Th("API Key"), Th(""))),
                Tbody(*rows),
                cls="accounts-table",
            ),
        ])

    # Add new account form
    parts.extend([
        H3("Add Alpaca Account"),
        Form(
            Input(type="text", name="account_name",
                  placeholder="Account name (optional)", value=""),
            Input(type="password", name="api_key",
                  placeholder="Alpaca Paper API Key", required=True),
            Input(type="password", name="secret_key",
                  placeholder="Alpaca Paper Secret Key", required=True),
            Button("Save Keys", type="submit"),
            method="post", action="/profile/keys", cls="keys-form",
        ),
    ])

    return (
        Title("Profile — AlpaTrade"),
        Main(_nav(session), Div(*parts, cls="profile-page"), style="height: auto;"),
    )


@rt("/profile/keys")
def profile_keys(session, api_key: str = "", secret_key: str = "", account_name: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/signin")
    if not api_key or not secret_key:
        return RedirectResponse("/profile?msg=Both+keys+are+required", status_code=303)

    try:
        from utils.auth import store_alpaca_keys
        name = account_name.strip() or "Default Account"
        store_alpaca_keys(user["user_id"], api_key, secret_key, account_name=name)
        return RedirectResponse("/profile?msg=Alpaca+keys+saved+successfully", status_code=303)
    except Exception as e:
        logger.error(f"Failed to store Alpaca keys: {e}")
        return RedirectResponse("/profile?msg=Error+saving+keys", status_code=303)


@rt("/profile/keys/remove")
def profile_keys_remove(session, account_id: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/signin")
    if not account_id:
        return RedirectResponse("/profile", status_code=303)
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
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
    except Exception as e:
        logger.error(f"Failed to remove account: {e}")
        return RedirectResponse("/profile?msg=Error+removing+account", status_code=303)


# ---------------------------------------------------------------------------
# Google OAuth routes
# ---------------------------------------------------------------------------

if _oauth_enabled:
    @rt("/login")
    async def login_get(request):
        # Build absolute redirect URI from the incoming request
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/auth/callback"
        return await _authlib_oauth.google.authorize_redirect(request, redirect_uri)

    @rt("/auth/callback")
    async def auth_callback(request, session):
        try:
            token = await _authlib_oauth.google.authorize_access_token(request)
        except Exception as e:
            logger.error(f"OAuth token exchange failed: {e}")
            return RedirectResponse("/signin?error=Google+login+failed")

        # authlib parses the id_token automatically via OIDC
        userinfo = token.get("userinfo", {})
        if not userinfo:
            userinfo = await _authlib_oauth.google.userinfo(token=token)

        google_id = userinfo.get("sub", "")
        email = userinfo.get("email", "")
        name = userinfo.get("name", "")

        if not email:
            return RedirectResponse("/signin?error=Google+did+not+provide+email")

        from utils.auth import get_user_by_google_id, get_user_by_email, create_user, link_google_id

        # Try to find by Google ID first
        user = get_user_by_google_id(google_id) if google_id else None

        if not user:
            # Check if email already registered (link Google ID to existing account)
            user = get_user_by_email(email)
            if user and google_id:
                link_google_id(email, google_id)
            elif not user:
                # Create new user
                user = create_user(email=email, google_id=google_id, display_name=name)

        if user:
            _session_login(session, user)
        else:
            return RedirectResponse("/signin?error=Could+not+create+account")

        return RedirectResponse("/")

@rt("/logout")
def logout_get(session):
    session.pop("user", None)
    session["query_count"] = 0
    # Clear per-user session state
    sid = session.get("session_id")
    if sid and sid in _user_sessions:
        _user_sessions[sid].user_id = None
    return RedirectResponse("/")

if not _oauth_enabled:
    # Stub Google login when OAuth is not configured
    @rt("/login")
    def login_get():
        return RedirectResponse("/signin")


# ---------------------------------------------------------------------------
# User Guide page
# ---------------------------------------------------------------------------


def _guide_toc():
    """Table of contents with anchor links."""
    return Div(
        H4("Table of Contents"),
        Ul(
            Li(A("Backtesting", href="#backtest")),
            Ul(
                Li(A("Quick Start", href="#bt-quickstart")),
                Li(A("Parameter Grid", href="#bt-grid")),
                Li(A("Parameters Reference", href="#bt-params")),
                Li(A("Reading Results", href="#bt-results")),
                Li(A("Equity Curve Chart", href="#bt-chart")),
            ),
            Li(A("Paper Trading", href="#paper")),
            Ul(
                Li(A("Starting a Session", href="#pt-start")),
                Li(A("Monitoring & Stopping", href="#pt-monitor")),
                Li(A("Email Reports", href="#pt-email")),
            ),
            Li(A("Full Cycle", href="#full")),
            Li(A("Validation", href="#validate")),
            Li(A("Reconciliation", href="#reconcile")),
            Li(A("Research Commands", href="#research")),
            Ul(
                Li(A("News", href="#r-news")),
                Li(A("Company Profile", href="#r-profile")),
                Li(A("Financials", href="#r-financials")),
                Li(A("Price & Technicals", href="#r-price")),
                Li(A("Market Movers", href="#r-movers")),
                Li(A("Analyst Ratings", href="#r-analysts")),
                Li(A("Valuation Comparison", href="#r-valuation")),
            ),
            Li(A("Query & Reporting", href="#query")),
            Ul(
                Li(A("Trades & Runs", href="#q-trades")),
                Li(A("Performance Reports", href="#q-report")),
                Li(A("Top Strategies", href="#q-top")),
            ),
            Li(A("Strategy Slugs", href="#slugs")),
            Ul(
                Li(A("Format", href="#s-format")),
                Li(A("Buy the Dip", href="#s-btd")),
                Li(A("Momentum", href="#s-mom")),
                Li(A("VIX Fear Index", href="#s-vix")),
                Li(A("Box-Wedge", href="#s-bwg")),
            ),
            Li(A("Options & Flags", href="#options")),
            Ul(
                Li(A("Extended Hours", href="#o-hours")),
                Li(A("Intraday Exits", href="#o-intraday")),
                Li(A("PDT Rule", href="#o-pdt")),
            ),
        ),
        cls="toc",
    )


def _guide_backtest():
    """Backtest section."""
    return (
        H2("Backtesting", id="backtest"),

        H3("Quick Start", id="bt-quickstart"),
        P("Run a parameterized backtest across multiple strategy configurations:"),
        Pre(Code("agent:backtest lookback:1m")),
        P("This runs the Buy the Dip strategy over the last month using the default "
          "7 symbols (AAPL, MSFT, GOOGL, AMZN, NVDA, TSLA, META) with $10,000 starting "
          "capital. The backtester automatically tests multiple parameter combinations and "
          "reports the best one."),

        H3("Parameter Grid", id="bt-grid"),
        P("The backtester doesn't run a single configuration — it builds a ",
          Strong("parameter grid"), " and tests every combination. This is how it finds "
          "the optimal strategy parameters for the given time period."),
        Div(
            P(Strong("Default grid for Buy the Dip:")),
            NotStr("""<table>
<thead><tr><th>Parameter</th><th>Values tested</th><th>Count</th></tr></thead>
<tbody>
<tr><td><code>dip_threshold</code></td><td>3%, 5%, 7%</td><td>3</td></tr>
<tr><td><code>take_profit</code></td><td>1%, 1.5%</td><td>2</td></tr>
<tr><td><code>hold_days</code></td><td>1, 2, 3 days</td><td>3</td></tr>
<tr><td><code>stop_loss</code></td><td>0.5%</td><td>1</td></tr>
<tr><td><code>position_size</code></td><td>10%</td><td>1</td></tr>
</tbody></table>"""),
            P("Total combinations: 3 x 2 x 3 x 1 x 1 = ", Strong("18 variations")),
            cls="param-grid",
        ),
        P("Each variation runs a full backtest — fetching price data, simulating entries "
          "and exits, calculating P&L, fees, and risk metrics. The best configuration is "
          "selected by ", Strong("Sharpe ratio"), " (risk-adjusted return)."),
        Div("The grid uses itertools.product() internally, so adding more values to any "
            "parameter multiplies the total. Keep grids reasonable (under ~100 variations) "
            "to avoid long runtimes.", cls="tip"),

        H3("Parameters Reference", id="bt-params"),
        NotStr("""<table>
<thead><tr><th>Parameter</th><th>Default</th><th>Description</th></tr></thead>
<tbody>
<tr><td><code>lookback:1m</code></td><td>3m</td><td>Data period — <code>1m</code>, <code>3m</code>, <code>6m</code>, <code>1y</code></td></tr>
<tr><td><code>symbols:AAPL,TSLA</code></td><td>7 large caps</td><td>Comma-separated ticker list</td></tr>
<tr><td><code>capital:50000</code></td><td>10000</td><td>Starting capital ($)</td></tr>
<tr><td><code>strategy:buy_the_dip</code></td><td>buy_the_dip</td><td>Strategy name</td></tr>
<tr><td><code>hours:extended</code></td><td>regular</td><td>Include pre/after-market (4AM-8PM ET)</td></tr>
<tr><td><code>intraday_exit:true</code></td><td>false</td><td>Use 5-min bars for precise TP/SL timing</td></tr>
<tr><td><code>pdt:false</code></td><td>auto</td><td>Disable Pattern Day Trader rule (for &gt;$25k accounts)</td></tr>
</tbody></table>"""),
        P(Strong("Examples:")),
        Pre(Code(
            "# 1-month backtest, custom symbols\n"
            "agent:backtest lookback:1m symbols:AAPL,TSLA,NVDA\n\n"
            "# 6-month backtest with extended hours\n"
            "agent:backtest lookback:6m hours:extended\n\n"
            "# Large account, no PDT rule, intraday exits\n"
            "agent:backtest lookback:3m capital:50000 pdt:false intraday_exit:true"
        )),

        H3("Reading Results", id="bt-results"),
        P("After a backtest completes, you'll see a results table:"),
        NotStr("""<table>
<thead><tr><th>Metric</th><th>What it means</th></tr></thead>
<tbody>
<tr><td><strong>Sharpe Ratio</strong></td><td>Risk-adjusted return. Higher is better. &gt;1 is good, &gt;2 is excellent</td></tr>
<tr><td><strong>Total Return</strong></td><td>Percentage gain/loss on initial capital</td></tr>
<tr><td><strong>Annualized Return</strong></td><td>Return projected to a 1-year basis</td></tr>
<tr><td><strong>Total P&amp;L</strong></td><td>Dollar profit or loss</td></tr>
<tr><td><strong>Win Rate</strong></td><td>Percentage of trades that were profitable</td></tr>
<tr><td><strong>Total Trades</strong></td><td>Number of trades executed across all symbols</td></tr>
<tr><td><strong>Max Drawdown</strong></td><td>Largest peak-to-trough decline. Lower is better</td></tr>
</tbody></table>"""),
        P("The ", Strong("Params"), " line shows which parameter combination won: "
          "dip threshold, take profit target, and hold days."),

        H3("Equity Curve Chart", id="bt-chart"),
        P("An interactive Plotly chart renders below the results showing:"),
        Ul(
            Li(Strong("Strategy"), " (blue solid) — your portfolio value over time"),
            Li(Strong("Buy & Hold SPY"), " (orange dashed) — S&P 500 benchmark"),
            Li(Strong("Buy & Hold Portfolio"), " (green dotted) — holding your symbols passively"),
            Li(Strong("Initial Capital"), " (gray dashed) — starting value reference"),
        ),
        P("Hover over the chart to compare values at any date. If the blue line is above "
          "the others, the strategy outperformed passive investing."),
    )


def _guide_paper():
    """Paper trading section."""
    return (
        H2("Paper Trading", id="paper"),

        H3("Starting a Session", id="pt-start"),
        P("Paper trading runs continuously in the background, placing real orders on "
          "Alpaca's paper trading API:"),
        Pre(Code("agent:paper duration:7d")),
        P("This monitors your symbols every 5 minutes for 7 days, executing the Buy the "
          "Dip strategy with real market data — but no real money is at risk."),
        NotStr("""<table>
<thead><tr><th>Parameter</th><th>Default</th><th>Description</th></tr></thead>
<tbody>
<tr><td><code>duration:7d</code></td><td>7d</td><td>How long to run — <code>1h</code>, <code>1d</code>, <code>7d</code>, <code>1m</code></td></tr>
<tr><td><code>symbols:AAPL,MSFT</code></td><td>7 large caps</td><td>Tickers to trade</td></tr>
<tr><td><code>poll:60</code></td><td>300</td><td>Seconds between strategy checks</td></tr>
<tr><td><code>hours:extended</code></td><td>regular</td><td>Trade pre/after-market</td></tr>
<tr><td><code>email:false</code></td><td>true</td><td>Disable daily P&amp;L email reports</td></tr>
<tr><td><code>pdt:false</code></td><td>auto</td><td>Disable PDT rule</td></tr>
</tbody></table>"""),

        H3("Monitoring & Stopping", id="pt-monitor"),
        Pre(Code(
            "agent:status    # check paper trading state\n"
            "agent:stop      # cancel the background session"
        )),
        P("Paper trading logs appear in the console. When the session ends, a summary "
          "with total trades and P&L is shown."),

        H3("Email Reports", id="pt-email"),
        P("When enabled (default), a daily P&L summary is emailed via Postmark. "
          "Requires ", Code("POSTMARK_API_KEY"), ", ", Code("TO_EMAIL"), ", and ",
          Code("FROM_EMAIL"), " in your ", Code(".env"), " file."),
    )


def _guide_full():
    """Full cycle section."""
    return (
        H2("Full Cycle", id="full"),
        P("The full cycle chains all phases automatically:"),
        Pre(Code("agent:full lookback:1m duration:1m")),
        P("Workflow:"),
        Ol(
            Li(Strong("Backtest"), " — find the optimal parameters"),
            Li(Strong("Validate"), " — check backtest trades for anomalies"),
            Li(Strong("Paper Trade"), " — deploy the winning config live (paper)"),
            Li(Strong("Validate"), " — verify paper trades against market data"),
        ),
        P("Each phase passes its results to the next. If validation finds issues, "
          "it attempts up to 10 self-correction iterations before stopping."),
        NotStr("""<table>
<thead><tr><th>Parameter</th><th>Description</th></tr></thead>
<tbody>
<tr><td><code>lookback:3m</code></td><td>Backtest data period</td></tr>
<tr><td><code>duration:1m</code></td><td>Paper trading duration</td></tr>
<tr><td><code>symbols:AAPL,TSLA</code></td><td>Tickers to trade</td></tr>
<tr><td><code>hours:extended</code></td><td>Extended trading hours</td></tr>
</tbody></table>"""),
    )


def _guide_validate():
    """Validation section."""
    return (
        H2("Validation", id="validate"),
        P("Validate backtest or paper trade results against real market data:"),
        Pre(Code(
            "agent:validate run-id:abc12345\n"
            "agent:validate run-id:abc12345 source:paper_trade"
        )),
        P("The validator checks:"),
        Ul(
            Li("Price accuracy — do entry/exit prices match actual market data?"),
            Li("P&L math — is profit/loss calculated correctly?"),
            Li("Market hours — were trades placed during valid trading hours?"),
            Li("Weekend trades — no trades should occur on weekends"),
            Li("TP/SL logic — did take-profit and stop-loss triggers fire correctly?"),
        ),
        P("If anomalies are found, the validator attempts up to ", Strong("10 self-correction "
          "iterations"), " to fix them. After 10 failures, it stops and reports the issues "
          "with suggestions."),
    )


def _guide_reconcile():
    """Reconciliation section."""
    return (
        H2("Reconciliation", id="reconcile"),
        P("Compare your database records against your actual Alpaca account:"),
        Pre(Code(
            "agent:reconcile              # last 7 days\n"
            "agent:reconcile window:14d   # last 14 days"
        )),
        P("Reports:"),
        Ul(
            Li(Strong("Position mismatches"), " — DB says you hold X shares but Alpaca disagrees"),
            Li(Strong("Missing trades"), " — orders in Alpaca not recorded in DB"),
            Li(Strong("Extra trades"), " — DB trades not found in Alpaca"),
            Li(Strong("P&L comparison"), " — DB total P&L vs Alpaca equity/cash"),
        ),
    )


def _guide_research():
    """Research commands section."""
    return (
        H2("Research Commands", id="research"),
        P("Market research commands use the ", Code("command:TICKER"), " syntax. "
          "Data is sourced from XAI Grok and Tavily APIs."),

        H3("News", id="r-news"),
        Pre(Code(
            "news:TSLA                    # company news (default 10 articles)\n"
            "news:TSLA limit:20           # more articles\n"
            "news:TSLA provider:xai       # force XAI Grok provider\n"
            "news:TSLA provider:tavily    # force Tavily search\n"
            "news                         # general market news"
        )),
        P("Returns headlines with source and date. By default, the system tries XAI first "
          "and falls back to Tavily."),

        H3("Company Profile", id="r-profile"),
        Pre(Code("profile:TSLA")),
        P("Company overview: sector, industry, market cap, description, and key stats."),

        H3("Financials", id="r-financials"),
        Pre(Code(
            "financials:AAPL              # annual income & balance sheet\n"
            "financials:AAPL period:quarterly"
        )),
        P("Revenue, net income, EPS, debt, and other fundamental data."),

        H3("Price & Technicals", id="r-price"),
        Pre(Code("price:TSLA")),
        P("Current quote, daily change, volume, 52-week range, and technical indicators."),

        H3("Market Movers", id="r-movers"),
        Pre(Code(
            "movers              # top gainers and losers\n"
            "movers gainers      # only gainers\n"
            "movers losers       # only losers"
        )),
        P("Today's biggest price movers in the US market."),

        H3("Analyst Ratings", id="r-analysts"),
        Pre(Code("analysts:AAPL")),
        P("Consensus rating (buy/hold/sell), price targets, and recent analyst actions."),

        H3("Valuation Comparison", id="r-valuation"),
        Pre(Code(
            "valuation:AAPL              # single stock valuation\n"
            "valuation:AAPL,MSFT,GOOGL   # side-by-side comparison"
        )),
        P("P/E, P/S, P/B, EV/EBITDA, and other valuation multiples. Compare "
          "multiple tickers to spot relative value."),
    )


def _guide_query():
    """Query & reporting section."""
    return (
        H2("Query & Reporting", id="query"),

        H3("Trades & Runs", id="q-trades"),
        Pre(Code(
            "trades                       # recent trades from DB\n"
            "runs                         # recent backtest/paper runs"
        )),
        P("Shows tables from the PostgreSQL database with your trade history "
          "and run summaries."),

        H3("Performance Reports", id="q-report"),
        Pre(Code(
            "agent:report                         # summary of recent runs\n"
            "agent:report run-id:abc12345         # detailed single-run report\n"
            "agent:report type:backtest           # filter by trade type\n"
            "agent:report strategy:btd            # filter by strategy slug prefix"
        )),
        P("The summary view shows a compact table with return, Sharpe ratio, P&L, "
          "and trade count for each run. The detail view shows full metrics for a "
          "specific run."),

        H3("Top Strategies", id="q-top"),
        Pre(Code(
            "agent:top                    # rank all strategy slugs by avg annual return\n"
            "agent:top strategy:btd       # filter by slug prefix"
        )),
        P("Aggregates across all runs to rank strategy configurations by average "
          "annualized return. Shows Sharpe ratio, return, win rate, drawdown, and "
          "how many times each config has been tested."),
    )


def _guide_slugs():
    """Strategy slugs section."""
    return (
        H2("Strategy Slugs", id="slugs"),
        P("Each backtest variation gets a human-readable ", Strong("slug"),
          " that encodes the strategy type, parameters, and lookback period "
          "into a compact identifier. Slugs let you compare configurations at "
          "a glance and filter results with ", Code("agent:top"), " or ",
          Code("agent:report"), "."),

        H3("Format", id="s-format"),
        Pre(Code("{strategy}-{param1}-{param2}-...-{lookback}")),
        P("Units use consistent suffixes: ", Code("d"), " = days, ",
          Code("m"), " = months. Percentages drop the decimal point for "
          "fractional values (0.5% becomes ", Code("05"), ")."),

        H3("Buy the Dip", id="s-btd"),
        P("Prefix: ", Code("btd")),
        Pre(Code("btd-7dp-05sl-1tp-1d-3m")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("btd")), Td("Strategy: buy_the_dip")),
                Tr(Td(Code("{n}dp")), Td("Dip threshold %")),
                Tr(Td(Code("{n}sl")), Td("Stop loss %")),
                Tr(Td(Code("{n}tp")), Td("Take profit %")),
                Tr(Td(Code("{n}d")), Td("Hold (days)")),
                Tr(Td(Code("{period}")), Td("Lookback (e.g. 1m, 3m)")),
            ),
        ),
        P("Example: ", Code("btd-7dp-05sl-1tp-1d-3m"),
          " = 7% dip, 0.5% stop loss, 1% take profit, 1 day hold, 3-month lookback"),

        H3("Momentum", id="s-mom"),
        P("Prefix: ", Code("mom")),
        Pre(Code("mom-20lb-5mt-5d-10tp-5sl-1m")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("mom")), Td("Strategy: momentum")),
                Tr(Td(Code("{n}lb")), Td("Lookback period (days)")),
                Tr(Td(Code("{n}mt")), Td("Momentum threshold %")),
                Tr(Td(Code("{n}d")), Td("Hold (days)")),
                Tr(Td(Code("{n}tp")), Td("Take profit %")),
                Tr(Td(Code("{n}sl")), Td("Stop loss %")),
                Tr(Td(Code("{period}")), Td("Lookback")),
            ),
        ),

        H3("VIX Fear Index", id="s-vix"),
        P("Prefix: ", Code("vix")),
        Pre(Code("vix-20t-on")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("vix")), Td("Strategy: vix")),
                Tr(Td(Code("{n}t")), Td("VIX threshold")),
                Tr(Td(Code("{type}")), Td("Hold type (e.g. on = overnight)")),
            ),
        ),

        H3("Box-Wedge", id="s-bwg"),
        P("Prefix: ", Code("bwg")),
        Pre(Code("bwg-2r-5ct")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("bwg")), Td("Strategy: box_wedge")),
                Tr(Td(Code("{n}r")), Td("Risk %")),
                Tr(Td(Code("{n}ct")), Td("Contraction threshold %")),
            ),
        ),

        Div(
            "The ", Strong("PDT (Pattern Day Trader)"), " rule is enforced by default "
            "for accounts under $25k: max 3 day trades per rolling 5-business-day window. "
            "PDT status does not affect the slug itself — two backtests with identical "
            "parameters but different PDT settings share the same slug. Use ",
            Code("pdt:false"), " to disable for accounts with $25k+ equity.",
            cls="tip",
        ),
    )


def _guide_options():
    """Options & flags section."""
    return (
        H2("Options & Flags", id="options"),
        P("These flags can be appended to backtest, paper trade, and full cycle commands."),

        H3("Extended Hours", id="o-hours"),
        Pre(Code("agent:backtest lookback:1m hours:extended")),
        P("Regular hours: 9:30 AM - 4:00 PM ET. Extended hours: 4:00 AM - 8:00 PM ET "
          "(pre-market + after-hours). Extended hours backtests include more trading "
          "opportunities but may have lower liquidity and wider spreads."),

        H3("Intraday Exits", id="o-intraday"),
        Pre(Code("agent:backtest lookback:1m intraday_exit:true")),
        P("When enabled, the backtester uses ", Strong("5-minute intraday bars"), " to "
          "determine exactly when take-profit or stop-loss would trigger within each "
          "trading day. This is more accurate than daily bars (which only check "
          "open/high/low/close) but takes longer to run."),
        P("Key behavior: determines which of TP/SL is hit first. No same-day re-entry "
          "after exit."),

        H3("PDT Rule", id="o-pdt"),
        Pre(Code("agent:backtest lookback:1m pdt:false")),
        P("The ", Strong("Pattern Day Trader (PDT)"), " rule is a FINRA regulation: "
          "accounts under $25,000 are limited to 3 day trades per rolling 5-business-day "
          "window. AlpaTrade enforces this by default."),
        P("Set ", Code("pdt:false"), " if your account has $25k+ equity. This removes "
          "the day-trade limit and allows the strategy to trade more aggressively."),
    )


@rt("/guide")
def guide_get(session):
    return (
        Title("User Guide — AlpaTrade"),
        Main(
            _nav(session),
            Div(
                H1("User Guide"),
                P("Complete reference for all AlpaTrade commands. "
                  "Type any command in the terminal on the ", A("home page", href="/"), ".",
                  style="color: var(--pico-muted-color);"),
                _guide_toc(),
                *_guide_backtest(),
                *_guide_paper(),
                *_guide_full(),
                *_guide_validate(),
                *_guide_reconcile(),
                *_guide_research(),
                *_guide_query(),
                *_guide_slugs(),
                *_guide_options(),
                Hr(),
                P("Need quick help? Type ", Code("help"), " in the terminal for a "
                  "compact command reference.",
                  style="color: var(--pico-muted-color); margin-bottom: 2rem;"),
                cls="guide",
            ),
            style="height: auto;",
        ),
    )


# ---------------------------------------------------------------------------
# Download page
# ---------------------------------------------------------------------------

@rt("/download")
def download_get(session):
    uv_cmd = "uv tool install alpatrade"
    curl_cmd = "curl -fsSL https://alpatrade.chat/install.sh | bash"
    return (
        Title("Download — AlpaTrade"),
        Main(
            _nav(session),
            Div(
                H2("Install AlpaTrade"),
                H4("uv (recommended)"),
                P("Install with uv (requires Python 3.11+):", style="color: var(--pico-muted-color);"),
                Div(
                    Pre(Code(uv_cmd), id="uv-cmd"),
                    Button("Copy", cls="copy-btn", onclick="navigator.clipboard.writeText(document.getElementById('uv-cmd').textContent)"),
                    style="position: relative;",
                ),
                P("After install, create a ", Code(".env"), " file with your API keys, then run:",
                  style="color: var(--pico-muted-color); margin-top: 0.5rem;"),
                Pre(Code("alpatrade")),
                Hr(),
                H4("One-line install (alternative)"),
                P("Installs uv automatically if needed:", style="color: var(--pico-muted-color);"),
                Div(
                    Pre(Code(curl_cmd), id="curl-cmd"),
                    Button("Copy", cls="copy-btn", onclick="navigator.clipboard.writeText(document.getElementById('curl-cmd').textContent)"),
                    style="position: relative;",
                ),
                Hr(),
                H4("From source"),
                Div("""
```bash
git clone https://github.com/predictivelabsai/alpatrade.git ~/.alpatrade
cd ~/.alpatrade
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # edit with your API keys
alpatrade
```
""", cls="marked"),
                Hr(),
                H4("Requirements"),
                Ul(
                    Li("Python 3.11+"),
                    Li("PostgreSQL (for trade history)"),
                    Li("Alpaca paper trading account"),
                    Li("Massive (Polygon) API key for market data"),
                ),
                cls="dl-page",
            ),
        ),
    )


@rt("/install.sh")
def install_script_get():
    script_path = Path(__file__).parent / "install.sh"
    if script_path.exists():
        content = script_path.read_text()
    else:
        content = "#!/bin/bash\necho 'install.sh not found on server'\nexit 1\n"
    return Response(content, media_type="text/plain",
                    headers={"Content-Disposition": "attachment; filename=install.sh"})


# ---------------------------------------------------------------------------
# Screenshots page
# ---------------------------------------------------------------------------

# Screenshots: (filename, caption)
_SCREENSHOTS = [
    ("help.png", "Command reference — default landing view"),
    ("news.png", "News command — company headlines"),
    ("trades.png", "Trades table — executed trades from DB"),
    ("backtest.png", "Backtest results — strategy performance"),
    ("backtest-streaming.png", "Live log console — real-time backtest streaming"),
]


@rt("/screenshots")
def screenshots_get(session):
    static_dir = Path(__file__).parent / "static"
    figures = []
    for fname, caption in _SCREENSHOTS:
        if (static_dir / fname).exists():
            figures.append(
                Figure(
                    Img(src=f"/static/{fname}", alt=caption, loading="lazy"),
                    Figcaption(caption),
                )
            )
    if not figures:
        figures.append(P("No screenshots available yet.", style="color: var(--pico-muted-color);"))
    return (
        Title("Screenshots — AlpaTrade"),
        Main(
            _nav(session),
            H2("Screenshots"),
            Div(*figures, cls="screenshot-grid") if len(figures) > 1 or (figures and figures[0].tag == "figure") else Div(*figures),
        ),
    )


serve(port=5002)

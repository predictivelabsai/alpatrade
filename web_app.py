"""FastHTML web shell for AlpaTrade — browser-based CLI."""
import asyncio
import collections
import logging
import os
import sys
import threading
from pathlib import Path

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

# Singleton state container (persists across requests)
cli = StrategyCLI()
cli._log_capture = LogCapture()
cli._cmd_task = None      # asyncio.Task for current long-running command
cli._cmd_result = None    # markdown result when command completes
cli._last_chart_json = None  # Plotly JSON for equity curve chart
cli._cmd_286_html = None  # cached 286 response to handle HTMX race condition

# Commands that trigger background streaming
_STREAMING_COMMANDS = {"agent:backtest", "agent:paper", "agent:full", "agent:validate", "agent:reconcile"}

# ---------------------------------------------------------------------------
# Google OAuth setup (optional — gracefully skip if no creds)
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
_oauth_enabled = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

if _oauth_enabled:
    from fasthtml.oauth import GoogleAppClient, redir_url

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
// Auto-scroll log console when new content arrives
document.addEventListener('htmx:afterSwap', function(evt) {
    var lc = document.getElementById('log-console');
    if (lc) lc.scrollTop = lc.scrollHeight;
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
        A("Guide", href="/guide"),
        A("Dashboard", href="https://alpatrade.dev", target="_blank"),
        A("Download", href="/download"),
        A("Screenshots", href="/screenshots"),
    ]
    if user:
        links.append(Span(user.get("email", "user"), style="color: var(--pico-color);"))
        links.append(A("Logout", href="/logout"))
    elif _oauth_enabled:
        links.append(A("Sign in", href="/login"))
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
    ]
    if _oauth_enabled:
        parts.append(P("Sign in with Google for unlimited access."))
        parts.append(A("Sign in with Google", href="/login"))
    else:
        parts.append(P("Authentication is not configured on this instance."))
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
                      placeholder="Type a command...",
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

        # Check if this is a long-running agent command
        first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
        if first_word in _STREAMING_COMMANDS:
            return _start_streaming_command(command)

        processor = CommandProcessor(cli)
        result_md = await processor.process_command(command) or ""

    return Div(
        P(B(f"> {command}"), cls="cmd-echo"),
        Div(result_md, cls="marked"),
        cls="cmd-entry",
    )


# ---------------------------------------------------------------------------
# Streaming log console for long-running commands
# ---------------------------------------------------------------------------


def _start_streaming_command(command: str):
    """Launch a long-running command as a background task and return log console HTML."""
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
            processor = CommandProcessor(cli)
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
            Pre("Starting...", cls="log-pre"),
            id="log-console", cls="log-console",
            hx_get="/logs", hx_trigger="every 1s", hx_swap="innerHTML",
        ),
        cls="cmd-entry",
    )


@rt("/logs")
def logs_get():
    """Return current log lines; HTTP 286 stops HTMX polling when done."""
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
# Google OAuth routes
# ---------------------------------------------------------------------------

if _oauth_enabled:
    @rt("/login")
    def login_get(request):
        client = GoogleAppClient(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
        redirect_uri = redir_url(request, "/auth/callback")
        login_url = client.login_link(redirect_uri)
        return RedirectResponse(login_url)

    @rt("/auth/callback")
    async def auth_callback(request, session, code: str = "", error: str = ""):
        if error or not code:
            return RedirectResponse("/")
        # Create a fresh client per request (thread safety — retr_info stores token on instance)
        client = GoogleAppClient(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
        redirect_uri = redir_url(request, "/auth/callback")
        info = await client.retr_info_async(code, redirect_uri)
        session["user"] = {"email": info.get("email", ""), "name": info.get("name", "")}
        session["query_count"] = 0
        return RedirectResponse("/")

    @rt("/logout")
    def logout_get(session):
        session.pop("user", None)
        session["query_count"] = 0
        return RedirectResponse("/")
else:
    # Stub routes when OAuth is not configured
    @rt("/login")
    def login_get():
        return RedirectResponse("/")

    @rt("/logout")
    def logout_get(session):
        session.pop("user", None)
        session["query_count"] = 0
        return RedirectResponse("/")


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
    pip_cmd = "pip install alpatrade"
    curl_cmd = "curl -fsSL https://alpatrade.dev/install.sh | bash"
    return (
        Title("Download — AlpaTrade"),
        Main(
            _nav(session),
            Div(
                H2("Install AlpaTrade"),
                H4("pip (recommended)"),
                P("Install from PyPI (requires Python 3.11+):", style="color: var(--pico-muted-color);"),
                Div(
                    Pre(Code(pip_cmd), id="pip-cmd"),
                    Button("Copy", cls="copy-btn", onclick="navigator.clipboard.writeText(document.getElementById('pip-cmd').textContent)"),
                    style="position: relative;",
                ),
                P("After install, create a ", Code(".env"), " file with your API keys, then run:",
                  style="color: var(--pico-muted-color); margin-top: 0.5rem;"),
                Pre(Code("alpatrade")),
                Hr(),
                H4("One-line install (alternative)"),
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

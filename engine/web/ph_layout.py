"""PEHero-skinned shared shell for the merged AlpaTrade app.

Every feature module renders its pages through :func:`page`, so the parchment /
forest house style (``static/app.css``), the left collapsible command menu, the
center chat and the right NEWS pane stay identical across verticals.

Public surface (imported by feature modules):

* ``head(title)``  — the ``<head>`` fragment (title, meta, app.css, marked +
  plotly + htmx + voice.js).
* ``page(active, *content, user=None, title='AlpaTrade', right_news=True)`` —
  full app shell: brand + left command menu, the ``*content`` center column
  (usually :func:`chat_center`), and the right NEWS pane.
* ``chat_center()`` — the center chat: header (with voice mic button), messages,
  composer, and the suggestion cards rendered BELOW the input row.
* ``auth_shell(*content, title)`` — centered card shell for login / register.

Design notes
------------
The palette, class names and markup mirror ``static/app.css`` (ported verbatim
from PEHero, rebranded to AlpaTrade). Per the house style the brand lives in the
left-pane header and the user menu / login in the left-pane footer; the news
pane is news-only (no "Trace" tab); suggestion cards sit under the composer.
Clicking any command-menu item calls ``fillChat(...)`` to load it into the
composer.
"""
from __future__ import annotations

from typing import Optional

from fasthtml.common import (
    A, Button, Details, Div, Form, H3, Hr, Input, Link, Meta, NotStr, P,
    Script, Style, Summary, Span, Textarea, Title,
)

from engine.web.ph_commands import (
    AGENT_SHORTCUTS,
    ALPHA_RESEARCH_SHORTCUTS,
    MAIN_NAV,
)

# --- CDN assets -------------------------------------------------------------
_MARKED_CDN = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
_HTMX_CDN = "https://cdn.jsdelivr.net/npm/htmx.org@2.0.7/dist/htmx.min.js"

# Brand mark — green tile with the nested-diamond motif (matches the app icon + favicon).
TILE_MARK = (
    '<svg viewBox="0 0 32 32" class="tile-mark" aria-hidden="true">'
    '<rect width="32" height="32" rx="7" fill="#1F5D43"/>'
    '<polygon points="16,5.5 26.5,16 16,26.5 5.5,16" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
    '<polygon points="16,9.5 22.5,16 16,22.5 9.5,16" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="1.3"/>'
    '<polygon points="16,12.6 19.4,16 16,19.4 12.6,16" fill="#fff"/></svg>'
)

# Small inline mic glyph for the voice button.
_MIC_SVG = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 '
    '3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19"'
    ' x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>'
)

# --- client helpers (fillChat / newChat / composer + pane toggles) ----------
PH_JS = """
function fillChat(t){var i=document.getElementById('chat-input');
  if(i){i.value=t;i.focus();autoResize(i);return;}
  sessionStorage.setItem('alpatrade.pendingPrompt',t);window.location.href='/app';}
function autoResize(el){if(!el)return;el.style.height='auto';
  el.style.height=Math.min(el.scrollHeight,192)+'px';}
function newChat(){setNewsPane(true);var m=document.getElementById('messages');if(m)m.innerHTML='';
  var w=document.getElementById('welcome-hero');if(w)w.style.display='';
  var i=document.getElementById('chat-input');if(i){i.value='';autoResize(i);i.focus();return;}
  window.location.href='/app';}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();
  var f=document.getElementById('chat-form');
  if(typeof window.sendMessage==='function'){window.sendMessage(e);}
  else if(f&&f.requestSubmit){f.requestSubmit();}}}
function setNewsPane(open){var p=document.getElementById('right-pane');
  var a=document.getElementById('app');var b=document.getElementById('news-btn');
  if(!p)return;if(open===undefined)open=!p.classList.contains('open');
  p.classList.toggle('open',open);if(a)a.classList.toggle('pane-closed',!open);
  if(b){b.classList.toggle('active',open);b.setAttribute('aria-expanded',String(open));}}
function toggleNewsPane(){setNewsPane();}
function toggleLeftPane(){var p=document.getElementById('left-pane');
  var o=document.getElementById('left-overlay');
  if(p)p.classList.toggle('open');if(o)o.classList.toggle('visible');}
window.fillChat=fillChat;window.newChat=newChat;window.autoResize=autoResize;
window.handleKey=handleKey;window.toggleNewsPane=toggleNewsPane;window.setNewsPane=setNewsPane;
window.toggleLeftPane=toggleLeftPane;
document.addEventListener('DOMContentLoaded',function(){
  var p=document.getElementById('right-pane');if(p)setNewsPane(p.classList.contains('open'));
  var t=sessionStorage.getItem('alpatrade.pendingPrompt');
  if(t&&document.getElementById('chat-input')){
    sessionStorage.removeItem('alpatrade.pendingPrompt');fillChat(t);
  }
});
"""


# ---------------------------------------------------------------------------
# <head>
# ---------------------------------------------------------------------------
def head(title: str = "AlpaTrade"):
    """The shared ``<head>`` fragment for every app page."""
    return (
        Title(title),
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(name="description", content="AlpaTrade — multi-asset trading, backtesting & paper-trading"),
        Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Meta(name="theme-color", content="#1F5D43"),
        Style("html,body{margin:0}"),
        Link(rel="stylesheet", href="/static/app.css"),
        Script(src=_HTMX_CDN),
        Script(src=_MARKED_CDN),
        Script(src=_PLOTLY_CDN),
        Script(PH_JS),
        Script(src="/static/voice.js", defer=True),
    )


# ---------------------------------------------------------------------------
# Left pane — brand · new chat · sessions · command menu · user/login
# ---------------------------------------------------------------------------
def _brand():
    return A(
        Span(NotStr(TILE_MARK), cls="brand-mark"),
        Span("AlpaTrade", cls="brand-name"),
        Span("beta", cls="brand-badge"),
        href="/", cls="brand-link",
    )


def _menu_group(label: str, items, active: Optional[str]):
    """One collapsible command group (pehero cat-toggle / agent-item markup)."""
    is_open = any(cmd == active for cmd, _ in items)
    rows = []
    for cmd, desc in items:
        cls = "agent-item" + (" active" if cmd == active else "")
        rows.append(Button(
            Span("›", cls="aitem-icon"),
            Span(cmd, cls="aitem-name"),
            Span(desc, cls="aitem-prefix"),
            cls=cls, type="button", title=desc,
            onclick=f"fillChat({cmd!r})",
        ))
    return Details(
        Summary(
            Span("▸", cls="cat-icon"),
            Span(label, cls="cat-name"),
            Span(str(len(items)), cls="cat-count"),
            Span("›", cls="cat-arrow"),
            cls="cat-toggle",
        ),
        Div(*rows, cls="agent-list"),
        cls="agent-group",
        **({"open": True} if is_open else {}),
    )


def _nav_section(label: str, *children):
    """A compact top-level sidebar section, collapsed on every page load."""
    return Details(
        Summary(
            Span(label, cls="nav-section-name"),
            Span(">", cls="nav-section-expand", aria_hidden="true"),
            Span("<", cls="nav-section-collapse", aria_hidden="true"),
            cls="nav-section-toggle",
        ),
        Div(*children, cls="nav-section-body"),
        cls="nav-section",
    )


# Extra tool pages, appended by their feature modules as they're built.
# Each entry: (label, href, active-key). EXPLORE = visual/map tools (IPO Map, Hedge
# Funds, Market Intel); TOOLS = actionable tools (SEC Filings, Press Releases).
EXPLORE_PAGES: list = []
TOOLS_PAGES: list = []
PUBLIC_PAGES: list = []
RESEARCH_PAGES: list = []
MONITORING_PAGES: list = []


def _EXPLORE_EXTRA(active):
    return [A(lbl, href=href, cls="page-link" + (" active" if active == key else ""))
            for lbl, href, key in EXPLORE_PAGES]


def _TOOLS_EXTRA(active):
    return [A(lbl, href=href, cls="page-link" + (" active" if active == key else ""))
            for lbl, href, key in TOOLS_PAGES]


def _PUBLIC_EXTRA(active):
    return [A(lbl, href=href, cls="page-link" + (" active" if active == key else ""))
            for lbl, href, key in PUBLIC_PAGES]


def _RESEARCH_EXTRA(active):
    return [A(lbl, href=href, cls="page-link" + (" active" if active == key else ""))
            for lbl, href, key in RESEARCH_PAGES]


def _MONITORING_EXTRA(active):
    return [A(lbl, href=href, cls="page-link" + (" active" if active == key else ""))
            for lbl, href, key in MONITORING_PAGES]


def _left_pane(active: Optional[str], user: Optional[dict]):
    if user:
        footer_inner = Div(
            Span("◇", cls="user-mark"),
            Span(user.get("email", "account"), cls="user-email"),
            A("Profile", href="/profile", cls="profile-link"),
            A("Sign out", href="/logout", cls="sign-out-btn"),
            cls="signed-in-bar",
        )
    else:
        footer_inner = A("Sign in", href="/login", cls="sign-in-btn")

    return Div(
        Div(_brand(), cls="left-header"),
        Div(
            A("＋ New chat", cls="new-chat-btn", href="#",
              onclick="newChat();return false;"),
            _nav_section(
                "Explore",
                Div(
                    A("📊 Dashboard", href="/dashboard", cls="page-link" + (" active" if active == "dashboard" else "")),
                    A("🗺 Market Map", href="/map", cls="page-link" + (" active" if active == "map" else "")),
                    A("📈 Charts", href="/charts", cls="page-link" + (" active" if active == "charts" else "")),
                    *_EXPLORE_EXTRA(active),
                    cls="page-links",
                ),
            ),
            _nav_section(
                "Chats",
                Div(Div("No chats yet.", cls="sessions-empty"),
                    cls="session-list", id="session-list"),
            ),
            _nav_section(
                "Agents",
                Div(*[_menu_group(lbl, items, active) for lbl, items in AGENT_SHORTCUTS],
                    cls="agent-browser"),
            ),
            _nav_section(
                "Alpha Research",
                Div(*[_menu_group(lbl, items, active)
                      for lbl, items in ALPHA_RESEARCH_SHORTCUTS],
                    cls="agent-browser"),
            ),
            _nav_section(
                "Monitoring",
                Div(*_MONITORING_EXTRA(active), cls="page-links"),
            ),
            _nav_section(
                "Tools",
                Div(
                    *_TOOLS_EXTRA(active),
                    cls="page-links",
                ),
                Div(*[_menu_group(lbl, items, active) for lbl, items in MAIN_NAV],
                    cls="agent-browser"),
            ),
            _nav_section(
                "Public Markets",
                Div(*_PUBLIC_EXTRA(active), cls="page-links"),
            ),
            _nav_section(
                "Research",
                Div(*_RESEARCH_EXTRA(active), cls="page-links"),
            ),
            _nav_section(
                "Admin",
                Div(
                    A("⚙ Settings", href="/settings", cls="page-link" + (" active" if active == "settings" else "")),
                    A("❓ Help & shortcuts", href="/guide", cls="page-link" + (" active" if active == "guide" else "")),
                    cls="page-links",
                ),
            ),
            cls="left-body",
        ),
        Div(footer_inner, cls="left-footer"),
        cls="left-pane", id="left-pane",
    )


# ---------------------------------------------------------------------------
# Center — the chat (header · messages · composer · suggestion cards below)
# ---------------------------------------------------------------------------
# Natural-language prompts — the router figures out the command/tool to run.
_SUGGESTION_CARDS = [
    "Show me the premarket movers",
    "Show me my positions",
    "Buy 1 share of TSLA at market",
    "Show me a market map",
    "Compare AAPL vs MSFT vs NVDA",
    "Backtest buy-the-dip on AAPL over the last month",
    "What's the latest news on TSLA?",
]


def _welcome_hero():
    chips = [
        Button(Span("◆", cls="sugg-icon"), Span(c),
               cls="suggestion-chip", type="button", onclick=f"fillChat({c!r})")
        for c in ("Show me my positions", "What's the latest on TSLA?",
                  "Backtest buy-the-dip on AAPL")
    ]
    return Div(
        Span("◆", cls="hero-mark"),
        Div("How can I help you trade?", cls="welcome-title"),
        P("Ask in plain English — I'll route it. Try "
          "“show me my positions” or “backtest buy-the-dip on AAPL”. "
          "Power users can still type commands like trades:paper.",
          cls="welcome-sub"),
        Div(*chips, cls="suggestions"),
        id="welcome-hero", cls="welcome-hero",
    )


def _sample_cards():
    """Suggestion cards rendered BELOW the composer (Gemini-style)."""
    cards = [
        Button(Span(c, cls="sample-card-text"), cls="sample-card",
               type="button", title=c, onclick=f"fillChat({c!r})")
        for c in _SUGGESTION_CARDS
    ]
    return Div(
        Span("Try a prompt", cls="sample-cards-label"),
        Div(*cards, cls="sample-cards-row"),
        id="sample-cards", cls="sample-cards",
    )


def chat_center():
    """The center chat column: header (with voice mic), messages, composer,
    and the suggestion cards below the textarea / send row."""
    header = Div(
        Div(
            Button("☰", cls="mobile-menu-btn", type="button", onclick="toggleLeftPane()"),
            Span("AlpaTrade", cls="chat-header-title"),
            Span("·", cls="chat-header-dot"),
            Span("auto-routed", cls="chat-header-agent", id="current-agent-label"),
            cls="chat-header-left",
        ),
        Div(
            Button(NotStr('&lt; <span>News</span>'), id="news-btn", cls="news-toggle-btn",
                   type="button", title="Maximize News", aria_expanded="false",
                   aria_controls="right-pane", onclick="toggleNewsPane()"),
            cls="chat-header-right",
        ),
        cls="chat-header",
    )
    composer = Form(
        Textarea(
            id="chat-input", name="msg", cls="chat-textarea", rows="2",
            placeholder="Ask anything — or type a command like  trades:paper · agent:backtest lookback:1m",
            onkeydown="handleKey(event)", oninput="autoResize(this)",
        ),
        Button(NotStr(_MIC_SVG), id="voice-btn", cls="voice-btn", type="button",
               title="Voice — ask for your positions", onclick="toggleVoice()"),
        Button("Send", type="submit", cls="chat-send", id="send-btn"),
        id="chat-form", cls="chat-form",
        onsubmit="if(window.sendMessage)return sendMessage(event);return false;",
    )
    return Div(
        header,
        Div(id="messages", cls="messages"),
        _welcome_hero(),
        composer,
        _sample_cards(),
        cls="center-pane",
    )


# ---------------------------------------------------------------------------
# Right pane — NEWS only (loads /news via htmx; no Trace tab)
# ---------------------------------------------------------------------------
def _news_pane(open_by_default: bool = False):
    return Div(
        Div(
            Div(H3("News", cls="right-title"),
                Span("market headlines", cls="right-subtitle"),
                cls="right-header-left"),
            Button(">", cls="right-close", type="button", title="Minimize News",
                   aria_label="Minimize News", onclick="setNewsPane(false)"),
            cls="right-header",
        ),
        Div(
            Div(Div("◌", cls="news-loading-icon"),
                P("Loading news…", cls="news-loading-text"),
                id="news-loading", cls="news-loading htmx-indicator"),
            Div(id="news-body", cls="news-body",
                hx_get="/news", hx_trigger="load, every 1800s",
                hx_swap="innerHTML", hx_indicator="#news-loading"),
            cls="right-body",
        ),
        id="right-pane", cls="right-pane" + (" open" if open_by_default else ""),
    )


# ---------------------------------------------------------------------------
# page / auth_shell
# ---------------------------------------------------------------------------
def page(active, *content, user: Optional[dict] = None,
         title: str = "AlpaTrade", right_news: bool = True,
         right_news_open: bool = False):
    """Full app shell. ``*content`` is the center column (usually
    :func:`chat_center`); ``active`` highlights the matching command-menu item."""
    # Keep one constrained grid item between the sidebar and fixed overlays.
    # The document itself intentionally does not scroll, so every feature page
    # needs this shared viewport instead of relying on route-specific overflow.
    center = Div(*content, cls="page-pane")
    children = [_left_pane(active, user), center]
    if right_news:
        children.append(_news_pane(right_news_open))
    children.append(Div(id="left-overlay", cls="left-overlay", onclick="toggleLeftPane()"))
    return (
        *head(title),
        Div(*children, cls="app" + ("" if right_news and right_news_open else " pane-closed"),
            id="app"),
    )


def auth_shell(*content, title: str = "AlpaTrade"):
    """Centered parchment card shell for login / register / profile pages."""
    return (
        *head(title),
        Div(
            Div(
                Div(Span(NotStr(TILE_MARK), cls="brand-mark"), Span("AlpaTrade"), cls="auth-brand"),
                *content,
                cls="auth-card",
            ),
            cls="auth-page",
        ),
    )

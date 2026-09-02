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

import os
from typing import Optional

from fasthtml.common import (
    A, Button, Details, Div, Form, H3, Hr, Input, Link, Meta, NotStr, P,
    Script, Style, Summary, Span, Textarea, Title,
)

from engine.web.ph_commands import (
    AGENT_SHORTCUTS,
    ALPHA_RESEARCH_SHORTCUTS,
    HERMES_SHORTCUTS,
)

# --- CDN assets -------------------------------------------------------------
# Cache-bust app.css by its mtime so style changes reach browsers without a
# manual hard refresh (static files are otherwise long-cached).
try:
    _CSS_VER = str(int(os.path.getmtime(
        os.path.join(os.path.dirname(__file__), "..", "..", "static", "app.css"))))
except OSError:
    _CSS_VER = "1"

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

# --- uniform nav icon set (line icons, replace per-OS emoji) ----------------
# Feather/Lucide-style single-stroke glyphs. Keyed by page active-key and by
# section (``sec-*``); every glyph inherits ``currentColor`` so it tracks the
# link's muted/active colour. See :func:`_icon` / :func:`_page_link`.
_ICONS = {
    "_default": '<circle cx="12" cy="12" r="3.2"/>',
    # Explore
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    "map": '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
    "charts": '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "hedgefunds": '<line x1="3" y1="22" x2="21" y2="22"/><line x1="6" y1="18" x2="6" y2="11"/><line x1="10" y1="18" x2="10" y2="11"/><line x1="14" y1="18" x2="14" y2="11"/><line x1="18" y1="18" x2="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    "marketintel": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "premarket": '<path d="M17 18a5 5 0 0 0-10 0"/><line x1="12" y1="2" x2="12" y2="9"/><line x1="4.22" y1="10.22" x2="5.64" y2="11.64"/><line x1="1" y1="18" x2="3" y2="18"/><line x1="21" y1="18" x2="23" y2="18"/><line x1="18.36" y1="11.64" x2="19.78" y2="10.22"/><line x1="23" y1="22" x2="1" y2="22"/><polyline points="8 6 12 2 16 6"/>',
    # Trade
    "backtests": '<rect x="4" y="13" width="4" height="7" rx="1"/><rect x="10" y="9" width="4" height="11" rx="1"/><rect x="16" y="4" width="4" height="16" rx="1"/>',
    "paper": '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="12" cy="12" r="3"/>',
    "news": '<rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="8" x2="17" y2="8"/><line x1="7" y1="12" x2="17" y2="12"/><line x1="7" y1="16" x2="13" y2="16"/>',
    "advisor": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
    # Monitoring
    "agent-pipeline": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    # Tools
    "filings": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    "press": '<rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="8" x2="17" y2="8"/><line x1="7" y1="12" x2="17" y2="12"/><line x1="7" y1="16" x2="13" y2="16"/>',
    "spacs": '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/>',
    # Public Markets
    "indexoptions": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "ipomap": '<circle cx="12" cy="12" r="9"/><polygon points="16 8 13.5 13.5 8 16 10.5 10.5 16 8"/>',
    "ipopipeline": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="8" y1="11" x2="16" y2="11"/><line x1="8" y1="15" x2="14" y2="15"/>',
    # Research pages
    "research-premarket": '<path d="M17 18a5 5 0 0 0-10 0"/><line x1="12" y1="2" x2="12" y2="9"/><line x1="4.22" y1="10.22" x2="5.64" y2="11.64"/><line x1="1" y1="18" x2="3" y2="18"/><line x1="21" y1="18" x2="23" y2="18"/><line x1="18.36" y1="11.64" x2="19.78" y2="10.22"/><line x1="23" y1="22" x2="1" y2="22"/><polyline points="8 6 12 2 16 6"/>',
    "research-models": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "research-news": '<rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="8" x2="17" y2="8"/><line x1="7" y1="12" x2="17" y2="12"/><line x1="7" y1="16" x2="13" y2="16"/>',
    "research-timing": '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 16 14"/>',
    "research-history": '<polyline points="3 4 3 10 9 10"/><path d="M3.5 15a9 9 0 1 0 2.2-9.3L3 10"/><polyline points="12 8 12 12 15 14"/>',
    # Admin
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "guide": '<circle cx="12" cy="12" r="9"/><path d="M9.2 9a3 3 0 0 1 5.6 1c0 2-3 2.5-3 4"/><line x1="12" y1="17" x2="12" y2="17.01"/>',
    # Section headers
    "sec-explore": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    "sec-chats": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    "sec-agents": '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><line x1="9" y1="13" x2="9" y2="15"/><line x1="15" y1="13" x2="15" y2="15"/>',
    "sec-monitoring": '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><polyline points="6 11 9 8 11 10 15 6"/>',
    "sec-tools": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "sec-public": '<circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/><path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18z"/>',
    "sec-research": '<path d="M2 3h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    "sec-admin": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="2" y1="14" x2="6" y2="14"/><line x1="10" y1="8" x2="14" y2="8"/><line x1="18" y1="16" x2="22" y2="16"/>',
    "sec-trade": '<path d="M7 4v3"/><rect x="5.5" y="7" width="3" height="7"/><path d="M7 10v10"/><path d="M17 3v2"/><rect x="15.5" y="5" width="3" height="8"/><path d="M17 13v7"/>',
}


def _icon(name: str, cls: str = "nav-ico"):
    """A uniform inline-SVG line icon; falls back to a small dot when unknown."""
    inner = _ICONS.get(name, _ICONS["_default"])
    # width/height live on the element itself so the glyph can never balloon if
    # app.css is cached/late; CSS only fine-tunes the size and colour.
    svg = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
           'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
           'stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>')
    return Span(NotStr(svg), cls=cls)


def _strip_emoji(label: str) -> str:
    """Drop a leading emoji/symbol + space so labels render icon-then-text."""
    i = 0
    while i < len(label) and (not label[i].isascii() or label[i] in " \t"):
        i += 1
    return label[i:] or label


def _page_link(label: str, href: str, key: str, active):
    """A sidebar page link: uniform icon + clean text, active-highlighted."""
    return A(
        _icon(key),
        Span(_strip_emoji(label), cls="page-link-text"),
        href=href,
        cls="page-link" + (" active" if active == key else ""),
    )


# --- client helpers (fillChat / newChat / composer + pane toggles) ----------
PH_JS = """
function fillChat(t){var i=document.getElementById('chat-input');
  if(i){i.value=t;i.focus();autoResize(i);return;}
  sessionStorage.setItem('alpatrade.pendingPrompt',t);window.location.href='/app';}
function autoResize(el){if(!el)return;el.style.height='auto';
  el.style.height=Math.min(el.scrollHeight,192)+'px';}
function newChat(){setNewsPane(true);window.location.href='/app?new=1';}
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
function filterNews(el){var cat=el.getAttribute('data-cat');
  var pills=document.querySelectorAll('#news-body .news-pill');
  for(var i=0;i<pills.length;i++){pills[i].classList.toggle('active',pills[i]===el);}
  var items=document.querySelectorAll('#news-body .news-item');
  var visible=0;
  for(var j=0;j<items.length;j++){
    var show=(cat==='latest')||(items[j].getAttribute('data-cat')===cat);
    items[j].style.display=show?'':'none';
    if(show)visible++;
  }
  var empty=document.getElementById('news-empty-filter');
  if(empty)empty.style.display=visible?'none':'block';
}
// --- sidebar drawer + scroll persistence across navigation ---------------
// Each <details data-nav-key> remembers its open/closed state in localStorage
// so navigating to a new page no longer collapses the whole menu and loses
// the user's place. The section holding the active page is always revealed.
function navSave(){var st={};var s=document.querySelectorAll('#left-pane details[data-nav-key]');
  for(var i=0;i<s.length;i++){st[s[i].getAttribute('data-nav-key')]=s[i].open;}
  try{localStorage.setItem('alpatrade.nav',JSON.stringify(st));}catch(e){}}
function navRestore(){var st={};
  try{var r=localStorage.getItem('alpatrade.nav');if(r)st=JSON.parse(r)||{};}catch(e){st={};}
  var s=document.querySelectorAll('#left-pane details[data-nav-key]');
  for(var i=0;i<s.length;i++){var k=s[i].getAttribute('data-nav-key');
    if(Object.prototype.hasOwnProperty.call(st,k))s[i].open=!!st[k];
    s[i].addEventListener('toggle',navSave);}
  var a=document.querySelector('#left-pane .page-link.active,#left-pane .agent-item.active,#left-pane .session-row.active');
  if(a){var d=a.closest('details[data-nav-key]');
    while(d){d.open=true;var pr=d.parentElement;d=pr?pr.closest('details[data-nav-key]'):null;}}
  var lb=document.querySelector('.left-body');
  if(lb){try{var sc=localStorage.getItem('alpatrade.navScroll');if(sc)lb.scrollTop=parseInt(sc,10)||0;}catch(e){}
    var tmr;lb.addEventListener('scroll',function(){if(tmr)return;
      tmr=setTimeout(function(){tmr=null;try{localStorage.setItem('alpatrade.navScroll',String(lb.scrollTop));}catch(e){}},150);});}}
window.fillChat=fillChat;window.newChat=newChat;window.autoResize=autoResize;
window.handleKey=handleKey;window.toggleNewsPane=toggleNewsPane;window.setNewsPane=setNewsPane;
window.toggleLeftPane=toggleLeftPane;window.filterNews=filterNews;
window.navSave=navSave;window.navRestore=navRestore;
document.addEventListener('DOMContentLoaded',function(){
  var p=document.getElementById('right-pane');if(p)setNewsPane(p.classList.contains('open'));
  navRestore();
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
        Link(rel="stylesheet", href=f"/static/app.css?v={_CSS_VER}"),
        Script(src=_HTMX_CDN),
        Script(src=_MARKED_CDN),
        Script(src=_PLOTLY_CDN),
        Script(PH_JS),
        Script(src="/static/voice.js", defer=True),
    )


# ---------------------------------------------------------------------------
# Left pane — brand · new chat · sessions · command menu · user/login
# ---------------------------------------------------------------------------
def _brand(user: Optional[dict] = None):
    # Keep signed-in users in the app: the logo jumps to the dashboard (/app)
    # instead of the public landing page (/), so it never looks like a logout.
    # Anonymous visitors (e.g. on auth shells that reuse the brand) still land
    # on the marketing home page.
    href = "/app" if user else "/"
    return A(
        Span(NotStr(TILE_MARK), cls="brand-mark"),
        Span("AlpaTrade", cls="brand-name"),
        Span("beta", cls="brand-badge"),
        href=href, cls="brand-link",
    )


def _menu_group(label: str, items, active: Optional[str]):
    """One collapsible command group (pehero cat-toggle / agent-item markup).

    Items render as plain-language actions only — the description is the whole
    label; the raw command lives in the hover tooltip (and lands in the
    composer on click, ready to edit), so the syntax never competes with the
    name for space.
    """
    is_open = any(cmd == active for cmd, _ in items)
    rows = []
    for cmd, desc in items:
        cls = "agent-item" + (" active" if cmd == active else "")
        rows.append(Button(
            Span(desc or cmd, cls="aitem-name"),
            cls=cls, type="button", title=f"{desc}: {cmd}" if desc else cmd,
            onclick=f"fillChat({cmd!r})",
        ))
    return Details(
        Summary(
            Span(label, cls="cat-name"),
            Span("›", cls="cat-arrow"),
            cls="cat-toggle",
        ),
        Div(*rows, cls="agent-list"),
        cls="agent-group",
        **{"data-nav-key": "grp-" + label.lower().replace(" ", "-")},
        **({"open": True} if is_open else {}),
    )


def _nav_section(label: str, *children, opened: bool = False,
                 icon: Optional[str] = None):
    """A compact top-level sidebar section.

    Open/closed state is remembered client-side across navigation
    (``data-nav-key`` + ``navRestore`` in ``PH_JS``); ``opened`` is only the
    first-visit default, and the section holding the active page is always
    force-opened on load.
    """
    summary_kids = []
    if icon:
        summary_kids.append(_icon(icon, cls="nav-ico nav-section-ico"))
    summary_kids += [
        Span(label, cls="nav-section-name"),
        Span(">", cls="nav-section-expand", aria_hidden="true"),
        Span("<", cls="nav-section-collapse", aria_hidden="true"),
    ]
    return Details(
        Summary(*summary_kids, cls="nav-section-toggle"),
        Div(*children, cls="nav-section-body"),
        cls="nav-section",
        **{"data-nav-key": "sec-" + label.lower().replace(" ", "-").replace("&", "and")},
        **({"open": True} if opened else {}),
    )


# Extra tool pages, appended by their feature modules as they're built.
# Each entry: (label, href, active-key). TRADE = first-class product surfaces
# (Backtests, Paper Runs — ph_runs); EXPLORE = visual/map tools (IPO Map, Hedge
# Funds, Market Intel); TOOLS = actionable tools (SEC Filings, Press Releases).
TRADE_PAGES: list = []
EXPLORE_PAGES: list = []
TOOLS_PAGES: list = []
PUBLIC_PAGES: list = []
RESEARCH_PAGES: list = []
MONITORING_PAGES: list = []


def _TRADE_EXTRA(active):
    return [_page_link(lbl, href, key, active) for lbl, href, key in TRADE_PAGES]


def _EXPLORE_EXTRA(active):
    return [_page_link(lbl, href, key, active) for lbl, href, key in EXPLORE_PAGES]


def _TOOLS_EXTRA(active):
    return [_page_link(lbl, href, key, active) for lbl, href, key in TOOLS_PAGES]


def _PUBLIC_EXTRA(active):
    return [_page_link(lbl, href, key, active) for lbl, href, key in PUBLIC_PAGES]


def _RESEARCH_EXTRA(active):
    return [_page_link(lbl, href, key, active) for lbl, href, key in RESEARCH_PAGES]


def _MONITORING_EXTRA(active):
    return [_page_link(lbl, href, key, active) for lbl, href, key in MONITORING_PAGES]


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
        Div(_brand(user), cls="left-header"),
        Div(
            A("＋ New chat", cls="new-chat-btn", href="#",
              onclick="newChat();return false;"),
            _nav_section(
                "Trade",
                Div(
                    _page_link("Dashboard", "/dashboard", "dashboard", active),
                    _page_link("Backtests", "/backtests", "backtests", active),
                    _page_link("Paper runs", "/paper", "paper", active),
                    *_TRADE_EXTRA(active),
                    cls="page-links",
                ),
                icon="sec-trade",
                opened=True,
            ),
            _nav_section(
                "Chats",
                Div(Div("Your conversations appear here.", cls="sessions-empty"),
                    cls="session-list", id="session-list",
                    hx_get="/app/chats", hx_trigger="load", hx_swap="innerHTML"),
                opened=active == "app",
                icon="sec-chats",
            ),
            _nav_section(
                "Agents",
                Div(*[_menu_group(lbl, items, active)
                      for lbl, items in AGENT_SHORTCUTS + HERMES_SHORTCUTS],
                    cls="agent-browser"),
                icon="sec-agents",
                opened=active == "app",
            ),
            _nav_section(
                "Research",
                Div(
                    _page_link("Market Map", "/map", "map", active),
                    _page_link("Charts", "/charts", "charts", active),
                    *_RESEARCH_EXTRA(active),
                    *_EXPLORE_EXTRA(active),
                    *_TOOLS_EXTRA(active),
                    *_PUBLIC_EXTRA(active),
                    _menu_group("Alpha research agents", [
                        item for _, items in ALPHA_RESEARCH_SHORTCUTS for item in items
                    ], active),
                    cls="page-links",
                ),
                icon="sec-research",
            ),
            _nav_section(
                "Account",
                Div(
                    *_MONITORING_EXTRA(active),
                    _page_link("Settings", "/settings", "settings", active),
                    _page_link("Help & shortcuts", "/guide", "guide", active),
                    cls="page-links",
                ),
                icon="sec-admin",
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
def _verify_banner(user: dict):
    """Persistent nudge for signed-in users whose email is not yet verified.

    Browsing stays open; costly actions (AI chat, backtests, paper runs) gate
    on verification separately. POSTs to /verify/resend in ph_auth.
    """
    from fasthtml.common import A, Div
    return Div(
        Div(
            Span("Verify your email to use AI chat, backtests and paper trading."),
            A("Resend link", href="#", cls="verify-resend",
              onclick="event.preventDefault();fetch('/verify/resend',{method:'POST'})"
                      ".then(()=>this.textContent='Sent — check your inbox')"),
            cls="verify-banner-inner",
        ),
        cls="verify-banner",
    )


def page(active, *content, user: Optional[dict] = None,
         title: str = "AlpaTrade", right_news: bool = True,
         right_news_open: bool = False):
    """Full app shell. ``*content`` is the center column (usually
    :func:`chat_center`); ``active`` highlights the matching command-menu item."""
    # Keep one constrained grid item between the sidebar and fixed overlays.
    # The document itself intentionally does not scroll, so every feature page
    # needs this shared viewport instead of relying on route-specific overflow.
    center = Div(*content, cls="page-pane")
    if user and not user.get("email_verified_at"):
        center = Div(_verify_banner(user), center, cls="page-pane")
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

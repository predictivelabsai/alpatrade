"""House-style 3-pane shell + design tokens for the assethero platform UI.

One `page(...)` wraps every vertical view in: top bar (brand · asset-class switcher ·
user menu) · left nav · center content · right AI rail. Verticals supply their own
nav items and center content; the asset switcher and rail are shared.
"""
from __future__ import annotations

from typing import Optional

from fasthtml.common import (
    A, Button, Div, Form, H1, H3, Input, Li, Main, Nav, P, Script, Span,
    Style, Title, Ul, NotStr,
)

# --- asset-class registry (drives the top-bar switcher) ---------------------
# (key, label, icon, href, enabled)
ASSET_CLASSES = [
    ("equities", "Equities", "📈", "/equities", True),
    ("crypto", "Crypto", "🪙", "/crypto", False),
    ("fx", "FX / Macro", "💱", "/fx", False),
    ("prediction", "Prediction", "🔮", "/prediction", False),
    ("research", "Research", "🔬", "/research", False),
]

LAYOUT_CSS = """
:root{
  --bg:#0f1420; --panel:#161d2c; --panel-2:#1d2738; --line:#26324a;
  --text:#e7ecf5; --muted:#93a1bd; --accent:#3b82f6; --accent-2:#22c55e;
  --warn:#f59e0b; --danger:#ef4444; --radius:12px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:14px;}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3,h4{margin:.2rem 0 .6rem}
.topbar{display:flex;align-items:center;gap:1rem;padding:.6rem 1rem;background:var(--panel);
  border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.brand{font-weight:800;font-size:1.1rem;letter-spacing:.3px;color:var(--text);white-space:nowrap}
.brand .h{color:var(--accent)}
.switcher{display:flex;gap:.35rem;flex-wrap:wrap;flex:1}
.pill{display:inline-flex;align-items:center;gap:.35rem;padding:.32rem .7rem;border-radius:999px;
  background:var(--panel-2);border:1px solid var(--line);color:var(--muted);font-weight:600;font-size:.82rem}
.pill.active{background:var(--accent);border-color:var(--accent);color:#fff}
.pill.disabled{opacity:.5;cursor:not-allowed}
.pill .soon{font-size:.62rem;opacity:.8}
.usermenu{display:flex;align-items:center;gap:.6rem;color:var(--muted);white-space:nowrap}
.layout{display:grid;grid-template-columns:210px 1fr 320px;min-height:calc(100vh - 49px)}
.leftnav{background:var(--panel);border-right:1px solid var(--line);padding:.8rem .6rem}
.leftnav ul{list-style:none;margin:0;padding:0}
.leftnav li{margin:.15rem 0}
.leftnav a{display:block;padding:.5rem .7rem;border-radius:8px;color:var(--muted);font-weight:600}
.leftnav a:hover{background:var(--panel-2);text-decoration:none;color:var(--text)}
.leftnav a.active{background:var(--panel-2);color:var(--text);border-left:3px solid var(--accent)}
.center{padding:1.2rem 1.4rem;overflow-x:auto}
.rail{background:var(--panel);border-left:1px solid var(--line);padding:.9rem .8rem;display:flex;flex-direction:column}
.card{background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius);padding:1rem;margin-bottom:1rem}
.kpi{display:flex;gap:1rem;flex-wrap:wrap}
.kpi .box{flex:1;min-width:120px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius);padding:.8rem 1rem}
.kpi .box .v{font-size:1.4rem;font-weight:800}
.kpi .box .l{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:700;text-transform:uppercase;font-size:.72rem;letter-spacing:.04em}
.pos{color:var(--accent-2)} .neg{color:var(--danger)}
input,select,button{font:inherit}
input,select{background:var(--bg);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:.5rem .6rem}
.btn{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:.55rem .9rem;font-weight:700;cursor:pointer}
.btn:hover{filter:brightness(1.08)}
.btn.ghost{background:var(--panel-2);color:var(--text);border:1px solid var(--line)}
.rail h3{font-size:.95rem}
.rail .chips{display:flex;flex-wrap:wrap;gap:.35rem;margin:.4rem 0 .8rem}
.rail .chip{font-size:.74rem;background:var(--panel-2);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:.25rem .55rem;cursor:pointer}
.rail .resp{flex:1;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;
  padding:.6rem;min-height:120px;font-size:.85rem}
.muted{color:var(--muted)} .right{text-align:right}
.authwrap{max-width:380px;margin:8vh auto;padding:0 1rem}
.formrow{display:flex;flex-direction:column;gap:.3rem;margin-bottom:.8rem}
.notice{padding:.6rem .8rem;border-radius:8px;background:var(--panel-2);border:1px solid var(--line);margin-bottom:1rem}
.err{border-color:var(--danger);color:#ffd7d7}
"""

ASSISTANT_JS = """
function ahSend(vertical){
  const inp=document.getElementById('ah-ask'); if(!inp||!inp.value.trim())return;
  ahRun(vertical, inp.value.trim()); inp.value='';
}
function ahChip(vertical, q){ ahRun(vertical, q); }
function ahRun(vertical, q){
  const resp=document.getElementById('ah-resp');
  resp.innerHTML='<span class="muted">…thinking</span>';
  fetch('/'+vertical+'/assistant',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:'q='+encodeURIComponent(q)})
    .then(r=>r.text()).then(t=>{resp.innerHTML='<div class="marked">'+t+'</div>';
      if(window.marked&&false){} })
    .catch(e=>{resp.innerText='error: '+e});
}
function ahVertical(){var r=document.getElementById('ah-root');return r?r.getAttribute('data-vertical'):'equities';}
document.addEventListener('keydown',function(e){
  if(e.key==='Enter'&&document.activeElement&&document.activeElement.id==='ah-ask'){
    e.preventDefault(); ahSend(ahVertical());}
});
"""


def switcher(active: str):
    pills = []
    for key, label, icon, href, enabled in ASSET_CLASSES:
        cls = "pill" + (" active" if key == active else "") + ("" if enabled else " disabled")
        inner = [Span(icon), Span(label)]
        if not enabled:
            inner.append(Span("soon", cls="soon"))
        pills.append(A(*inner, cls=cls, href=(href if enabled else "#"),
                       title=("" if enabled else "Coming in a later phase")))
    return Div(*pills, cls="switcher")


def topbar(active: str, user: Optional[dict]):
    if user:
        right = Div(Span(user.get("email", "user"), cls="muted"),
                    A("Profile", href="/profile"), A("Logout", href="/logout"), cls="usermenu")
    else:
        right = Div(A("Login", href="/login"), cls="usermenu")
    return Div(
        Div(NotStr('Alpa<span class="h">Trade</span>'), cls="brand"),
        switcher(active),
        right,
        cls="topbar",
    )


def left_nav(nav_items, active_nav: str):
    items = []
    for label, href in nav_items:
        cls = "active" if href == active_nav else None
        items.append(Li(A(label, href=href, cls=cls)))
    return Nav(Ul(*items), cls="leftnav")


def ai_rail(active: str, chips=None, title="AI Assistant"):
    chips = chips or []
    chip_els = [Span(c, cls="chip", onclick=f"ahChip('{active}', {c!r})") for c in chips]
    return Div(
        H3("🤖 " + title),
        P("Ask about your data or run a command.", cls="muted"),
        Div(*chip_els, cls="chips"),
        Div("Responses appear here.", id="ah-resp", cls="resp marked"),
        Div(
            Input(id="ah-ask", placeholder="e.g. runs  ·  trades  ·  help", autocomplete="off"),
            Button("Send", cls="btn", onclick=f"ahSend('{active}')", style="margin-top:.5rem;width:100%"),
            style="margin-top:.6rem",
        ),
        cls="rail",
    )


def page(active_vertical: str, nav_items, *content, user: Optional[dict] = None,
         active_nav: str = "", title: str = "AlpaTrade", right_rail=None,
         rail_chips=None):
    """Full 3-pane page. `right_rail` overrides the default AI rail when provided."""
    rail = right_rail if right_rail is not None else ai_rail(active_vertical, rail_chips)
    return (
        Title(title),
        Style(LAYOUT_CSS),
        Script(ASSISTANT_JS),
        Div(
            topbar(active_vertical, user),
            Div(
                left_nav(nav_items, active_nav),
                Main(*content, cls="center"),
                rail,
                cls="layout",
            ),
            id="ah-root", data_vertical=active_vertical,
        ),
    )


def auth_page(*content, title="AlpaTrade"):
    """Minimal centered shell for login/register (no nav/rail)."""
    return (
        Title(title),
        Style(LAYOUT_CSS),
        Div(Div(NotStr('Alpa<span class="h">Trade</span>'), cls="brand",
                style="font-size:1.6rem;text-align:center;margin-bottom:1.2rem"),
            *content, cls="authwrap"),
    )

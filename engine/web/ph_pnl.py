"""Paper PnL page — the daily PnL report as a live in-app tool.

Renders the same account snapshot the nightly email uses (scripts.daily_pnl_report),
in the parchment/forest shell. Feature-module contract: register(app, rt).
"""
from __future__ import annotations

from fasthtml.common import Button, Div, NotStr, Span, Style
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_PNL_CSS = """
.app{padding-right:0}
.pnlpage{max-width:820px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.pnlpage .pnl-head{display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:.6rem;margin:.4rem 0 1rem}
.pnlpage h1{font-size:1.3rem;margin:0;color:var(--ink)}
.pnlpage .pnl-sub{font-size:.82rem;color:var(--ink-muted);margin:.15rem 0 0}
.pnlpage table{border-collapse:collapse}
.pnlpage table td,.pnlpage table th{border:1px solid var(--line)}
.pnl-refresh{font-size:.8rem;color:var(--bg);background:var(--accent);border:0;
  border-radius:.4rem;padding:.4rem .8rem;cursor:pointer}
.pnl-refresh:hover{opacity:.9}
"""

_PNL_JS = """
(function(){
  async function load(){
    var box=document.getElementById('pnl-body'); if(!box) return;
    box.style.opacity='.5';
    try{ var r=await fetch('/pnl/data'); box.innerHTML=await r.text(); }
    catch(e){ box.innerHTML='<p>Could not load PnL: '+e+'</p>'; }
    box.style.opacity='1';
  }
  window._pnlReload=load;
})();
"""


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


def _report_html() -> str:
    from scripts.daily_pnl_report import gather, render
    try:
        return render(gather())
    except Exception as e:  # noqa: BLE001
        return f"<p class='pnl-sub'>Could not load the paper account: {e}</p>"


def _pnl_page(user):
    body = Div(
        NotStr('<h1>📊 Paper PnL</h1>'),
        Div(
            Span("Live paper-trading account — day P&L and open positions.", cls="pnl-sub"),
            Button("↻ Refresh", cls="pnl-refresh", type="button", onclick="_pnlReload()"),
            cls="pnl-head",
        ),
        Div(NotStr(_report_html()), id="pnl-body"),
        cls="pnlpage",
    )
    return page("pnl", Style(_PNL_CSS), body, Style(""),
                NotStr(f"<script>{_PNL_JS}</script>"),
                user=user, title="Paper PnL · AlpaTrade", right_news=False)


def register(app, rt):
    @rt("/pnl", methods=["GET"])
    def pnl_get(session):
        return _pnl_page(_user(session))

    @rt("/pnl/data", methods=["GET"])
    def pnl_data():
        from starlette.responses import HTMLResponse
        return HTMLResponse(_report_html())

    return ["/pnl", "/pnl/data"]

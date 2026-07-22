"""Hedge Funds page — top institutional managers by 13F AUM + activist filings.

Backend: engine.publicmarkets.hedge_funds (reads shared hedgefolio schema). No
per-security infotable in this DB, so this is fund-level AUM + activism (not per-ticker
ownership). Feature-module contract: register(app, rt).
"""
from __future__ import annotations

from fasthtml.common import A, Div, NotStr, P, Script, Style, Table, Tbody, Td, Th, Thead, Tr
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}
.hfpage{max-width:1180px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.hfpage h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.hfpage h3{color:var(--accent);margin:1.4rem 0 .4rem;font-size:1rem}
.hfpage .hf-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.hf-plot{width:100%;min-height:460px;background:#fff;border:1px solid var(--line);
  border-radius:.6rem;padding:.3rem}
.hf-status{font-size:.8rem;color:var(--ink-muted);margin:.5rem 0}
.hfpage table{border-collapse:collapse;width:100%;font-size:.82rem}
.hfpage th,.hfpage td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.hfpage thead{background:var(--bg-raise)}
.hfpage a{color:var(--accent)}
"""

_JS = """
(function(){
  async function draw(){
    var el=document.getElementById('hf-plot'), s=document.getElementById('hf-status');
    if(!el||!window.Plotly) return;
    try{
      var d=await (await fetch('/hedge-funds/data')).json();
      if(!d.funds||!d.funds.length){ s.textContent='No 13F data.'; return; }
      var labels=d.funds.map(f=>f.name), values=d.funds.map(f=>f.value),
          parents=d.funds.map(()=>''),
          text=d.funds.map(f=>'$'+(f.value/1e12>=1?(f.value/1e12).toFixed(2)+'T':(f.value/1e9).toFixed(0)+'B'));
      Plotly.newPlot(el,[{type:'treemap',labels:labels,parents:parents,values:values,
        text:text,texttemplate:'%{label}<br>%{text}',hovertemplate:'%{label}<br>%{text}<extra></extra>',
        marker:{colors:values,colorscale:[[0,'#CFE5DA'],[1,'#1F5D43']]},tiling:{pad:2}}],
        {margin:{l:0,r:0,t:0,b:0},height:460,paper_bgcolor:'#fff',
         font:{family:'Inter,sans-serif',size:11,color:'#14231B'}},{displayModeBar:false,responsive:true});
      s.textContent=d.funds.length+' managers · sized by 13F portfolio value';
    }catch(e){ s.textContent='Could not load: '+e; }
  }
  if(document.readyState!=='loading') draw(); else document.addEventListener('DOMContentLoaded',draw);
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


def _b(v):
    return f"${v/1e12:.2f}T" if v >= 1e12 else (f"${v/1e9:.1f}B" if v >= 1e9 else f"${v/1e6:.0f}M")


def _page(user):
    from engine.publicmarkets.hedge_funds import activist_filings
    acts = activist_filings(limit=20)
    act_rows = [Tr(Td(a["date"][:10]), Td((a["filer"] or "")[:34]),
                   Td((a["subject"] or "")[:26]), Td(a["ticker"] or ""),
                   Td(A(a["form"] or "view", href=a.get("url") or "#", target="_blank")))
                for a in acts]
    body = Div(
        NotStr("<h1>🏦 Hedge Funds</h1>"),
        P("Top institutional managers by 13F portfolio value, and recent activist filings. "
          "(Fund-level AUM + activism — per-security holdings aren't in this dataset.)", cls="hf-sub"),
        Div(id="hf-plot", cls="hf-plot"), Div("", id="hf-status", cls="hf-status"),
        NotStr("<h3>Recent activist filings</h3>"),
        Table(Thead(Tr(Th("Date"), Th("Filer"), Th("Target"), Th("Ticker"), Th("Form"))),
              Tbody(*act_rows)),
        cls="hfpage",
    )
    return page("hedgefunds", Style(_CSS), body, Script(_JS),
                user=user, title="Hedge Funds · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("🏦 Hedge Funds", "/hedge-funds", "hedgefunds")
    if entry not in ph_layout.EXPLORE_PAGES:
        ph_layout.EXPLORE_PAGES.append(entry)

    @rt("/hedge-funds", methods=["GET"])
    def hf_get(session):
        return _page(_user(session))

    @rt("/hedge-funds/data", methods=["GET"])
    def hf_data(limit: int = 40):
        from engine.publicmarkets.hedge_funds import top_funds
        return JSONResponse({"funds": top_funds(limit)})

    return ["/hedge-funds", "/hedge-funds/data"]

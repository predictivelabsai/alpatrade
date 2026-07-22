"""Market Intel page — sector-ETF annual-return heatmap (client-side Plotly).

Backend: engine.publicmarkets.market_intel (yfinance, no DB). Plotly is loaded by the
shell head. Feature-module contract: register(app, rt).
"""
from __future__ import annotations

from fasthtml.common import Div, NotStr, P, Script, Style
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}
.mintel{max-width:1080px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.mintel h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.mintel .mi-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.mi-plot{width:100%;min-height:520px;background:#fff;border:1px solid var(--line);
  border-radius:.6rem;padding:.3rem}
.mi-status{font-size:.8rem;color:var(--ink-muted);margin:.5rem 0}
"""

_JS = """
(function(){
  async function draw(){
    var el=document.getElementById('mi-plot'), s=document.getElementById('mi-status');
    if(!el||!window.Plotly) return;
    s.textContent='Loading sector returns…';
    try{
      var d=await (await fetch('/market-intel/data')).json();
      if(!d.sectors||!d.sectors.length){ s.textContent='No sector data.'; return; }
      var z=d.matrix, text=z.map(row=>row.map(v=>v==null?'':(v>0?'+':'')+v+'%'));
      Plotly.newPlot(el,[{
        type:'heatmap', x:d.years.map(String), y:d.sectors, z:z,
        text:text, texttemplate:'%{text}', hovertemplate:'%{y} · %{x}: %{z}%<extra></extra>',
        colorscale:[[0,'#b0653f'],[0.5,'#EFEDE4'],[1,'#1F5D43']], zmid:0, showscale:true,
        xgap:2, ygap:2
      }],{margin:{l:150,r:20,t:20,b:40},height:520,paper_bgcolor:'#fff',plot_bgcolor:'#fff',
          font:{family:'Inter,sans-serif',size:12,color:'#14231B'}},{displayModeBar:false,responsive:true});
      s.textContent=d.sectors.length+' sectors × '+d.years.length+' years · annual % return (green up, red down)';
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


def _page(user):
    body = Div(
        NotStr("<h1>🌡 Market Intel</h1>"),
        P("Annual returns of the 11 SPDR sector ETFs — where the money's rotating.", cls="mi-sub"),
        Div(id="mi-plot", cls="mi-plot"),
        Div("", id="mi-status", cls="mi-status"),
        cls="mintel",
    )
    return page("marketintel", Style(_CSS), body, Script(_JS),
                user=user, title="Market Intel · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    if ("🌡 Market Intel", "/market-intel", "marketintel") not in ph_layout.EXPLORE_PAGES:
        ph_layout.EXPLORE_PAGES.append(("🌡 Market Intel", "/market-intel", "marketintel"))

    @rt("/market-intel", methods=["GET"])
    def mi_get(session):
        return _page(_user(session))

    @rt("/market-intel/data", methods=["GET"])
    def mi_data(years: int = 5):
        from engine.publicmarkets.market_intel import sector_returns
        return JSONResponse(sector_returns(years))

    return ["/market-intel", "/market-intel/data"]

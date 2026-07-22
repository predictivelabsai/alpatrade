"""IPO Map + Pipeline pages — priced-IPO treemap and pre-IPO/upcoming table.

Backend: engine.publicmarkets.ipo (reads shared liquidround.ipo_data/ipo_pipeline).
Feature-module contract: register(app, rt).
"""
from __future__ import annotations

from fasthtml.common import A, Div, NotStr, P, Script, Span, Style, Table, Tbody, Td, Th, Thead, Tr
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}
.ipopage{max-width:1180px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.ipopage h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.ipopage .ip-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.ip-plot{width:100%;min-height:520px;background:#fff;border:1px solid var(--line);
  border-radius:.6rem;padding:.3rem}
.ip-status{font-size:.8rem;color:var(--ink-muted);margin:.5rem 0}
.ipopage table{border-collapse:collapse;width:100%;font-size:.82rem}
.ipopage th,.ipopage td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.ipopage thead{background:var(--bg-raise)}
.ip-links{margin:.2rem 0 1rem}
.ip-links a{font-size:.82rem;color:var(--accent);margin-right:1rem;text-decoration:none}
.ip-links a.active{font-weight:600;text-decoration:underline}
"""

_JS = """
(function(){
  function retColor(r){
    if(r==null||isNaN(r)) return '#9AA39C';
    var c=Math.max(-1,Math.min(1,r/60));
    if(c>=0) return 'rgb('+Math.round(122-91*c)+','+Math.round(134+21*c)+','+Math.round(126-59*c)+')';
    var a=-c; return 'rgb('+Math.round(122+58*a)+','+Math.round(134-63*a)+','+Math.round(126-79*a)+')';
  }
  async function draw(){
    var el=document.getElementById('ip-plot'), s=document.getElementById('ip-status');
    if(!el||!window.Plotly) return;
    s.textContent='Loading IPOs…';
    try{
      var d=await (await fetch('/ipo-map/data')).json();
      if(!d.ipos||!d.ipos.length){ s.textContent='No IPO data.'; return; }
      var ids=[],labels=[],parents=[],values=[],colors=[],text=[],seen={};
      d.ipos.forEach(function(x){
        var reg=x.region||'Other', sec=reg+' / '+(x.sector||'Other'), tk=sec+' / '+x.ticker;
        if(!seen[reg]){seen[reg]=1; ids.push(reg);labels.push(reg);parents.push('');values.push(0);colors.push('#EFEDE4');text.push('');}
        if(!seen[sec]){seen[sec]=1; ids.push(sec);labels.push(x.sector||'Other');parents.push(reg);values.push(0);colors.push('#EFEDE4');text.push('');}
        ids.push(tk);labels.push(x.ticker);parents.push(sec);values.push(x.size||1);colors.push(retColor(x.return_pct));
        text.push(x.return_pct==null?'':(x.return_pct>0?'+':'')+x.return_pct.toFixed(0)+'%');
      });
      Plotly.newPlot(el,[{type:'treemap',ids:ids,labels:labels,parents:parents,values:values,
        branchvalues:'remainder',marker:{colors:colors},text:text,texttemplate:'%{label}<br>%{text}',
        hovertemplate:'%{label}<br>%{text}<extra></extra>',tiling:{pad:2}}],
        {margin:{l:0,r:0,t:0,b:0},height:520,paper_bgcolor:'#fff',
         font:{family:'Inter,sans-serif',size:11,color:'#14231B'}},{displayModeBar:false,responsive:true});
      s.textContent=d.count+' priced IPOs · sized by market cap, coloured by return since IPO';
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


def _links(active):
    return Div(
        A("🧭 IPO Map", href="/ipo-map", cls="active" if active == "ipomap" else ""),
        A("📋 IPO Pipeline", href="/ipo-pipeline", cls="active" if active == "ipopipeline" else ""),
        cls="ip-links",
    )


def _map_page(user):
    body = Div(NotStr("<h1>🧭 IPO Map</h1>"), _links("ipomap"),
               P("Priced IPOs by region → sector → ticker; sized by market cap, coloured by return.", cls="ip-sub"),
               Div(id="ip-plot", cls="ip-plot"), Div("", id="ip-status", cls="ip-status"),
               cls="ipopage")
    return page("ipomap", Style(_CSS), body, Script(_JS), user=user, title="IPO Map · AlpaTrade", right_news=False)


def _pipeline_page(user):
    from engine.publicmarkets.ipo import ipo_pipeline_data
    rows = ipo_pipeline_data(100)

    def _b(v):
        return f"${v/1e9:.1f}B" if v else "—"
    trs = [Tr(Td(r["company"] or ""), Td(r["kind"] or ""), Td(r["sector"] or ""),
              Td(r["country"] or ""), Td(_b(r["valuation"])), Td(r["last_round"] or ""),
              Td(r["last_round_date"][:10])) for r in rows]
    body = Div(NotStr("<h1>📋 IPO Pipeline</h1>"), _links("ipopipeline"),
               P("Pre-IPO private companies + filed/upcoming listings.", cls="ip-sub"),
               Table(Thead(Tr(Th("Company"), Th("Kind"), Th("Sector"), Th("Country"),
                              Th("Valuation"), Th("Last round"), Th("Date"))), Tbody(*trs)),
               cls="ipopage")
    return page("ipopipeline", Style(_CSS), body, user=user, title="IPO Pipeline · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    for entry in [("🧭 IPO Map", "/ipo-map", "ipomap")]:
        if entry not in ph_layout.EXPLORE_PAGES:
            ph_layout.EXPLORE_PAGES.append(entry)

    @rt("/ipo-map", methods=["GET"])
    def ipo_map_get(session):
        return _map_page(_user(session))

    @rt("/ipo-map/data", methods=["GET"])
    def ipo_map_data_route():
        from engine.publicmarkets.ipo import ipo_map_data
        return JSONResponse(ipo_map_data())

    @rt("/ipo-pipeline", methods=["GET"])
    def ipo_pipeline_get(session):
        return _pipeline_page(_user(session))

    return ["/ipo-map", "/ipo-map/data", "/ipo-pipeline"]

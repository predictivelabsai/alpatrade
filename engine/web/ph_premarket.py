"""Premarket dashboard — FastHTML port of Finespresso's Streamlit screener."""
from __future__ import annotations

from fasthtml.common import Button, Div, NotStr, Option, Script, Select, Span, Style
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}.pm{max-width:1180px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.pm-head{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;flex-wrap:wrap;
  margin:.4rem 0 1rem}.pm h1{font-size:1.35rem;margin:0;color:var(--ink)}
.pm-sub,.pm-status{font-size:.8rem;color:var(--ink-muted);margin:.2rem 0}
.pm-actions{display:flex;gap:.5rem;align-items:center}.pm select{padding:.45rem;border:1px solid var(--line);
  border-radius:.4rem;background:var(--bg);color:var(--ink)}.pm-btn{border:0;border-radius:.4rem;
  padding:.5rem .85rem;background:var(--accent);color:white;cursor:pointer}
.pm-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem;margin:1rem 0}
.pm-metric{border:1px solid var(--line);border-radius:.6rem;background:var(--bg-elev);padding:.75rem}
.pm-metric-label{font-size:.7rem;color:var(--ink-muted);text-transform:uppercase;letter-spacing:.04em}
.pm-metric-value{font-size:1.25rem;color:var(--ink);font-weight:650;margin-top:.2rem}
.pm-grid{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}.pm-panel{border:1px solid var(--line);
  border-radius:.65rem;background:var(--bg-elev);overflow:hidden}.pm-panel h2{font-size:.9rem;margin:0;
  padding:.7rem .8rem;border-bottom:1px solid var(--line)}.pm-row{display:grid;
  grid-template-columns:4.3rem minmax(0,1fr) 5rem 5.3rem;gap:.45rem;align-items:center;
  padding:.6rem .8rem;border-bottom:1px solid var(--line);cursor:pointer}.pm-row:hover{background:var(--bg-raise)}
.pm-ticker{font-family:var(--font-mono);font-weight:650}.pm-company{font-size:.75rem;color:var(--ink-muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pm-price{font-size:.76rem;text-align:right}
.pm-move{text-align:right;font-family:var(--font-mono);font-weight:650}.pm-up{color:#1F7A4D}.pm-down{color:#B4472F}
.pm-sectors{margin-top:.9rem;border:1px solid var(--line);border-radius:.65rem;overflow:hidden}
.pm-sector-row{display:grid;grid-template-columns:minmax(10rem,1fr) 4fr 4rem;align-items:center;
  gap:.7rem;padding:.55rem .8rem;border-bottom:1px solid var(--line);font-size:.78rem}
.pm-bar{height:.55rem;background:#ead8d0;border-radius:1rem;overflow:hidden}.pm-bar span{height:100%;
  display:block;background:#4c9a75}.pm-empty{padding:3rem 1rem;text-align:center;color:var(--ink-muted)}
.pm-modal{position:fixed;inset:0;background:rgba(20,35,27,.42);display:none;align-items:center;
  justify-content:center;z-index:30;padding:1rem}.pm-modal.open{display:flex}.pm-card{width:min(680px,100%);
  max-height:85vh;overflow:auto;background:var(--bg);border-radius:.7rem;padding:1rem;box-shadow:0 18px 50px #14231b55}
.pm-card-head{display:flex;justify-content:space-between;align-items:center}.pm-close{border:0;background:none;
  font-size:1.2rem;cursor:pointer}.pm-catalyst{padding:.6rem 0;border-top:1px solid var(--line);font-size:.8rem}
.pm-catalyst a{color:var(--accent)}@media(max-width:760px){.pm-grid{grid-template-columns:1fr}
  .pm-metrics{grid-template-columns:1fr 1fr}.pm-row{grid-template-columns:3.8rem 1fr 4.6rem}
  .pm-price{display:none}}@media(max-width:430px){.pm-metrics{grid-template-columns:1fr 1fr}}
"""

_JS = """
(function(){
  var current=null;
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
  function row(x,dir){return '<div class="pm-row" data-ticker="'+esc(x.ticker)+'"><div class="pm-ticker">'+
    esc(x.ticker)+'</div><div class="pm-company">'+esc(x.company_name||x.sector||'')+
    '</div><div class="pm-price">$'+Number(x.premarket_close||0).toFixed(2)+'</div><div class="pm-move pm-'+dir+'">'+
    (x.movement_pct>=0?'+':'')+Number(x.movement_pct||0).toFixed(2)+'%</div></div>';}
  function render(d){
    current=d;var s=d.summary||{}, top=d.top||{gainers:[],fallers:[]};
    document.getElementById('pm-scanned').textContent=s.total_stocks_scanned||0;
    document.getElementById('pm-up').textContent=s.total_up_movements||0;
    document.getElementById('pm-down').textContent=s.total_down_movements||0;
    document.getElementById('pm-time').textContent=(d.scan_timestamp||'No scan').slice(0,16).replace('T',' ');
    document.getElementById('pm-gainers').innerHTML=top.gainers.length?top.gainers.map(x=>row(x,'up')).join(''):
      '<div class="pm-empty">No gainers in this scan.</div>';
    document.getElementById('pm-fallers').innerHTML=top.fallers.length?top.fallers.map(x=>row(x,'down')).join(''):
      '<div class="pm-empty">No fallers in this scan.</div>';
    var sectors=Object.entries(d.sectors||{});document.getElementById('pm-sectors').innerHTML=sectors.map(function(e){
      var b=e[1],total=(b.total_gainers||0)+(b.total_losers||0),pct=total?100*(b.total_gainers||0)/total:0;
      return '<div class="pm-sector-row"><span>'+esc(e[0])+'</span><div class="pm-bar"><span style="width:'+
        pct+'%"></span></div><span>'+(b.total_gainers||0)+' / '+(b.total_losers||0)+'</span></div>';}).join('');
    document.querySelectorAll('.pm-row').forEach(function(el){el.onclick=function(){detail(el.dataset.ticker);};});
    document.getElementById('pm-status').textContent='Latest completed scan · prices relative to prior regular close';
  }
  function allRows(){if(!current)return[];var out=[];Object.values(current.sectors||{}).forEach(function(s){
    out=out.concat(s.up||[],s.down||[]);});return out;}
  function detail(ticker){var x=allRows().find(function(r){return r.ticker===ticker;});if(!x)return;
    var cats=x.catalysts||[], sources=x.ai_sources||[];
    document.getElementById('pm-detail').innerHTML='<div class="pm-card-head"><h2>'+esc(x.ticker)+' · '+
      (x.movement_pct>=0?'+':'')+Number(x.movement_pct).toFixed(2)+'%</h2><button class="pm-close" onclick="closePm()">×</button></div>'+
      '<p>'+esc(x.company_name||'')+' · '+esc(x.sector||'')+'</p><p>Prior close $'+Number(x.prev_close).toFixed(2)+
      ' → premarket $'+Number(x.premarket_close).toFixed(2)+' · range $'+Number(x.premarket_low).toFixed(2)+'–$'+
      Number(x.premarket_high).toFixed(2)+'</p><h3>Premarket catalyst</h3>'+
      (x.ai_reasoning?'<p>'+esc(x.ai_reasoning)+'</p>':(cats.length?'':'<p>No attributed catalyst in the press-release feed.</p>'))+
      cats.map(function(c){return '<div class="pm-catalyst"><a target="_blank" rel="noopener" href="'+esc(c.link||'#')+
        '">'+esc(c.title||'Press release')+'</a><br><small>'+esc(c.event||c.publisher||'')+'</small></div>';}).join('')+
      sources.slice(cats.length).map(function(c){return '<div class="pm-catalyst"><a target="_blank" href="'+
        esc(c.url||'#')+'">'+esc(c.title||'Source')+'</a></div>';}).join('');
    document.getElementById('pm-modal').classList.add('open');
  }
  window.closePm=function(){document.getElementById('pm-modal').classList.remove('open');};
  window.loadPremarket=async function(){var st=document.getElementById('pm-status');st.textContent='Loading latest scan…';
    try{var d=await(await fetch('/premarket/data?limit='+document.getElementById('pm-limit').value)).json();
      if(d.error){st.textContent=d.error;return;}render(d);}catch(e){st.textContent='Could not load premarket data.';}};
  window.runPremarket=async function(){var b=document.getElementById('pm-run'),st=document.getElementById('pm-status');
    b.disabled=true;st.textContent='Scanning 165 names · this can take a minute…';
    try{var d=await(await fetch('/premarket/scan',{method:'POST'})).json();if(d.error)throw Error(d.error);render(d);}
    catch(e){st.textContent='Scan failed: '+e.message;}finally{b.disabled=false;}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',loadPremarket);else loadPremarket();
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
    metrics = Div(
        *[Div(Span(label, cls="pm-metric-label"), Div("—", id=key, cls="pm-metric-value"),
              cls="pm-metric") for label, key in (
                  ("Scan time (ET)", "pm-time"), ("Stocks scanned", "pm-scanned"),
                  ("Gainers", "pm-up"), ("Fallers", "pm-down"))],
        cls="pm-metrics",
    )
    body = Div(
        Div(Div(NotStr("<h1>☀ Premarket Intelligence</h1>"),
                Div("165 US stocks · 11 sectors · 04:00–09:30 ET catalysts", cls="pm-sub")),
            Div(Select(Option("Top 5", value="5"), Option("Top 10", value="10", selected=True),
                       Option("Top 20", value="20"), id="pm-limit", onchange="loadPremarket()"),
                Button("Run fresh scan", id="pm-run", cls="pm-btn", onclick="runPremarket()"),
                cls="pm-actions"), cls="pm-head"),
        metrics,
        Div(Div(NotStr("<h2>▲ Top premarket gainers</h2>"), Div(id="pm-gainers"), cls="pm-panel"),
            Div(NotStr("<h2>▼ Top premarket fallers</h2>"), Div(id="pm-fallers"), cls="pm-panel"),
            cls="pm-grid"),
        Div(NotStr("<h2 style='font-size:.9rem;padding:.7rem .8rem;margin:0'>Sector breadth · gainers / fallers</h2>"),
            Div(id="pm-sectors"), cls="pm-sectors"),
        Div("Loading…", id="pm-status", cls="pm-status"),
        Div(Div(id="pm-detail", cls="pm-card"), id="pm-modal", cls="pm-modal",
            onclick="if(event.target===this)closePm()"),
        cls="pm",
    )
    return page("premarket", Style(_CSS), body, Script(_JS), user=user,
                title="Premarket Intelligence · AlpaTrade", right_news=True)


def _payload(report, limit=10):
    from engine.premarket import top_movers
    if not report:
        return {"error": "No premarket scan is available yet. Run a fresh scan.",
                "summary": {}, "sectors": {}, "top": {"gainers": [], "fallers": [], "movers": []}}
    return {**report, "top": top_movers(report, min(max(limit, 1), 25))}


def register(app, rt):
    from engine.web import ph_layout
    entry = ("☀ Premarket", "/premarket", "premarket")
    if entry not in ph_layout.EXPLORE_PAGES:
        ph_layout.EXPLORE_PAGES.append(entry)

    @rt("/premarket", methods=["GET"])
    def premarket_get(session):
        return _page(_user(session))

    @rt("/premarket/data", methods=["GET"])
    def premarket_data(limit: int = 10):
        from engine.premarket import latest_report
        return JSONResponse(_payload(latest_report(), limit))

    @app.post("/premarket/scan")
    async def premarket_scan():
        try:
            import asyncio
            from engine.premarket import scan_premarket
            report = await asyncio.to_thread(scan_premarket)
            return JSONResponse(_payload(report, 10))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=502)

    return ["/premarket", "/premarket/data", "/premarket/scan"]

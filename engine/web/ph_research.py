"""Finespresso Research — FastHTML views over the shared public schema and stored scans."""
from __future__ import annotations

import math

from fasthtml.common import A, Div, NotStr, P, Script, Style
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, RedirectResponse

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}.research{max-width:1180px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.research h1{font-size:1.35rem;margin:.4rem 0 .15rem}.r-sub{font-size:.83rem;color:var(--ink-muted);margin:0 0 1rem}
.r-tabs{display:flex;gap:.4rem;flex-wrap:wrap;margin:.8rem 0 1.2rem}.r-tabs a{font-size:.78rem;padding:.42rem .65rem;
border:1px solid var(--line);border-radius:.45rem;color:var(--ink);text-decoration:none;background:#fff}
.r-tabs a.active{background:var(--accent);color:#fff}.r-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}
.r-card{background:#fff;border:1px solid var(--line);border-radius:.6rem;padding:.8rem;overflow:auto}.r-card.wide{grid-column:1/-1}
.r-card h2{font-size:.92rem;margin:0 0 .65rem}.r-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;margin-bottom:.8rem}
.r-metric{border:1px solid var(--line);border-radius:.5rem;padding:.6rem;background:var(--bg-raise)}
.r-metric b{display:block;font-size:1.05rem}.r-metric span,.r-status{font-size:.74rem;color:var(--ink-muted)}
.r-controls{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.8rem}.r-controls select,.r-controls input,.r-controls button{
font:inherit;font-size:.78rem;border:1px solid var(--line);border-radius:.4rem;padding:.45rem;background:#fff}
.r-controls button{background:var(--accent);color:#fff;cursor:pointer}.r-plot{min-height:390px;width:100%}
.r-table{width:100%;border-collapse:collapse;font-size:.76rem}.r-table th,.r-table td{padding:.4rem;border-bottom:1px solid var(--line);text-align:left}
.r-up{color:#1F5D43}.r-down{color:#B4472F}.r-empty{padding:1.5rem;color:var(--ink-muted);text-align:center}
@media(max-width:760px){.r-grid{grid-template-columns:1fr}.r-card.wide{grid-column:auto}.r-metrics{grid-template-columns:repeat(2,1fr)}}
"""

_TABS = (
    ("Premarket", "/research/premarket", "research-premarket"),
    ("Model Analytics", "/research/models", "research-models"),
    ("News Intelligence", "/research/news", "research-news"),
    ("News Timing", "/research/timing", "research-timing"),
    ("Historical Research", "/research/history", "research-history"),
)


def _json_content(value):
    """Encode dates and PostgreSQL NaNs into strict browser-safe JSON."""
    value = jsonable_encoder(value)
    if isinstance(value, dict):
        return {key: _json_content(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_content(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


def _tabs(active):
    return Div(*[A(label, href=href, cls="active" if key == active else "")
                 for label, href, key in _TABS], cls="r-tabs")


def _shell(active, title, subtitle, script, user=None):
    body = Div(NotStr(f"<h1>{title}</h1>"), P(subtitle, cls="r-sub"), _tabs(active),
               Div(id="research-root", cls="r-grid"),
               Div("Loading shared research data…", id="research-status", cls="r-status"),
               cls="research")
    return page(active, Style(_CSS), body, Script(script), user=user, title=f"{title} · AlpaTrade",
                right_news=active == "research-premarket")


_COMMON_JS = """
const root=document.getElementById('research-root'),status=document.getElementById('research-status');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=n=>n==null?'—':(n>=0?'+':'')+Number(n).toFixed(2)+'%';
const metric=(v,l)=>`<div class="r-metric"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
const card=(title,body,wide='')=>`<section class="r-card ${wide}"><h2>${esc(title)}</h2>${body}</section>`;
async function get(url){let r=await fetch(url);let d=await r.json();if(!r.ok||d.error)throw Error(d.error||r.statusText);return d}
"""

_PREMARKET_JS = _COMMON_JS + """
async function load(){
 try{let run=new URLSearchParams(location.search).get('run_id')||'',d=await get('/research/api/premarket?run_id='+encodeURIComponent(run)),rows=d.rows||[],up=rows.filter(x=>x.movement_pct>0),dn=rows.filter(x=>x.movement_pct<0);
 let tr=a=>`<table class="r-table"><thead><tr><th>Ticker</th><th>Company</th><th>Sector</th><th>Move</th><th>Price</th></tr></thead><tbody>`+
 a.slice(0,20).map(x=>`<tr><td><a href="/research/history?ticker=${esc(x.ticker)}">${esc(x.ticker)}</a></td><td>${esc(x.company_name)}</td><td>${esc(x.sector)}</td><td class="${x.movement_pct>=0?'r-up':'r-down'}">${pct(x.movement_pct)}</td><td>$${Number(x.premarket_close||0).toFixed(2)}</td></tr>`).join('')+'</tbody></table>';
 root.innerHTML=`<div class="r-metrics wide">${metric(rows.length,'Stocks scanned')}${metric(up.length,'Gainers')}${metric(dn.length,'Fallers')}${metric(d.run?.timestamp||'—','Snapshot')}</div>`+
 card('Sector breadth','<div id="breadth" class="r-plot"></div>','wide')+card('Top gainers',tr(up.sort((a,b)=>b.movement_pct-a.movement_pct)))+card('Top fallers',tr(dn.sort((a,b)=>a.movement_pct-b.movement_pct)));
 let sectors={};rows.forEach(x=>{let s=x.sector||'Unknown';sectors[s]??={up:0,down:0};sectors[s][x.movement_pct>=0?'up':'down']++});
 let ys=Object.keys(sectors).sort(),ups=ys.map(y=>sectors[y].up),downs=ys.map(y=>-sectors[y].down);
 Plotly.newPlot('breadth',[{type:'bar',orientation:'h',y:ys,x:downs,name:'Fallers',marker:{color:'#B4472F'}},{type:'bar',orientation:'h',y:ys,x:ups,name:'Gainers',marker:{color:'#1F5D43'}}],
 {barmode:'relative',margin:{l:150,r:20,t:15,b:35},paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1',legend:{orientation:'h'}},{responsive:true,displayModeBar:false});
 status.textContent='Snapshot served from the stored premarket scan report.';
 }catch(e){root.innerHTML=card('No premarket snapshot',`<div class="r-empty">${esc(e.message)}</div>`,'wide');status.textContent='No scans are stored yet — run one from the Premarket page.'}}
load();
"""

_MODELS_JS = _COMMON_JS + """
async function load(){
 try{let d=await get('/research/api/correlations?min_samples=5'),m=await get('/research/api/models');
 root.innerHTML=`<div class="r-metrics wide">${metric(d.count,'Matched predictions')}${metric(d.correlation==null?'—':d.correlation.toFixed(3),'Pearson correlation')}${metric(d.mae==null?'—':d.mae.toFixed(3)+'%','Mean absolute error')}${metric(d.matrix.length,'Qualified slices')}</div>`+
 card('Predicted vs actual move','<div id="scatter" class="r-plot"></div>','wide')+card('Event × industry correlation','<div id="heat" class="r-plot"></div>','wide')+
 card('Direction models',modelTable(m.binary,'binary'))+card('Magnitude models',modelTable(m.regression,'regression'));
 Plotly.newPlot('scatter',[{type:'scattergl',mode:'markers',x:d.points.map(x=>x.predicted),y:d.points.map(x=>x.actual),text:d.points.map(x=>x.event+' · '+x.industry),marker:{color:'#1F5D43',opacity:.55}}],
 {xaxis:{title:'Predicted move %'},yaxis:{title:'Actual next-day move %'},margin:{t:15,r:15,b:55,l:55},paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1',shapes:[{type:'line',x0:-20,y0:-20,x1:20,y1:20,line:{dash:'dash',color:'#7A867E'}}]},{responsive:true,displayModeBar:false});
 let es=[...new Set(d.matrix.map(x=>x.event))],ins=[...new Set(d.matrix.map(x=>x.industry))],lookup={};d.matrix.forEach(x=>lookup[x.event+'|'+x.industry]=x);
 let z=es.map(e=>ins.map(i=>lookup[e+'|'+i]?.correlation??null)),txt=es.map(e=>ins.map(i=>{let x=lookup[e+'|'+i];return x?(x.correlation==null?'—':x.correlation.toFixed(2))+' (n='+x.count+')':''}));
 Plotly.newPlot('heat',[{type:'heatmap',x:ins,y:es,z:z,text:txt,hovertemplate:'%{y} · %{x}<br>%{text}<extra></extra>',colorscale:[[0,'#B4472F'],[.5,'#EFEDE4'],[1,'#1F5D43']],zmin:-1,zmax:1,zmid:0}],
 {height:Math.max(440,es.length*23),margin:{l:170,r:20,t:15,b:110},paper_bgcolor:'#fff'},{responsive:true,displayModeBar:false});
 status.textContent='Model results and realized moves from public schema.';
 }catch(e){root.innerHTML=card('Analytics unavailable',`<div class="r-empty">${esc(e.message)}</div>`,'wide')}
}
function modelTable(rows,type){if(!rows.length)return '<div class="r-empty">No stored model runs.</div>';let cols=type==='binary'?['accuracy','precision','recall','f1']:['r2','mae','rmse'];return `<table class="r-table"><thead><tr><th>Event</th>${cols.map(x=>'<th>'+x.toUpperCase()+'</th>').join('')}<th>Sample</th><th>Version</th></tr></thead><tbody>`+rows.slice(0,50).map(r=>`<tr><td>${esc(r.event)}</td>${cols.map(c=>`<td>${r[c]==null?'—':Number(r[c]).toFixed(3)}</td>`).join('')}<td>${r.test_sample??'—'}</td><td>${esc(r.version||'')}</td></tr>`).join('')+'</tbody></table>'}
load();
"""

_NEWS_JS = _COMMON_JS + """
async function load(){
 let market=new URLSearchParams(location.search).get('market')||'',ticker=new URLSearchParams(location.search).get('ticker')||'';
 try{let d=await get('/research/api/news?market='+encodeURIComponent(market)+'&ticker='+encodeURIComponent(ticker));
 let controls=`<form class="r-controls"><select name="market"><option value="">All markets</option>${['nordics','euronext','baltics','biotech','us'].map(x=>`<option ${market===x?'selected':''}>${x}</option>`)}</select><input name="ticker" value="${esc(ticker)}" placeholder="Ticker"><button>Filter</button></form>`;
 let table=`<table class="r-table"><thead><tr><th>Date</th><th>Market/source</th><th>Ticker</th><th>Event</th><th>Headline</th><th>Prediction</th></tr></thead><tbody>`+d.rows.map(x=>`<tr><td>${esc(String(x.published||'').slice(0,10))}</td><td>${esc(x.publisher)}</td><td>${esc(x.ticker)}</td><td>${esc(x.event)}</td><td><a target="_blank" href="${esc(x.link||'#')}">${esc(x.title)}</a></td><td class="${(x.predicted_move||0)>=0?'r-up':'r-down'}">${pct(x.predicted_move)}</td></tr>`).join('')+'</tbody></table>';
 root.innerHTML=card('All publisher feeds',controls+table,'wide');status.textContent=d.rows.length+' real news items from public.news.';
 }catch(e){root.innerHTML=card('News unavailable',esc(e.message),'wide')}}
load();
"""

_TIMING_JS = _COMMON_JS + """
async function load(){try{let d=await get('/research/api/timing?days=30');root.innerHTML=
 `<div class="r-metrics wide">${metric(d.count,'News items')}${metric(d.days,'Days')}${metric(Math.max(...d.hours),'Peak hourly count')}${metric(Object.entries(d.sessions).sort((a,b)=>b[1]-a[1])[0][0],'Busiest session')}</div>`+
 card('Publication hour distribution','<div id="hours" class="r-plot"></div>','wide')+card('Market-session distribution','<div id="sessions" class="r-plot"></div>','wide');
 Plotly.newPlot('hours',[{type:'bar',x:d.hours.map((_,i)=>i),y:d.hours,marker:{color:'#1F5D43'}}],{xaxis:{title:'Publication hour'},yaxis:{title:'Items'},margin:{t:15,r:15,b:50,l:50},paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1'},{responsive:true,displayModeBar:false});
 Plotly.newPlot('sessions',[{type:'bar',x:Object.keys(d.sessions),y:Object.values(d.sessions),marker:{color:['#C89B3C','#1F5D43','#3E7CB1']}}],{margin:{t:15,r:15,b:45,l:45},paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1'},{responsive:true,displayModeBar:false});
 status.textContent='Timezone reflects stored publication timestamps.'}catch(e){root.innerHTML=card('Timing unavailable',esc(e.message),'wide')}}load();
"""

_HISTORY_JS = _COMMON_JS + """
async function load(){try{let runs=await get('/research/api/runs');let ticker=new URLSearchParams(location.search).get('ticker')||'';
 let rows=runs.rows||[],table=`<form class="r-controls"><input name="ticker" value="${esc(ticker)}" placeholder="Find ticker"><button>Search</button></form><table class="r-table"><thead><tr><th>Date</th><th>Type</th><th>Stocks</th><th>Up</th><th>Down</th><th></th></tr></thead><tbody>`+
 rows.map(x=>`<tr><td>${esc(x.timestamp)}</td><td>${esc(x.scan_type)}</td><td>${x.total_stocks_scanned??'—'}</td><td>${x.total_up_movements??'—'}</td><td>${x.total_down_movements??'—'}</td><td><a href="/research/premarket?run_id=${x.run_id}">Open snapshot</a></td></tr>`).join('')+'</tbody></table>';
 root.innerHTML=card('Premarket scan history',table,'wide');status.textContent='Historical data is read-only.'}catch(e){root.innerHTML=card('History unavailable',esc(e.message),'wide')}}load();
"""


def register(app, rt):
    from engine.web import ph_layout
    for entry in [
        ("☀ Premarket Snapshots", "/research/premarket", "research-premarket"),
        ("🧮 Model Analytics", "/research/models", "research-models"),
        ("📰 News Intelligence", "/research/news", "research-news"),
        ("🕐 News Timing", "/research/timing", "research-timing"),
        ("⌛ Historical Research", "/research/history", "research-history"),
    ]:
        if entry not in ph_layout.RESEARCH_PAGES:
            ph_layout.RESEARCH_PAGES.append(entry)

    @rt("/research", methods=["GET"])
    def research_index():
        return RedirectResponse("/research/premarket", status_code=302)

    @rt("/research/premarket", methods=["GET"])
    def premarket(session):
        return _shell("research-premarket", "☀ Premarket Research",
                      "Sector breadth and movers from the latest premarket scan. "
                      "Fresh scans appear here automatically.",
                      _PREMARKET_JS, _user(session))

    @rt("/research/models", methods=["GET"])
    def models(session):
        return _shell("research-models", "◫ Model Analytics",
                      "Prediction quality, realized moves and event × industry correlation.",
                      _MODELS_JS, _user(session))

    @rt("/research/news", methods=["GET"])
    def news(session):
        return _shell("research-news", "📰 News Intelligence",
                      "Nordic, Euronext, Baltic, biotech and US publisher feeds.",
                      _NEWS_JS, _user(session))

    @rt("/research/timing", methods=["GET"])
    def timing(session):
        return _shell("research-timing", "◷ News Timing",
                      "When market-moving company news is published.", _TIMING_JS, _user(session))

    @rt("/research/history", methods=["GET"])
    def history(session):
        return _shell("research-history", "⌛ Historical Research",
                      "Browse completed premarket scans and locate earlier movers.",
                      _HISTORY_JS, _user(session))

    @rt("/research/api/premarket", methods=["GET"])
    def api_premarket(run_id: str = ""):
        from engine.research.data import premarket_runs, premarket_snapshot
        try:
            runs = premarket_runs(1)
            return JSONResponse(_json_content({"run": runs[0] if runs else None,
                                               "rows": premarket_snapshot(run_id or None)}))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)

    @rt("/research/api/runs", methods=["GET"])
    def api_runs():
        from engine.research.data import premarket_runs
        try:
            return JSONResponse(_json_content({"rows": premarket_runs()}))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)

    @rt("/research/api/news", methods=["GET"])
    def api_news(market: str = "", publisher: str = "", ticker: str = "", days: int = 7):
        from engine.research.data import news_feed
        try:
            return JSONResponse(_json_content(
                {"rows": news_feed(market=market, publisher=publisher, ticker=ticker, days=days)}))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)

    @rt("/research/api/correlations", methods=["GET"])
    def api_correlations(industry: str = "", event: str = "", min_samples: int = 5):
        from engine.research.data import correlation_summary
        try:
            return JSONResponse(_json_content(correlation_summary(industry, event, min_samples)))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)

    @rt("/research/api/models", methods=["GET"])
    def api_models():
        from engine.research.data import model_results
        try:
            return JSONResponse(_json_content(model_results()))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)

    @rt("/research/api/timing", methods=["GET"])
    def api_timing(days: int = 30, market: str = ""):
        from engine.research.data import news_timing
        try:
            return JSONResponse(_json_content(news_timing(days, market)))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)

    return ["/research", *[x[1] for x in _TABS]]

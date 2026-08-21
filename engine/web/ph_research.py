"""Finespresso Research — FastHTML views over the shared ``public`` schema."""
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
.r-warning{grid-column:1/-1;padding:.65rem .8rem;border:1px solid #D9A441;border-radius:.5rem;background:#FFF8E7;
color:#765512;font-size:.78rem}.r-ask{font:inherit;font-size:.7rem;border:1px solid var(--line);border-radius:.35rem;
padding:.28rem .42rem;background:#fff;color:var(--accent);cursor:pointer;white-space:nowrap}.r-ask:hover{border-color:var(--accent)}
.r-detail{font-size:.8rem;line-height:1.5}.r-detail b{color:var(--ink)}.r-catalyst{white-space:pre-wrap;
padding:.65rem;border:1px solid var(--line);border-radius:.45rem;background:var(--bg-raise);margin-top:.55rem}
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
async function get(url){let r=await fetch(url);let d=await r.json();if(!r.ok||d.error){let e=d.message||d.error;
 if(e&&typeof e==='object')e=e.message||e.code;throw Error(e||r.statusText)}return d}
"""

_PREMARKET_JS = _COMMON_JS + """
const money=n=>n==null?'—':'$'+Number(n).toFixed(2);
const volume=n=>n==null?'—':Number(n).toLocaleString();
function scopeUrl(kind,value,d){let p=new URLSearchParams();if(d.source==='public.premarket_scan_results')p.set('run_id',new URLSearchParams(location.search).get('run_id'));
 else if(d.effective_date)p.set('date',d.effective_date);p.set(kind,value);p.set('top_n',new URLSearchParams(location.search).get('top_n')||'10');return '/research/premarket?'+p.toString()}
function askPrompt(x,d){return `Explain ${x.ticker}'s premarket movement and stored catalyst evidence for ${d.effective_date}. Include watch conditions and liquidity or gap-reversal risks.`}
function moverTable(items,d){if(!items.length)return '<div class="r-empty">No matching movers.</div>';
 return `<table class="r-table"><thead><tr><th>Ticker</th><th>Company</th><th>Sector</th><th>Move</th><th>09:00 price</th><th>Volume</th><th></th></tr></thead><tbody>`+
 items.map(x=>`<tr><td><a href="${esc(scopeUrl('ticker',x.ticker,d))}">${esc(x.ticker)}</a></td><td>${esc(x.company_name)}</td><td><a href="${esc(scopeUrl('sector',x.sector,d))}">${esc(x.sector)}</a></td><td class="${x.movement_pct>=0?'r-up':'r-down'}">${pct(x.movement_pct)}</td><td>${money(x.premarket_close)}</td><td>${volume(x.volume)}</td><td><button type="button" class="r-ask" data-prompt="${esc(askPrompt(x,d))}">Ask Premarket Agent</button></td></tr>`).join('')+'</tbody></table>'}
function plotPremarket(c){if(!c||!window.Plotly)return;let breadth=c.breadth||[],names=breadth.map(x=>x.sector).reverse(),by={};breadth.forEach(x=>by[x.sector]=x);
 let movers=(c.gainers||[]).concat(c.fallers||[]).sort((a,b)=>a.movement_pct-b.movement_pct),traces=[
 {type:'bar',orientation:'h',name:'Fallers',x:names.map(n=>-by[n].fallers),y:names,xaxis:'x',yaxis:'y',marker:{color:'#B4472F'},hovertemplate:'%{y}<br>%{x} fallers<extra></extra>'},
 {type:'bar',orientation:'h',name:'Gainers',x:names.map(n=>by[n].gainers),y:names,xaxis:'x',yaxis:'y',marker:{color:'#1F5D43'},hovertemplate:'%{y}<br>%{x} gainers<extra></extra>'},
 {type:'bar',orientation:'h',name:'Mover %',x:movers.map(x=>x.movement_pct),y:movers.map(x=>x.ticker),xaxis:'x2',yaxis:'y2',marker:{color:movers.map(x=>x.movement_pct>=0?'#1F5D43':'#B4472F')},text:movers.map(x=>(x.movement_pct>=0?'+':'')+Number(x.movement_pct).toFixed(2)+'%'),textposition:'outside',cliponaxis:false,hovertemplate:'%{y}<br>%{x:.2f}%<extra></extra>'}
 ];
 let layout={height:650,barmode:'relative',margin:{l:150,r:30,t:35,b:65},paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1',font:{color:'#415046',size:10},legend:{orientation:'h',y:-.1},
 xaxis:{title:'Sector breadth (count)',domain:[0,1],gridcolor:'#E3DFD2',zerolinecolor:'#7A867E'},yaxis:{domain:[.55,1],automargin:true},xaxis2:{title:'Top movers (%)',gridcolor:'#E3DFD2',zerolinecolor:'#7A867E'},yaxis2:{domain:[0,.38],automargin:true}};
 Plotly.newPlot('premarket-overview',traces,layout,{responsive:true,displayModeBar:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d'],toImageButtonOptions:{format:'png',filename:'premarket-overview',width:1200,height:760}})}
async function load(){
 try{let q=new URLSearchParams(location.search),api=new URLSearchParams();['run_id','date','sector','ticker','top_n'].forEach(k=>{if(q.get(k))api.set(k,q.get(k))});api.set('chart','auto');
 let d=await get('/research/api/premarket?'+api.toString()),s=d.summary||{},top=d.top||{gainers:[],fallers:[]},filters=d.filters||{},isArchive=d.source==='public.premarket_scan_results';
 let sectorOptions=['<option value="">All sectors</option>'].concat((d.available_sectors||[]).map(x=>`<option value="${esc(x)}" ${filters.sector===x?'selected':''}>${esc(x)}</option>`)).join('');
 let hidden=isArchive?`<input type="hidden" name="run_id" value="${esc(q.get('run_id')||'')}">`:'';
 let dateControl=isArchive?'':`<input type="date" name="date" value="${esc(q.get('date')||d.effective_date||'')}">`;
 let controls=`<form class="r-controls" method="get">${hidden}${dateControl}<select name="sector">${sectorOptions}</select><select name="top_n">${[5,10,20,50].map(n=>`<option value="${n}" ${Number(q.get('top_n')||10)===n?'selected':''}>Top ${n}</option>`).join('')}</select><button>Apply</button><a class="r-ask" href="/research/premarket">Latest available</a></form>`;
 let warning=d.freshness?.stale||isArchive?`<div class="r-warning">${esc(d.freshness?.message||'Historical archive')}</div>`:'';
 let detail='';if(filters.ticker&&d.rows?.length){let x=d.rows[0];detail=card(`${x.ticker} snapshot`,`<div class="r-detail"><b>${esc(x.company_name)}</b> · ${esc(x.sector)}<br>Prior close ${money(x.prev_close)} → 09:00 ET ${money(x.premarket_close)} (${pct(x.movement_pct)}) · accumulated volume ${volume(x.volume)}<div class="r-catalyst">${esc(x.analysis_excerpt||'No matching stored Grok catalyst analysis for this date.')}</div><button type="button" class="r-ask" data-prompt="${esc(askPrompt(x,d))}">Ask Premarket Agent</button></div>`,'wide')}
 root.innerHTML=warning+card('Snapshot filters',controls,'wide')+`<div class="r-metrics wide">${metric(s.total_stocks_scanned||0,'Valid names')}${metric(s.total_up_movements||0,'Gainers')}${metric(s.total_down_movements||0,'Fallers')}${metric(s.total_unchanged||0,'Unchanged')}</div>`+
 card('Sector breadth and ranked movers','<div id="premarket-overview" class="r-plot"></div>','wide')+detail+card('Top gainers',moverTable(top.gainers||[],d))+card('Top fallers',moverTable(top.fallers||[],d));
 document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>fillChat(b.dataset.prompt));plotPremarket(d.chart);
 status.textContent=`${isArchive?'Legacy archive':'Read-only scheduler snapshot'} · ${d.as_of?String(d.as_of).slice(0,16).replace('T',' ')+' ET':'no observation'} · ${d.freshness?.state||'unknown'} freshness.`;
 }catch(e){root.innerHTML=card('No scheduler snapshot',`<div class="r-empty">${esc(e.message)}</div>`,'wide');status.textContent='No data was written or refreshed.'}}
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
 root.innerHTML=card('Scheduler snapshot history',table,'wide');status.textContent='Historical data is read-only.'}catch(e){root.innerHTML=card('History unavailable',esc(e.message),'wide')}}load();
"""


def register(app, rt):
    from engine.web import ph_layout
    for entry in [
        ("☀ Premarket", "/research/premarket", "research-premarket"),
        ("◫ Model Analytics", "/research/models", "research-models"),
        ("📰 News Intelligence", "/research/news", "research-news"),
        ("◷ News Timing", "/research/timing", "research-timing"),
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
                      "Scheduler snapshots, sector breadth and movers. AlpaTrade never refreshes this dataset.",
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
                      "Browse completed scheduler scans and locate earlier movers.",
                      _HISTORY_JS, _user(session))

    @rt("/research/api/premarket", methods=["GET"])
    def api_premarket(
        run_id: str = "",
        date: str = "",
        sector: str = "",
        ticker: str = "",
        top_n: int = 10,
        chart: str = "auto",
    ):
        from engine.research.data import premarket_run, premarket_snapshot
        from engine.research.premarket import (
            PremarketValidationError,
            build_chart_payload,
            legacy_archive_snapshot,
            read_premarket,
        )
        try:
            if run_id and date:
                return JSONResponse(
                    {"error": "run_id cannot be combined with date"}, status_code=400,
                )
            if run_id:
                run = premarket_run(run_id)
                if not run:
                    return JSONResponse({"error": "Legacy premarket run not found"}, status_code=404)
                snapshot = legacy_archive_snapshot(
                    premarket_snapshot(run_id),
                    run,
                    top_n=top_n,
                    sector=sector or None,
                    ticker=ticker or None,
                )
            else:
                run = None
                snapshot = read_premarket(
                    selected_date=date or None,
                    sector=sector or None,
                    ticker=ticker or None,
                    top_n=top_n,
                )
            return JSONResponse(_json_content({
                **snapshot,
                "run": run,
                "chart": build_chart_payload(snapshot, chart),
            }))
        except PremarketValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception:  # noqa: BLE001
            return JSONResponse(
                {"error": "Premarket scheduler data is unavailable."}, status_code=503,
            )

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

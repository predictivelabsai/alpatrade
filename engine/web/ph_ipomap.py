"""IPO Map + Pipeline dashboards backed by the shared LiquidRound dataset."""
from __future__ import annotations

from fasthtml.common import A, Div, H1, H2, Option, P, Script, Select, Span, Style
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CSS = """

.ipopage{width:100%;max-width:1220px;margin:0 auto;padding:1rem 1.2rem 3rem;overflow:auto}
.ipo-hero{background:linear-gradient(135deg,var(--bg-elev),var(--accent-dim));border:1px solid var(--line);
 border-radius:.8rem;padding:1rem 1.15rem;margin-bottom:1rem}
.ipo-hero h1{font-size:1.45rem;margin:0 0 .25rem;color:var(--ink)}
.ipo-hero p{font-size:.82rem;color:var(--ink-muted);margin:0}
.ip-tabs{display:flex;gap:.5rem;margin-top:.8rem}
.ip-tabs a{font-size:.75rem;text-decoration:none;padding:.3rem .6rem;border:1px solid var(--line);
 border-radius:999px;background:var(--bg-elev)}
.ip-tabs a.active{background:var(--accent);color:white;border-color:var(--accent)}
.ipo-filters{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:.65rem;margin-bottom:.8rem}
.ipo-filter{width:100%;padding:.45rem .55rem;border:1px solid var(--line);border-radius:.45rem;
 background:var(--bg-elev);color:var(--ink);font:inherit;font-size:.76rem}
.ipo-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem;margin:.8rem 0}
.ipo-kpi,.ipo-card{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;padding:.8rem}
.ipo-kpi strong{display:block;font:600 1.2rem var(--font-mono);color:var(--ink)}
.ipo-kpi span{font-size:.67rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-dim)}
.ipo-card{margin:.75rem 0;overflow:auto}
.ipo-card h2{font-size:.88rem;margin:0 0 .55rem;color:var(--ink)}
.ipo-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
.ipo-plot{width:100%;min-height:520px}.ipo-small-plot{width:100%;min-height:330px}
.ipo-legend{display:flex;flex-wrap:wrap;gap:1rem;font-size:.7rem;color:var(--ink-muted);
 background:var(--bg);padding:.55rem;border-radius:.4rem}
.ipo-gradient{width:52px;height:10px;display:inline-block;border-radius:2px;
 background:linear-gradient(90deg,#b83a3a,#d5b64c,#1f6b45);margin-right:.35rem}
.ipo-table{width:100%;border-collapse:collapse;font-size:.72rem}
.ipo-table th{background:var(--ink);color:white;text-align:left;padding:.45rem}
.ipo-table td{padding:.42rem;border-bottom:1px solid var(--line)}
.ipo-pos{color:var(--green);font-weight:600}.ipo-neg{color:var(--red);font-weight:600}
.ipo-status{font-size:.72rem;color:var(--ink-dim);margin:.4rem 0}
.ipo-pl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.65rem}
.ipo-pl-card{border:1px solid var(--line);border-radius:.55rem;padding:.75rem;background:var(--bg)}
.ipo-pl-head{display:flex;justify-content:space-between;gap:.5rem;font-weight:600}
.ipo-pl-val{color:var(--accent);font-family:var(--font-mono)}
.ipo-pl-sector,.ipo-pl-meta,.ipo-pl-summary{font-size:.69rem;color:var(--ink-muted);margin:.35rem 0}
.ipo-pl-bar{display:grid;grid-template-columns:150px 1fr 70px;gap:.5rem;align-items:center;
 font-size:.69rem;margin:.35rem 0}
.ipo-pl-track{height:12px;background:var(--bg-raise);border-radius:3px;overflow:hidden}
.ipo-pl-fill{height:100%;background:var(--accent)}
.ipo-empty{padding:2rem;text-align:center;color:var(--ink-dim)}
@media(max-width:800px){.ipo-filters,.ipo-kpis,.ipo-row{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.ipo-filters,.ipo-kpis,.ipo-row{grid-template-columns:1fr}}
"""

_COMMON_JS = """
function money(v){if(!v)return '—';if(v>=1e12)return '$'+(v/1e12).toFixed(1)+'T';
 if(v>=1e9)return '$'+(v/1e9).toFixed(1)+'B';if(v>=1e6)return '$'+(v/1e6).toFixed(1)+'M';
 return '$'+Number(v).toLocaleString();}
function pct(v){return v==null?'—':(v>=0?'+':'')+Number(v).toFixed(1)+'%';}
function esc(v){var d=document.createElement('div');d.textContent=v==null?'':String(v);return d.innerHTML;}
"""

_MAP_JS = _COMMON_JS + """
(async function(){
 const status=document.getElementById('ipo-status');
 try{
  const payload=await (await fetch('/ipo-map/data')).json(), all=payload.ipos||[];
  const keys=['region','country','exchange','sector'];
  keys.forEach(k=>{const s=document.getElementById('ipo-'+k);
   [...new Set(all.map(x=>x[k]||'Unknown'))].sort().forEach(v=>s.add(new Option(v,v)));});
  function render(){
   const rows=all.filter(x=>keys.every(k=>!document.getElementById('ipo-'+k).value||
     (x[k]||'Unknown')===document.getElementById('ipo-'+k).value));
   const perf=rows.filter(x=>x.return_pct!=null), total=rows.reduce((n,x)=>n+(x.market_cap||0),0);
   const avg=perf.length?perf.reduce((n,x)=>n+x.return_pct,0)/perf.length:null;
   const best=perf.slice().sort((a,b)=>b.return_pct-a.return_pct)[0];
   document.getElementById('ipo-kpis').innerHTML=[
    ['Total IPOs',rows.length],['Avg performance',pct(avg)],['Total market cap',money(total)],
    ['Best performer',best?best.ticker+' '+pct(best.return_pct):'—']
   ].map(x=>'<div class="ipo-kpi"><strong>'+esc(x[1])+'</strong><span>'+x[0]+'</span></div>').join('');
   const ids=[],labels=[],parents=[],values=[],colors=[],text=[],seen={};
   rows.forEach(x=>{const reg=x.region||'Other',country=reg+'/'+(x.country||'Unknown'),
    sec=country+'/'+(x.sector||'Other'),tk=sec+'/'+x.ticker;
    [[reg,reg,''],[country,x.country||'Unknown',reg],[sec,x.sector||'Other',country]].forEach(n=>{
      if(!seen[n[0]]){seen[n[0]]=1;ids.push(n[0]);labels.push(n[1]);parents.push(n[2]);
       values.push(0);colors.push(0);text.push('');}});
    ids.push(tk);labels.push(x.ticker);parents.push(sec);values.push(x.market_cap||1);
    colors.push(x.return_pct||0);text.push(pct(x.return_pct));});
   Plotly.react('ipo-treemap',[{type:'treemap',ids,labels,parents,values,branchvalues:'remainder',
    marker:{colors,colorscale:'RdYlGn',cmid:0},text,texttemplate:'%{label}<br>%{text}',
    hovertemplate:'%{label}<br>%{text}<extra></extra>',tiling:{pad:2}}],
    {margin:{l:0,r:0,t:0,b:0},height:520,paper_bgcolor:'#fff',
     font:{family:'Inter,sans-serif',size:11,color:'#14231B'}},{displayModeBar:false,responsive:true});
   Plotly.react('ipo-distribution',[{type:'histogram',x:perf.map(x=>x.return_pct),nbinsx:20,
    marker:{color:'#1F5D43'}}],{margin:{l:45,r:10,t:10,b:45},height:330,
    xaxis:{title:'Return since IPO (%)'},yaxis:{title:'Companies'},paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1'},
    {displayModeBar:false,responsive:true});
   const sectors={};perf.forEach(x=>{const k=x.sector||'Other';(sectors[k]??=[]).push(x.return_pct);});
   const sr=Object.entries(sectors).map(([k,v])=>[k,v.reduce((a,b)=>a+b,0)/v.length]).sort((a,b)=>a[1]-b[1]);
   Plotly.react('ipo-sectors',[{type:'bar',orientation:'h',y:sr.map(x=>x[0]),x:sr.map(x=>x[1]),
    marker:{color:sr.map(x=>x[1]),colorscale:'RdYlGn',cmid:0}}],
    {margin:{l:110,r:10,t:10,b:45},height:330,xaxis:{title:'Average return (%)'},
     paper_bgcolor:'#fff',plot_bgcolor:'#F7F6F1'},{displayModeBar:false,responsive:true});
   function table(target,data){document.getElementById(target).innerHTML='<table class="ipo-table"><thead><tr>'+
    '<th>Ticker</th><th>Company</th><th>Country</th><th>Sector</th><th>Performance</th><th>Market cap</th>'+
    '</tr></thead><tbody>'+data.map(x=>'<tr><td>'+esc(x.ticker)+'</td><td>'+esc(x.company)+'</td><td>'+
    esc(x.country)+'</td><td>'+esc(x.sector)+'</td><td class="'+(x.return_pct>=0?'ipo-pos':'ipo-neg')+'">'+
    pct(x.return_pct)+'</td><td>'+money(x.market_cap)+'</td></tr>').join('')+'</tbody></table>';}
   const ranked=perf.slice().sort((a,b)=>b.return_pct-a.return_pct);
   table('ipo-top',ranked.slice(0,10));table('ipo-worst',ranked.slice(-10).reverse());
   status.textContent=rows.length+' priced IPOs · hierarchy: region → country → sector → ticker';
  }
  keys.forEach(k=>document.getElementById('ipo-'+k).addEventListener('change',render));render();
 }catch(e){status.textContent='Could not load IPO data: '+e;}
})();
"""

_PIPELINE_JS = _COMMON_JS + """
(async function(){
 const root=document.getElementById('ipo-pipeline-body');
 const ex=v=>(!v||String(v).toUpperCase()==='UNKNOWN')?'—':esc(v);
 try{
  const rows=await (await fetch('/ipo-pipeline/data')).json();
  const privateRows=rows.filter(x=>x.kind==='private'), completed=rows.filter(x=>x.kind==='ipo_completed');
  const upcoming=rows.filter(x=>x.kind!=='private'&&x.kind!=='ipo_completed');
  document.getElementById('pipeline-kpis').innerHTML=[
   ['Private companies',privateRows.length],['Upcoming / filed',upcoming.length],
   ['Recently completed',completed.length],['Tracked valuation',money(privateRows.reduce((n,x)=>n+(x.valuation||0),0))]
  ].map(x=>'<div class="ipo-kpi"><strong>'+esc(x[1])+'</strong><span>'+x[0]+'</span></div>').join('');
  const valued=privateRows.filter(x=>x.valuation).sort((a,b)=>b.valuation-a.valuation),max=valued[0]?.valuation||1;
  document.getElementById('pipeline-bars').innerHTML=valued.map(x=>'<div class="ipo-pl-bar"><span>'+
   esc(x.company)+'</span><div class="ipo-pl-track"><div class="ipo-pl-fill" style="width:'+
   (x.valuation/max*100)+'%"></div></div><b>'+money(x.valuation)+'</b></div>').join('')||'No valuation data.';
  document.getElementById('pipeline-cards').innerHTML=privateRows.map(x=>'<article class="ipo-pl-card">'+
   '<div class="ipo-pl-head"><span>'+esc(x.company)+'</span><span class="ipo-pl-val">'+money(x.valuation)+'</span></div>'+
   '<p class="ipo-pl-sector">'+esc(x.sector||'—')+'</p><p class="ipo-pl-meta">Round: '+esc(x.last_round||'—')+
   ' · Date: '+esc((x.last_round_date||'').slice(0,10)||'—')+' · Rounds: '+esc(x.total_rounds||'—')+
   ' · Staff: '+esc(x.employees||'—')+'</p>'+(x.summary&&!x.summary.trim().startsWith('{')?
   '<p class="ipo-pl-summary">'+esc(x.summary.slice(0,240))+'</p>':'')+
   (x.website?'<a href="'+esc(x.website)+'" target="_blank" rel="noopener">Website ↗</a>':'')+'</article>').join('');
  function completedTable(target,data){document.getElementById(target).innerHTML=data.length?'<table class="ipo-table"><thead><tr>'+
   '<th>Company</th><th>Ticker</th><th>Exchange</th><th>Price</th><th>IPO date</th><th>Since IPO</th>'+
   '</tr></thead><tbody>'+data.map(x=>'<tr><td>'+esc(x.company)+'</td><td>'+esc(x.ticker||'—')+'</td><td>'+
   ex(x.exchange)+'</td><td>'+(x.proposed_price?'$'+Number(x.proposed_price).toFixed(2):'—')+'</td><td>'+
   esc((x.expected_date||'').slice(0,10)||'—')+'</td><td class="'+((x.return_pct==null||x.return_pct>=0)?'ipo-pos':'ipo-neg')+'">'+
   (x.return_pct==null?'—':pct(x.return_pct))+'</td></tr>').join('')+'</tbody></table>':'<div class="ipo-empty">No records.</div>';}
  function upcomingTable(target,data){document.getElementById(target).innerHTML=data.length?'<table class="ipo-table"><thead><tr>'+
   '<th>Company</th><th>Ticker</th><th>Exchange</th><th>Price</th><th>Deal / valuation</th><th>Expected</th><th>Status</th>'+
   '</tr></thead><tbody>'+data.map(x=>'<tr><td>'+esc(x.company)+'</td><td>'+esc(x.ticker||'—')+'</td><td>'+
   ex(x.exchange)+'</td><td>'+(x.proposed_price?'$'+Number(x.proposed_price).toFixed(2):'—')+'</td><td>'+
   money(x.deal_value||x.valuation)+'</td><td>'+esc((x.expected_date||'').slice(0,10)||'—')+'</td><td>'+
   esc(x.status||x.kind||'—')+'</td></tr>').join('')+'</tbody></table>':'<div class="ipo-empty">No records.</div>';}
  completedTable('pipeline-completed',completed);upcomingTable('pipeline-upcoming',upcoming);
  root.textContent=rows.length+' pipeline companies · completed verified against priced IPOs and live quotes';
 }catch(e){root.innerHTML='<div class="ipo-empty">Could not load pipeline: '+esc(e)+'</div>';}
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


def _tabs(active):
    return Div(
        A("IPO Map", href="/ipo-map", cls="active" if active == "map" else ""),
        A("IPO Pipeline", href="/ipo-pipeline", cls="active" if active == "pipeline" else ""),
        cls="ip-tabs",
    )


def _map_page(user):
    body = Div(
        Div(H1("Global IPO heatmap"),
            P("Recent IPOs sized by market cap and colored by performance since listing."),
            _tabs("map"), cls="ipo-hero"),
        Div(
            Select(Option("All regions", value=""), id="ipo-region", cls="ipo-filter", aria_label="Region"),
            Select(Option("All countries", value=""), id="ipo-country", cls="ipo-filter", aria_label="Country"),
            Select(Option("All exchanges", value=""), id="ipo-exchange", cls="ipo-filter", aria_label="Exchange"),
            Select(Option("All sectors", value=""), id="ipo-sector", cls="ipo-filter", aria_label="Sector"),
            cls="ipo-filters",
        ),
        Div(id="ipo-kpis", cls="ipo-kpis"),
        Div(H2("Performance treemap"), Div(id="ipo-treemap", cls="ipo-plot"),
            Div(Span(cls="ipo-gradient"), "Color = return since IPO · Size = market cap · "
                "Hierarchy = region → country → sector → ticker", cls="ipo-legend"),
            cls="ipo-card"),
        Div(
            Div(H2("Performance distribution"), Div(id="ipo-distribution", cls="ipo-small-plot"), cls="ipo-card"),
            Div(H2("Sector performance"), Div(id="ipo-sectors", cls="ipo-small-plot"), cls="ipo-card"),
            cls="ipo-row",
        ),
        Div(
            Div(H2("🚀 Top performers"), Div(id="ipo-top"), cls="ipo-card"),
            Div(H2("📉 Worst performers"), Div(id="ipo-worst"), cls="ipo-card"),
            cls="ipo-row",
        ),
        Div("Loading IPO data…", id="ipo-status", cls="ipo-status"),
        cls="ipopage",
    )
    return page("ipomap", Style(_CSS), body, Script(_MAP_JS), user=user,
                title="IPO Map · AlpaTrade", right_news=False)


def _pipeline_page(user):
    body = Div(
        Div(H1("Companies heading to public markets"),
            P("Private mega-caps and upcoming or filed US IPOs from the shared LiquidRound dataset."),
            _tabs("pipeline"), cls="ipo-hero"),
        Div(id="pipeline-kpis", cls="ipo-kpis"),
        Div(H2("Private valuations"), Div(id="pipeline-bars"), cls="ipo-card"),
        Div(H2("Pre-IPO private companies"), Div(id="pipeline-cards", cls="ipo-pl-grid"), cls="ipo-card"),
        Div(H2("Recently completed IPOs"), Div(id="pipeline-completed"), cls="ipo-card"),
        Div(H2("Upcoming & filed IPOs"), Div(id="pipeline-upcoming"), cls="ipo-card"),
        Div("Loading pipeline…", id="ipo-pipeline-body", cls="ipo-status"),
        cls="ipopage",
    )
    return page("ipopipeline", Style(_CSS), body, Script(_PIPELINE_JS), user=user,
                title="IPO Pipeline · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    for entry in (
        ("🧭 IPO Map", "/ipo-map", "ipomap"),
        ("📋 IPO Pipeline", "/ipo-pipeline", "ipopipeline"),
    ):
        if entry not in ph_layout.PUBLIC_PAGES:
            ph_layout.PUBLIC_PAGES.append(entry)

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

    @rt("/ipo-pipeline/data", methods=["GET"])
    def ipo_pipeline_data_route():
        from engine.publicmarkets.ipo import ipo_pipeline_data
        return JSONResponse(ipo_pipeline_data())

    return ["/ipo-map", "/ipo-map/data", "/ipo-pipeline", "/ipo-pipeline/data"]

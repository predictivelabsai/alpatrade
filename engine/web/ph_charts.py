"""Dedicated charting pages for the merged AlpaTrade app.

Two full-width pages that render through :func:`engine.web.ph_layout.page` so the
parchment / forest shell stays identical to the rest of the app (the news pane is
dropped):

* ``/map``     — finviz-style **market map**: a treemap of S&P sectors/stocks
  coloured by return, sized by liquidity. Period selector; data from ``/map/data``.
* ``/charts``  — **candlestick** price chart (with volume) + a normalised
  multi-ticker **compare** mode. Ticker/period controls; data from ``/charts/data``
  and ``/charts/compare``.

The heavy lifting (universe, batched returns) lives in :mod:`engine.market_map`;
OHLCV comes from :func:`utils.data_loader.get_intraday_data`. Plotly is already
loaded globally by the shell ``<head>``.

Feature-module contract: :func:`register(app, rt)` attaches the routes.
"""
from __future__ import annotations

from typing import Optional

from fasthtml.common import Button, Div, Input, NotStr, Option, Script, Select, Span, Style
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CHARTS_CSS = """
.app{padding-right:0}
.chartpage{max-width:1180px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.chartpage .cp-head{display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:.6rem;margin:.4rem 0 1rem}
.chartpage h1{font-size:1.3rem;margin:0;color:var(--ink)}
.chartpage .cp-sub{font-size:.82rem;color:var(--ink-muted);margin:.15rem 0 0}
.cp-controls{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.cp-controls select,.cp-controls input{font-family:var(--font-body);font-size:.82rem;
  color:var(--ink);background:var(--bg-elev);border:1px solid var(--line);
  border-radius:.4rem;padding:.35rem .55rem}
.cp-controls input{width:15rem}
.cp-btn{font-size:.8rem;color:var(--bg);background:var(--accent);border:0;
  border-radius:.4rem;padding:.4rem .8rem;cursor:pointer}
.cp-btn:hover{opacity:.9}
.cp-seg{display:inline-flex;border:1px solid var(--line);border-radius:.4rem;overflow:hidden}
.cp-seg button{font-size:.8rem;padding:.35rem .7rem;background:var(--bg-elev);
  border:0;color:var(--ink-muted);cursor:pointer}
.cp-seg button.active{background:var(--accent);color:var(--bg)}
.cp-plot{width:100%;min-height:520px;background:#fff;border:1px solid var(--line);
  border-radius:.6rem;padding:.3rem}
.cp-status{font-size:.8rem;color:var(--ink-muted);margin:.5rem 0}
.cp-legend{font-size:.72rem;color:var(--ink-dim);margin-top:.6rem;display:flex;
  align-items:center;gap:.5rem;flex-wrap:wrap}
.cp-swatch{display:inline-block;width:2.4rem;height:.7rem;border-radius:2px;
  background:linear-gradient(90deg,#d47a55,#9aa39c,#2f9a6f)}
"""

_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "ytd"]


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


def _header(title: str, sub: str):
    return Div(
        Div(
            Button("☰", cls="mobile-menu-btn", type="button", onclick="toggleLeftPane()"),
            Span(title, cls="chat-header-title"),
            cls="chat-header-left",
        ),
        Div(NotStr('<a class="news-toggle-btn" href="/equities">Open chat</a>'),
            cls="chat-header-right"),
        cls="chat-header",
    )


# --------------------------------------------------------------------------- map
_MAP_JS = """
(function(){
  function retColor(r){
    if(r==null||isNaN(r)) return '#9AA39C';
    var c=Math.max(-1,Math.min(1,r/6));
    if(c>=0) return 'rgb('+Math.round(122-91*c)+','+Math.round(134+21*c)+','+Math.round(126-59*c)+')';
    var a=-c; return 'rgb('+Math.round(122+58*a)+','+Math.round(134-63*a)+','+Math.round(126-79*a)+')';
  }
  window.loadMap=function(){
    var period=document.getElementById('map-period').value;
    var el=document.getElementById('map-plot');
    var st=document.getElementById('map-status');
    st.textContent='Loading market map ('+period+')…';
    fetch('/map/data?period='+encodeURIComponent(period)).then(function(r){return r.json();})
      .then(function(d){
        if(!d.stocks||!d.stocks.length){ st.textContent='No data.'; return; }
        var ids=[],labels=[],parents=[],values=[],colors=[],texts=[],hovers=[];
        (d.sectors||[]).forEach(function(s){
          ids.push(s.name);labels.push(s.name);parents.push('');values.push(0);
          colors.push(retColor(s.return));
          texts.push('<b>'+s.name+'</b>  '+(s.return>=0?'+':'')+s.return.toFixed(1)+'%');
          hovers.push(s.name+' — '+(s.return>=0?'+':'')+s.return.toFixed(2)+'% ('+s.count+' names)');
        });
        (d.stocks||[]).forEach(function(x){
          ids.push(x.sector+'/'+x.ticker);labels.push(x.ticker);parents.push(x.sector);
          values.push(x.size||1);colors.push(retColor(x.return));
          texts.push(x.ticker+'<br>'+(x.return>=0?'+':'')+x.return.toFixed(1)+'%');
          hovers.push('<b>'+x.ticker+'</b><br>$'+x.price+'<br>'+(x.return>=0?'+':'')+x.return.toFixed(2)+'%');
        });
        var tm={type:'treemap',ids:ids,labels:labels,parents:parents,values:values,
          branchvalues:'remainder',text:texts,textinfo:'text',hovertext:hovers,hoverinfo:'text',
          marker:{colors:colors,line:{width:1,color:'#F7F6F1'}},
          textfont:{color:'#FFFFFF',size:12},pathbar:{visible:true}};
        Plotly.newPlot(el,[tm],{margin:{t:8,l:4,r:4,b:4},paper_bgcolor:'#FFFFFF',
          font:{color:'#415046',size:11}},{responsive:true,displayModeBar:false});
        var up=d.stocks.filter(function(s){return s.return>0;}).length;
        st.textContent=d.stocks.length+' S&P names · '+up+' up / '+(d.stocks.length-up)+
          ' down · sized by liquidity, coloured by '+period+' return.';
      }).catch(function(){ st.textContent='Error loading market map.'; });
  };
  if(document.getElementById('map-plot')) window.loadMap();
})();
"""


def _map_page(user):
    controls = Div(
        Select(*[Option(p, value=p, selected=(p == "1mo")) for p in _PERIODS],
               id="map-period", onchange="loadMap()"),
        Button("Refresh", cls="cp-btn", type="button", onclick="loadMap()"),
        cls="cp-controls",
    )
    body = Div(
        _header("Market Map", "S&P sector returns"),
        Div(
            Div(
                Div(
                    Div("Market Map", cls="", style="font-size:1.3rem;color:var(--ink);font-weight:600"),
                    Div("S&P 500 sectors & stocks — coloured by return, sized by liquidity.",
                        cls="cp-sub"),
                ),
                controls,
                cls="cp-head",
            ),
            Div(id="map-plot", cls="cp-plot"),
            Div(id="map-status", cls="cp-status"),
            Div(Span("Loss", ), Span(cls="cp-swatch"), Span("Gain"),
                Span("· click a sector to zoom, click the top bar to reset", style="margin-left:.4rem"),
                cls="cp-legend"),
            cls="chartpage",
        ),
        cls="center-pane",
    )
    return page("map", Style(_CHARTS_CSS), body, Script(_MAP_JS),
                user=user, title="Market Map · AlpaTrade", right_news=False)


# ------------------------------------------------------------------------ charts
_CHARTS_JS = """
(function(){
  var PALETTE=['#1F5D43','#B4472F','#3E7CB1','#C89B3C','#7A5FA0','#4C9A82','#B4657A','#6E8C4E'];
  var mode='candle';
  window.setChartMode=function(m){
    mode=m;
    document.getElementById('seg-candle').classList.toggle('active',m==='candle');
    document.getElementById('seg-compare').classList.toggle('active',m==='compare');
    document.getElementById('cp-hint').textContent = m==='candle'
      ? 'One ticker — e.g. AAPL' : 'Several tickers — e.g. AAPL, MSFT, NVDA';
    window.loadChart();
  };
  window.loadChart=function(){
    var tks=document.getElementById('cp-ticker').value.trim();
    var period=document.getElementById('cp-period').value;
    var el=document.getElementById('cp-plot');
    var st=document.getElementById('cp-status');
    if(!tks){ st.textContent='Enter a ticker.'; return; }
    st.textContent='Loading…';
    var url = mode==='candle'
      ? '/charts/data?ticker='+encodeURIComponent(tks.split(/[ ,]+/)[0])+'&period='+period
      : '/charts/compare?tickers='+encodeURIComponent(tks)+'&period='+period;
    fetch(url).then(function(r){return r.json();}).then(function(d){
      if(d.error){ st.textContent=d.error; return; }
      var lay={paper_bgcolor:'#FFFFFF',plot_bgcolor:'#F7F6F1',font:{color:'#415046',size:11},
        margin:{t:36,r:15,b:34,l:58}};
      if(mode==='candle'){
        if(!d.dates||!d.dates.length){ st.textContent='No data for '+d.ticker; return; }
        var cs={x:d.dates,open:d.open,high:d.high,low:d.low,close:d.close,type:'candlestick',
          name:d.ticker,increasing:{line:{color:'#1F5D43'}},decreasing:{line:{color:'#B4472F'}},
          xaxis:'x',yaxis:'y'};
        var tr=[cs];
        if(d.volume&&d.volume.length) tr.push({x:d.dates,y:d.volume,type:'bar',name:'Vol',
          xaxis:'x',yaxis:'y2',marker:{color:'rgba(122,134,126,0.35)'}});
        lay.title={text:d.ticker+' — '+d.period,font:{size:13,color:'#14231B'}};
        lay.showlegend=false;
        lay.xaxis={gridcolor:'#E3DFD2',rangeslider:{visible:false}};
        lay.yaxis={gridcolor:'#E3DFD2',tickprefix:'$',domain:[0.24,1]};
        lay.yaxis2={gridcolor:'#F0ECE0',domain:[0,0.18],showticklabels:false};
        Plotly.newPlot(el,tr,lay,{responsive:true,displayModeBar:false});
        st.textContent=d.ticker+' · '+d.dates.length+' bars · '+d.period;
      } else {
        if(!d.series||!d.series.length){ st.textContent='No data.'; return; }
        var ct=d.series.map(function(s,i){var last=s.pct[s.pct.length-1];
          return {x:s.dates,y:s.pct,type:'scatter',mode:'lines',
            name:s.name+' '+(last>=0?'+':'')+last.toFixed(1)+'%',
            line:{color:PALETTE[i%PALETTE.length],width:2}};});
        lay.title={text:'Relative return — '+d.period,font:{size:13,color:'#14231B'}};
        lay.showlegend=true;lay.legend={orientation:'h',y:-0.16};
        lay.xaxis={gridcolor:'#E3DFD2'};
        lay.yaxis={gridcolor:'#E3DFD2',ticksuffix:'%',zeroline:true,zerolinecolor:'#C9C2AE'};
        Plotly.newPlot(el,ct,lay,{responsive:true,displayModeBar:false});
        st.textContent=d.series.length+' tickers · '+d.period;
      }
    }).catch(function(){ st.textContent='Error loading chart.'; });
  };
  if(document.getElementById('cp-plot')) window.loadChart();
})();
"""


def _charts_page(user):
    controls = Div(
        Div(
            Button("Candlestick", id="seg-candle", cls="active", type="button",
                   onclick="setChartMode('candle')"),
            Button("Compare", id="seg-compare", type="button",
                   onclick="setChartMode('compare')"),
            cls="cp-seg",
        ),
        Input(id="cp-ticker", value="AAPL", placeholder="AAPL",
              onkeydown="if(event.key==='Enter')loadChart()"),
        Select(*[Option(p, value=p, selected=(p == "6mo"))
                 for p in ["1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd"]],
               id="cp-period", onchange="loadChart()"),
        Button("Go", cls="cp-btn", type="button", onclick="loadChart()"),
        cls="cp-controls",
    )
    body = Div(
        _header("Charts", "candlestick & compare"),
        Div(
            Div(
                Div(
                    Div("Charts", style="font-size:1.3rem;color:var(--ink);font-weight:600"),
                    Div("Candlestick (OHLC + volume) or normalised multi-ticker compare.",
                        cls="cp-sub", id="cp-hint"),
                ),
                controls,
                cls="cp-head",
            ),
            Div(id="cp-plot", cls="cp-plot"),
            Div(id="cp-status", cls="cp-status"),
            cls="chartpage",
        ),
        cls="center-pane",
    )
    return page("charts", Style(_CHARTS_CSS), body, Script(_CHARTS_JS),
                user=user, title="Charts · AlpaTrade", right_news=False)


# --------------------------------------------------------------------------- data
def _ohlc(ticker: str, period: str) -> dict:
    from utils.data_loader import get_intraday_data
    interval = "1d" if period not in ("1d", "5d") else "5m"
    df = get_intraday_data((ticker or "").upper(), interval=interval, period=period)
    if df.empty:
        return {"ticker": (ticker or "").upper(), "period": period, "error": f"No data for {ticker.upper()}"}
    dates = [d.isoformat() if hasattr(d, "isoformat") else str(d) for d in df.index]
    r = lambda s: [round(float(v), 2) for v in df[s]]  # noqa: E731
    return {"ticker": (ticker or "").upper(), "period": period, "dates": dates,
            "open": r("Open"), "high": r("High"), "low": r("Low"), "close": r("Close"),
            "volume": [int(v) for v in df["Volume"]] if "Volume" in df else []}


def _compare(tickers: str, period: str) -> dict:
    import re
    from utils.data_loader import get_intraday_data
    syms = [t for t in re.split(r"[,\s]+", (tickers or "").upper()) if t][:8]
    series = []
    for sym in syms:
        df = get_intraday_data(sym, interval="1d", period=period)
        if df.empty or len(df) < 2:
            continue
        closes = [float(c) for c in df["Close"]]
        base = closes[0] or closes[-1]
        pct = [round((c - base) / base * 100.0, 2) for c in closes]
        dates = [d.isoformat() if hasattr(d, "isoformat") else str(d) for d in df.index]
        series.append({"name": sym, "dates": dates, "pct": pct})
    return {"period": period, "series": series}


# --------------------------------------------------------------------------- register
def register(app, rt):
    """Attach the market-map + charts pages and their JSON data endpoints."""

    @rt("/map", methods=["GET"])
    def map_get(session):
        return _map_page(_user(session))

    @rt("/map/data", methods=["GET"])
    def map_data(period: str = "1mo"):
        from engine.market_map import market_map_data
        return JSONResponse(market_map_data(period))

    @rt("/charts", methods=["GET"])
    def charts_get(session):
        return _charts_page(_user(session))

    @rt("/charts/data", methods=["GET"])
    def charts_data(ticker: str = "AAPL", period: str = "6mo"):
        return JSONResponse(_ohlc(ticker, period))

    @rt("/charts/compare", methods=["GET"])
    def charts_compare(tickers: str = "AAPL,MSFT", period: str = "6mo"):
        return JSONResponse(_compare(tickers, period))

    return ["/map", "/map/data", "/charts", "/charts/data", "/charts/compare"]

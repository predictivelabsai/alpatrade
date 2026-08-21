"""Core chat/app feature module for the merged AlpaTrade app (pehero skin).

This is the heart of the app, served at ``/app``. It ports the behaviour of the
legacy ``agui_app.py`` (CLI-command interception + LangGraph AI chat) into the
parchment / forest house style via :func:`engine.web.ph_layout.page` and
:func:`engine.web.ph_layout.chat_center`.

Streaming model
---------------
Where ``agui_app`` used a WebSocket + HTMX-OOB widget with its own markup, this
module uses the pehero SSE contract instead so it can live inside the shared
``ph_layout`` skin unchanged:

* The composer built by :func:`ph_layout.chat_center` posts to ``/app/chat`` via
  a client ``window.sendMessage`` (injected here) and reads an
  ``text/event-stream`` response.
* Server events: ``session`` · ``agent_route`` · ``token`` · ``tool_start`` ·
  ``tool_end`` · ``error`` · ``done`` (see :func:`_sse`).

Routing (identical decision logic to ``agui_app``)
--------------------------------------------------
Free-form text streams token-by-token from the primary DeepAgents harness
(``agui_app.primary_agent``, XAI Grok) via ``astream_events(v2)``. Recognised
CLI commands (``trades``/``runs``/``top``/``report``/``monitor``/``research``/
``charts``/``accounts``/``options``, ``agent:*``, ``alpha:*``, ``positions``, ``news:``,
``load:``, ``equity``, ``help`` …) are intercepted by
``agui_app._command_interceptor`` and executed through
``tui.command_processor.CommandProcessor``; the markdown result is streamed as a
single ``token`` block (long-running ``agent:*`` and Alpha Research commands run to completion, then
their result — with an auto-appended equity curve for backtests — is streamed).

Routes registered by :func:`register`
--------------------------------------
* ``GET  /app``        — the chat page (login required, else redirect to /signin).
* ``POST /app/chat``   — the SSE streaming send endpoint.
* ``GET  /news``       — ``MarketResearch().news(...)`` markdown for the right pane.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid as _uuid
from dataclasses import replace
from typing import Optional

from fasthtml.common import A, Button, Div, Script, Span, Style
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse

from engine.web import ph_layout
from engine.agents.routing import agent_override

# --- reuse the legacy AG-UI wiring verbatim --------------------------------
# Importing agui_app builds the primary DeepAgents harness (XAI Grok + StructuredTool
# wrappers), the command-interception logic and the CLI help text. We reuse
# those directly so the routing decisions stay identical to the old app.
import agui_app as _agui
from engine.ai import StreamingCommand

primary_agent = _agui.primary_agent
# Compatibility alias for local helpers/tests written before the harness migration.
langgraph_agent = primary_agent
_command_interceptor = _agui._command_interceptor
_app_state = _agui._app_state

# In-memory per-thread AI history (context for the primary agent). Keyed by the
# thread id stored on the session cookie. Command results are stateless.
_HISTORY: dict[str, list[dict]] = {}
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE helper (kept local so the module has no cross-repo dependency)
# ---------------------------------------------------------------------------
def _sse(name: str, data) -> str:
    """Format one server-sent event."""
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


def _tool_chart_marker(event: dict) -> str:
    """Return a chart marker from a LangChain ``on_tool_end`` event, if any.

    Tool results are context for the model, but chart markers are also a UI
    transport contract.  Models commonly paraphrase the textual part and omit
    the opaque JSON marker, so the server must forward it independently.
    """
    output = event.get("data", {}).get("output", "")
    content = getattr(output, "content", output)
    if isinstance(content, list):
        content = "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    text = str(content or "")
    match = re.search(r"__CHART_DATA__[\s\S]+?__END_CHART__", text)
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# Client JS — defines window.sendMessage for the ph_layout composer, renders
# markdown (marked.js), inline Plotly charts (__CHART_DATA__ markers), table
# toolbars, and parses the News pane markdown after htmx swaps it in.
# ---------------------------------------------------------------------------
CHAT_JS = r"""
(function () {
  var streaming = false;

  function $(s){ return document.querySelector(s); }
  function scrollBottom(){ var m=$('#messages'); if(m) m.scrollTop=m.scrollHeight; }

  function addBubble(role, text, agent){
    var wrap=document.createElement('div');
    wrap.className='msg msg-'+role;
    if(role==='assistant' && agent){
      var hdr=document.createElement('div');
      hdr.className='msg-agent';
      hdr.innerHTML='<span class="msg-agent-icon">◆</span><span class="msg-agent-label">'+agent+'</span>';
      wrap.appendChild(hdr);
    }
    var b=document.createElement('div');
    b.className='msg-bubble';
    b.textContent=text;
    wrap.appendChild(b);
    $('#messages').appendChild(wrap);
    scrollBottom();
    return b;
  }

  function appendTool(bubble, name){
    if(!bubble) return;
    var log=bubble.parentElement.querySelector('.tool-log');
    if(!log){ log=document.createElement('div'); log.className='tool-log'; bubble.parentElement.appendChild(log); }
    var step=document.createElement('div');
    step.className='tool-step';
    step.innerHTML='→ <span class="tool-name">'+name+'</span>';
    log.appendChild(step);
  }

  function setProgress(bubble, message, seconds){
    if(!bubble) return;
    var wrap=bubble.parentElement, p=wrap.querySelector('.chat-progress');
    if(!p){ p=document.createElement('div');p.className='chat-progress';
      p.innerHTML='<span class="progress-dot"></span><span class="progress-text"></span><span class="progress-secs"></span>';
      wrap.insertBefore(p,bubble); }
    p.querySelector('.progress-text').textContent=message||'Working';
    p.querySelector('.progress-secs').textContent=seconds!=null?' '+seconds+'s':'';
  }
  function clearProgress(bubble){
    if(!bubble)return;var p=bubble.parentElement.querySelector('.chat-progress');if(p)p.remove();
  }

  function renderMd(text){ return window.marked ? marked.parse(text) : text; }

  // Pull a __CHART_DATA__{...}__END_CHART__ marker out before markdown runs
  function extractChart(txt, bubble){
    var m=txt.match(/__CHART_DATA__([\s\S]+?)__END_CHART__/);
    if(m){ bubble._chart=m[1]; txt=txt.replace(/__CHART_DATA__[\s\S]*?__END_CHART__/,''); }
    return txt;
  }

  // diverging red→grey→green scale for a % return (finviz style)
  function retColor(r){
    if(r==null||isNaN(r)) return '#9AA39C';
    var c=Math.max(-1,Math.min(1,r/6));   // saturate near ±6%
    if(c>=0) return 'rgb('+Math.round(122-91*c)+','+Math.round(134+21*c)+','+Math.round(126-59*c)+')';
    var a=-c; return 'rgb('+Math.round(122+58*a)+','+Math.round(134-63*a)+','+Math.round(126-79*a)+')';
  }
  var PALETTE=['#1F5D43','#B4472F','#3E7CB1','#C89B3C','#7A5FA0','#4C9A82','#B4657A','#6E8C4E'];

  function renderChart(bubble){
    if(!bubble || !bubble._chart || !window.Plotly) return;
    var data; try{ data=JSON.parse(bubble._chart); }catch(e){ return; }
    var tall=(data.type==='treemap');
    var wrap=document.createElement('div'); wrap.style.cssText='width:100%;margin:.6rem 0;';
    var div=document.createElement('div'); div.style.cssText='width:100%;min-height:'+(tall?'480px':'360px')+';';
    wrap.appendChild(div);
    var dl=document.createElement('button'); dl.textContent='Download PNG'; dl.className='table-action-btn';
    dl.style.marginTop='.4rem';
    var fname={equity_curve:'equity',treemap:'market-map',compare:'compare'}[data.type]||(data.ticker||'chart');
    dl.onclick=function(){ Plotly.downloadImage(div,{format:'png',width:1200,height:tall?720:600,filename:fname}); };
    wrap.appendChild(dl);
    bubble.appendChild(wrap);
    var base={paper_bgcolor:'#FFFFFF',plot_bgcolor:'#F7F6F1',
      font:{color:'#415046',family:'Inter,sans-serif',size:11},
      xaxis:{gridcolor:'#E3DFD2',linecolor:'#E3DFD2'},
      yaxis:{gridcolor:'#E3DFD2',linecolor:'#E3DFD2',tickprefix:'$'},
      legend:{orientation:'h',y:-0.15},margin:{t:38,r:15,b:40,l:60},showlegend:true};

    if(data.type==='treemap'){
      var ids=[],labels=[],parents=[],values=[],colors=[],texts=[],hovers=[];
      (data.sectors||[]).forEach(function(s){
        ids.push(s.name); labels.push(s.name); parents.push(''); values.push(0);
        colors.push(retColor(s.return));
        texts.push(s.name+'  '+(s.return>=0?'+':'')+s.return.toFixed(1)+'%'); hovers.push(s.name);
      });
      (data.stocks||[]).forEach(function(d){
        ids.push(d.sector+'/'+d.ticker); labels.push(d.ticker); parents.push(d.sector);
        values.push(d.size||1); colors.push(retColor(d.return));
        texts.push(d.ticker+'<br>'+(d.return>=0?'+':'')+d.return.toFixed(1)+'%');
        hovers.push(d.ticker+'<br>$'+d.price+'<br>'+(d.return>=0?'+':'')+d.return.toFixed(2)+'%');
      });
      var tm={type:'treemap',ids:ids,labels:labels,parents:parents,values:values,
        branchvalues:'remainder',text:texts,textinfo:'text',hovertext:hovers,hoverinfo:'text',
        marker:{colors:colors,line:{width:1,color:'#F7F6F1'}},textfont:{color:'#FFFFFF',size:11},
        pathbar:{visible:true}};
      Plotly.newPlot(div,[tm],{margin:{t:30,l:4,r:4,b:4},paper_bgcolor:'#FFFFFF',
        title:{text:'Market Map — '+data.period+' returns',font:{size:13,color:'#14231B'}},
        font:{color:'#415046',size:10}},{responsive:true,displayModeBar:false});

    } else if(data.type==='candlestick'){
      var cs={x:data.dates,open:data.open,high:data.high,low:data.low,close:data.close,
        type:'candlestick',name:data.ticker,xaxis:'x',yaxis:'y',
        increasing:{line:{color:'#1F5D43'}},decreasing:{line:{color:'#B4472F'}}};
      var traces=[cs];
      if(data.volume && data.volume.length){
        traces.push({x:data.dates,y:data.volume,type:'bar',name:'Vol',xaxis:'x',yaxis:'y2',
          marker:{color:'rgba(122,134,126,0.35)'}});
      }
      Plotly.newPlot(div,traces,{paper_bgcolor:'#FFFFFF',plot_bgcolor:'#F7F6F1',
        title:{text:data.ticker+' — '+data.period,font:{size:13,color:'#14231B'}},
        font:{color:'#415046',size:11},showlegend:false,margin:{t:38,r:15,b:30,l:58},
        xaxis:{gridcolor:'#E3DFD2',rangeslider:{visible:false}},
        yaxis:{gridcolor:'#E3DFD2',tickprefix:'$',domain:[0.26,1]},
        yaxis2:{gridcolor:'#F0ECE0',domain:[0,0.2],showticklabels:false}},
        {responsive:true,displayModeBar:false});

    } else if(data.type==='compare'){
      var ct=(data.series||[]).map(function(s,i){
        var last=s.pct[s.pct.length-1];
        return {x:s.dates,y:s.pct,type:'scatter',mode:'lines',
          name:s.name+' '+(last>=0?'+':'')+last.toFixed(1)+'%',
          line:{color:PALETTE[i%PALETTE.length],width:2}};
      });
      base.yaxis={gridcolor:'#E3DFD2',ticksuffix:'%',zeroline:true,zerolinecolor:'#C9C2AE'};
      base.title={text:'Relative return — '+data.period,font:{size:13,color:'#14231B'}};
      Plotly.newPlot(div,ct,base,{responsive:true,displayModeBar:false});

    } else if(data.type==='equity_curve'){
      var eq={x:data.dates,y:data.equity,type:'scatter',mode:'lines',name:'Equity',
        line:{color:'#1F5D43',width:2},fill:'tozeroy',fillcolor:'rgba(31,93,67,0.08)'};
      var cap={x:[data.dates[0],data.dates[data.dates.length-1]],
        y:[data.initial_capital,data.initial_capital],type:'scatter',mode:'lines',
        name:'Initial Capital',line:{color:'#7A867E',width:1,dash:'dash'}};
      var fin=data.equity[data.equity.length-1]-data.initial_capital;
      var pct=(fin/data.initial_capital*100).toFixed(1);
      var sign=fin>=0?'+':'';
      base.title={text:'Equity Curve  ('+sign+'$'+fin.toFixed(0)+' / '+sign+pct+'%)',
        font:{size:13,color:'#14231B'}};
      Plotly.newPlot(div,[eq,cap],base,{responsive:true,displayModeBar:false});

    } else if(data.type==='research_correlation_heatmap'){
      var events=[...new Set((data.matrix||[]).map(function(x){return x.event;}))];
      var industries=[...new Set((data.matrix||[]).map(function(x){return x.industry;}))];
      var lookup={};(data.matrix||[]).forEach(function(x){lookup[x.event+'|'+x.industry]=x;});
      var z=events.map(function(e){return industries.map(function(i){
        var x=lookup[e+'|'+i];return x?x.correlation:null;});});
      var tx=events.map(function(e){return industries.map(function(i){
        var x=lookup[e+'|'+i];return x?(x.correlation==null?'—':x.correlation.toFixed(2))+' (n='+x.count+')':'';});});
      Plotly.newPlot(div,[{type:'heatmap',x:industries,y:events,z:z,text:tx,
        hovertemplate:'%{y} · %{x}<br>%{text}<extra></extra>',
        colorscale:[[0,'#B4472F'],[.5,'#EFEDE4'],[1,'#1F5D43']],zmin:-1,zmax:1,zmid:0}],
        {title:{text:'Prediction correlation by event and industry',font:{size:13,color:'#14231B'}},
         height:Math.max(420,events.length*23),margin:{l:160,r:15,t:42,b:100},
         paper_bgcolor:'#FFFFFF',font:{color:'#415046',size:10}},
        {responsive:true,displayModeBar:false});

    } else if(data.type==='research_correlation_scatter'){
      var pts=data.points||[];
      Plotly.newPlot(div,[{type:'scattergl',mode:'markers',
        x:pts.map(function(x){return x.predicted;}),y:pts.map(function(x){return x.actual;}),
        text:pts.map(function(x){return x.event+' · '+x.industry;}),
        marker:{color:'#1F5D43',opacity:.55}}],
        {title:{text:'Predicted vs actual next-day move',font:{size:13,color:'#14231B'}},
         xaxis:{title:'Predicted move %',gridcolor:'#E3DFD2'},
         yaxis:{title:'Actual move %',gridcolor:'#E3DFD2'},
         margin:{t:42,r:15,b:55,l:55},paper_bgcolor:'#FFFFFF',plot_bgcolor:'#F7F6F1'},
        {responsive:true,displayModeBar:false});

    } else {
      var tr={x:data.dates,y:data.close,type:'scatter',mode:'lines',name:data.ticker,
        line:{color:'#1F5D43',width:2},fill:'tozeroy',fillcolor:'rgba(31,93,67,0.08)'};
      base.title={text:data.ticker+' — '+data.period,font:{size:13,color:'#14231B'}};
      base.showlegend=false;
      Plotly.newPlot(div,[tr],base,{responsive:true,displayModeBar:false});
    }
    bubble._chartRendered=true;
    delete bubble._chart;
  }

  function tableCSV(t){
    var rows=[]; t.querySelectorAll('tr').forEach(function(tr){ var c=[];
      tr.querySelectorAll('th,td').forEach(function(td){ c.push('"'+td.textContent.trim().replace(/"/g,'""')+'"'); });
      rows.push(c.join(',')); }); return rows.join('\n');
  }
  function enhanceTables(el){
    if(!el) return;
    el.querySelectorAll('table').forEach(function(t){
      if(t.dataset.enhanced) return; t.dataset.enhanced='1';
      var bar=document.createElement('div'); bar.className='table-toolbar';
      var cp=document.createElement('button'); cp.textContent='Copy CSV'; cp.className='table-action-btn';
      cp.onclick=function(){ navigator.clipboard.writeText(tableCSV(t)).then(function(){
        cp.textContent='Copied!'; setTimeout(function(){cp.textContent='Copy CSV';},1400); }); };
      var dl=document.createElement('button'); dl.textContent='Download CSV'; dl.className='table-action-btn';
      dl.onclick=function(){ var b=new Blob([tableCSV(t)],{type:'text/csv'}); var a=document.createElement('a');
        a.href=URL.createObjectURL(b); a.download='alpatrade-data.csv'; a.click(); URL.revokeObjectURL(a.href); };
      bar.appendChild(cp); bar.appendChild(dl);
      t.parentNode.insertBefore(bar,t);
    });
  }

  function handleEvent(raw, cb){
    var type=null,data='';
    raw.split('\n').forEach(function(line){
      if(line.indexOf('event: ')===0) type=line.slice(7).trim();
      else if(line.indexOf('data: ')===0) data+=line.slice(6);
    });
    if(!type) return;
    try{ cb(type, data?JSON.parse(data):{}); }catch(e){ console.error('bad sse',raw,e); }
  }

  async function sendMessage(evt){
    if(evt && evt.preventDefault) evt.preventDefault();
    if(streaming) return false;
    var ta=$('#chat-input'); if(!ta) return false;
    var msg=ta.value.trim(); if(!msg) return false;

    streaming=true;
    var sb=$('#send-btn'); if(sb) sb.disabled=true;
    var wh=$('#welcome-hero'); if(wh) wh.style.display='none';

    addBubble('user', msg);
    ta.value=''; ta.style.height='';

    var requestedHermes=/^\s*\/hermes(?:\s|$)/i.test(msg);
    var bubble=addBubble('assistant','',requestedHermes?'Hermes':'AlpaTrade AI'), acc='';
    bubble.classList.add('streaming');
    setProgress(bubble,requestedHermes?'Connecting to Hermes...':'Sending request...',0);
    try{
      var resp=await fetch('/app/chat',{method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams({msg:msg})});
      if(!resp.ok){ clearProgress(bubble);bubble.textContent='Error: '+resp.status;
        bubble.classList.remove('streaming');streaming=false;if(sb)sb.disabled=false;return false; }
      var reader=resp.body.getReader(), dec=new TextDecoder(), buf='';
      while(true){
        var r=await reader.read(); if(r.done) break;
        buf+=dec.decode(r.value,{stream:true});
        var idx;
        while((idx=buf.indexOf('\n\n'))!==-1){
          var raw=buf.slice(0,idx); buf=buf.slice(idx+2);
          handleEvent(raw,function(type,p){
            if(type==='agent_route'){
              var lbl=$('#current-agent-label'); if(lbl) lbl.textContent=p.agent||p.slug||'AlpaTrade';
              var al=bubble.parentElement.querySelector('.msg-agent-label');if(al)al.textContent=p.agent||p.slug||'AlpaTrade';
              setProgress(bubble,p.slug==='hermes'?'Hermes connected; preparing request...':'Preparing response...',0);
            } else if(type==='progress'){
              setProgress(bubble,p.message,p.elapsed_seconds);
            } else if(type==='token'){
              clearProgress(bubble);
              acc+=p.text;
              // Chart markers are a UI transport contract, not prose. Render as
              // soon as a complete marker arrives instead of depending on a
              // later `done` event (which can be lost by proxies/buffered SSE).
              if(acc.indexOf('__CHART_DATA__')!==-1 &&
                 acc.indexOf('__END_CHART__')!==-1){
                var clean=extractChart(acc,bubble);
                acc=clean;
                bubble.innerHTML=clean.trim()?renderMd(clean):'';
                enhanceTables(bubble); renderChart(bubble);
              } else {
                bubble.innerHTML=renderMd(acc);
              }
              scrollBottom();
            } else if(type==='tool_start'){
              appendTool(bubble||(bubble=addBubble('assistant','','')), p.name);
              setProgress(bubble,'Using '+(p.name||'tool')+'...');
            } else if(type==='tool_end'){
              setProgress(bubble,'Tool finished; preparing answer...');
            } else if(type==='error'){
              clearProgress(bubble);
              if(!bubble) bubble=addBubble('assistant','','');
              bubble.textContent='Error: '+(p.message||'unknown');
            } else if(type==='done'){
              clearProgress(bubble);
              if(bubble){
                bubble.classList.remove('streaming');
                var t=extractChart(acc,bubble);
                // Incremental chart rendering may already have appended Plotly.
                // Do not destroy it when the final SSE event arrives.
                if(!bubble._chartRendered)
                  bubble.innerHTML=t.trim()?renderMd(t):bubble.innerHTML;
                enhanceTables(bubble); renderChart(bubble);
              }
            }
          });
        }
      }
    }catch(e){
      clearProgress(bubble);
      if(!bubble) bubble=addBubble('assistant','','');
      bubble.textContent='Error: '+e;
    }
    streaming=false; if(sb) sb.disabled=false;
    if(window.htmx) htmx.ajax('GET','/app/chats',{target:'#session-list',swap:'innerHTML'});
    var ta2=$('#chat-input'); if(ta2) ta2.focus();
    scrollBottom();
    return false;
  }
  window.sendMessage=sendMessage;

  window.deleteChat=async function(tid,evt){
    if(evt){evt.preventDefault();evt.stopPropagation();}
    if(!confirm('Delete this chat?'))return;
    var r=await fetch('/app/chats/'+encodeURIComponent(tid),{method:'DELETE'});
    if(r.ok){var active=window.ALPA_THREAD_ID;if(active===tid)window.location.href='/app?new=1';
      else if(window.htmx)htmx.ajax('GET','/app/chats',{target:'#session-list',swap:'innerHTML'});}
  };

  async function loadConversationList(){
    var host=$('#session-list');if(!host)return;
    try{var r=await fetch('/app/chats',{cache:'no-store'});if(!r.ok)return;
      host.innerHTML=await r.text();
    }catch(e){console.warn('chat list unavailable',e);}
  }
  loadConversationList();
  window.addEventListener('pageshow',loadConversationList);

  var lastHistoryId=null;
  async function loadSavedMessages(force){
    var host=$('#messages');if(!host||streaming)return;
    var tid=window.ALPA_THREAD_ID||'';
    try{var r=await fetch('/app/chat/history?thread='+encodeURIComponent(tid),{cache:'no-store'});
      if(!r.ok)return;var data=await r.json();
      var messages=data.messages||[],last=messages.length?messages[messages.length-1].message_id:null;
      if(!force&&last===lastHistoryId)return;
      host.innerHTML='';
      messages.forEach(function(m){var b=addBubble(m.role,m.content,m.metadata&&m.metadata.agent);
        if(m.role==='assistant'){var clean=extractChart(m.content,b);b.innerHTML=renderMd(clean);enhanceTables(b);renderChart(b);}});
      lastHistoryId=last;
    }catch(e){console.warn('chat history unavailable',e);}
  }
  loadSavedMessages(true);
  setInterval(function(){loadSavedMessages(false);},5000);

  // News pane now returns ready-made HTML cards (see /news) — no markdown step.
})();
"""

# Minimal styles for the tool-call log + streaming cursor inside bubbles
# (parchment/forest tokens; class names not present in app.css).
CHAT_STYLE = """
.tool-log { margin-top:.4rem; display:flex; flex-direction:column; gap:.15rem; }
.tool-step { font-family:var(--font-mono); font-size:.68rem; color:var(--ink-dim); }
.tool-step .tool-name { color:var(--accent); }
.chat-progress { display:flex;align-items:center;gap:.42rem;margin:.1rem 0 .45rem;
  color:var(--ink-dim);font:600 .67rem var(--font-mono); }
.progress-dot { width:7px;height:7px;border-radius:50%;background:var(--accent);
  animation:pulse 1.1s ease-in-out infinite; }
.progress-secs { color:var(--ink-muted);font-weight:400; }
.news-category { border-bottom:1px solid var(--line); }
.news-category-title { padding:.65rem .2rem; cursor:pointer; font-size:.74rem;
  color:var(--ink); font-weight:650; list-style:none; }
.news-category-title::-webkit-details-marker { display:none; }
.pm-news-up { color:#1F7A4D; }.pm-news-down { color:#B4472F; }
"""


# ---------------------------------------------------------------------------
# SSE streaming send handler
# ---------------------------------------------------------------------------
def _load_owned_history(thread_id: str, user_id: str) -> list[dict]:
    """Load one user's persisted thread without making DB failure fatal."""
    try:
        from engine.ai.chat_store import load_conversation_messages
        return [
            {"role": row["role"], "content": row["content"]}
            for row in load_conversation_messages(thread_id, user_id=user_id)
            if row["role"] in {"user", "assistant"}
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load chat %s: %s", thread_id, exc)
        return []


def _save_chat_message(
    thread_id: str,
    user_id: str,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
) -> None:
    """Persist one account-owned message without taking chat offline on errors."""
    if not user_id or not content:
        return
    try:
        from engine.ai.chat_store import save_conversation, save_message
        save_conversation(thread_id, user_id=user_id)
        save_message(thread_id, role, content, metadata=metadata)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist chat %s message: %s", thread_id, exc)


def _hermes_backtest_config(message: str) -> Optional[dict]:
    """Parse the stable subset of natural-language Hermes backtest commands."""
    if not re.search(r"\bbacktest\b", message, re.IGNORECASE):
        return None
    lowered = message.lower().strip()
    read_words = ("show", "result", "details", "parameters", "params", "period", "status")
    if any(word in lowered for word in read_words):
        return None
    action = re.search(
        r"\b(start|run|queue|launch|execute|perform|optimi[sz]e)\b",
        lowered,
    )
    if not action and not lowered.startswith("backtest"):
        return None
    symbols = []
    for symbol in re.findall(r"\b[A-Z]{1,5}\b", message):
        if symbol not in symbols and symbol not in {"HERMES", "USD", "PDT"}:
            symbols.append(symbol)
    period = re.search(
        r"\b(\d+)\s*(day|days|month|months|year|years)\b", message, re.IGNORECASE
    )
    lookback = "3m"
    if period:
        amount, unit = int(period.group(1)), period.group(2).lower()
        suffix = "d" if unit.startswith("day") else "m" if unit.startswith("month") else "y"
        lookback = f"{amount}{suffix}"
    strategy = "buy_the_dip"
    for supported in ("buy_the_dip", "momentum", "vix", "box_wedge"):
        if supported in message.lower():
            strategy = supported
            break
    return {
        "lookback": lookback,
        "strategy": strategy,
        "symbols": symbols or ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"],
        "objective": {"maximize": "sharpe_ratio"},
        "agent_name": "Hermes",
        "agent_framework": "hermes",
    }


async def _dispatch_hermes_job_command(
    message: str, user_id: str, thread_id: str
) -> Optional[str]:
    """Handle durable Hermes operations before invoking the remote model."""
    lowered = message.lower()
    uuids = re.findall(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        lowered,
    )
    control_match = re.search(r"\b(pause|resume|stop)\b", lowered)
    if control_match and "paper" in lowered and uuids:
        from engine.agents.hermes_jobs import request_control
        action = control_match.group(1)
        job = await asyncio.to_thread(request_control, uuids[0], user_id, action)
        if not job:
            return (
                "## Hermes paper control\n\nNo matching active paper job was found "
                "under your account."
            )
        action_label = {"pause": "paused", "resume": "resumed", "stop": "stop requested"}[action]
        return (
            f"## Hermes paper job {action_label}\n\n"
            f"- **Job ID:** `{job['job_id']}`\n"
            f"- **Run ID:** `{job['run_id']}`\n"
            f"- **Status:** `{job['status']}`\n"
            f"- **Candidate ID:** `{job.get('candidate_id') or 'n/a'}`"
        )

    candidate_action = re.search(r"\b(start|run|launch|trade|promote)\b", lowered)
    starting_candidate = (
        ("candidate" in lowered or "best param" in lowered)
        and "paper" in lowered
        and bool(candidate_action)
        and (
            candidate_action.group(1) != "run"
            or bool(uuids)
            or lowered.startswith("run ")
        )
    )
    if (
        "paper" in lowered and "email" in lowered and "report" in lowered
        and uuids and not starting_candidate
    ):
        from engine.agents.hermes_jobs import set_email_reports
        disabled = any(word in lowered for word in ("disable", "off", "stop email", "cancel email"))
        job = await asyncio.to_thread(set_email_reports, uuids[0], user_id, not disabled)
        if not job:
            return "## Hermes reports\n\nNo matching active paper job was found under your account."
        state = "disabled" if disabled else "enabled daily for your login email"
        return (
            "## Hermes paper reports updated\n\n"
            f"- **Job ID:** `{job['job_id']}`\n"
            f"- **Status:** `{job['status']}`\n"
            f"- **Email reports:** {state}"
        )

    if starting_candidate:
        from engine.agents.hermes_jobs import enqueue_candidate_paper
        candidate_id = uuids[0] if uuids else ""
        if not candidate_id:
            from engine.agents.hermes_jobs import list_owned
            completed = [
                item for item in await asyncio.to_thread(list_owned, user_id)
                if item.get("kind") == "backtest" and item.get("status") == "completed"
                and item.get("candidate_id")
            ]
            completed.sort(
                key=lambda item: float(
                    ((item.get("result") or {}).get("best_config") or {}).get("sharpe_ratio")
                    or float("-inf")
                ),
                reverse=True,
            )
            if not completed:
                return "## Hermes paper trading\n\nNo completed owned candidate was found."
            candidate_id = str(completed[0]["candidate_id"])
        period = re.search(r"\b(\d+)\s*(day|days|week|weeks|month|months|year|years)\b", lowered)
        duration = "365d" if "continuous" in lowered or "continuously" in lowered else "7d"
        if period:
            amount, unit = int(period.group(1)), period.group(2)
            multiplier = 1 if unit.startswith("day") else 7 if unit.startswith("week") else 30 if unit.startswith("month") else 365
            duration = f"{amount * multiplier}d"
        poll_match = re.search(r"\b(?:every|poll)\s+(\d+)\s*(?:seconds?|secs?|s)\b", lowered)
        poll = max(15, int(poll_match.group(1))) if poll_match else 60
        email_reports = "email" in lowered and any(
            word in lowered for word in ("report", "daily", "notify", "notification")
        )
        job = await asyncio.to_thread(
            enqueue_candidate_paper,
            candidate_id, user_id, thread_id,
            duration=duration, poll=poll, email_reports=email_reports,
        )
        report = "daily reports enabled for your login email" if email_reports else "email reports disabled"
        return (
            "## Hermes paper trading queued\n\n"
            f"- **Job ID:** `{job['job_id']}`\n"
            f"- **Run ID:** `{job['run_id']}`\n"
            f"- **Candidate ID:** `{job['candidate_id']}`\n"
            f"- **Status:** `{job['status']}`\n"
            f"- **Duration:** `{duration}`\n"
            f"- **Poll interval:** `{poll}s`\n"
            f"- **Reports:** {report}\n\n"
            "Paper mode only. Use `/hermes pause paper job <job-id>`, "
            "`resume`, or `stop` to control it."
        )

    if "job" in lowered and any(word in lowered for word in ("show", "list", "running", "status")):
        from engine.agents.hermes_jobs import list_owned
        jobs = await asyncio.to_thread(list_owned, user_id)
        if not jobs:
            return "## Hermes jobs\n\nNo queued, running, or completed jobs were found for your account."
        lines = ["## Hermes jobs", ""]
        for job in jobs[:20]:
            progress = (job.get("progress") or {}).get("message", "")
            candidate = f" · candidate `{job['candidate_id']}`" if job.get("candidate_id") else ""
            reports = ""
            if job.get("kind") == "paper" and (job.get("config") or {}).get("email_notifications"):
                reports = " · daily email on"
            lines.append(
                f"- **{job['kind']} · {job['status']}** — job `{job['job_id']}` · "
                f"run `{job['run_id']}`{candidate}"
                + reports + (f" · {progress}" if progress else "")
            )
        return "\n".join(lines)

    if "backtest" in lowered and any(
        word in lowered for word in ("show", "result", "details", "parameters", "params", "period")
    ):
        from engine.agents.hermes_jobs import list_owned
        jobs = await asyncio.to_thread(list_owned, user_id)
        ids = set(uuids)
        matches = [
            job for job in jobs
            if job.get("kind") == "backtest"
            and (not ids or str(job.get("job_id")) in ids or str(job.get("run_id")) in ids)
        ]
        job = next((item for item in matches if item.get("status") == "completed"), None)
        if job is None:
            return "## Hermes backtest result\n\nNo matching completed backtest was found."
        config = job.get("config") or {}
        result = job.get("result") or {}
        best = result.get("best_config") or {}
        return (
            "## Hermes backtest result\n\n"
            f"- **Job ID:** `{job['job_id']}`\n"
            f"- **Run ID:** `{job['run_id']}`\n"
            f"- **Candidate ID:** `{job.get('candidate_id') or 'not created'}`\n"
            f"- **Status:** `{job['status']}`\n"
            f"- **Strategy:** `{config.get('strategy', 'buy_the_dip')}`\n"
            f"- **Data period:** `{config.get('lookback', 'not recorded')}`\n"
            f"- **Symbols:** {', '.join(config.get('symbols') or [])}\n"
            f"- **Best parameters:** `{json.dumps(best.get('params') or {}, default=str)}`\n"
            f"- **Sharpe ratio:** {best.get('sharpe_ratio', 'n/a')}\n"
            f"- **Total return:** {best.get('total_return', 'n/a')}\n"
            f"- **Maximum drawdown:** {best.get('max_drawdown', 'n/a')}\n"
            f"- **Win rate:** {best.get('win_rate', 'n/a')}\n"
            f"- **Trades:** {best.get('total_trades', 'n/a')}"
        )

    config = _hermes_backtest_config(message)
    if config is None:
        return None
    from engine.agents.hermes_jobs import enqueue
    job = await asyncio.to_thread(
        enqueue, "backtest", user_id, thread_id, config
    )
    return (
        "## Hermes backtest queued\n\n"
        f"- **Job ID:** `{job['job_id']}`\n"
        f"- **Run ID:** `{job['run_id']}`\n"
        f"- **Status:** `{job['status']}`\n"
        f"- **Strategy:** `{config['strategy']}`\n"
        f"- **Lookback:** `{config['lookback']}`\n"
        f"- **Symbols:** {', '.join(config['symbols'])}\n\n"
        "The backtest is running in the background. You may leave this page; "
        "Hermes will add the candidate and metrics to this saved chat when it finishes."
    )


async def _stream(msg: str, session) -> StreamingResponse:
    """Return an SSE StreamingResponse for one user message.

    Snapshot the session up front (the generator runs after the request scope),
    build a legacy-shaped compat session for the reused interceptor, then either
    stream the primary agent harness (free-form) or a single command result.
    """
    uid = session.get("user_id")
    thread_id = session.get("thread_id") or str(_uuid.uuid4())
    runtime_override, routed_msg = agent_override(msg)

    # agui_app's interceptor + CommandProcessor read session["user"]["user_id"].
    compat = dict(session)
    if uid is not None:
        compat["user"] = {"user_id": str(uid)}

    async def gen():
        yield _sse("session", {"sid": thread_id})
        user_key = str(uid) if uid is not None else ""
        history = _HISTORY.get(thread_id)
        if history is None:
            history = _load_owned_history(thread_id, user_key) if user_key else []
            _HISTORY[thread_id] = history
        _save_chat_message(thread_id, user_key, "user", msg)

        # Durable trading commands are deterministic: queue them before asking
        # the remote Hermes model, so job creation never waits on model planning,
        # terminal approvals, retries, or context compression.
        if runtime_override == "hermes" and routed_msg:
            try:
                broker_reply = await _dispatch_hermes_job_command(
                    routed_msg, user_key, thread_id
                )
            except Exception as exc:  # noqa: BLE001
                message = f"Could not queue Hermes job: {exc}"
                yield _sse("agent_route", {"slug": "hermes", "agent": "Hermes"})
                yield _sse("error", {"message": message})
                _save_chat_message(
                    thread_id, user_key, "assistant", f"Error: {message}",
                    {"agent": "Hermes", "framework": "hermes", "error": True},
                )
                yield _sse("done", {})
                return
            if broker_reply is not None:
                yield _sse("agent_route", {"slug": "hermes", "agent": "Hermes"})
                yield _sse("token", {"text": broker_reply})
                history.append({"role": "user", "content": routed_msg})
                history.append({"role": "assistant", "content": broker_reply})
                _save_chat_message(
                    thread_id, user_key, "assistant", broker_reply,
                    {"agent": "Hermes", "framework": "hermes", "dispatch": "job"},
                )
                yield _sse("done", {})
                return

        if runtime_override and not routed_msg:
            yield _sse("agent_route", {
                "slug": runtime_override,
                "agent": runtime_override.title(),
            })
            yield _sse("token", {
                "text": f"Usage: `/{runtime_override} your request`",
            })
            _save_chat_message(
                thread_id, user_key, "assistant",
                f"Usage: `/{runtime_override} your request`",
                {"agent": runtime_override.title(), "framework": runtime_override},
            )
            yield _sse("done", {})
            return

        # 1) CLI command interception (identical logic to agui_app)
        result = None
        if runtime_override is None:
            try:
                result = await _command_interceptor(msg, compat)
            except Exception as e:  # noqa: BLE001
                yield _sse("error", {"message": f"command failed: {e}"})
                yield _sse("done", {})
                return

        if result is not None:
            yield _sse("agent_route", {"slug": "command", "agent": "Command"})
            md = ""
            try:
                if isinstance(result, StreamingCommand):
                    # Long-running agent:* command — run to completion, then emit.
                    from tui.command_processor import CommandProcessor
                    cp = CommandProcessor(result.app_state, user_id=uid)
                    md = await cp.process_command(result.raw_command)
                    md = md or "Command executed."
                    md = _maybe_append_equity(msg, md)
                else:
                    md = result
            except Exception as e:  # noqa: BLE001
                md = f"# Error\n\n```\n{e}\n```"
            yield _sse("token", {"text": md})
            _save_chat_message(
                thread_id, user_key, "assistant", md,
                {"agent": "Command", "framework": "command"},
            )
            yield _sse("done", {})
            return

        # 2) Free-form text → stream the primary agent harness
        from engine.agents.runtime import get_runtime
        from engine.config import build_chat_model, get_settings

        settings = get_settings(str(uid) if uid is not None else None)
        selected_framework = runtime_override or settings.agent_framework
        display_name = "Hermes" if selected_framework == "hermes" else "AlpaTrade AI"
        yield _sse("agent_route", {
            "slug": selected_framework,
            "agent": display_name,
        })
        yield _sse("progress", {
            "message": (
                "Hermes connected; preparing tools"
                if selected_framework == "hermes"
                else "Preparing model and tools"
            ),
            "elapsed_seconds": 0,
        })
        # Framework overrides share the same thread context, so a user can ask
        # Hermes to inspect the preceding discussion and then return to the default.
        history.append({"role": "user", "content": routed_msg})

        from langchain_core.messages import HumanMessage, AIMessage
        lc = [
            HumanMessage(content=m["content"]) if m["role"] == "user"
            else AIMessage(content=m["content"])
            for m in history
        ]

        full = ""
        tool_chart = ""
        try:
            runtime = get_runtime(selected_framework)
            if runtime_override:
                model = None if selected_framework == "hermes" else build_chat_model(
                    settings, streaming=True
                )
                role = _agui._chat_role(model)
                if selected_framework == "hermes":
                    if uid is None:
                        raise PermissionError("Sign in before using Hermes trading tools")
                    from engine.agents.hermes_access import hermes_system_instructions
                    role = replace(
                        role,
                        instructions=role.instructions + hermes_system_instructions(
                            str(uid), thread_id
                        ),
                    )
                agent = runtime.build(role)
            else:
                agent = _agui.agent_for_user(str(uid) if uid is not None else None)
            if hasattr(agent, "astream_events"):
                # LangGraph-family runtimes: fine-grained token + tool events (default path).
                async for event in agent.astream_events({"messages": lc}, version="v2"):
                    kind = event.get("event", "")
                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk is not None and getattr(chunk, "content", ""):
                            full += chunk.content
                            yield _sse("token", {"text": chunk.content})
                    elif kind == "on_tool_start":
                        yield _sse("tool_start", {"name": event.get("name", "tool")})
                    elif kind == "on_tool_end":
                        marker = _tool_chart_marker(event)
                        if marker:
                            tool_chart = marker
                        yield _sse("tool_end", {"name": event.get("name", "tool")})
            elif hasattr(runtime, "astream"):
                # Remote gateways may be silent while their model or tools work.
                # Pump chunks in the background so the UI still receives honest
                # elapsed-time status events instead of an unexplained cursor.
                queue: asyncio.Queue = asyncio.Queue()

                async def pump_remote() -> None:
                    try:
                        async for item in runtime.astream(
                            agent,
                            routed_msg,
                            # Hermes already persists this stable session. Sending
                            # browser history again duplicates context every turn.
                            history=None,
                            session_id=f"alpatrade:{thread_id}",
                            session_key=f"alpatrade-user:{uid or 'anonymous'}",
                        ):
                            await queue.put(("chunk", item))
                    except Exception as remote_error:  # noqa: BLE001
                        await queue.put(("error", remote_error))
                    finally:
                        await queue.put(("done", None))

                started = time.monotonic()
                remote_task = asyncio.create_task(pump_remote())
                try:
                    while True:
                        try:
                            kind, value = await asyncio.wait_for(queue.get(), timeout=2.0)
                        except TimeoutError:
                            elapsed = int(time.monotonic() - started)
                            if elapsed < 8:
                                status = "Hermes is planning the request"
                            elif elapsed < 30:
                                status = "Hermes is running tools or waiting for data"
                            else:
                                status = "Backtest still running; waiting for results"
                            yield _sse("progress", {
                                "message": status,
                                "elapsed_seconds": elapsed,
                            })
                            continue
                        if kind == "chunk":
                            full += str(value)
                            yield _sse("token", {"text": str(value)})
                        elif kind == "error":
                            raise value
                        else:
                            break
                finally:
                    if not remote_task.done():
                        remote_task.cancel()
            else:
                # Non-LangGraph runtime (e.g. pydantic_ai): no event stream → single-shot.
                import asyncio as _asyncio
                res = await _asyncio.to_thread(
                    runtime.run, agent, routed_msg, history=history[:-1])
                full = res.text
                yield _sse("token", {"text": full})
        except Exception as e:  # noqa: BLE001
            # Hermes is an optional sidecar. If it fails before emitting content,
            # transparently return to DeepAgents so chat remains available.
            if selected_framework == "hermes" and not full:
                yield _sse("agent_route", {
                    "slug": "deepagents",
                    "agent": "AlpaTrade AI (Hermes unavailable)",
                })
                try:
                    fallback_runtime = get_runtime("deepagents")
                    fallback = fallback_runtime.build(
                        _agui._chat_role(build_chat_model(settings, streaming=True))
                    )
                    async for event in fallback.astream_events({"messages": lc}, version="v2"):
                        if event.get("event", "") == "on_chat_model_stream":
                            chunk = event.get("data", {}).get("chunk")
                            text = getattr(chunk, "content", "") if chunk is not None else ""
                            if text:
                                full += text
                                yield _sse("token", {"text": text})
                except Exception as fallback_error:  # noqa: BLE001
                    message = f"Hermes unavailable ({e}); fallback failed ({fallback_error})"
                    yield _sse("error", {"message": message})
                    history.append({"role": "assistant", "content": f"Error: {message}"})
                    _save_chat_message(
                        thread_id, user_key, "assistant", f"Error: {message}",
                        {"agent": "Hermes", "framework": "hermes", "error": True},
                    )
                    yield _sse("done", {})
                    return
            else:
                yield _sse("error", {"message": str(e)})
                history.append({"role": "assistant", "content": f"Error: {e}"})
                _save_chat_message(
                    thread_id, user_key, "assistant", f"Error: {e}",
                    {"agent": display_name, "framework": selected_framework,
                     "error": True},
                )
                yield _sse("done", {})
                return

        if tool_chart and "__CHART_DATA__" not in full:
            full += "\n\n" + tool_chart
            yield _sse("token", {"text": "\n\n" + tool_chart})
        history.append({"role": "assistant", "content": full})
        _save_chat_message(
            thread_id, user_key, "assistant", full,
            {"agent": display_name, "framework": selected_framework},
        )
        yield _sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _maybe_append_equity(msg: str, result: str) -> str:
    """For a successful backtest, append its equity-curve chart marker (parity
    with agui_app._handle_streaming_command)."""
    first = msg.strip().lower().split()[0] if msg.strip() else ""
    if not first.startswith("agent:backtest"):
        return result
    if not result or result[:20].lower().count("error"):
        return result
    try:
        m = re.search(r"Run ID\*?\*?:?\s*`?([a-f0-9-]+)", result)
        if m:
            from utils.equity_chart import show_equity_curve
            eq = show_equity_curve(run_id=m.group(1))
            if "__CHART_DATA__" in eq:
                result += "\n\n" + eq
    except Exception:  # noqa: BLE001
        pass
    return result


# ---------------------------------------------------------------------------
# register(app, rt) — feature-module contract
# ---------------------------------------------------------------------------
def register(app, rt):
    """Wire the core chat routes into the shared FastHTML app."""

    def _current_user(session) -> Optional[dict]:
        uid = session.get("user_id")
        if not uid:
            return None
        try:
            from engine.auth import get_user_by_id
            return get_user_by_id(uid)
        except Exception:  # noqa: BLE001
            return {"user_id": uid, "email": ""}

    @rt("/app")
    def app_home(session, new: str = "", thread: str = ""):
        user = _current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        uid = str(user["user_id"])
        selected_thread = None
        if thread:
            try:
                _uuid.UUID(thread)
                from engine.ai.chat_store import conversation_belongs_to_user
                if conversation_belongs_to_user(thread, uid):
                    selected_thread = thread
            except Exception:  # noqa: BLE001
                selected_thread = None
        if selected_thread:
            session["thread_id"] = selected_thread
        elif new == "1" or thread:
            session["thread_id"] = str(_uuid.uuid4())
        else:
            current = str(session.get("thread_id") or "")
            try:
                from engine.ai.chat_store import (
                    conversation_belongs_to_user,
                    list_conversations,
                )
                if current and conversation_belongs_to_user(current, uid):
                    session["thread_id"] = current
                else:
                    recent = list_conversations(user_id=uid, limit=1)
                    session["thread_id"] = (
                        recent[0]["thread_id"] if recent else str(_uuid.uuid4())
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not resolve active chat for %s: %s", uid, exc)
                if not current:
                    session["thread_id"] = str(_uuid.uuid4())
        thread_id = str(session["thread_id"])
        return (
            *ph_layout.page("app", ph_layout.chat_center(), user=user, title="AlpaTrade",
                            right_news_open=True),
            Script(f"window.ALPA_THREAD_ID={json.dumps(thread_id)};"),
            Style(CHAT_STYLE),
            Script(CHAT_JS),
        )

    @rt("/app/chats")
    def app_chats(session):
        """Return the logged-in user's persisted conversation list."""
        uid = session.get("user_id")
        if not uid:
            return Div("Sign in to view chats.", cls="sessions-empty")
        try:
            from engine.ai.chat_store import list_conversations
            conversations = list_conversations(user_id=str(uid), limit=30)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list chats for %s: %s", uid, exc)
            conversations = []
        if not conversations:
            return Div("No chats yet.", cls="sessions-empty")
        current = str(session.get("thread_id") or "")
        rows = []
        for conversation in conversations:
            tid = conversation["thread_id"]
            title = conversation.get("first_msg") or conversation.get("title") or "New chat"
            title = " ".join(str(title).split())
            if len(title) > 46:
                title = title[:43] + "..."
            rows.append(Div(
                A(title, href=f"/app?thread={tid}", cls="session-link",
                  title=str(conversation.get("first_msg") or title)),
                Button("x", type="button", cls="session-delete",
                       aria_label="Delete chat",
                       onclick=f"deleteChat({json.dumps(tid)},event)"),
                cls="session-row" + (" active" if tid == current else ""),
            ))
        return Div(*rows, cls="session-items")

    @app.get("/app/chat/history")
    async def app_chat_history(session, thread: str = ""):
        """Return only the active thread when it belongs to this account."""
        uid = session.get("user_id")
        thread_id = thread or session.get("thread_id")
        if not uid or not thread_id:
            return JSONResponse({"messages": []})
        try:
            from engine.ai.chat_store import load_conversation_messages
            messages = load_conversation_messages(thread_id, user_id=str(uid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load active chat %s: %s", thread_id, exc)
            messages = []
        return JSONResponse({"messages": [
            {
                "message_id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "metadata": row.get("metadata") or {},
            }
            for row in messages
        ]})

    @app.delete("/app/chats/{thread_id}")
    async def app_delete_chat(thread_id: str, session):
        """Delete an owned conversation; another user's thread is untouched."""
        uid = session.get("user_id")
        if not uid:
            return JSONResponse({"deleted": False}, status_code=401)
        try:
            from engine.ai.chat_store import conversation_belongs_to_user, delete_conversation
            if not conversation_belongs_to_user(thread_id, str(uid)):
                return JSONResponse({"deleted": False}, status_code=404)
            delete_conversation(thread_id, user_id=str(uid))
            _HISTORY.pop(thread_id, None)
            return JSONResponse({"deleted": True})
        except Exception:  # noqa: BLE001
            return JSONResponse({"deleted": False}, status_code=404)

    @app.post("/app/chat")
    async def app_chat(session, msg: str = ""):
        if not session.get("user_id"):
            return StreamingResponse(
                iter([_sse("error", {"message": "not signed in"}), _sse("done", {})]),
                media_type="text/event-stream",
            )
        if not msg.strip():
            return StreamingResponse(
                iter([_sse("done", {})]), media_type="text/event-stream")
        if not session.get("thread_id"):
            session["thread_id"] = str(_uuid.uuid4())
        return await _stream(msg, session)

    @rt("/news")
    async def news():
        """Categorized premarket catalysts plus multi-source market headlines."""
        from fasthtml.common import A, Details, Div, Span, P, Summary, to_xml
        from starlette.responses import HTMLResponse
        sections = []
        try:
            from engine.premarket import latest_report, top_movers
            movers = top_movers(latest_report(), 8)["movers"]
            if movers:
                mover_cards = []
                for mover in movers:
                    direction = "up" if mover.get("movement_pct", 0) >= 0 else "down"
                    catalyst = (mover.get("catalysts") or [{}])[0]
                    inner = [
                        Div(Span(mover["ticker"], cls="news-source"),
                            Span(f"{mover['movement_pct']:+.2f}%",
                                 cls=f"news-time pm-news-{direction}"),
                            cls="news-item-header"),
                        Div(catalyst.get("title") or mover.get("company_name") or
                            "Premarket price move", cls="news-item-title"),
                    ]
                    mover_cards.append(A(
                        *inner, href=catalyst.get("link") or f"/premarket#{mover['ticker']}",
                        target="_blank" if catalyst.get("link") else None,
                        rel="noopener", cls="news-item"))
                sections.append(Details(
                    Summary(f"Premarket movers · {len(mover_cards)}", cls="news-category-title"),
                    Div(*mover_cards), cls="news-category", open=True))
        except Exception:  # noqa: BLE001
            pass
        try:
            from engine.publicmarkets.news import categorized_news
            for category, rows in categorized_news(60).items():
                cards = []
                for row in rows[:8]:
                    cards.append(A(
                        Div(Span(row.get("ticker") or row.get("publisher") or "Release",
                                 cls="news-source"),
                            Span((row.get("published") or "")[:10], cls="news-time"),
                            cls="news-item-header"),
                        Div(row.get("title") or "", cls="news-item-title"),
                        href=row.get("link") or "#", target="_blank", rel="noopener",
                        cls="news-item"))
                sections.append(Details(
                    Summary(f"{category} · {len(rows)}", cls="news-category-title"),
                    Div(*cards), cls="news-category"))
        except Exception:  # noqa: BLE001
            pass
        if sections:
            return HTMLResponse(to_xml(Div(*sections, cls="news-categories")))
        try:
            from utils.news_feed import fetch_news, time_ago
            articles = await fetch_news()
        except Exception as e:  # noqa: BLE001
            return HTMLResponse(to_xml(P(f"Could not load news: {e}", cls="news-empty")))
        if not articles:
            return HTMLResponse(to_xml(P("No market news right now — check back shortly.",
                                         cls="news-empty")))
        items = []
        for a in articles:
            summary = (a.get("summary") or "").strip()
            # NB: FastHTML escapes text children — do NOT pre-escape (double-encodes entities).
            parts = [
                Div(
                    Span(a.get("icon") or a["source"], cls="news-source"),
                    Span(time_ago(a.get("published", "")), cls="news-time"),
                    cls="news-item-header",
                ),
                Div(a["title"], cls="news-item-title"),
            ]
            if summary:
                parts.append(Div(summary[:160], cls="news-item-summary"))
            items.append(A(*parts, href=a["url"], target="_blank", rel="noopener",
                           cls="news-item"))
        return HTMLResponse(to_xml(Div(*items)))

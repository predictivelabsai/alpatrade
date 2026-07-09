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
Free-form text streams token-by-token from the LangGraph agent
(``agui_app.langgraph_agent``, XAI Grok) via ``astream_events(v2)``. Recognised
CLI commands (``trades``/``runs``/``top``/``report``/``monitor``/``research``/
``charts``/``accounts``/``options``, ``agent:*``, ``positions``, ``news:``,
``load:``, ``equity``, ``help`` …) are intercepted by
``agui_app._command_interceptor`` and executed through
``tui.command_processor.CommandProcessor``; the markdown result is streamed as a
single ``token`` block (long-running ``agent:*`` commands run to completion, then
their result — with an auto-appended equity curve for backtests — is streamed).

Routes registered by :func:`register`
--------------------------------------
* ``GET  /app``        — the chat page (login required, else redirect to /signin).
* ``POST /app/chat``   — the SSE streaming send endpoint.
* ``GET  /news``       — ``MarketResearch().news(...)`` markdown for the right pane.
"""
from __future__ import annotations

import json
import re
import uuid as _uuid
from typing import Optional

from fasthtml.common import Script, Style
from starlette.responses import RedirectResponse, StreamingResponse

from engine.web import ph_layout

# --- reuse the legacy AG-UI wiring verbatim --------------------------------
# Importing agui_app builds the LangGraph agent (XAI Grok + StructuredTool
# wrappers), the command-interception logic and the CLI help text. We reuse
# those directly so the routing decisions stay identical to the old app.
import agui_app as _agui
from engine.ai import StreamingCommand

langgraph_agent = _agui.langgraph_agent
_command_interceptor = _agui._command_interceptor
_app_state = _agui._app_state

# In-memory per-thread AI history (context for the LangGraph agent). Keyed by the
# thread id stored on the session cookie. Command results are stateless.
_HISTORY: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# SSE helper (kept local so the module has no cross-repo dependency)
# ---------------------------------------------------------------------------
def _sse(name: str, data) -> str:
    """Format one server-sent event."""
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


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

  function renderMd(text){ return window.marked ? marked.parse(text) : text; }

  // Pull a __CHART_DATA__{...}__END_CHART__ marker out before markdown runs
  function extractChart(txt, bubble){
    var m=txt.match(/__CHART_DATA__([\s\S]+?)__END_CHART__/);
    if(m){ bubble._chart=m[1]; txt=txt.replace(/__CHART_DATA__[\s\S]*?__END_CHART__/,''); }
    return txt;
  }

  function renderChart(bubble){
    if(!bubble || !bubble._chart || !window.Plotly) return;
    var data; try{ data=JSON.parse(bubble._chart); }catch(e){ return; }
    var wrap=document.createElement('div'); wrap.style.cssText='width:100%;margin:.6rem 0;';
    var div=document.createElement('div'); div.style.cssText='width:100%;min-height:360px;';
    wrap.appendChild(div);
    var dl=document.createElement('button'); dl.textContent='Download PNG'; dl.className='table-action-btn';
    dl.style.marginTop='.4rem';
    dl.onclick=function(){ Plotly.downloadImage(div,{format:'png',width:1200,height:600,
      filename:(data.type==='equity_curve'?'equity':(data.ticker||'chart'))}); };
    wrap.appendChild(dl);
    bubble.appendChild(wrap);
    var layout={paper_bgcolor:'#FFFFFF',plot_bgcolor:'#F7F6F1',
      font:{color:'#415046',family:'Inter,sans-serif',size:11},
      xaxis:{gridcolor:'#E3DFD2',linecolor:'#E3DFD2'},
      yaxis:{gridcolor:'#E3DFD2',linecolor:'#E3DFD2',tickprefix:'$'},
      legend:{orientation:'h',y:-0.15},margin:{t:38,r:15,b:40,l:60},showlegend:true};
    if(data.type==='equity_curve'){
      var eq={x:data.dates,y:data.equity,type:'scatter',mode:'lines',name:'Equity',
        line:{color:'#1F5D43',width:2},fill:'tozeroy',fillcolor:'rgba(31,93,67,0.08)'};
      var cap={x:[data.dates[0],data.dates[data.dates.length-1]],
        y:[data.initial_capital,data.initial_capital],type:'scatter',mode:'lines',
        name:'Initial Capital',line:{color:'#7A867E',width:1,dash:'dash'}};
      var fin=data.equity[data.equity.length-1]-data.initial_capital;
      var pct=(fin/data.initial_capital*100).toFixed(1);
      var sign=fin>=0?'+':'';
      layout.title={text:'Equity Curve  ('+sign+'$'+fin.toFixed(0)+' / '+sign+pct+'%)',
        font:{size:13,color:'#14231B'}};
      Plotly.newPlot(div,[eq,cap],layout,{responsive:true,displayModeBar:false});
    } else {
      var tr={x:data.dates,y:data.close,type:'scatter',mode:'lines',name:data.ticker,
        line:{color:'#1F5D43',width:2},fill:'tozeroy',fillcolor:'rgba(31,93,67,0.08)'};
      layout.title={text:data.ticker+' — '+data.period,font:{size:13,color:'#14231B'}};
      layout.showlegend=false;
      Plotly.newPlot(div,[tr],layout,{responsive:true,displayModeBar:false});
    }
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

    var bubble=null, acc='';
    try{
      var resp=await fetch('/app/chat',{method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams({msg:msg})});
      if(!resp.ok){ addBubble('assistant','Error: '+resp.status); streaming=false; if(sb) sb.disabled=false; return false; }
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
              bubble=addBubble('assistant','',p.agent); bubble.classList.add('streaming');
            } else if(type==='token'){
              if(!bubble){ bubble=addBubble('assistant','',''); bubble.classList.add('streaming'); }
              acc+=p.text; bubble.innerHTML=renderMd(acc); scrollBottom();
            } else if(type==='tool_start'){
              appendTool(bubble||(bubble=addBubble('assistant','','')), p.name);
            } else if(type==='error'){
              if(!bubble) bubble=addBubble('assistant','','');
              bubble.textContent='Error: '+(p.message||'unknown');
            } else if(type==='done'){
              if(bubble){
                bubble.classList.remove('streaming');
                var t=extractChart(acc,bubble);
                bubble.innerHTML=t.trim()?renderMd(t):bubble.innerHTML;
                enhanceTables(bubble); renderChart(bubble);
              }
            }
          });
        }
      }
    }catch(e){
      if(!bubble) bubble=addBubble('assistant','','');
      bubble.textContent='Error: '+e;
    }
    streaming=false; if(sb) sb.disabled=false;
    var ta2=$('#chat-input'); if(ta2) ta2.focus();
    scrollBottom();
    return false;
  }
  window.sendMessage=sendMessage;

  // Render the News pane markdown after htmx swaps it in.
  document.body.addEventListener('htmx:afterSwap', function(e){
    var tgt=e.detail && e.detail.target;
    if(tgt && tgt.id==='news-body' && window.marked){
      var raw=tgt.textContent||''; if(raw.trim()) tgt.innerHTML=marked.parse(raw);
    }
  });
})();
"""

# Minimal styles for the tool-call log + streaming cursor inside bubbles
# (parchment/forest tokens; class names not present in app.css).
CHAT_STYLE = """
.tool-log { margin-top:.4rem; display:flex; flex-direction:column; gap:.15rem; }
.tool-step { font-family:var(--font-mono); font-size:.68rem; color:var(--ink-dim); }
.tool-step .tool-name { color:var(--accent); }
"""


# ---------------------------------------------------------------------------
# SSE streaming send handler
# ---------------------------------------------------------------------------
async def _stream(msg: str, session) -> StreamingResponse:
    """Return an SSE StreamingResponse for one user message.

    Snapshot the session up front (the generator runs after the request scope),
    build a legacy-shaped compat session for the reused interceptor, then either
    stream the LangGraph agent (free-form) or a single command result.
    """
    uid = session.get("user_id")
    thread_id = session.get("thread_id") or str(_uuid.uuid4())

    # agui_app's interceptor + CommandProcessor read session["user"]["user_id"].
    compat = dict(session)
    if uid is not None:
        compat["user"] = {"user_id": str(uid)}

    async def gen():
        yield _sse("session", {"sid": thread_id})

        # 1) CLI command interception (identical logic to agui_app)
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
            yield _sse("done", {})
            return

        # 2) Free-form text → stream the LangGraph agent
        yield _sse("agent_route", {"slug": "ai", "agent": "AlpaTrade AI"})
        history = _HISTORY.setdefault(thread_id, [])
        history.append({"role": "user", "content": msg})

        from langchain_core.messages import HumanMessage, AIMessage
        lc = [
            HumanMessage(content=m["content"]) if m["role"] == "user"
            else AIMessage(content=m["content"])
            for m in history
        ]

        full = ""
        try:
            async for event in langgraph_agent.astream_events({"messages": lc}, version="v2"):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is not None and getattr(chunk, "content", ""):
                        full += chunk.content
                        yield _sse("token", {"text": chunk.content})
                elif kind == "on_tool_start":
                    yield _sse("tool_start", {"name": event.get("name", "tool")})
                elif kind == "on_tool_end":
                    yield _sse("tool_end", {"name": event.get("name", "tool")})
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"message": str(e)})
            history.append({"role": "assistant", "content": f"Error: {e}"})
            yield _sse("done", {})
            return

        history.append({"role": "assistant", "content": full})
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
    def app_home(session, new: str = ""):
        user = _current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        if new == "1" or not session.get("thread_id"):
            session["thread_id"] = str(_uuid.uuid4())
        return (
            *ph_layout.page("app", ph_layout.chat_center(), user=user, title="AlpaTrade"),
            Style(CHAT_STYLE),
            Script(CHAT_JS),
        )

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
        return await _stream(msg, session)

    @rt("/news")
    def news(ticker: str = ""):
        """Market news as markdown (rendered client-side via marked.js)."""
        try:
            from utils.market_research_util import MarketResearch
            return MarketResearch().news(ticker=(ticker.upper() or None), limit=12)
        except Exception as e:  # noqa: BLE001
            return f"Could not load news: {e}"

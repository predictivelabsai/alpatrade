"""
AG-UI core: WebSocket-based chat with LangGraph agents.

Streaming via LangGraph astream_events(v2) — replaces pydantic-ai + AG-UI protocol.
"""

from typing import Dict, List, Optional, Any
from fasthtml.common import (
    Div, Form, Hidden, Textarea, Button, Span, Script, Style, Pre, NotStr,
)
import asyncio
import collections
import logging
import re
import threading
import uuid

from .styles import get_chat_styles
from .chat_store import (
    save_conversation, save_message,
    load_conversation_messages, list_conversations,
)


# ---------------------------------------------------------------------------
# Follow-up suggestions — contextual pills shown after command results
# ---------------------------------------------------------------------------

def _get_followup_suggestions(msg: str, result: str = None) -> list:
    """Return contextual follow-up suggestions based on the command and its result."""
    cmd = msg.strip().lower()
    first = cmd.split()[0] if cmd.split() else ""

    # Extract run_id from result text
    run_id = None
    if result:
        m = re.search(r'Run ID\*?\*?:?\s*`?([a-f0-9-]+)',result)
        if m:
            run_id = m.group(1)

    # Extract ticker from colon-commands like news:TSLA
    ticker = None
    if ":" in first:
        parts = first.split(":")
        base = parts[0]
        if base in ("news", "price", "analysts", "profile", "financials") and len(parts) > 1 and parts[1]:
            ticker = parts[1].upper()

    if first.startswith("agent:backtest"):
        suggestions = []
        if run_id:
            suggestions.append(f"agent:validate run-id:{run_id}")
            suggestions.append(f"equity:{run_id[:8]}")
        suggestions.extend(["agent:report", "agent:top"])
        return suggestions[:4]

    if first.startswith("agent:paper"):
        return ["agent:status", "agent:logs", "agent:stop"]

    if first.startswith("agent:validate"):
        suggestions = []
        if run_id:
            suggestions.append(f"equity:{run_id[:8]}")
        suggestions.extend(["agent:report", "trades", "agent:top"])
        return suggestions[:4]

    if first in ("agent:report",):
        return ["agent:top", "trades", "runs"]

    if first in ("agent:top",):
        return ["agent:backtest lookback:1m", "agent:report"]

    if cmd == "trades":
        return ["agent:report", "runs", "agent:top"]

    if cmd == "runs":
        return ["trades", "agent:report", "agent:status"]

    if first.startswith("news:") and ticker:
        return [f"chart:{ticker}", f"price:{ticker}", f"analysts:{ticker}", f"profile:{ticker}"]

    if first.startswith("price:") and ticker:
        return [f"chart:{ticker}", f"news:{ticker}", f"analysts:{ticker}", f"financials:{ticker}"]

    if first.startswith("analysts:") and ticker:
        return [f"chart:{ticker}", f"price:{ticker}", f"news:{ticker}", f"financials:{ticker}"]

    if first.startswith("profile:") and ticker:
        return [f"chart:{ticker}", f"price:{ticker}", f"news:{ticker}", f"analysts:{ticker}"]

    if first.startswith("financials:") and ticker:
        return [f"chart:{ticker}", f"price:{ticker}", f"news:{ticker}", f"analysts:{ticker}"]

    if cmd == "movers":
        return ["price:AAPL", "news:TSLA", "agent:backtest lookback:1m"]

    # Default
    return ["help", "trades", "agent:backtest lookback:1m"]


# ---------------------------------------------------------------------------
# Result enrichment — wrap certain command outputs in structured cards
# ---------------------------------------------------------------------------

def _enrich_result(command: str, result: str):
    """Extract metrics from results and return a card HTML string, or None."""
    cmd = command.strip().lower()
    first = cmd.split()[0] if cmd.split() else ""

    # Backtest results — extract key metrics
    if first.startswith("agent:backtest") and result:
        metrics = {}
        for pattern, label in [
            (r'Sharpe(?:\s+Ratio)?[:\s|]+\*?\*?([0-9.-]+)', 'Sharpe'),
            (r'Total Return[:\s|]+\*?\*?([0-9.+-]+%?)', 'Return'),
            (r'(?:Net |Total )?P&?L[:\s|]+\*?\*?\$?([0-9.,+-]+)', 'P&L'),
            (r'Win Rate[:\s|]+\*?\*?([0-9.]+%?)', 'Win Rate'),
            (r'(?:Total )?Trades[:\s|]+\*?\*?([0-9]+)', 'Trades'),
        ]:
            m = re.search(pattern, result, re.IGNORECASE)
            if m:
                metrics[label] = m.group(1)

        if not metrics:
            return None

        metric_divs = []
        for label, value in metrics.items():
            val_class = "metric-value"
            if label in ('Sharpe', 'Return', 'P&L'):
                try:
                    num = float(value.replace('%', '').replace(',', '').replace('$', ''))
                    val_class += " positive" if num >= 0 else " negative"
                except ValueError:
                    pass
            metric_divs.append(
                f'<div class="metric"><div class="metric-label">{label}</div>'
                f'<div class="{val_class}">{value}</div></div>'
            )

        # Extract run_id for detail link
        run_id_match = re.search(r'Run ID\*?\*?:?\s*`?([a-f0-9-]+)',result)
        run_id_html = ""
        if run_id_match:
            rid = run_id_match.group(1)
            run_id_html = (
                f'<a href="#" style="font-size:0.7rem;color:#3b82f6;text-decoration:none" '
                f'hx-get="/agui/detail/{rid}" hx-target="#detail-content" hx-swap="innerHTML" '
                f'onclick="showTab(\'detail\');var l=document.querySelector(\'.app-layout\');'
                f'if(l&&!l.classList.contains(\'right-open\'))l.classList.add(\'right-open\');"'
                f'>{rid[:8]}...</a>'
            )

        card_html = (
            '<div class="result-card backtest-card">'
            f'<div class="card-header"><h3>Backtest Results</h3>{run_id_html}</div>'
            f'<div class="card-metrics">{"".join(metric_divs)}</div>'
            '</div>'
        )

        return card_html

    # Validation results
    if first.startswith("agent:validate") and result:
        status_match = re.search(r'Status[:\s|]+\*?\*?(PASS|FAIL|ERROR)', result, re.IGNORECASE)
        if status_match:
            status = status_match.group(1).upper()
            badge_cls = "badge-green" if status == "PASS" else "badge-red"
            return (
                '<div class="result-card">'
                f'<div class="card-header"><h3>Validation</h3>'
                f'<span class="{badge_cls}">{status}</span></div>'
                '</div>'
            )

    # News results
    if first.startswith("news:") and result and ("# News" in result or "## News" in result):
        ticker_part = first.split(":")[1].upper() if ":" in first else ""
        if ticker_part:
            return (
                '<div class="result-card news-card">'
                f'<div class="card-header"><h3>Latest News</h3>'
                f'<span class="badge-blue">{ticker_part}</span></div>'
                '</div>'
            )

    return None


# ---------------------------------------------------------------------------
# StreamingCommand sentinel — returned by command interceptor for long-running
# commands so the WS handler can fire-and-forget a background task.
# ---------------------------------------------------------------------------

class StreamingCommand:
    """Sentinel returned by the command interceptor for long-running commands."""

    def __init__(self, raw_command: str, session: dict, app_state: Any):
        self.raw_command = raw_command
        self.session = session
        self.app_state = app_state


# ---------------------------------------------------------------------------
# Shared JS snippets
# ---------------------------------------------------------------------------

_SCROLL_CHAT_JS = "var m=document.getElementById('chat-messages');if(m)m.scrollTop=m.scrollHeight;"
_GUARD_ENABLE_JS = "window._aguiProcessing=true;"
_GUARD_DISABLE_JS = "window._aguiProcessing=false;"


# ---------------------------------------------------------------------------
# Log line filter — suppress verbose init messages
# ---------------------------------------------------------------------------

_LOG_SKIP_PATTERNS = frozenset({
    "Massive API key found", "No Massive API key found",
    "Database pool initialized", "will use Massive for price data",
    "will use yfinance for price data",
})


def _filter_log_lines(lines):
    return [l for l in lines if not any(l.split(" ", 1)[-1].startswith(p) for p in _LOG_SKIP_PATTERNS)]


# ---------------------------------------------------------------------------
# LogCapture — thread-safe logging handler that buffers lines for streaming
# ---------------------------------------------------------------------------

class LogCapture(logging.Handler):
    """Captures log records into a deque for streaming to the browser."""

    def __init__(self, maxlen=500):
        super().__init__()
        self.lines: collections.deque = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._lock:
                self.lines.append(msg)
        except Exception:
            self.handleError(record)

    def get_lines(self) -> list:
        with self._lock:
            return list(self.lines)

    def clear(self):
        with self._lock:
            self.lines.clear()


# ---------------------------------------------------------------------------
# UI renderer
# ---------------------------------------------------------------------------

class UI:
    """Renders chat components for a given thread."""

    def __init__(self, thread_id: str, autoscroll: bool = True):
        self.thread_id = thread_id
        self.autoscroll = autoscroll

    def _clear_input(self):
        return self._render_input_form(oob_swap=True)

    def _render_messages(self, messages: list[dict], oob: bool = False):
        attrs = {"id": "chat-messages", "cls": "chat-messages"}
        if oob:
            attrs["hx_swap_oob"] = "outerHTML"
        return Div(
            *[self._render_message(m) for m in messages],
            **attrs,
        )

    def _render_message(self, message: dict):
        role = message.get("role", "assistant")
        cls = "chat-user" if role == "user" else "chat-assistant"
        mid = message.get("message_id", str(uuid.uuid4()))
        return Div(
            Div(message.get("content", ""), cls="chat-message-content marked"),
            cls=f"chat-message {cls}",
            id=mid,
        )

    def _render_input_form(self, oob_swap=False):
        container_attrs = {"cls": "chat-input", "id": "chat-input-container"}
        if oob_swap:
            container_attrs["hx_swap_oob"] = "outerHTML"

        return Div(
            Div(id="suggestion-buttons"),
            Div(id="chat-status", cls="chat-status"),
            Form(
                Hidden(name="thread_id", value=self.thread_id),
                Textarea(
                    id="chat-input",
                    name="msg",
                    placeholder="Type a command or ask a question...\nShift+Enter for new line",
                    autofocus=True,
                    autocomplete="off",
                    cls="chat-input-field",
                    rows="2",
                    onkeydown="handleKeyDown(this, event)",
                    oninput="autoResize(this)",
                ),
                Button("Send", type="submit", cls="chat-input-button",
                       onclick="if(window._aguiProcessing){event.preventDefault();return false;}"),
                cls="chat-input-form",
                id="chat-form",
                ws_send=True,
            ),
            Div(Span("Enter", cls="kbd"), " to send  ", Span("Shift+Enter", cls="kbd"), " new line", cls="input-hint"),
            **container_attrs,
        )

    def _render_welcome(self):
        """Render the welcome hero with suggestion cards."""
        _ICON_CHAT = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>'
        _ICON_CHART = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>'
        _ICON_PLAY = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>'
        _ICON_NEWS = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></svg>'
        _ICON_SEARCH = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>'

        cards = [
            ("Run a Backtest", "Test strategies over the last month", "agent:backtest lookback:1m", "#3b82f6", _ICON_CHART),
            ("Start Paper Trading", "Trade with virtual money in real-time", "agent:paper duration:1d", "#8b5cf6", _ICON_PLAY),
            ("Market News", "Latest headlines and top movers", "news:TSLA", "#f59e0b", _ICON_NEWS),
            ("Research a Stock", "Price, analysts, and financials", "price:AAPL", "#10b981", _ICON_SEARCH),
        ]

        card_els = []
        for title, desc, cmd, color, icon_svg in cards:
            card_els.append(
                Div(
                    Div(NotStr(icon_svg), cls="welcome-card-icon",
                        style=f"background:{color}15;color:{color}"),
                    Div(title, cls="welcome-card-title"),
                    Div(desc, cls="welcome-card-desc"),
                    cls="welcome-card",
                    onclick=(
                        f"if(window._aguiProcessing)return;"
                        f"var ta=document.getElementById('chat-input');"
                        f"var fm=document.getElementById('chat-form');"
                        f"if(ta&&fm){{ta.value={repr(cmd)};fm.requestSubmit();}}"
                    ),
                )
            )

        return Div(
            Div(
                Div(NotStr(_ICON_CHAT), cls="welcome-icon"),
                Div("AlpaTrade", cls="welcome-title"),
                Div("Your AI-powered trading assistant", cls="welcome-subtitle"),
                Div(*card_els, cls="welcome-grid"),
                cls="welcome-hero",
            ),
            id="welcome-screen",
        )

    def chat(self, **kwargs):
        """Return the full chat widget (messages + input + scripts)."""
        components = [
            get_chat_styles(),
            Div(
                self._render_welcome(),
                id="chat-messages",
                cls="chat-messages",
                hx_get=f"/agui/messages/{self.thread_id}",
                hx_trigger="load",
                hx_swap="outerHTML",
            ),
            self._render_input_form(),
            Script("""
                // Welcome-active class management
                (function() {
                    function checkWelcome() {
                        var container = document.querySelector('.chat-container');
                        var welcome = document.getElementById('welcome-screen');
                        if (container) {
                            if (welcome) container.classList.add('welcome-active');
                            else container.classList.remove('welcome-active');
                        }
                    }
                    checkWelcome();
                    // Watch the container itself (not just messages) so we catch outerHTML swaps
                    var container = document.querySelector('.chat-container');
                    if (container) {
                        var observer = new MutationObserver(checkWelcome);
                        observer.observe(container, {childList: true, subtree: true});
                    }
                })();

                function autoResize(textarea) {
                    textarea.style.height = 'auto';
                    var maxH = 12 * 16;
                    var h = Math.min(textarea.scrollHeight, maxH);
                    textarea.style.height = h + 'px';
                    textarea.style.overflowY = textarea.scrollHeight > maxH ? 'auto' : 'hidden';
                }
                function handleKeyDown(textarea, event) {
                    autoResize(textarea);
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        if (window._aguiProcessing) return;
                        var form = textarea.closest('form');
                        if (form && textarea.value.trim()) form.requestSubmit();
                    }
                }
                // Extract __CHART_DATA__...__END_CHART__ before markdown
                // (marked.parse converts __ to <strong>, destroying the marker)
                function extractAndRenderCharts(txt, el) {
                    var chartMatch = txt.match(/__CHART_DATA__(.+?)__END_CHART__/);
                    if (chartMatch) {
                        var chartJson = chartMatch[1];
                        txt = txt.replace(/__CHART_DATA__.*?__END_CHART__/, '');
                        if (el) {
                            el._pendingChart = chartJson;
                        }
                    }
                    return txt;
                }

                // Add inline chart after markdown render (with download button)
                function renderInlineChart(el) {
                    if (!el._pendingChart || !window.Plotly) return;
                    try {
                        var data = JSON.parse(el._pendingChart);
                        var wrapper = document.createElement('div');
                        wrapper.className = 'inline-chart-wrapper';
                        wrapper.style.cssText = 'width:100%;margin:0.75rem 0;';

                        var chartDiv = document.createElement('div');
                        chartDiv.className = 'inline-chart';
                        chartDiv.style.cssText = 'width:100%;min-height:480px;border-radius:0.5rem;overflow:hidden;';
                        wrapper.appendChild(chartDiv);

                        // Download button
                        var dlBtn = document.createElement('button');
                        dlBtn.textContent = 'Download PNG';
                        dlBtn.className = 'chart-download-btn';
                        dlBtn.style.cssText = 'margin-top:0.5rem;padding:0.35rem 0.75rem;font-size:0.75rem;background:#3b82f6;color:#fff;border:none;border-radius:4px;cursor:pointer;';
                        dlBtn.onclick = function() {
                            var fname = data.type === 'equity_curve' ? 'equity-'+(data.run_id||'').substring(0,8) : (data.ticker||'chart');
                            if (window.downloadChart) window.downloadChart(chartDiv, fname);
                        };
                        wrapper.appendChild(dlBtn);
                        el.appendChild(wrapper);

                        var lightLayout = {
                            paper_bgcolor:'#ffffff',plot_bgcolor:'#f8fafc',
                            font:{color:'#64748b',family:'-apple-system,sans-serif',size:11},
                            xaxis:{gridcolor:'#e2e8f0',linecolor:'#e2e8f0'},
                            yaxis:{gridcolor:'#e2e8f0',linecolor:'#e2e8f0',tickprefix:'$'},
                            legend:{orientation:'h',y:-0.15},margin:{t:40,r:15,b:40,l:60},
                            showlegend:true
                        };

                        if (data.type === 'equity_curve') {
                            var eqTrace = {x:data.dates,y:data.equity,type:'scatter',mode:'lines',
                                name:'Equity',line:{color:'#3b82f6',width:2},fill:'tozeroy',
                                fillcolor:'rgba(59,130,246,0.08)'};
                            var capLine = {x:[data.dates[0],data.dates[data.dates.length-1]],
                                y:[data.initial_capital,data.initial_capital],type:'scatter',mode:'lines',
                                name:'Initial Capital',line:{color:'#94a3b8',width:1,dash:'dash'}};
                            var shortId = data.run_id ? data.run_id.substring(0,8) : '';
                            var finalPnl = data.equity[data.equity.length-1] - data.initial_capital;
                            var pnlPct = (finalPnl / data.initial_capital * 100).toFixed(1);
                            var pnlColor = finalPnl >= 0 ? '#16a34a' : '#dc2626';
                            var pnlSign = finalPnl >= 0 ? '+' : '';
                            lightLayout.title = {text:'Equity Curve — '+shortId+'  ('+pnlSign+'$'+finalPnl.toFixed(0)+' / '+pnlSign+pnlPct+'%)',
                                font:{size:13,color:'#1e293b'}};
                            Plotly.newPlot(chartDiv,[eqTrace,capLine],lightLayout,{responsive:true,displayModeBar:false});
                        } else {
                            var trace = {x:data.dates,y:data.close,type:'scatter',mode:'lines',
                                name:data.ticker,line:{color:'#3b82f6',width:2},fill:'tozeroy',
                                fillcolor:'rgba(59,130,246,0.08)'};
                            lightLayout.title = {text:data.ticker+' — '+data.period,font:{size:13,color:'#1e293b'}};
                            lightLayout.showlegend = false;
                            Plotly.newPlot(chartDiv,[trace],lightLayout,{responsive:true,displayModeBar:false});
                        }
                    } catch(e) { console.error('Inline chart error:', e); }
                    delete el._pendingChart;
                }

                // Convert table to CSV string
                function tableToCSV(table) {
                    var rows = [];
                    table.querySelectorAll('tr').forEach(function(tr) {
                        var cells = [];
                        tr.querySelectorAll('th, td').forEach(function(td) {
                            var val = td.textContent.trim().replace(/"/g, '""');
                            cells.push('"' + val + '"');
                        });
                        rows.push(cells.join(','));
                    });
                    return rows.join('\\n');
                }

                // Add toolbar (Copy CSV + Download CSV) above tables
                function enhanceTables(container) {
                    container.querySelectorAll('table').forEach(function(table) {
                        if (table.dataset.enhanced) return;
                        table.dataset.enhanced = '1';
                        var toolbar = document.createElement('div');
                        toolbar.className = 'table-toolbar';
                        var copyBtn = document.createElement('button');
                        copyBtn.textContent = 'Copy CSV';
                        copyBtn.className = 'table-action-btn';
                        copyBtn.onclick = function() {
                            var csv = tableToCSV(table);
                            navigator.clipboard.writeText(csv).then(function() {
                                copyBtn.textContent = 'Copied!';
                                setTimeout(function(){ copyBtn.textContent = 'Copy CSV'; }, 1500);
                            });
                        };
                        var dlBtn = document.createElement('button');
                        dlBtn.textContent = 'Download CSV';
                        dlBtn.className = 'table-action-btn';
                        dlBtn.onclick = function() {
                            var csv = tableToCSV(table);
                            var blob = new Blob([csv], {type: 'text/csv'});
                            var url = URL.createObjectURL(blob);
                            var a = document.createElement('a');
                            a.href = url;
                            a.download = 'alpatrade-data.csv';
                            a.click();
                            URL.revokeObjectURL(url);
                        };
                        toolbar.appendChild(copyBtn);
                        toolbar.appendChild(dlBtn);
                        table.parentNode.insertBefore(toolbar, table);
                    });
                }

                // Post-render: add table toolbars + inline charts
                function postRenderEnhance(el) {
                    enhanceTables(el);
                    renderInlineChart(el);
                }

                function renderMarkdown(elementId) {
                    setTimeout(function() {
                        var el = document.getElementById(elementId);
                        if (el && window.marked && el.classList.contains('marked')) {
                            var txt = el.textContent || el.innerText;
                            if (txt.trim()) {
                                txt = extractAndRenderCharts(txt, el);
                                el.innerHTML = txt.trim() ? marked.parse(txt) : '';
                                el.classList.remove('marked');
                                el.classList.add('marked-done');
                                delete el.dataset.rendering;
                                postRenderEnhance(el);
                            }
                        }
                    }, 100);
                }
                // Auto-render .marked elements on DOM changes
                // Skip elements that are still streaming (have a .chat-streaming sibling)
                if (window.marked) {
                    new MutationObserver(function() {
                        document.querySelectorAll('.marked').forEach(function(el) {
                            var parent = el.parentElement;
                            if (parent) {
                                var cursor = parent.querySelector('.chat-streaming');
                                if (cursor && cursor.textContent) return;
                            }
                            var txt = el.textContent || el.innerText;
                            if (txt.trim() && !el.dataset.rendering) {
                                el.dataset.rendering = '1';
                                setTimeout(function() {
                                    if (!el.classList.contains('marked')) { delete el.dataset.rendering; return; }
                                    var finalTxt = el.textContent || el.innerText;
                                    if (finalTxt.trim()) {
                                        finalTxt = extractAndRenderCharts(finalTxt, el);
                                        el.innerHTML = finalTxt.trim() ? marked.parse(finalTxt) : '';
                                        el.classList.remove('marked');
                                        el.classList.add('marked-done');
                                        postRenderEnhance(el);
                                    }
                                    delete el.dataset.rendering;
                                }, 150);
                            }
                        });
                    }).observe(document.body, {childList: true, subtree: true});
                }
            """),
        ]

        if self.autoscroll:
            components.append(Script("""
                (function() {
                    var obs = new MutationObserver(function() {
                        var m = document.getElementById('chat-messages');
                        if (m) m.scrollTop = m.scrollHeight;
                    });
                    var t = document.getElementById('chat-messages');
                    if (t) obs.observe(t, {childList: true, subtree: true});
                })();
            """))

        # Hidden div used as OOB swap target for executing JS via WebSocket.
        # Bare <script> tags sent via WS are NOT executed by HTMX — scripts
        # must be children of an element that is OOB-swapped into the DOM.
        components.append(Div(id="agui-js", style="display:none"))

        return Div(
            *components,
            hx_ext="ws",
            ws_connect=f"/agui/ws/{self.thread_id}",
            cls="chat-container welcome-active",
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Thread (conversation)
# ---------------------------------------------------------------------------

class AGUIThread:
    """Single conversation thread with message history and LangGraph agent."""

    def __init__(self, thread_id: str, langgraph_agent, user_id: str = None):
        self.thread_id = thread_id
        self._agent = langgraph_agent
        self._user_id = user_id
        self._messages: list[dict] = []  # [{role, content, message_id}]
        self._connections: Dict[str, Any] = {}
        self.ui = UI(self.thread_id, autoscroll=True)
        self._suggestions: list[str] = []
        self._command_interceptor = None  # async callable(msg, session) -> str|None
        self._loaded = False

    def _ensure_loaded(self):
        """Load messages from DB on first access."""
        if self._loaded:
            return
        self._loaded = True
        try:
            rows = load_conversation_messages(self.thread_id)
            self._messages = rows
        except Exception:
            pass

    def subscribe(self, connection_id, send):
        self._connections[connection_id] = send

    def unsubscribe(self, connection_id: str):
        self._connections.pop(connection_id, None)

    async def send(self, element):
        for _, send_fn in self._connections.items():
            await send_fn(element)

    async def _send_js(self, js_code: str):
        """Execute JS in the browser via OOB swap into the hidden agui-js div."""
        await self.send(Div(Script(js_code), id="agui-js", hx_swap_oob="innerHTML"))

    async def set_suggestions(self, suggestions: list[str]):
        self._suggestions = suggestions[:4]
        if self._suggestions:
            el = Div(
                *[
                    Button(
                        Span(s), Span("\u2192", cls="arrow"),
                        onclick=f"if(window._aguiProcessing)return;"
                        f"var ta=document.getElementById('chat-input');"
                        f"var fm=document.getElementById('chat-form');"
                        f"if(ta&&fm){{ta.value={repr(s)};fm.requestSubmit();}}",
                        cls="suggestion-btn",
                    )
                    for s in self._suggestions
                ],
                id="suggestion-buttons",
                hx_swap_oob="outerHTML",
            )
        else:
            el = Div(id="suggestion-buttons", hx_swap_oob="outerHTML")
        await self.send(el)

    async def _refresh_conv_list(self):
        """Push an OOB swap to refresh the sidebar conversation list."""
        await self.send(Div(id="conv-list", hx_get="/agui-conv/list",
                            hx_trigger="load", hx_swap="innerHTML", hx_swap_oob="outerHTML"))

    async def _handle_message(self, msg: str, session):
        self._ensure_loaded()

        # Block double-submit immediately
        await self._send_js(_GUARD_ENABLE_JS)

        # Remove welcome screen + switch to scrollable layout
        await self._send_js(
            "var w=document.getElementById('welcome-screen');if(w)w.remove();"
            "var c=document.querySelector('.chat-container');if(c)c.classList.remove('welcome-active');"
        )
        await self.set_suggestions([])

        # CLI command interception — bypass AI agent for known commands
        if self._command_interceptor:
            result = await self._command_interceptor(msg, session)
            if result is not None:
                if isinstance(result, StreamingCommand):
                    asyncio.create_task(
                        self._handle_streaming_command(msg, result, session)
                    )
                else:
                    await self._handle_command_result(msg, result, session)
                return

        # AI message — route to LangGraph
        await self._handle_ai_run(msg, session)

    async def _handle_ai_run(self, msg: str, session):
        """Stream a LangGraph agent response via astream_events(v2)."""
        from langchain_core.messages import HumanMessage, AIMessage

        _open_trace = (
            "var l=document.querySelector('.app-layout');"
            "if(l&&!l.classList.contains('right-open'))l.classList.add('right-open');"
            "setTimeout(function(){var tc=document.getElementById('trace-content');"
            "if(tc)tc.scrollTop=tc.scrollHeight;},100);"
        )

        user_mid = str(uuid.uuid4())
        asst_mid = str(uuid.uuid4())
        content_id = f"message-content-{asst_mid}"

        # 1. Save user message
        user_dict = {"role": "user", "content": msg, "message_id": user_mid}
        self._messages.append(user_dict)
        try:
            title = msg[:80] if len(self._messages) == 1 else None
            save_conversation(self.thread_id, user_id=self._user_id, title=title)
        except Exception:
            pass
        try:
            save_message(self.thread_id, "user", msg, user_mid)
        except Exception:
            pass

        # 2. Send user bubble
        await self.send(Div(
            Div(
                Div(msg, cls="chat-message-content"),
                cls="chat-message chat-user",
                id=user_mid,
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        ))

        # Clear input + disable
        await self.send(self.ui._clear_input())
        await self._send_js(
            "var b=document.querySelector('.chat-input-button'),t=document.getElementById('chat-input');"
            "if(b){b.disabled=true;b.classList.add('sending')}"
            "if(t){t.disabled=true;t.placeholder='Thinking...'}"
        )

        # 3. Create empty streaming assistant bubble
        await self.send(Div(
            Div(
                Div(
                    Span("", id=content_id),
                    Span("", cls="chat-streaming", id=f"streaming-{asst_mid}"),
                    cls="chat-message-content",
                ),
                cls="chat-message chat-assistant",
                id=f"message-{asst_mid}",
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        ))

        # 4. Trace: run started
        run_trace_id = str(uuid.uuid4())
        await self.send(Div(
            Div(
                Span("AI run started", cls="trace-label"),
                cls="trace-entry trace-run-start",
                id=f"trace-run-{run_trace_id}",
            ),
            Script(_open_trace),
            id="trace-content",
            hx_swap_oob="beforeend",
        ))

        # 5. Convert message history to LangChain format
        lc_messages = []
        for m in self._messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            else:
                lc_messages.append(AIMessage(content=content))

        # 6. Stream via astream_events
        full_response = ""
        try:
            async for event in self._agent.astream_events(
                {"messages": lc_messages}, version="v2"
            ):
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token = chunk.content
                        full_response += token
                        # Append token to streaming bubble
                        await self.send(Span(
                            token,
                            id=content_id,
                            hx_swap_oob="beforeend",
                        ))

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "tool")
                    tool_run_id = event.get("run_id", "")[:8]
                    # Trace: tool call
                    await self.send(Div(
                        Div(
                            Span(f"Tool: {tool_name}", cls="trace-label"),
                            Span("running...", cls="trace-detail"),
                            cls="trace-entry trace-tool-active",
                            id=f"trace-tool-{tool_run_id}",
                        ),
                        Script(_open_trace),
                        id="trace-content",
                        hx_swap_oob="beforeend",
                    ))
                    # Tool indicator in chat
                    await self.send(Div(
                        Div(
                            Div(f"Running {tool_name}...", cls="chat-message-content"),
                            cls="chat-message chat-tool",
                            id=f"tool-{tool_run_id}",
                        ),
                        id="chat-messages",
                        hx_swap_oob="beforeend",
                    ))

                elif kind == "on_tool_end":
                    tool_run_id = event.get("run_id", "")[:8]
                    # Update tool indicator
                    await self.send(Div(
                        Div("Done", cls="chat-message-content"),
                        cls="chat-message chat-tool",
                        id=f"tool-{tool_run_id}",
                        hx_swap_oob="outerHTML",
                    ))
                    # Update trace
                    await self.send(Div(
                        Span("Tool complete", cls="trace-label"),
                        cls="trace-entry trace-tool-done",
                        id=f"trace-tool-{tool_run_id}",
                        hx_swap_oob="outerHTML",
                    ))

        except Exception as e:
            error_msg = str(e)
            full_response = f"Error: {error_msg}"
            # Show error in chat
            await self.send(Span(
                f"\n\n**Error:** {error_msg}",
                id=content_id,
                hx_swap_oob="beforeend",
            ))
            # Trace: error
            await self.send(Div(
                Div(
                    Span("Error", cls="trace-label"),
                    Span(error_msg[:200], cls="trace-detail"),
                    cls="trace-entry trace-error",
                ),
                id="trace-content",
                hx_swap_oob="beforeend",
            ))

        # 7. Finalize: remove cursor, add marked class, render markdown
        await self.send(Span("", id=f"streaming-{asst_mid}", hx_swap_oob="outerHTML"))
        await self._send_js(
            f"var el=document.getElementById('{content_id}');"
            f"if(el)el.classList.add('marked');"
            f"renderMarkdown('{content_id}');"
        )

        # Trace: run finished
        await self.send(Div(
            Div(
                Span("Run finished", cls="trace-label"),
                cls="trace-entry trace-run-end",
            ),
            id="trace-content",
            hx_swap_oob="beforeend",
        ))

        # 8. Save assistant message
        asst_dict = {"role": "assistant", "content": full_response, "message_id": asst_mid}
        self._messages.append(asst_dict)
        try:
            save_message(self.thread_id, "assistant", full_response, asst_mid)
        except Exception:
            pass

        # Refresh sidebar
        await self._refresh_conv_list()

        # Re-enable input
        await self.send(self.ui._clear_input())
        await self._send_js(
            _GUARD_DISABLE_JS +
            "var b=document.querySelector('.chat-input-button'),t=document.getElementById('chat-input');"
            "if(b){b.disabled=false;b.classList.remove('sending')}"
            "if(t){t.disabled=false;t.placeholder='Type a command or ask a question...';t.focus()}"
        )
        await self._send_js(_SCROLL_CHAT_JS)

    async def _handle_command_result(self, msg: str, result: str, session):
        """Display a CLI command result in chat with trace pane integration."""

        # Disable input during processing
        await self._send_js(
            "var b=document.querySelector('.chat-input-button'),t=document.getElementById('chat-input');"
            "if(b){b.disabled=true;b.classList.add('sending')}"
            "if(t){t.disabled=true;t.placeholder='Thinking...'}"
        )

        _open_trace = (
            "var l=document.querySelector('.app-layout');"
            "if(l&&!l.classList.contains('right-open'))l.classList.add('right-open');"
            "setTimeout(function(){var tc=document.getElementById('trace-content');"
            "if(tc)tc.scrollTop=tc.scrollHeight;},100);"
        )
        cmd_id = str(uuid.uuid4())

        # Append user message
        user_mid = str(uuid.uuid4())
        user_dict = {"role": "user", "content": msg, "message_id": user_mid}
        self._messages.append(user_dict)

        # Persist
        try:
            save_conversation(self.thread_id, user_id=self._user_id,
                              title=msg[:80] if len(self._messages) == 1 else None)
        except Exception:
            try:
                save_conversation(self.thread_id, user_id=self._user_id)
            except Exception:
                pass
        try:
            save_message(self.thread_id, "user", msg, user_mid)
        except Exception:
            pass

        # Send user message + open trace with "Command started"
        await self.send(Div(
            Div(
                Div(msg, cls="chat-message-content"),
                cls="chat-message chat-user",
                id=user_mid,
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        ))
        await self.send(Div(
            Div(
                Span(f"Command: {msg}", cls="trace-label"),
                cls="trace-entry trace-run-start",
                id=f"trace-cmd-{cmd_id}",
            ),
            Script(_open_trace),
            id="trace-content",
            hx_swap_oob="beforeend",
        ))

        # Show streaming cursor while "processing"
        asst_id = str(uuid.uuid4())
        content_id = f"content-{asst_id}"
        await self.send(Div(
            Div(
                Div(
                    Span("", id=f"message-content-{asst_id}"),
                    Span("", cls="chat-streaming", id=f"streaming-{asst_id}"),
                    cls="chat-message-content",
                ),
                cls="chat-message chat-assistant",
                id=f"message-{asst_id}",
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        ))

        # Brief pause to show the streaming state
        await asyncio.sleep(0.15)

        # Remove streaming cursor and inject final content
        await self.send(Span("", id=f"streaming-{asst_id}", hx_swap_oob="outerHTML"))

        # Result enrichment — prepend card if available
        card_html = _enrich_result(msg, result)
        md_id = f"md-{content_id}"
        if card_html:
            await self.send(Div(
                Div(
                    NotStr(card_html),
                    Div(result, cls="marked", id=md_id),
                    cls="chat-message-content result-enriched", id=content_id,
                ),
                cls="chat-message chat-assistant",
                id=f"message-{asst_id}",
                hx_swap_oob="outerHTML",
            ))
            await self._send_js(f"renderMarkdown('{md_id}');")
        else:
            await self.send(Div(
                Div(result, cls="chat-message-content marked", id=content_id),
                cls="chat-message chat-assistant",
                id=f"message-{asst_id}",
                hx_swap_oob="outerHTML",
            ))
            await self._send_js(f"renderMarkdown('{content_id}');")

        # Auto-scroll to bottom after result swap
        await self._send_js(_SCROLL_CHAT_JS)

        # Trace: command complete
        await self.send(Div(
            Div(
                Span("Command complete", cls="trace-label"),
                cls="trace-entry trace-done",
            ),
            id="trace-content",
            hx_swap_oob="beforeend",
        ))

        # Store message
        asst_dict = {"role": "assistant", "content": result, "message_id": asst_id}
        self._messages.append(asst_dict)
        try:
            save_message(self.thread_id, "assistant", result, asst_id)
        except Exception:
            pass

        # Refresh sidebar conversation list
        await self._refresh_conv_list()

        # Re-enable input + release guard
        await self._send_js(
            _GUARD_DISABLE_JS +
            "var b=document.querySelector('.chat-input-button'),t=document.getElementById('chat-input');"
            "if(b){b.disabled=false;b.classList.remove('sending')}"
            "if(t){t.disabled=false;t.placeholder='Type a command or ask a question...';t.focus()}"
        )

        # Clear input form + show follow-up suggestions
        await self.send(self.ui._clear_input())
        await self.set_suggestions(_get_followup_suggestions(msg, result))

    async def _handle_streaming_command(self, msg: str, sc: StreamingCommand, session):
        """Run a long-running command in background, streaming logs via WS."""
        _open_trace = (
            "var l=document.querySelector('.app-layout');"
            "if(l&&!l.classList.contains('right-open'))l.classList.add('right-open');"
            "setTimeout(function(){var tc=document.getElementById('trace-content');"
            "if(tc)tc.scrollTop=tc.scrollHeight;},100);"
        )
        cmd_id = str(uuid.uuid4())
        asst_id = str(uuid.uuid4())
        log_pre_id = f"log-pre-{asst_id}"
        log_console_id = f"log-console-{asst_id}"
        content_id = f"content-{asst_id}"
        trace_progress_id = f"trace-progress-{cmd_id}"

        # 1. Append + send user message
        user_mid = str(uuid.uuid4())
        user_dict = {"role": "user", "content": msg, "message_id": user_mid}
        self._messages.append(user_dict)

        # Persist
        try:
            save_conversation(self.thread_id, user_id=self._user_id,
                              title=msg[:80] if len(self._messages) == 1 else None)
        except Exception:
            try:
                save_conversation(self.thread_id, user_id=self._user_id)
            except Exception:
                pass
        try:
            save_message(self.thread_id, "user", msg, user_mid)
        except Exception:
            pass

        await self.send(Div(
            Div(
                Div(msg, cls="chat-message-content"),
                cls="chat-message chat-user",
                id=user_mid,
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        ))

        # 2. Open trace pane with command label
        await self.send(Div(
            Div(
                Span(f"Command: {msg}", cls="trace-label"),
                cls="trace-entry trace-run-start",
                id=f"trace-cmd-{cmd_id}",
            ),
            Script(_open_trace),
            id="trace-content",
            hx_swap_oob="beforeend",
        ))

        # 3. Send log console bubble with progress bar
        progress_bar_id = f"progress-{asst_id}"
        await self.send(Div(
            Div(
                Div(
                    Div(
                        Div(Div(cls="progress-bar-fill", id=f"progress-fill-{asst_id}"), cls="progress-bar-outer"),
                        Div("", cls="progress-bar-label", id=f"progress-label-{asst_id}"),
                        cls="progress-bar-container", id=progress_bar_id,
                    ),
                    Pre("Starting...", id=log_pre_id, cls="agui-log-pre"),
                    cls="agui-log-console",
                    id=log_console_id,
                ),
                cls="chat-message chat-assistant",
                id=f"message-{asst_id}",
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        ))

        # 4. Add trace progress entry (updated in-place during polling)
        await self.send(Div(
            Div(
                Span("Running...", cls="trace-label"),
                Span("0 log lines", cls="trace-detail", id=f"trace-detail-{cmd_id}"),
                cls="trace-entry trace-streaming",
                id=trace_progress_id,
            ),
            id="trace-content",
            hx_swap_oob="beforeend",
        ))

        # 5. Clear input form then disable textarea + button after OOB swap
        await self.send(self.ui._clear_input())
        await self._send_js(
            "setTimeout(function(){"
            "var b=document.querySelector('.chat-input-button'),ta=document.getElementById('chat-input');"
            "if(b){b.disabled=true;b.classList.add('sending')}"
            "if(ta){ta.disabled=true;ta.placeholder='Running command...';}"
            "}, 100);"
        )

        # 6. Attach LogCapture to root logger and ensure INFO level
        log_capture = LogCapture(maxlen=1000)
        root_logger = logging.getLogger()
        prev_level = root_logger.level
        if root_logger.level > logging.INFO:
            root_logger.setLevel(logging.INFO)
        root_logger.addHandler(log_capture)

        # 7. Launch command in background
        result_holder = {"value": None, "error": None, "done": False}

        async def _run_command():
            try:
                from tui.command_processor import CommandProcessor
                user_id = session.get("user", {}).get("user_id") if session.get("user") else None
                cp = CommandProcessor(sc.app_state, user_id=user_id)
                result_holder["value"] = await cp.process_command(sc.raw_command)
            except Exception as e:
                import traceback
                result_holder["error"] = traceback.format_exc()
            finally:
                result_holder["done"] = True

        asyncio.create_task(_run_command())

        # 8. Poll loop — push log updates every 0.5s
        prev_line_count = 0
        while not result_holder["done"]:
            await asyncio.sleep(0.5)
            lines = log_capture.get_lines()
            if len(lines) != prev_line_count:
                prev_line_count = len(lines)
                # Filter verbose init lines for display only
                display_lines = _filter_log_lines(lines[-100:])
                log_text = "\n".join(display_lines) if display_lines else "Initializing..."
                try:
                    await self.send(Pre(
                        log_text,
                        id=log_pre_id,
                        cls="agui-log-pre",
                        hx_swap_oob="outerHTML",
                    ))
                    # Update trace detail
                    await self.send(Span(
                        f"{len(lines)} log lines",
                        cls="trace-detail",
                        id=f"trace-detail-{cmd_id}",
                        hx_swap_oob="outerHTML",
                    ))
                    # Progress bar — detect [N/M] pattern in recent lines
                    progress_js = ""
                    for raw_line in reversed(lines[-20:]):
                        pm = re.search(r'\[(\d+)/(\d+)\]', raw_line)
                        if pm:
                            current, total = int(pm.group(1)), int(pm.group(2))
                            pct = min(100, int(current / total * 100)) if total else 0
                            progress_js = (
                                f"var c=document.getElementById('{progress_bar_id}');"
                                f"if(c)c.classList.add('active');"
                                f"var f=document.getElementById('progress-fill-{asst_id}');"
                                f"if(f)f.style.width='{pct}%';"
                                f"var lb=document.getElementById('progress-label-{asst_id}');"
                                f"if(lb)lb.textContent='{current}/{total}';"
                            )
                            break
                    # Auto-scroll log console + chat + progress bar update
                    await self._send_js(
                        progress_js
                        + f"var lc=document.getElementById('{log_console_id}');"
                        "if(lc)lc.scrollTop=lc.scrollHeight;"
                        + _SCROLL_CHAT_JS
                    )
                except Exception:
                    break  # WS disconnected

        # 9. Cleanup: remove log handler, restore level
        root_logger.removeHandler(log_capture)
        root_logger.setLevel(prev_level)

        # 10. Final result
        if result_holder["error"]:
            final_result = f"# Error\n\n```\n{result_holder['error']}\n```"
        else:
            final_result = result_holder["value"] or "Command executed."

        # Auto-append equity curve chart for backtest results
        cmd_first = msg.strip().lower().split()[0] if msg.strip() else ""
        if cmd_first.startswith("agent:backtest") and final_result and "Error" not in final_result[:20]:
            try:
                run_id_match = re.search(r'Run ID\*?\*?:?\s*`?([a-f0-9-]+)',final_result)
                if run_id_match:
                    from utils.equity_chart import show_equity_curve
                    eq_result = show_equity_curve(run_id=run_id_match.group(1))
                    if "__CHART_DATA__" in eq_result:
                        final_result += "\n\n" + eq_result
            except Exception as _eq_err:
                logger.warning(f"Equity chart auto-append failed: {_eq_err}")

        # Replace log console with final markdown result (with enrichment)
        try:
            card_html = _enrich_result(msg, final_result)
            md_id = f"md-{content_id}"
            if card_html:
                await self.send(Div(
                    Div(
                        NotStr(card_html),
                        Div(final_result, cls="marked", id=md_id),
                        cls="chat-message-content result-enriched", id=content_id,
                    ),
                    cls="chat-message chat-assistant",
                    id=f"message-{asst_id}",
                    hx_swap_oob="outerHTML",
                ))
                await self._send_js(f"renderMarkdown('{md_id}');")
            else:
                await self.send(Div(
                    Div(final_result, cls="chat-message-content marked", id=content_id),
                    cls="chat-message chat-assistant",
                    id=f"message-{asst_id}",
                    hx_swap_oob="outerHTML",
                ))
                await self._send_js(f"renderMarkdown('{content_id}');")

            # Auto-scroll to bottom after result swap
            await self._send_js(_SCROLL_CHAT_JS)

            # Trace: command complete
            await self.send(Div(
                Div(
                    Span("Command complete", cls="trace-label"),
                    Span(
                        f"{prev_line_count} log lines total",
                        cls="trace-detail",
                    ),
                    cls="trace-entry trace-done",
                ),
                id="trace-content",
                hx_swap_oob="beforeend",
            ))

            # Store message in history
            asst_dict = {"role": "assistant", "content": final_result, "message_id": asst_id}
            self._messages.append(asst_dict)
            try:
                save_message(self.thread_id, "assistant", final_result, asst_id)
            except Exception:
                pass

            # Refresh sidebar conversation list
            await self._refresh_conv_list()

            # Re-enable input + release guard
            await self.send(self.ui._clear_input())
            await self._send_js(
                _GUARD_DISABLE_JS +
                "setTimeout(function(){var ta=document.getElementById('chat-input');"
                "if(ta)ta.focus();}, 100);"
            )

            # Follow-up suggestions
            await self.set_suggestions(_get_followup_suggestions(msg, final_result))
        except Exception:
            pass  # WS disconnected — no-op
            # Ensure guard is released even on error
            try:
                await self._send_js(_GUARD_DISABLE_JS)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

class AGUISetup:
    """Wire AG-UI routes into a FastHTML app."""

    def __init__(self, app, langgraph_agent, command_interceptor=None):
        self.app = app
        self._agent = langgraph_agent
        self._threads: Dict[str, AGUIThread] = {}
        self._command_interceptor = command_interceptor
        self._setup_routes()

    def _setup_routes(self):
        @self.app.get("/agui/ui/{thread_id}/chat")
        async def agui_chat_ui(thread_id: str, session):
            session["thread_id"] = thread_id
            return self.thread(thread_id, session).ui.chat()

        @self.app.ws(
            "/agui/ws/{thread_id}",
            conn=self._on_conn,
            disconn=self._on_disconn,
        )
        async def agui_ws(thread_id: str, msg: str, session):
            await self._threads[thread_id]._handle_message(msg, session)

        @self.app.route("/agui/messages/{thread_id}")
        def agui_messages(thread_id: str, session):
            thread = self.thread(thread_id, session)
            thread._ensure_loaded()
            if thread._messages:
                return thread.ui._render_messages(thread._messages)
            return Div(thread.ui._render_welcome(), id="chat-messages", cls="chat-messages")

    def thread(self, thread_id: str, session=None) -> AGUIThread:
        if thread_id not in self._threads:
            user_id = None
            if session and session.get("user"):
                user_id = session["user"].get("user_id")
            t = AGUIThread(thread_id=thread_id, langgraph_agent=self._agent,
                           user_id=user_id)
            if self._command_interceptor:
                t._command_interceptor = self._command_interceptor
            self._threads[thread_id] = t
        return self._threads[thread_id]

    def _on_conn(self, ws, send, session):
        tid = session.get("thread_id", "default")
        self.thread(tid, session).subscribe(str(id(ws)), send)

    def _on_disconn(self, ws, session):
        tid = session.get("thread_id", "default")
        if tid in self._threads:
            self._threads[tid].unsubscribe(str(id(ws)))

    def chat(self, thread_id: str):
        """Return a loader div that fetches the chat UI."""
        return Div(
            hx_get=f"/agui/ui/{thread_id}/chat",
            hx_trigger="load",
            hx_swap="innerHTML",
        )


def setup_agui(app, langgraph_agent, command_interceptor=None) -> AGUISetup:
    """One-line setup: wire AG-UI into a FastHTML app."""
    return AGUISetup(app, langgraph_agent, command_interceptor=command_interceptor)

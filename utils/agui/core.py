"""
AG-UI core: WebSocket-based chat with pydantic-ai agents.

Based on ft-agui core.py — adapted for AlpaTrade.
"""

from typing import Dict, List, Optional, Any, TypeVar, Generic
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.ui.ag_ui import AGUIAdapter
from pydantic_ai.ui import StateDeps
from ag_ui.core.types import (
    RunAgentInput,
    Tool,
    BaseMessage,
    UserMessage,
    AssistantMessage,
    Context,
)
from ag_ui.core.events import (
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    TextMessageStartEvent,
    TextMessageChunkEvent,
    StateSnapshotEvent,
)
from fasthtml.common import (
    Div, Form, Hidden, Textarea, Button, Span, Script, Style, Pre,
)
import asyncio
import collections
import logging
import threading
import uuid

from .patches import setup_ft_patches
from .styles import get_chat_styles


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

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# UI renderer
# ---------------------------------------------------------------------------

class UI(Generic[T]):
    """Renders chat components for a given thread."""

    def __init__(self, thread_id: str, autoscroll: bool = True):
        self.thread_id = thread_id
        self.autoscroll = autoscroll

    def _trigger_run(self, run_id: str):
        return Div(
            "...",
            Div(
                id=f"run-trigger-{run_id}",
                hx_get=f"/agui/run/{self.thread_id}/{run_id}",
                hx_trigger="load",
                style="display: none;",
            ),
            id="chat-status",
            hx_swap_oob="innerHTML",
        )

    def _clear_input(self):
        return self._render_input_form(oob_swap=True)

    def _render_messages(self, messages: List[BaseMessage], oob: bool = False):
        attrs = {"id": "chat-messages", "cls": "chat-messages"}
        if oob:
            attrs["hx_swap_oob"] = "outerHTML"
        return Div(
            *[
                m.__ft__() if hasattr(m, "__ft__") else self._render_message(m)
                for m in messages
            ],
            **attrs,
        )

    def _render_message(self, message: BaseMessage):
        cls = "chat-user" if message.role == "user" else "chat-assistant"
        return Div(
            Div(message.content, cls="chat-message-content"),
            cls=f"chat-message {cls}",
            id=message.id,
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
                    placeholder="Type a command or ask a question...",
                    autofocus=True,
                    autocomplete="off",
                    cls="chat-input-field",
                    rows="1",
                    onkeydown="handleKeyDown(this, event)",
                    oninput="autoResize(this)",
                ),
                Button("Send", type="submit", cls="chat-input-button"),
                cls="chat-input-form",
                id="chat-form",
                ws_send=True,
            ),
            **container_attrs,
        )

    def chat(self, **kwargs):
        """Return the full chat widget (messages + input + scripts)."""
        components = [
            get_chat_styles(),
            Div(
                id="chat-messages",
                cls="chat-messages",
                hx_get=f"/agui/messages/{self.thread_id}",
                hx_trigger="load",
                hx_swap="outerHTML",
            ),
            self._render_input_form(),
            Script("""
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
                        var form = textarea.closest('form');
                        if (form && textarea.value.trim()) form.requestSubmit();
                    }
                }
                function renderMarkdown(elementId) {
                    setTimeout(function() {
                        var el = document.getElementById(elementId);
                        if (el && window.marked) {
                            var txt = el.textContent || el.innerText;
                            if (txt.trim()) {
                                el.innerHTML = marked.parse(txt);
                                el.classList.remove('marked');
                                el.classList.add('marked-done');
                                delete el.dataset.rendering;
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
                                    var finalTxt = el.textContent || el.innerText;
                                    if (finalTxt.trim()) {
                                        el.innerHTML = marked.parse(finalTxt);
                                        el.classList.remove('marked');
                                        el.classList.add('marked-done');
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

        return Div(
            *components,
            hx_ext="ws",
            ws_connect=f"/agui/ws/{self.thread_id}",
            cls="chat-container",
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Thread (conversation)
# ---------------------------------------------------------------------------

class AGUIThread(Generic[T]):
    """Single conversation thread with message history and agent runs."""

    def __init__(self, thread_id: str, state: T, agent: Agent):
        self.thread_id = thread_id
        self._state = state
        self._runs: Dict[str, RunAgentInput] = {}
        self._agent = agent
        self._messages: List[BaseMessage] = []
        self._connections: Dict[str, Any] = {}
        self.ui = UI[T](self.thread_id, autoscroll=True)
        self._suggestions: List[str] = []
        self._command_interceptor = None  # async callable(msg, session) -> str|None

    def subscribe(self, connection_id, send):
        self._connections[connection_id] = send

    def unsubscribe(self, connection_id: str):
        self._connections.pop(connection_id, None)

    async def send(self, element):
        for _, send_fn in self._connections.items():
            await send_fn(element)

    async def set_suggestions(self, suggestions: List[str]):
        self._suggestions = suggestions[:4]
        if self._suggestions:
            el = Div(
                *[
                    Button(
                        s,
                        onclick=f"var ta=document.getElementById('chat-input');"
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

    async def _handle_message(self, msg: str, session):
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

        run_id = str(uuid.uuid4())
        message = UserMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=msg,
            name=session.get("username", "User"),
        )
        self._messages.append(message)

        run_input = RunAgentInput(
            thread_id=self.thread_id,
            run_id=run_id,
            messages=self._messages,
            state=self._state,
            tools=[],
            forwarded_props=[],
            context=[],
        )
        self._runs[run_id] = run_input

        await self.send(self.ui._render_messages(self._messages, oob=True))
        await self.send(self.ui._trigger_run(run_id))
        await self.send(self.ui._clear_input())

    async def _handle_command_result(self, msg: str, result: str, session):
        """Display a CLI command result in chat with trace pane integration."""
        import asyncio
        from fasthtml.common import Script

        _open_trace = (
            "var l=document.querySelector('.app-layout');"
            "if(l&&!l.classList.contains('right-open'))l.classList.add('right-open');"
            "setTimeout(function(){var tc=document.getElementById('trace-content');"
            "if(tc)tc.scrollTop=tc.scrollHeight;},100);"
        )
        cmd_id = str(uuid.uuid4())

        # Append user message
        user_msg = UserMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=msg,
            name=session.get("username", "User"),
        )
        self._messages.append(user_msg)

        # Send user message + open trace with "Command started"
        await self.send(Div(
            Div(
                Div(msg, cls="chat-message-content"),
                cls="chat-message chat-user",
                id=user_msg.id,
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
        await self.send(Div(
            Div(result, cls="chat-message-content marked", id=content_id),
            cls="chat-message chat-assistant",
            id=f"message-{asst_id}",
            hx_swap_oob="outerHTML",
        ))
        await self.send(Script(f"renderMarkdown('{content_id}');"))

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
        asst_msg = AssistantMessage(
            id=asst_id,
            role="assistant",
            content=result,
            name=self._agent.name or "AlpaTrade",
        )
        self._messages.append(asst_msg)

        # Clear input form
        await self.send(self.ui._clear_input())

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
        user_msg = UserMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=msg,
            name=session.get("username", "User"),
        )
        self._messages.append(user_msg)

        await self.send(Div(
            Div(
                Div(msg, cls="chat-message-content"),
                cls="chat-message chat-user",
                id=user_msg.id,
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

        # 3. Send log console bubble
        await self.send(Div(
            Div(
                Div(
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

        # 5. Clear input + disable textarea
        await self.send(self.ui._clear_input())
        await self.send(Script(
            "var ta=document.getElementById('chat-input');"
            "if(ta){ta.disabled=true;ta.placeholder='Running command...';}"
        ))

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
                log_text = "\n".join(lines[-100:])  # Show last 100 lines
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
                    # Auto-scroll log console
                    await self.send(Script(
                        f"var lc=document.getElementById('{log_console_id}');"
                        "if(lc)lc.scrollTop=lc.scrollHeight;"
                    ))
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

        # Replace log console with final markdown result
        try:
            await self.send(Div(
                Div(final_result, cls="chat-message-content marked", id=content_id),
                cls="chat-message chat-assistant",
                id=f"message-{asst_id}",
                hx_swap_oob="outerHTML",
            ))
            await self.send(Script(f"renderMarkdown('{content_id}');"))

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

            # Re-enable input
            await self.send(Script(
                "var ta=document.getElementById('chat-input');"
                "if(ta){ta.disabled=false;"
                "ta.placeholder='Type a command or ask a question...';"
                "ta.focus();}"
            ))
        except Exception:
            pass  # WS disconnected — no-op

        # Store message in history
        asst_msg = AssistantMessage(
            id=asst_id,
            role="assistant",
            content=final_result,
            name=self._agent.name or "AlpaTrade",
        )
        self._messages.append(asst_msg)

    async def _handle_run(self, run_id: str):
        if run_id not in self._runs:
            return Div("Run not found")

        run_input = self._runs[run_id]
        adapter = AGUIAdapter(self._agent, run_input=run_input)
        response = AssistantMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content="",
            name=self._agent.name or "AlpaTrade",
        )
        deps = StateDeps[T](state=self._state)
        streamed = False  # Track whether TextMessageStart fired

        async for event in adapter.run_stream(
            message_history=self._messages or [],
            deps=deps,
        ):
            if hasattr(event, "__ft__"):
                result = event.__ft__()
                # Support tuple/list returns for multi-target OOB swaps
                if isinstance(result, (tuple, list)):
                    for el in result:
                        await self.send(el)
                else:
                    await self.send(result)

            if event.type == EventType.TEXT_MESSAGE_START:
                response.id = event.message_id
                response.content = ""  # Reset for each new text message
                streamed = True
            elif event.type == EventType.TEXT_MESSAGE_CONTENT:
                response.content += event.delta
            elif event.type == EventType.RUN_FINISHED:
                self._messages.append(response)
                if not streamed and response.content:
                    # Fallback: show final content only if streaming didn't happen
                    content_id = f"content-{response.id}"
                    await self.send(
                        Div(
                            Div(
                                Div(
                                    response.content,
                                    cls="chat-message-content marked",
                                    id=content_id,
                                ),
                                cls="chat-message chat-assistant",
                                id=f"message-{response.id}",
                            ),
                            id="chat-messages",
                            hx_swap_oob="beforeend",
                        )
                    )
                    await self.send(Script(f"renderMarkdown('{content_id}');"))
                await self.send(Div(id="chat-status", hx_swap_oob="innerHTML"))
            elif event.type == EventType.STATE_SNAPSHOT:
                self._state = event.snapshot

        return Div()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

class AGUISetup(Generic[T]):
    """Wire AG-UI routes into a FastHTML app."""

    def __init__(self, app, agent: Agent, state: T, command_interceptor=None):
        self.app = app
        self.agent = agent
        self._state: T = state
        self._threads: Dict[str, AGUIThread[T]] = {}
        self._command_interceptor = command_interceptor
        setup_ft_patches()
        self._setup_routes()

    def _setup_routes(self):
        @self.app.get("/agui/ui/{thread_id}/chat")
        async def agui_chat_ui(thread_id: str, session):
            session["thread_id"] = thread_id
            return self.thread(thread_id).ui.chat()

        @self.app.get("/agui/ui/{thread_id}/state")
        async def agui_state_ui(thread_id: str):
            st = self.thread(thread_id)._state
            if hasattr(st, "__ft__"):
                return st.__ft__()
            return Div()

        @self.app.ws(
            "/agui/ws/{thread_id}",
            conn=self._on_conn,
            disconn=self._on_disconn,
        )
        async def agui_ws(thread_id: str, msg: str, session):
            await self._threads[thread_id]._handle_message(msg, session)

        @self.app.route("/agui/run/{thread_id}/{run_id}")
        async def agui_run(thread_id: str, run_id: str):
            return await self._threads[thread_id]._handle_run(run_id)

        @self.app.route("/agui/messages/{thread_id}")
        def agui_messages(thread_id: str):
            thread = self.thread(thread_id)
            if thread._messages:
                return thread.ui._render_messages(thread._messages)
            return Div(id="chat-messages", cls="chat-messages")

    def thread(self, thread_id: str) -> AGUIThread[T]:
        if thread_id not in self._threads:
            t = AGUIThread[T](thread_id=thread_id, state=self._state, agent=self.agent)
            if self._command_interceptor:
                t._command_interceptor = self._command_interceptor
            self._threads[thread_id] = t
        return self._threads[thread_id]

    def _on_conn(self, ws, send, session):
        tid = session.get("thread_id", "default")
        self.thread(tid).subscribe(str(id(ws)), send)

    def _on_disconn(self, ws, session):
        tid = session.get("thread_id", "default")
        self.thread(tid).unsubscribe(str(id(ws)))

    def chat(self, thread_id: str):
        """Return a loader div that fetches the chat UI."""
        return Div(
            hx_get=f"/agui/ui/{thread_id}/chat",
            hx_trigger="load",
            hx_swap="innerHTML",
        )

    def state(self, thread_id: str):
        return Div(
            hx_get=f"/agui/ui/{thread_id}/state",
            hx_trigger="load",
            hx_swap="innerHTML",
        )

    async def set_suggestions(self, thread_id: str, suggestions: List[str]):
        await self.thread(thread_id).set_suggestions(suggestions)


def setup_agui(app, agent: Agent, initial_state: T, state_type: type,
               command_interceptor=None) -> AGUISetup:
    """One-line setup: wire AG-UI into a FastHTML app."""
    state = state_type.model_validate_json(initial_state.model_dump_json())
    return AGUISetup(app, agent, state, command_interceptor=command_interceptor)

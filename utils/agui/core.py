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
    Div, Form, Hidden, Textarea, Button, Span, Script, Style,
)
import uuid

from .patches import setup_ft_patches
from .styles import get_chat_styles

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
            elif event.type == EventType.TEXT_MESSAGE_CONTENT:
                response.content += event.delta
            elif event.type == EventType.RUN_FINISHED:
                self._messages.append(response)
                content_id = f"content-{response.id}"
                await self.send(
                    Div(
                        Div(
                            response.content,
                            cls="chat-message-content marked",
                            id=content_id,
                        ),
                        cls="chat-message chat-assistant",
                        id=f"message-{response.id}",
                        hx_swap_oob="outerHTML",
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

    def __init__(self, app, agent: Agent, state: T):
        self.app = app
        self.agent = agent
        self._state: T = state
        self._threads: Dict[str, AGUIThread[T]] = {}
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
        self._threads.setdefault(
            thread_id,
            AGUIThread[T](thread_id=thread_id, state=self._state, agent=self.agent),
        )
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


def setup_agui(app, agent: Agent, initial_state: T, state_type: type) -> AGUISetup:
    """One-line setup: wire AG-UI into a FastHTML app."""
    state = state_type.model_validate_json(initial_state.model_dump_json())
    return AGUISetup(app, agent, state)

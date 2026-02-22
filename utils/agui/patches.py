"""
FastHTML rendering patches (__ft__) for AG-UI protocol event types.

Based on ft-agui patches.py — extended with thinking trace + artifact pane support.
Events render in both the chat area and the right-pane trace panel via OOB swaps.

Returns tuples when multiple OOB targets are needed — core.py sends each element
separately via WebSocket so HTMX processes them independently.
"""

from fasthtml.common import Div, Span, Pre, Script, patch
from ag_ui.core.types import BaseMessage
from ag_ui.core.events import (
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageChunkEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    StateSnapshotEvent,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    StepStartedEvent,
    StepFinishedEvent,
)


_OPEN_TRACE_JS = (
    "var l=document.querySelector('.app-layout');"
    "if(l&&!l.classList.contains('right-open'))l.classList.add('right-open');"
    "setTimeout(function(){var tc=document.getElementById('trace-content');"
    "if(tc)tc.scrollTop=tc.scrollHeight;},100);"
)


def setup_ft_patches():
    """Monkey-patch __ft__() onto AG-UI event types for FastHTML rendering."""

    @patch
    def __ft__(self: BaseMessage):
        cls = "chat-user" if self.role == "user" else "chat-assistant"
        return Div(
            Div(self.content, cls="chat-message-content marked"),
            cls=f"chat-message {cls}",
            id=self.id,
        )

    @patch
    def __ft__(self: RunStartedEvent):
        return (
            Div(
                Div(
                    Span("Run started", cls="trace-label"),
                    cls="trace-entry trace-run-start",
                    id=f"trace-run-{self.run_id}",
                ),
                Script(_OPEN_TRACE_JS),
                id="trace-content",
                hx_swap_oob="beforeend",
            ),
        )

    @patch
    def __ft__(self: TextMessageStartEvent):
        return (
            # Append message bubble to #chat-messages
            # NOTE: no "marked" class during streaming — added by TextMessageEndEvent
            Div(
                Div(
                    Div(
                        Span("", id=f"message-content-{self.message_id}"),
                        Span("", cls="chat-streaming", id=f"streaming-{self.message_id}"),
                        cls="chat-message-content",
                    ),
                    cls="chat-message chat-assistant",
                    id=f"message-{self.message_id}",
                ),
                id="chat-messages",
                hx_swap_oob="beforeend",
            ),
            # Append trace entry to #trace-content
            Div(
                Div(
                    Span("Generating response...", cls="trace-label"),
                    cls="trace-entry trace-streaming",
                    id=f"trace-msg-{self.message_id}",
                ),
                id="trace-content",
                hx_swap_oob="beforeend",
            ),
        )

    @patch
    def __ft__(self: TextMessageChunkEvent):
        return Span(
            self.delta,
            id=f"message-content-{self.message_id}",
            hx_swap_oob="beforeend",
        )

    @patch
    def __ft__(self: TextMessageContentEvent):
        return Span(
            self.delta,
            id=f"message-content-{self.message_id}",
            hx_swap_oob="beforeend",
        )

    @patch
    def __ft__(self: TextMessageEndEvent):
        content_id = f"message-content-{self.message_id}"
        return (
            # Remove streaming cursor (outerHTML replaces the span, removing ::after)
            Span("", id=f"streaming-{self.message_id}", hx_swap_oob="outerHTML"),
            # Update trace + add marked class + trigger markdown render
            Div(
                Span("Response complete", cls="trace-label"),
                Script(
                    f"var el=document.getElementById('{content_id}');"
                    f"if(el)el.classList.add('marked');"
                    f"renderMarkdown('{content_id}');"
                ),
                cls="trace-entry trace-done",
                id=f"trace-msg-{self.message_id}",
                hx_swap_oob="outerHTML",
            ),
        )

    @patch
    def __ft__(self: StateSnapshotEvent):
        if hasattr(self.snapshot, "__ft__"):
            return self.snapshot.__ft__()
        return Div(Pre(str(self.snapshot)), id="agui-state", hx_swap_oob="innerHTML")

    @patch
    def __ft__(self: ToolCallStartEvent):
        return (
            # Append tool indicator to #chat-messages
            Div(
                Div(
                    Div(f"Running {self.tool_call_name}...", cls="chat-message-content"),
                    cls="chat-message chat-tool",
                    id=f"tool-{self.tool_call_id}",
                ),
                id="chat-messages",
                hx_swap_oob="beforeend",
            ),
            # Append trace entry to #trace-content (with auto-open script)
            Div(
                Div(
                    Span(f"Tool: {self.tool_call_name}", cls="trace-label"),
                    Span("running...", cls="trace-detail"),
                    cls="trace-entry trace-tool-active",
                    id=f"trace-tool-{self.tool_call_id}",
                ),
                Script(_OPEN_TRACE_JS),
                id="trace-content",
                hx_swap_oob="beforeend",
            ),
        )

    @patch
    def __ft__(self: ToolCallArgsEvent):
        args_str = self.delta if hasattr(self, 'delta') else ""
        if args_str:
            return Span(
                args_str,
                cls="trace-detail",
                id=f"trace-tool-{self.tool_call_id}",
                hx_swap_oob="beforeend",
            )
        return Span()

    @patch
    def __ft__(self: ToolCallEndEvent):
        return (
            Div(
                Div("Done", cls="chat-message-content"),
                cls="chat-message chat-tool",
                id=f"tool-{self.tool_call_id}",
                hx_swap_oob="outerHTML",
            ),
            Div(
                Span("Tool complete", cls="trace-label"),
                cls="trace-entry trace-tool-done",
                id=f"trace-tool-{self.tool_call_id}",
                hx_swap_oob="outerHTML",
            ),
        )

    @patch
    def __ft__(self: RunFinishedEvent):
        return (
            Div(
                Div(
                    Span("Run finished", cls="trace-label"),
                    cls="trace-entry trace-run-end",
                ),
                id="trace-content",
                hx_swap_oob="beforeend",
            ),
            Div(id="chat-status", hx_swap_oob="innerHTML"),
        )

    @patch
    def __ft__(self: RunErrorEvent):
        return (
            Div(
                Div(
                    Div("Error:", cls="agui-error-title"),
                    Div(self.message, cls="agui-error-details"),
                    cls="chat-message-content",
                ),
                cls="chat-message chat-error",
                id="chat-messages",
                hx_swap_oob="beforeend",
            ),
            Div(
                Div(
                    Span("Error", cls="trace-label"),
                    Span(self.message, cls="trace-detail"),
                    cls="trace-entry trace-error",
                ),
                id="trace-content",
                hx_swap_oob="beforeend",
            ),
        )

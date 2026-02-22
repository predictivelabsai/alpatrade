"""
FastHTML rendering patches (__ft__) for AG-UI protocol event types.

Based on ft-agui patches.py — extended with thinking trace event support.
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
        return Div(
            Div(id=f"run-{self.run_id}"),
            id="agui-messages",
            hx_swap_oob="beforeend",
        )

    @patch
    def __ft__(self: TextMessageStartEvent):
        return Div(
            Div(
                Div(
                    Span("", id=f"message-content-{self.message_id}", cls="marked"),
                    Span("", cls="chat-streaming", id=f"streaming-{self.message_id}"),
                    cls="chat-message-content",
                ),
                cls="chat-message chat-assistant",
                id=f"message-{self.message_id}",
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
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
        return Span("", id=f"streaming-{self.message_id}")

    @patch
    def __ft__(self: StateSnapshotEvent):
        if hasattr(self.snapshot, "__ft__"):
            return self.snapshot.__ft__()
        return Div(Pre(str(self.snapshot)), id="agui-state", hx_swap_oob="innerHTML")

    @patch
    def __ft__(self: ToolCallStartEvent):
        # Render in both chat (compact) and trace pane (detailed)
        return Div(
            # Chat inline indicator
            Div(
                Div(f"Running {self.tool_call_name}...", cls="chat-message-content"),
                cls="chat-message chat-tool",
                id=f"tool-{self.tool_call_id}",
            ),
            id="chat-messages",
            hx_swap_oob="beforeend",
        )

    @patch
    def __ft__(self: ToolCallEndEvent):
        return Div(
            Div(
                "Done",
                cls="chat-message-content",
            ),
            cls="chat-message chat-tool",
            id=f"tool-{self.tool_call_id}",
            hx_swap_oob="outerHTML",
        )

    @patch
    def __ft__(self: RunErrorEvent):
        return Div(
            Div(
                Div("Error:", cls="agui-error-title"),
                Div(self.message, cls="agui-error-details"),
                cls="chat-message-content",
            ),
            cls="chat-message chat-error",
            id="agui-messages",
            hx_swap_oob="beforeend",
        )

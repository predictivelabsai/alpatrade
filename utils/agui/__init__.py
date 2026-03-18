"""
Vendored AG-UI integration for FastHTML + LangGraph.

Based on ft-agui (https://github.com/Novia-RDI-Seafaring/ft-ag-ui)
by Christoffer Bjorkskog / Novia University — MIT license.

Adapted for AlpaTrade: 3-pane layout, LangGraph streaming, no external
ft-agui dependency.
"""

from .core import setup_agui, AGUISetup, AGUIThread, UI, StreamingCommand
from .styles import get_chat_styles, get_custom_theme, CHAT_UI_STYLES
from .chat_store import (
    save_conversation, save_message,
    load_conversation_messages, list_conversations,
    delete_conversation,
)

__all__ = [
    "setup_agui",
    "AGUISetup",
    "AGUIThread",
    "UI",
    "StreamingCommand",
    "get_chat_styles",
    "get_custom_theme",
    "CHAT_UI_STYLES",
    "save_conversation",
    "save_message",
    "load_conversation_messages",
    "list_conversations",
    "delete_conversation",
]

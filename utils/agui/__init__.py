"""Compatibility shim — AG-UI integration relocated to `engine.ai` in the assethero
engine extraction (Phase 1). Import from `engine.ai` in new code; this facade keeps
existing `from utils.agui import ...` working and is removed in the Phase 7 cleanup."""
from engine.ai import (  # noqa: F401
    setup_agui, AGUISetup, AGUIThread, UI, StreamingCommand,
    get_chat_styles, get_custom_theme, CHAT_UI_STYLES,
    save_conversation, save_message,
    load_conversation_messages, list_conversations, delete_conversation,
)
from engine.ai import __all__  # noqa: F401

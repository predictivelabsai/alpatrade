"""
Vendored AG-UI integration for FastHTML + pydantic-ai.

Based on ft-agui (https://github.com/Novia-RDI-Seafaring/ft-ag-ui)
by Christoffer Bjorkskog / Novia University — MIT license.

Adapted for AlpaTrade: 3-pane layout, custom patches, no external
ft-agui dependency.
"""

from .core import setup_agui, AGUISetup, AGUIThread, UI
from .styles import get_chat_styles, get_custom_theme, CHAT_UI_STYLES
from .patches import setup_ft_patches

__all__ = [
    "setup_agui",
    "AGUISetup",
    "AGUIThread",
    "UI",
    "get_chat_styles",
    "get_custom_theme",
    "CHAT_UI_STYLES",
    "setup_ft_patches",
]

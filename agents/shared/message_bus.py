"""Compatibility shim — relocated to `engine.agents.message_bus` in the assethero engine extraction (Phase 1).
Removed in the Phase 7 cleanup."""
import sys as _sys
import engine.agents.message_bus as _relocated
_sys.modules[__name__] = _relocated

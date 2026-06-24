"""Compatibility shim — relocated to `engine.auth` in the assethero engine extraction (Phase 1).
Removed in the Phase 7 cleanup."""
import sys as _sys
import engine.auth as _relocated
_sys.modules[__name__] = _relocated

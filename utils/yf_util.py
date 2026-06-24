"""Compatibility shim — relocated to `engine.feeds.yf` in the assethero engine extraction (Phase 1).
Import from the new location in new code; this alias keeps existing imports working and
is removed in the Phase 7 cleanup."""
import sys as _sys
import engine.feeds.yf as _relocated
_sys.modules[__name__] = _relocated

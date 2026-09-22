"""Central feature switch for the optional Hermes integration."""
from __future__ import annotations

import os


def hermes_enabled() -> bool:
    """Return whether Hermes runtime, broker, and UI surfaces are enabled."""
    return os.getenv("HERMES_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }

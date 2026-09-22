"""Framework-neutral chat runtime override parsing."""
from __future__ import annotations


_RUNTIME_PREFIXES = {
    "/hermes": "hermes",
    "/deepagents": "deepagents",
    "/langgraph": "langgraph",
}


def agent_override(message: str) -> tuple[str | None, str]:
    """Return a one-message runtime override and the message without its prefix."""
    stripped = message.strip()
    first, separator, remainder = stripped.partition(" ")
    runtime = _RUNTIME_PREFIXES.get(first.lower())
    if not runtime:
        return None, message
    if runtime == "hermes":
        from engine.agents.hermes_feature import hermes_enabled
        if not hermes_enabled():
            return "hermes_disabled", remainder.strip() if separator else ""
    return runtime, remainder.strip() if separator else ""

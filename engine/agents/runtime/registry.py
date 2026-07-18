"""Select an :class:`AgentRuntime` from ``AGENT_FRAMEWORK`` with graceful fallback.

Resolution: requested name (or ``engine.config`` setting) → normalise aliases →
if that backend's library isn't installed (``available()`` is False), fall back to
LangGraph. So an unset/typo'd/uninstalled framework never breaks — same philosophy as
``engine.config.build_chat_model``'s model fallback.
"""
from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

# name → "module:class"
_ADAPTERS = {
    "langgraph": "engine.agents.runtime.langgraph_rt:LangGraphRuntime",
    "deepagents": "engine.agents.runtime.deepagents_rt:DeepAgentsRuntime",
    "pydantic_ai": "engine.agents.runtime.pydantic_rt:PydanticAIRuntime",
    "hermes": "engine.agents.runtime.hermes_rt:HermesRuntime",
}
_ALIASES = {
    "pydantic": "pydantic_ai", "pydantic-ai": "pydantic_ai", "pydanticai": "pydantic_ai",
    "deep-agents": "deepagents", "deep_agents": "deepagents",
    "nous": "hermes", "hermes-runtime": "hermes", "nous-hermes": "hermes",
    "lang-graph": "langgraph", "lang_graph": "langgraph",
}
_FALLBACK = "langgraph"


def _load(key: str):
    mod_path, cls_name = _ADAPTERS[key].split(":")
    return getattr(importlib.import_module(mod_path), cls_name)


def _canonical(name: str | None) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        try:
            from engine.config import get_settings
            raw = (get_settings().agent_framework or _FALLBACK).lower()
        except Exception:  # noqa: BLE001
            raw = _FALLBACK
    key = _ALIASES.get(raw, raw)
    return key if key in _ADAPTERS else _FALLBACK


def get_runtime(name: str | None = None):
    """Return an ``AgentRuntime`` instance for ``name`` / the configured framework."""
    key = _canonical(name)
    cls = _load(key)
    if not getattr(cls, "available", lambda: True)():
        logger.warning("AGENT_FRAMEWORK %r unavailable (library not installed) → %s",
                       key, _FALLBACK)
        cls = _load(_FALLBACK)
    return cls()


def available_runtimes() -> dict[str, bool]:
    """Map every known framework → whether its backend is importable here."""
    out: dict[str, bool] = {}
    for key in _ADAPTERS:
        try:
            out[key] = bool(getattr(_load(key), "available", lambda: True)())
        except Exception:  # noqa: BLE001
            out[key] = False
    return out

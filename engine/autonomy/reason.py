"""Reasoning helper — lets autonomy pipeline nodes delegate to the agent runtime.

The pipeline nodes previously called the legacy ``Orchestrator`` / ``ReportAgent``
directly, bypassing the pluggable runtime layer (``engine.agents.runtime``).
This module provides a thin ``reason()`` function that builds a one-shot agent
from the configured runtime (LangGraph / deepagents / hermes / pydantic-ai) and
asks it a question, returning the text. Nodes use it for the *judgement* parts
(e.g. "which of these strategies should we promote?") while keeping the
deterministic risk-gate (``policy.py``) and execution (``Orchestrator``) as
pure-function guards — the LLM never bypasses ``allow_live=False``.

Best-effort: on any runtime failure, returns ``""`` so the caller falls back to
the deterministic path. No node ever crashes because the LLM was unavailable.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.agents.runtime.base import RoleSpec

log = logging.getLogger("autonomy.reason")

# Module-level cache: build the reasoning agent once per framework, invalidated
# by clear_reasoning_cache() (called when a user changes agent_framework).
_reasoning_agent = None
_reasoning_framework: Optional[str] = None


def _get_reasoning_agent():
    """Build (or return cached) the reasoning agent for the configured framework.

    Rebuilds when the configured framework changes, so a settings change is
    picked up on the next call without a process restart (Phase 3b).
    """
    global _reasoning_agent, _reasoning_framework
    from engine.config import get_settings
    from engine.agents.runtime.registry import get_runtime

    s = get_settings()
    fw = s.agent_framework
    if _reasoning_agent is None or _reasoning_framework != fw:
        runtime = get_runtime(fw)
        spec = RoleSpec(
            name="alpatrade-reasoner",
            instructions=(
                "You are the reasoning layer of an autonomous paper-trading pipeline. "
                "Given structured data (backtest summaries, paper-trade outcomes, regime "
                "labels), produce a concise decision. Be decisive and numerate. Never "
                "recommend live orders — this is paper-only. Output plain text."
            ),
            temperature=0.3,
            max_tokens=800,
        )
        _reasoning_agent = runtime.build(spec)
        _reasoning_framework = fw
        log.info("reasoning agent built via %s runtime", fw)
    return _reasoning_agent


def clear_reasoning_cache() -> None:
    """Invalidate the cached reasoning agent (call on framework/settings change)."""
    global _reasoning_agent, _reasoning_framework
    _reasoning_agent = None
    _reasoning_framework = None


def reason(prompt: str) -> str:
    """Ask the configured runtime a reasoning question. Returns '' on any failure."""
    try:
        from engine.agents.runtime.registry import get_runtime
        s = get_settings()
        runtime = get_runtime(s.agent_framework)
        agent = _get_reasoning_agent()
        result = runtime.run(agent, prompt)
        return result.text or ""
    except Exception as e:  # noqa: BLE001
        log.warning("reason() failed (%s); falling back to deterministic path.", e)
        return ""

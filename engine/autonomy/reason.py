"""Reasoning helper — short, cosmetic LLM notes for autonomy pipeline nodes.

Nodes use ``reason()`` for one- or two-sentence annotations ("why did these params
win?"). The notes only go into ``autonomy_events``; every decision stays with the
deterministic risk gate (``policy.py``) and execution (``Orchestrator``), and the
LLM never bypasses ``allow_live=False``.

This used to build a full deepagents agent per call, which sent ~6,300 prompt
tokens (planning/filesystem/sub-agent tool schemas) for a one-line note, on a
retired model slug billed as grok-4.3. It is now a single plain chat call with
reasoning disabled, a small output cap, the platform daily budget applied, and
usage recorded in ``alpatrade.llm_usage_logging``.

Best-effort: on any failure (including an exhausted budget) it returns ``""`` so
the caller falls back to the deterministic path.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("autonomy.reason")

SYSTEM_PROMPT = (
    "You are the reasoning layer of an autonomous paper-trading pipeline. "
    "Given structured data (backtest summaries, paper-trade outcomes, regime "
    "labels), produce a concise decision. Be decisive and numerate. Never "
    "recommend live orders — this is paper-only. Output plain text."
)
MAX_TOKENS = int(os.getenv("AUTONOMY_REASON_MAX_TOKENS", "200"))
REASONING_EFFORT = os.getenv("AUTONOMY_REASONING_EFFORT", "none")


def clear_reasoning_cache() -> None:
    """Kept for callers that invalidate on settings change; nothing is cached now."""
    return None


def _build_model(settings):
    from engine.config import build_chat_model
    return build_chat_model(settings, streaming=False, temperature=0.3,
                            max_tokens=MAX_TOKENS, reasoning_effort=REASONING_EFFORT)


def reason(prompt: str, *, job_id: str | None = None) -> str:
    """Ask the configured model one short question. Returns '' on any failure."""
    try:
        from engine.ai.llm_usage import enforce_daily_budget, extract_usage, record_usage
        from engine.config import get_settings

        settings = get_settings()
        funding = "user_byok" if settings.api_key else "platform"
        enforce_daily_budget(funding_source=funding)
        model = _build_model(settings)
        msg = model.invoke([("system", SYSTEM_PROMPT), ("user", prompt)])
        text = getattr(msg, "content", "") or ""
        if isinstance(text, list):  # content blocks
            text = " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in text)
        try:
            record_usage(
                user_id=None, thread_id=None, agent="autonomy",
                provider=settings.model_provider or "xai",
                model=getattr(model, "model_name", None) or getattr(model, "model", None)
                or settings.model_name,
                funding_source=funding, prompt=SYSTEM_PROMPT + prompt, response=text,
                usage=extract_usage(msg), job_id=job_id,
            )
        except Exception as e:  # noqa: BLE001 — accounting must not break the node
            log.warning("autonomy usage logging failed: %s", e)
        return text.strip()
    except Exception as e:  # noqa: BLE001
        log.warning("reason() failed (%s); falling back to deterministic path.", e)
        return ""

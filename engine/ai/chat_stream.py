"""Shared chat routing/streaming core used by the web chat and the mobile API.

`stream_chat_events(msg, user_id, thread_id, history)` yields plain event dicts so
each caller can serialise them however it likes (the web uses SSE named events; the
mobile `POST /v2/chat` endpoint reuses the same). Free-form text always uses the
shared DeepAgents service. Anonymous callers receive public research tools only.

Event dicts have a ``type`` of: session · agent_route · token · tool_start ·
tool_end · error · done.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


async def stream_chat_events(
    msg: str,
    user_id: Optional[str],
    thread_id: str,
    history: list[dict],
) -> AsyncIterator[dict]:
    yield {"type": "session", "sid": thread_id}
    yield {"type": "agent_route", "slug": "ai", "agent": "AlpaTrade AI"}
    full = ""
    try:
        from engine.ai.deepagents import get_deepagent_service

        service = get_deepagent_service()
        if user_id:
            await service.initialize()
        async for event in service.compatibility_events(
            msg,
            thread_id=thread_id,
            user_id=user_id,
            auth_type="authenticated" if user_id else "anonymous",
        ):
            kind = event.get("event", "")
            data = event.get("data") or {}
            if kind == "session":
                continue
            if kind == "agent_route":
                continue
            elif kind == "token":
                value = str(data.get("content") or "")
                full += value
                yield {"type": "token", "text": value}
            elif kind == "tool_start":
                yield {"type": "tool_start", "name": data.get("name", "tool")}
            elif kind == "tool_end":
                yield {"type": "tool_end", "name": data.get("name", "tool")}
            elif kind == "error":
                raise RuntimeError("agent request failed")
    except Exception as e:  # noqa: BLE001
        logger.warning("Primary chat agent failed: %s", e)
        yield {"type": "error", "message": "Agent request failed"}
        history.append({"role": "assistant", "content": "Agent request failed"})
        yield {"type": "done"}
        return

    history.append({"role": "assistant", "content": full})
    yield {"type": "done"}


# Simple in-memory per-thread history for API callers (mobile). Web keeps its own.
_API_HISTORY: dict[str, list[dict]] = {}
_MAX_API_THREADS = 500
_MAX_HISTORY_MESSAGES = 40


def api_history(thread_id: str) -> list[dict]:
    if thread_id not in _API_HISTORY and len(_API_HISTORY) >= _MAX_API_THREADS:
        _API_HISTORY.pop(next(iter(_API_HISTORY)))
    history = _API_HISTORY.setdefault(thread_id, [])
    if len(history) > _MAX_HISTORY_MESSAGES:
        del history[:-_MAX_HISTORY_MESSAGES]
    return history

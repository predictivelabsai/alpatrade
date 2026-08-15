"""Shared chat routing/streaming core used by the web chat and the mobile API.

`stream_chat_events(msg, user_id, thread_id, history)` yields plain event dicts so
each caller can serialise them however it likes (the web uses SSE named events; the
mobile `POST /v2/chat` endpoint reuses the same). Routing is identical everywhere:

  1. CLI-command interception → `tui.command_processor.CommandProcessor`
  2. otherwise free-form text → the primary DeepAgents harness (XAI Grok + tools)

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
    import agui_app as _agui
    from engine.ai import StreamingCommand
    from langchain_core.messages import HumanMessage, AIMessage

    primary_agent = _agui.agent_for_user(user_id)
    command_interceptor = _agui._command_interceptor

    yield {"type": "session", "sid": thread_id}

    # The interceptor + CommandProcessor read session["user"]["user_id"].
    compat: dict = {"thread_id": thread_id}
    if user_id is not None:
        compat["user"] = {"user_id": str(user_id)}

    # 1) CLI command interception
    try:
        result = await command_interceptor(msg, compat)
    except Exception as e:  # noqa: BLE001
        logger.warning("Chat command interception failed: %s", e)
        yield {"type": "error", "message": "Command failed"}
        yield {"type": "done"}
        return

    if result is not None:
        yield {"type": "agent_route", "slug": "command", "agent": "Command"}
        try:
            if isinstance(result, StreamingCommand):
                from tui.command_processor import CommandProcessor
                cp = CommandProcessor(result.app_state, user_id=user_id)
                md = await cp.process_command(result.raw_command) or "Command executed."
            else:
                md = result
        except Exception as e:  # noqa: BLE001
            logger.warning("Chat command execution failed: %s", e)
            md = "# Error\n\nCommand execution failed."
        yield {"type": "token", "text": md}
        yield {"type": "done"}
        return

    # 2) Free-form text → primary agent harness
    yield {"type": "agent_route", "slug": "ai", "agent": "AlpaTrade AI"}
    history.append({"role": "user", "content": msg})
    lc = [
        HumanMessage(content=m["content"]) if m["role"] == "user"
        else AIMessage(content=m["content"])
        for m in history
    ]

    full = ""
    try:
        async for event in primary_agent.astream_events({"messages": lc}, version="v2"):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk is not None and getattr(chunk, "content", ""):
                    full += chunk.content
                    yield {"type": "token", "text": chunk.content}
            elif kind == "on_tool_start":
                yield {"type": "tool_start", "name": event.get("name", "tool")}
            elif kind == "on_tool_end":
                yield {"type": "tool_end", "name": event.get("name", "tool")}
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

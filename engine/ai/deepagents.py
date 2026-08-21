"""Canonical tenant-safe DeepAgents service used by the v2 chat APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from engine.ai.deepagent_store import (
    AccountAccessError,
    MessageConflictError,
    PostgresDeepAgentStore,
    ResponseInProgressError,
    ResponseRecord,
    ThreadAccessError,
)
from engine.ai.deepagent_tools import (
    COORDINATOR_TOOLS,
    DeepAgentContext,
    _bind_deepagent_context,
    _reset_deepagent_context,
    public_research_tools,
    specialist_subagents,
)
from engine.config import MODEL_PROVIDERS, Settings, build_chat_model, get_settings

logger = logging.getLogger(__name__)

BLOCKED_TOOLS = frozenset({
    "ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute",
})
PROCESS_INSTANCE_ID = str(uuid.uuid4())
HEARTBEAT_SECONDS = max(5, int(os.getenv("DEEPAGENT_HEARTBEAT_SECONDS", "15")))


class DeepAgentsUnavailable(RuntimeError):
    pass


class BlockedToolMiddleware(AgentMiddleware):
    """Reject blocked tools and carry trusted context into native subagents."""

    @staticmethod
    def _rejection(request: ToolCallRequest) -> ToolMessage:
        call = request.tool_call
        return ToolMessage(
            content="This tool is unavailable in the API agent.",
            tool_call_id=str(call.get("id") or "blocked-tool"),
            name=str(call.get("name") or "blocked-tool"),
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        if str(request.tool_call.get("name") or "") in BLOCKED_TOOLS:
            return self._rejection(request)
        context = getattr(request.runtime, "context", None)
        token = _bind_deepagent_context(context) if context is not None else None
        try:
            return handler(request)
        finally:
            if token is not None:
                _reset_deepagent_context(token)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        if str(request.tool_call.get("name") or "") in BLOCKED_TOOLS:
            return self._rejection(request)
        context = getattr(request.runtime, "context", None)
        token = _bind_deepagent_context(context) if context is not None else None
        try:
            return await handler(request)
        finally:
            if token is not None:
                _reset_deepagent_context(token)


@dataclass(frozen=True)
class PreparedInvocation:
    thread_id: str
    response: ResponseRecord
    context: DeepAgentContext
    request_messages: list[dict[str, str]]
    provider: str
    model_name: str
    cached_payload: Optional[dict[str, Any]] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _content_text(value: Any) -> str:
    """Normalize provider-specific message chunks into plain user-visible text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("type") in {"text", "output_text"}:
        return str(value.get("text") or "")
    if isinstance(value, list):
        pieces: list[str] = []
        for item in value:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                pieces.append(str(item.get("text") or ""))
        return "".join(pieces)
    return ""


def _model_name(model: Any, fallback: str) -> str:
    for key in ("model_name", "model"):
        value = getattr(model, key, None)
        if isinstance(value, str) and value:
            return value
    return fallback


def _request_fingerprint(
    messages: list[dict[str, str]], account_id: Optional[str]
) -> str:
    body = json.dumps(
        {"messages": messages, "account_id": account_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _strict_checkpoint_serializer():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=None,
    )


def _trace(call_id: str, name: str, status: str, started: datetime,
           completed: Optional[datetime] = None) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "name": name,
        "status": status,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat() if completed else None,
    }


def _tool_output_failed(output: Any) -> bool:
    """Read only a tool envelope's status; never serialize its content."""
    if isinstance(output, ToolMessage):
        return output.status == "error"
    if isinstance(output, dict):
        return output.get("status") in {"error", "failed"}
    return getattr(output, "status", None) in {"error", "failed"}


class PostgresCheckpointManager:
    """One async psycopg pool and one strict MessagePack checkpointer per process."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.pool: Any = None
        self.checkpointer: Any = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> Any:
        if self.checkpointer is not None:
            return self.checkpointer
        async with self._lock:
            if self.checkpointer is not None:
                return self.checkpointer
            if not self.database_url:
                raise DeepAgentsUnavailable("PostgreSQL checkpoint storage is not configured")
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                from psycopg.rows import dict_row
                from psycopg_pool import AsyncConnectionPool

                conninfo = self.database_url.replace(
                    "postgresql+psycopg2://", "postgresql://", 1
                ).replace("postgresql+psycopg://", "postgresql://", 1)
                self.pool = AsyncConnectionPool(
                    conninfo=conninfo,
                    min_size=1,
                    max_size=max(2, int(os.getenv("DEEPAGENT_DB_POOL_SIZE", "5"))),
                    open=False,
                    kwargs={
                        "autocommit": True,
                        "prepare_threshold": 0,
                        "row_factory": dict_row,
                        "options": "-c search_path=alpatrade,public",
                    },
                    name="alpatrade-deepagents",
                )
                await self.pool.open(wait=True)
                # Pickle fallback is deliberately disabled. JsonPlus uses MessagePack
                # with its restricted extension allowlist for LangChain objects.
                serializer = _strict_checkpoint_serializer()
                self.checkpointer = AsyncPostgresSaver(self.pool, serde=serializer)
                await self.checkpointer.setup()
            except DeepAgentsUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                await self.close()
                raise DeepAgentsUnavailable(
                    "PostgreSQL checkpoint storage is unavailable"
                ) from exc
        return self.checkpointer

    async def close(self) -> None:
        checkpointer, pool = self.checkpointer, self.pool
        self.checkpointer = None
        self.pool = None
        del checkpointer
        if pool is not None:
            await pool.close()


class DeepAgentService:
    """Build, cache, invoke, stream, and persist DeepAgents safely."""

    def __init__(
        self,
        *,
        store: Optional[Any] = None,
        checkpoint_manager: Optional[Any] = None,
        settings_loader: Callable[[Optional[str]], Settings] = get_settings,
        model_builder: Callable[..., Any] = build_chat_model,
        agent_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.store = store
        self.checkpoint_manager = checkpoint_manager or PostgresCheckpointManager()
        self.settings_loader = settings_loader
        self.model_builder = model_builder
        self.agent_factory = agent_factory
        self._graphs: dict[tuple[str, str, bool], Any] = {}
        self._models: dict[tuple[str, str], Any] = {}
        self._graph_lock = asyncio.Lock()

    def _store(self) -> Any:
        if self.store is None:
            self.store = PostgresDeepAgentStore()
        return self.store

    async def initialize(self) -> None:
        await self.checkpoint_manager.initialize()
        try:
            await asyncio.to_thread(self._store().fail_stale_responses, 120)
        except Exception as exc:  # noqa: BLE001
            raise DeepAgentsUnavailable("DeepAgents persistence is unavailable") from exc

    async def close(self) -> None:
        self._graphs.clear()
        await self.checkpoint_manager.close()

    async def _graph_for(
        self,
        user_id: Optional[str],
        *,
        public_only: bool = False,
    ) -> tuple[Any, str, str]:
        settings = self.settings_loader(user_id)
        provider = (settings.model_provider or "").lower()
        if provider not in MODEL_PROVIDERS:
            raise DeepAgentsUnavailable("The configured model provider is unavailable")
        configured_key = (provider, settings.model_name)
        model = self._models.get(configured_key)
        if model is None:
            try:
                model = self.model_builder(
                    settings, streaming=True, temperature=0.2, max_tokens=3000
                )
            except Exception as exc:  # noqa: BLE001
                raise DeepAgentsUnavailable("The configured model provider is unavailable") from exc
            if provider == "anthropic" and not type(model).__module__.startswith(
                "langchain_anthropic"
            ):
                raise DeepAgentsUnavailable("The configured model provider is unavailable")
            self._models[configured_key] = model
        actual_name = _model_name(model, settings.model_name)
        cache_key = (provider, actual_name, public_only)
        graph = self._graphs.get(cache_key)
        if graph is not None:
            return graph, provider, actual_name

        async with self._graph_lock:
            graph = self._graphs.get(cache_key)
            if graph is not None:
                return graph, provider, actual_name
            # Anonymous compatibility chat is deliberately stateless: it has no
            # tenant identity under which a durable checkpoint could be owned.
            checkpointer = (
                None if public_only else await self.checkpoint_manager.initialize()
            )
            try:
                if self.agent_factory is None:
                    from deepagents import create_deep_agent
                    from deepagents.profiles import (
                        GeneralPurposeSubagentProfile,
                        HarnessProfile,
                        register_harness_profile,
                    )

                    harness_provider = (
                        "anthropic" if provider == "anthropic" else "openai"
                    )
                    security_profile = HarnessProfile(
                        excluded_tools=BLOCKED_TOOLS,
                        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                    )
                    register_harness_profile(
                        f"{harness_provider}:{actual_name}", security_profile
                    )
                    factory = create_deep_agent
                else:
                    factory = self.agent_factory
                graph = factory(
                    model=model,
                    tools=list(public_research_tools() if public_only else COORDINATOR_TOOLS),
                    system_prompt=self._system_prompt(public_only),
                    middleware=[BlockedToolMiddleware()],
                    subagents=(
                        [specialist_subagents()[0]] if public_only
                        else specialist_subagents()
                    ),
                    context_schema=DeepAgentContext,
                    checkpointer=checkpointer,
                    name="alpatrade-deepagent",
                )
            except Exception as exc:  # noqa: BLE001
                raise DeepAgentsUnavailable("DeepAgents could not be initialized") from exc
            self._graphs[cache_key] = graph
        return graph, provider, actual_name

    @staticmethod
    def _system_prompt(public_only: bool) -> str:
        boundary = (
            "This is an anonymous public-research session. Never claim access to "
            "accounts, portfolios, jobs, actions, or trading."
            if public_only else
            "All account data is caller-owned and every action is paper-only. "
            "Delegate deep work to the named specialist through task."
        )
        return (
            "You are AlpaTrade's coordinator. Use tools for current facts and never "
            "invent tool results. Keep write_todos for multi-step planning. The host "
            "filesystem and shell are unavailable. Do not ask for or reveal secrets, "
            "credentials, raw exceptions, or internal logs. Mutating tools enforce an "
            "explicit-intent gate; if rejected, explain that no action occurred. "
            "For premarket results, preserve the tool's facts/evidence/watch/risk framing "
            "and do not add prescriptive trading guidance. "
            f"{boundary}"
        )

    async def prepare(
        self,
        request: Any,
        *,
        user_id: str,
        auth_type: str,
        request_id: str,
    ) -> PreparedInvocation:
        graph, provider, model_name = await self._graph_for(user_id)
        del graph
        thread_id = request.thread_id or str(uuid.uuid4())
        messages = [message.model_dump() for message in request.messages]
        final = messages[-1]
        fingerprint = _request_fingerprint(messages, request.account_id)
        store = self._store()
        try:
            await asyncio.to_thread(store.validate_account, user_id, request.account_id)
            await asyncio.to_thread(
                store.ensure_thread, user_id, thread_id, final["content"][:200]
            )
            record = await asyncio.to_thread(
                store.begin_response,
                user_id=user_id,
                thread_id=thread_id,
                request_message_id=final["id"],
                account_id=request.account_id,
                request_id=request_id,
                auth_type=auth_type,
                provider=provider,
                model=model_name,
                process_instance_id=PROCESS_INSTANCE_ID,
                request_fingerprint=fingerprint,
            )
        except (
            AccountAccessError,
            ResponseInProgressError,
            ThreadAccessError,
        ):
            raise
        except Exception as exc:  # noqa: BLE001
            raise DeepAgentsUnavailable("DeepAgents persistence is unavailable") from exc
        if record.status != "running":
            if record.request_fingerprint and record.request_fingerprint != fingerprint:
                raise MessageConflictError(
                    "a replayed message id has different request content"
                )
            payload = dict(record.payload or self._failed_payload(
                record.response_id, thread_id, provider, model_name
            ))
            payload["cached"] = True
            return PreparedInvocation(
                thread_id, record,
                DeepAgentContext(
                    user_id=user_id, account_id=request.account_id,
                    thread_id=thread_id, request_message_id=final["id"],
                    response_id=record.response_id, auth_type=auth_type,
                    request_id=request_id, current_user_text=final["content"],
                ),
                messages, provider, model_name, payload,
            )
        try:
            await asyncio.to_thread(store.append_messages, user_id, thread_id, messages)
        except MessageConflictError:
            payload = self._failed_payload(
                record.response_id, thread_id, provider, model_name
            )
            try:
                await asyncio.to_thread(
                    store.fail_response, user_id, record.response_id, payload,
                    code="message_conflict", message="A message id was reused inconsistently.",
                )
            except Exception:  # noqa: BLE001
                logger.warning("Could not persist message-conflict response")
            raise
        except Exception as exc:  # noqa: BLE001
            payload = self._failed_payload(
                record.response_id, thread_id, provider, model_name
            )
            try:
                await asyncio.to_thread(
                    store.fail_response, user_id, record.response_id, payload,
                    code="persistence_unavailable",
                    message="The durable transcript could not be updated.",
                )
            except Exception:  # noqa: BLE001
                logger.warning("Could not persist transcript failure")
            raise DeepAgentsUnavailable("DeepAgents persistence is unavailable") from exc
        context = DeepAgentContext(
            user_id=user_id,
            account_id=request.account_id,
            thread_id=thread_id,
            request_message_id=final["id"],
            response_id=record.response_id,
            auth_type=auth_type,
            request_id=request_id,
            current_user_text=final["content"],
        )
        return PreparedInvocation(
            thread_id, record, context, messages, provider, model_name
        )

    async def invoke(self, invocation: PreparedInvocation) -> dict[str, Any]:
        payload: Optional[dict[str, Any]] = invocation.cached_payload
        async for event in self.events(invocation):
            if event["event"] == "done":
                payload = event["data"]["response"]
        if payload is None:
            raise RuntimeError("DeepAgent finished without a response")
        return payload

    async def events(self, invocation: PreparedInvocation) -> AsyncIterator[dict[str, Any]]:
        if invocation.cached_payload is not None:
            async for event in self._cached_events(invocation.cached_payload):
                yield event
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        producer = asyncio.create_task(self._produce(invocation, queue))
        last_heartbeat = time.monotonic()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    try:
                        await asyncio.to_thread(
                            self._store().heartbeat,
                            invocation.context.user_id,
                            invocation.response.response_id,
                        )
                    except Exception:  # noqa: BLE001 - response still gets a terminal event
                        logger.warning("Could not persist DeepAgent heartbeat")
                    last_heartbeat = time.monotonic()
                    yield {"event": "ping", "data": {"time": _utcnow().isoformat()}}
                    continue
                if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
                    try:
                        await asyncio.to_thread(
                            self._store().heartbeat,
                            invocation.context.user_id,
                            invocation.response.response_id,
                        )
                    except Exception:  # noqa: BLE001 - response still gets a terminal event
                        logger.warning("Could not persist DeepAgent heartbeat")
                    last_heartbeat = time.monotonic()
                yield event
                if event["event"] == "done":
                    break
        finally:
            if not producer.done():
                producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                payload = self._failed_payload(
                    invocation.response.response_id,
                    invocation.thread_id,
                    invocation.provider,
                    invocation.model_name,
                )
                try:
                    await asyncio.to_thread(
                        self._store().fail_response,
                        invocation.context.user_id,
                        invocation.response.response_id,
                        payload,
                        code="stream_disconnected",
                        message="The stream ended before the response completed.",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("Could not persist disconnected stream state")

    async def _cached_events(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "session", "data": {
            "id": payload["id"], "thread_id": payload["thread_id"],
            "framework": "deepagents", "model": payload["model"], "cached": True,
        }}
        yield {"event": "agent_route", "data": {
            "name": "coordinator", "status": "completed",
        }}
        if payload.get("status") == "failed":
            yield {"event": "error", "data": {
                "code": "recorded_failure",
                "message": "This request previously failed and was not rerun.",
            }}
        for collection, prefix in ((payload.get("tools", []), "tool"),
                                   (payload.get("subagents", []), "subagent")):
            for trace in collection:
                yield {"event": f"{prefix}_start", "data": {
                    "call_id": trace["call_id"],
                    "name": trace["name"],
                    "status": "started",
                    "started_at": trace.get("started_at"),
                }}
                yield {"event": f"{prefix}_end", "data": trace}
        for message in payload.get("messages", []):
            yield {"event": "message_start", "data": {"id": message["id"], "role": "assistant"}}
            if message.get("content"):
                yield {"event": "token", "data": {"message_id": message["id"],
                                                       "content": message["content"]}}
            yield {"event": "message_end", "data": {"id": message["id"]}}
        yield {"event": "done", "data": {"response": payload}}

    async def _produce(
        self,
        invocation: PreparedInvocation,
        output: asyncio.Queue[dict[str, Any]],
    ) -> None:
        response_id = invocation.response.response_id
        assistant_id = str(uuid.uuid4())
        tools: list[dict[str, Any]] = []
        subagents: list[dict[str, Any]] = []
        active: dict[str, tuple[str, str, datetime]] = {}
        sequence = 0
        emitted_text = ""
        store = self._store()
        specialist_specs = specialist_subagents()
        allowed_specialists = {spec["name"] for spec in specialist_specs}
        allowed_tool_names = {
            "write_todos", "task", *BLOCKED_TOOLS,
            *(tool.name for tool in COORDINATOR_TOOLS),
            *(
                tool.name
                for spec in specialist_specs
                for tool in spec.get("tools", ())
            ),
        }

        async def emit(event_type: str, data: dict[str, Any], *, persist: bool = False) -> None:
            nonlocal sequence
            sequence += 1
            if persist:
                try:
                    await asyncio.to_thread(
                        store.append_event,
                        response_id,
                        sequence,
                        event_type,
                        call_id=data.get("call_id") or data.get("id"),
                        name=data.get("name"),
                        status=data.get("status"),
                    )
                except Exception:  # noqa: BLE001 - stream remains terminal
                    logger.warning("Could not persist sanitized DeepAgent event")
            await output.put({"event": event_type, "data": data})

        try:
            await emit("session", {
                "id": response_id,
                "thread_id": invocation.thread_id,
                "framework": "deepagents",
                "model": {"provider": invocation.provider, "name": invocation.model_name},
                "cached": False,
            }, persist=True)
            await emit("agent_route", {"name": "coordinator", "status": "started"},
                       persist=True)
            await emit("message_start", {"id": assistant_id, "role": "assistant",
                                          "status": "started"}, persist=True)

            graph, _, _ = await self._graph_for(invocation.context.user_id)
            checkpointer = await self.checkpoint_manager.initialize()
            config = {"configurable": {
                "thread_id": f"{invocation.context.user_id}:{invocation.thread_id}",
            }}
            checkpoint = await checkpointer.aget_tuple(config)
            if checkpoint is None:
                transcript = await asyncio.to_thread(
                    store.load_messages,
                    invocation.context.user_id,
                    invocation.thread_id,
                )
                input_messages = [
                    HumanMessage(content=item["content"], id=item["id"])
                    if item["role"] == "user"
                    else AIMessage(content=item["content"], id=item["id"])
                    for item in transcript if item["role"] in {"user", "assistant"}
                ]
            else:
                input_messages = [
                    HumanMessage(content=item["content"], id=item["id"])
                    if item["role"] == "user"
                    else AIMessage(content=item["content"], id=item["id"])
                    for item in invocation.request_messages
                ]

            async for event in graph.astream_events(
                {"messages": input_messages},
                config=config,
                context=invocation.context,
                version="v2",
            ):
                event_type = event.get("event", "")
                name = str(event.get("name") or "")
                run_id = str(event.get("run_id") or uuid.uuid4())
                parent_ids = {str(value) for value in event.get("parent_ids", [])}
                if event_type == "on_tool_start":
                    is_subagent = name == "task"
                    display_name = name if name in allowed_tool_names else "tool"
                    if is_subagent:
                        raw_input = event.get("data", {}).get("input") or {}
                        if isinstance(raw_input, dict):
                            candidate = str(raw_input.get("subagent_type") or "")
                            display_name = (
                                candidate if candidate in allowed_specialists else "specialist"
                            )
                    started = _utcnow()
                    active[run_id] = (
                        "subagent" if is_subagent else "tool", display_name, started
                    )
                    await emit(
                        "subagent_start" if is_subagent else "tool_start",
                        {"call_id": run_id, "name": display_name, "status": "started",
                         "started_at": started.isoformat()},
                        persist=True,
                    )
                elif event_type in {"on_tool_end", "on_tool_error"}:
                    kind, display_name, started = active.pop(
                        run_id,
                        (
                            "subagent" if name == "task" else "tool",
                            (
                                "specialist" if name == "task"
                                else name if name in allowed_tool_names else "tool"
                            ),
                            _utcnow(),
                        ),
                    )
                    completed = _utcnow()
                    failed = event_type == "on_tool_error" or _tool_output_failed(
                        event.get("data", {}).get("output")
                    )
                    status = "failed" if failed else "completed"
                    record = _trace(run_id, display_name, status, started, completed)
                    (subagents if kind == "subagent" else tools).append(record)
                    await emit(
                        f"{kind}_end",
                        record,
                        persist=True,
                    )
                elif event_type == "on_chat_model_stream":
                    if any(
                        active_id in parent_ids and active[active_id][0] == "subagent"
                        for active_id in active
                    ):
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    text_value = _content_text(getattr(chunk, "content", None))
                    if text_value:
                        emitted_text += text_value
                        await emit("token", {
                            "message_id": assistant_id,
                            "content": text_value,
                        })

            snapshot = await graph.aget_state(config)
            snapshot_text = ""
            for message in reversed(snapshot.values.get("messages", [])):
                if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
                    snapshot_text = _content_text(message.content)
                    if snapshot_text:
                        break
            # The persisted/JSON message exactly matches what an SSE caller saw.
            # Snapshot text is the fallback for providers that do not stream tokens.
            final_text = emitted_text or snapshot_text
            if final_text and not emitted_text:
                await emit("token", {"message_id": assistant_id, "content": final_text})
            await asyncio.to_thread(
                store.save_assistant_message,
                invocation.context.user_id,
                invocation.thread_id,
                assistant_id,
                final_text,
                response_id,
            )
            payload = {
                "id": response_id,
                "thread_id": invocation.thread_id,
                "status": "completed",
                "framework": "deepagents",
                "model": {"provider": invocation.provider, "name": invocation.model_name},
                "messages": [{"id": assistant_id, "role": "assistant", "content": final_text}],
                "tools": tools,
                "subagents": subagents,
                "cached": False,
            }
            await asyncio.to_thread(
                store.complete_response, invocation.context.user_id, response_id, payload
            )
            await emit("message_end", {"id": assistant_id, "status": "completed"},
                       persist=True)
            await emit("done", {"response": payload, "status": "completed"}, persist=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DeepAgent response %s failed (%s)", response_id, type(exc).__name__
            )
            for call_id, (kind, name, started) in list(active.items()):
                record = _trace(call_id, name, "failed", started, _utcnow())
                (subagents if kind == "subagent" else tools).append(record)
                try:
                    await emit(f"{kind}_end", record, persist=True)
                except Exception:  # noqa: BLE001
                    logger.warning("Could not persist terminal tool trace")
            active.clear()
            payload = self._failed_payload(
                response_id, invocation.thread_id,
                invocation.provider, invocation.model_name,
                tools=tools, subagents=subagents,
            )
            try:
                await asyncio.to_thread(
                    store.fail_response,
                    invocation.context.user_id,
                    response_id,
                    payload,
                    code="agent_execution_failed",
                    message="The DeepAgent could not complete the response.",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to persist terminal DeepAgent failure")
            await emit("message_end", {"id": assistant_id, "status": "failed"},
                       persist=True)
            await emit("error", {
                "code": "agent_execution_failed",
                "message": "The DeepAgent could not complete the response.",
                "status": "failed",
            }, persist=True)
            await emit("done", {"response": payload, "status": "failed"}, persist=True)

    @staticmethod
    def _failed_payload(
        response_id: str,
        thread_id: str,
        provider: str,
        model_name: str,
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        subagents: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        return {
            "id": response_id,
            "thread_id": thread_id,
            "status": "failed",
            "framework": "deepagents",
            "model": {"provider": provider, "name": model_name},
            "messages": [],
            "tools": tools or [],
            "subagents": subagents or [],
            "cached": False,
        }

    async def compatibility_events(
        self,
        message: str,
        *,
        thread_id: str,
        user_id: Optional[str],
        auth_type: str = "anonymous",
        request_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Adapter for older wire formats; authenticated threads remain durable."""
        if user_id:
            # Older clients do not supply message UUIDs or UUID thread IDs. Map
            # their thread label deterministically, then use the same durable
            # response path so action FKs, tenancy, checkpoints, and crash
            # semantics remain identical to the canonical API.
            durable_thread_id = str(uuid.uuid5(
                uuid.UUID("64a0a74a-72cc-4f02-a079-7d72ff14a266"),
                f"{user_id}:{thread_id}",
            ))
            message_id = str(uuid.uuid4())

            class CompatMessage:
                def model_dump(self) -> dict[str, str]:
                    return {"id": message_id, "role": "user", "content": message}

            request = SimpleNamespace(
                messages=[CompatMessage()],
                thread_id=durable_thread_id,
                account_id=None,
            )
            invocation = await self.prepare(
                request,
                user_id=user_id,
                auth_type=auth_type,
                request_id=request_id or str(uuid.uuid4()),
            )
            async for event in self.events(invocation):
                event_type = event["event"]
                data = event["data"]
                if event_type == "session":
                    yield {"event": "session", "data": {
                        "thread_id": thread_id,
                        "framework": "deepagents",
                        "model": data.get("model"),
                    }}
                elif event_type == "token":
                    yield {"event": "token", "data": {
                        "content": data.get("content", ""),
                    }}
                elif event_type in {"tool_start", "tool_end"}:
                    yield {"event": event_type, "data": {"name": data.get("name", "tool")}}
                elif event_type in {"subagent_start", "subagent_end"}:
                    mapped = "tool_start" if event_type.endswith("start") else "tool_end"
                    yield {"event": mapped, "data": {"name": data.get("name", "specialist")}}
                elif event_type in {"agent_route", "error"}:
                    yield event
                elif event_type == "done":
                    yield {"event": "done", "data": {}}
            return

        public_only = not bool(user_id)
        graph, provider, model_name = await self._graph_for(
            user_id, public_only=public_only
        )
        context = DeepAgentContext(
            user_id=user_id,
            account_id=None,
            thread_id=thread_id,
            request_message_id=str(uuid.uuid4()),
            response_id=str(uuid.uuid4()),
            auth_type=auth_type,
            request_id=request_id or str(uuid.uuid4()),
            current_user_text=message,
            public_only=public_only,
        )
        checkpoint_thread = (
            f"compat:{user_id}:{thread_id}"
            if user_id else f"compat:anonymous:{uuid.uuid4()}"
        )
        config = {"configurable": {"thread_id": checkpoint_thread}}
        yield {"event": "session", "data": {
            "thread_id": thread_id,
            "framework": "deepagents",
            "model": {"provider": provider, "name": model_name},
        }}
        yield {"event": "agent_route", "data": {"name": "coordinator"}}
        try:
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                context=context,
                version="v2",
            ):
                kind = event.get("event")
                name = str(event.get("name") or "")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    value = _content_text(getattr(chunk, "content", None))
                    if value:
                        yield {"event": "token", "data": {"content": value}}
                elif kind == "on_tool_start":
                    yield {"event": "tool_start", "data": {"name": name}}
                elif kind == "on_tool_end":
                    yield {"event": "tool_end", "data": {"name": name}}
            yield {"event": "done", "data": {}}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Compatibility DeepAgent failed (%s)", type(exc).__name__)
            yield {"event": "error", "data": {
                "code": "agent_execution_failed",
                "message": "The DeepAgent could not complete the response.",
            }}
            yield {"event": "done", "data": {}}


_service: Optional[DeepAgentService] = None


def get_deepagent_service() -> DeepAgentService:
    global _service
    if _service is None:
        _service = DeepAgentService()
    return _service


def set_deepagent_service(service: Optional[DeepAgentService]) -> None:
    """Test hook for replacing the process service without provider calls."""
    global _service
    _service = service


async def close_deepagent_service() -> None:
    if _service is None:
        return
    close = getattr(_service, "close", None)
    if close is not None:
        await close()


def sse_encode(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


__all__ = [
    "AccountAccessError",
    "BLOCKED_TOOLS",
    "BlockedToolMiddleware",
    "DeepAgentService",
    "DeepAgentsUnavailable",
    "MessageConflictError",
    "ResponseInProgressError",
    "ThreadAccessError",
    "close_deepagent_service",
    "get_deepagent_service",
    "set_deepagent_service",
    "sse_encode",
]

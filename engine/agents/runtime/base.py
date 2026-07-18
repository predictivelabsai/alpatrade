"""Core contract every agent-runtime adapter implements.

Keep this tiny and framework-neutral: the autonomy pipeline depends only on this,
so swapping ``AGENT_FRAMEWORK`` never touches risk/execution logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Protocol, runtime_checkable


@dataclass
class RoleSpec:
    """Declarative description of one agent role, framework-independent.

    ``tools`` are LangChain-style ``StructuredTool``/``@tool`` objects or plain
    callables; each adapter translates them to its own tool type. ``model`` is a
    chat model from :func:`engine.config.build_chat_model` — if ``None`` the adapter
    builds the default one, so callers need not know the provider.
    """
    name: str
    instructions: str = ""
    tools: list = field(default_factory=list)
    model: Any = None
    subagents: list["RoleSpec"] = field(default_factory=list)
    temperature: float = 0.5
    max_tokens: int = 3000


@dataclass
class RunResult:
    """Uniform result of one agent invocation across frameworks."""
    text: str
    messages: list = field(default_factory=list)
    raw: Any = None
    runtime: str = ""


@runtime_checkable
class AgentRuntime(Protocol):
    """A framework adapter. Implementations live in ``*_rt.py`` modules."""

    name: str

    def build(self, spec: RoleSpec) -> Any:
        """Construct a framework-native agent from ``spec`` and return it."""
        ...

    def run(self, agent: Any, prompt: str, *, history: Optional[list] = None) -> RunResult:
        """Invoke ``agent`` on ``prompt`` (optionally with prior messages)."""
        ...

    def stream(self, agent: Any, prompt: str, *, history: Optional[list] = None) -> Iterator[str]:
        """Yield token/text chunks. Adapters without native streaming may yield once."""
        ...

    def supports_subagents(self) -> bool:
        """Whether this backend composes ``spec.subagents`` natively."""
        ...


def default_model(spec: RoleSpec):
    """Resolve ``spec.model`` or build the configured default chat model."""
    if spec.model is not None:
        return spec.model
    from engine.config import build_chat_model, get_settings
    return build_chat_model(get_settings(), streaming=True,
                            temperature=spec.temperature, max_tokens=spec.max_tokens)

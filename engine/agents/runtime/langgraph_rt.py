"""LangGraph adapter — the reference runtime (matches today's chat agent).

Wraps ``langgraph.prebuilt.create_react_agent`` so a :class:`RoleSpec` produces the
same kind of ReAct agent AlpaTrade already ships (``agui_app.langgraph_agent``).
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from engine.agents.runtime.base import RoleSpec, RunResult, default_model


class LangGraphRuntime:
    name = "langgraph"

    def build(self, spec: RoleSpec) -> Any:
        from langgraph.prebuilt import create_react_agent
        return create_react_agent(
            model=default_model(spec),
            tools=list(spec.tools),
            prompt=spec.instructions or None,
        )

    def _messages(self, prompt: str, history: Optional[list]):
        from langchain_core.messages import HumanMessage, AIMessage
        msgs = []
        for m in history or []:
            role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            msgs.append(HumanMessage(content=content) if role == "user"
                        else AIMessage(content=content))
        msgs.append(HumanMessage(content=prompt))
        return msgs

    def run(self, agent: Any, prompt: str, *, history: Optional[list] = None) -> RunResult:
        out = agent.invoke({"messages": self._messages(prompt, history)})
        msgs = out.get("messages", []) if isinstance(out, dict) else []
        text = ""
        for m in reversed(msgs):
            content = getattr(m, "content", "")
            if content:
                text = content if isinstance(content, str) else str(content)
                break
        return RunResult(text=text, messages=msgs, raw=out, runtime=self.name)

    def stream(self, agent: Any, prompt: str, *, history: Optional[list] = None) -> Iterator[str]:
        for chunk, _meta in agent.stream(
            {"messages": self._messages(prompt, history)}, stream_mode="messages"
        ):
            content = getattr(chunk, "content", "")
            if content:
                yield content if isinstance(content, str) else str(content)

    def supports_subagents(self) -> bool:
        return True

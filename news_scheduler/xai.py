"""Small, structured XAI calls for deterministic news enrichment stages."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import OpenAI

log = logging.getLogger(__name__)


def _json(content: str) -> dict[str, Any]:
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.I).strip()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("XAI response was not a JSON object")
    return value


def _model_name(model: str | None) -> str:
    from engine.config import current_xai_model
    return current_xai_model(model or os.getenv("XAI_MODEL") or "grok-4.3")


class XAIEnricher:
    """Two short calls per article (metadata JSON + one-line reason).

    Uses a current model (retired grok-4-1-fast slugs are billed as grok-4.3 anyway)
    with reasoning disabled by default, applies the platform daily LLM budget and
    records every call in ``alpatrade.llm_usage_logging`` (agent ``news``).
    """

    def __init__(self, client=None, model: str | None = None, *, account_usage: bool | None = None):
        self.client = client or OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")
        self.model = _model_name(model)
        self.reasoning_effort = os.getenv("XAI_REASONING_EFFORT", "none").strip() or None
        # Injected clients (tests/tools) skip DB accounting unless asked explicitly.
        self.account_usage = (client is None) if account_usage is None else account_usage

    def _complete(self, stage: str, *, max_tokens: int, messages: list[dict]) -> str:
        if self.account_usage:
            from engine.ai.llm_usage import enforce_daily_budget
            enforce_daily_budget(funding_source="platform")
        kwargs: dict[str, Any] = {"model": self.model, "temperature": 0,
                                  "max_tokens": max_tokens, "messages": messages}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        if self.account_usage:
            try:
                from engine.ai.llm_usage import extract_usage, record_usage
                usage = getattr(response, "usage", None)
                if usage is not None and hasattr(usage, "model_dump"):
                    usage = usage.model_dump()
                record_usage(user_id=None, thread_id=None, agent="news", provider="xai",
                             model=self.model, funding_source="platform",
                             prompt="".join(str(m.get("content", "")) for m in messages),
                             response=content, usage=extract_usage({"usage": usage or {}}),
                             job_id=f"news-{stage}")
            except Exception as exc:  # noqa: BLE001 — accounting must not stop ingestion
                log.warning("news usage logging failed: %s", type(exc).__name__)
        return content

    def metadata(self, row: dict[str, Any], *, allowed_events: tuple[str, ...] | None = None) -> dict[str, Any]:
        prompt = {"title": row.get("title"), "content": row.get("content"), "event": row.get("event")}
        if allowed_events:
            prompt["allowed_events"] = list(allowed_events)
        content = self._complete("metadata", max_tokens=1000, messages=[
            {"role": "system", "content": (
                "Return only JSON with company, company_type, ticker, yf_ticker, language (ISO code), title_en, content_en, event. "
                "Detect the issuer, listed ticker and language, translate faithfully to English. "
                "company_type MUST be exactly public for a publicly traded/listed issuer or private for a privately held issuer. "
                "When allowed_events is supplied, event MUST exactly equal one value from that list. "
                "Otherwise classify/retain a concise financial event name. "
                "Use an empty ticker only when it cannot be identified.")},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}])
        return {**row, **_json(content)}

    def reason(self, row: dict[str, Any]) -> str:
        content = self._complete("reason", max_tokens=160, messages=[
            {"role": "system", "content": "Explain in at most 40 words why the supplied ML side and percentage move could follow from the news. Return only the explanation."},
            {"role": "user", "content": json.dumps({"title": row.get("title_en"), "content": row.get("content_en"), "side": row.get("predicted_side"), "move": row.get("predicted_move")}, ensure_ascii=False)}])
        return content.strip()

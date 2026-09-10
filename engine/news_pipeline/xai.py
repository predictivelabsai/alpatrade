"""Small, structured XAI calls for deterministic news enrichment stages."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI


def _json(content: str) -> dict[str, Any]:
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.I).strip()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("XAI response was not a JSON object")
    return value


class XAIEnricher:
    def __init__(self, client=None, model: str | None = None):
        self.client = client or OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")
        self.model = model or os.getenv("XAI_MODEL", "grok-4-1-fast-reasoning")

    def metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        prompt = {"title": row.get("title"), "content": row.get("content"), "event": row.get("event")}
        response = self.client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=1000,
            messages=[{"role": "system", "content": (
                "Return only JSON with company, ticker, yf_ticker, language (ISO code), title_en, content_en, event. "
                "Detect the issuer, listed ticker and language, translate faithfully to English, and classify/retain a concise financial event name. "
                "Use an empty ticker only when it cannot be identified.")},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}])
        return {**row, **_json(response.choices[0].message.content or "")}

    def reason(self, row: dict[str, Any]) -> str:
        response = self.client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=160,
            messages=[{"role": "system", "content": "Explain in at most 40 words why the supplied ML side and percentage move could follow from the news. Return only the explanation."},
                      {"role": "user", "content": json.dumps({"title": row.get("title_en"), "content": row.get("content_en"), "side": row.get("predicted_side"), "move": row.get("predicted_move")}, ensure_ascii=False)}])
        return (response.choices[0].message.content or "").strip()

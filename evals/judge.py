"""DeepEval judge backed by XAI (grok) — no OpenAI key required.

GEval needs an LLM to grade free-form (chat) answers. We wrap grok via its
OpenAI-compatible API as a `DeepEvalBaseLLM` so DeepEval's metrics run on XAI.
Deterministic answers are graded by structural match (see run_evals.grade_deterministic).
"""
from __future__ import annotations

import json
import os

from deepeval.models import DeepEvalBaseLLM


class GrokJudge(DeepEvalBaseLLM):
    """DeepEval model wrapper for xAI grok (OpenAI-compatible chat completions)."""

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("DEEPEVAL_MODEL", "grok-4-fast")
        from openai import OpenAI
        self._client = OpenAI(api_key=os.getenv("XAI_API_KEY"),
                              base_url="https://api.x.ai/v1")

    def load_model(self):
        return self._client

    def get_model_name(self) -> str:
        return f"xai/{self.model}"

    def generate(self, prompt: str, schema=None):
        kwargs = {}
        if schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
            prompt = prompt + "\n\nReturn ONLY a valid JSON object."
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            **kwargs,
        )
        text = resp.choices[0].message.content or ""
        if schema is not None:
            try:
                return schema(**json.loads(text))
            except Exception:  # noqa: BLE001
                return schema.model_validate_json(text)
        return text

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)


def correctness_metric(threshold: float = 0.6):
    """GEval 'Correctness' metric graded by grok."""
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams
    return GEval(
        name="Correctness",
        criteria=(
            "Determine whether the AI answer is factually correct and covers the key "
            "facts in the expected answer. Minor phrasing differences are fine. For "
            "numeric/data answers, the numbers and entities must match. Missing or wrong "
            "key facts should be penalised. "
            "IMPORTANT: the expected answer is a MINIMUM baseline, not an exhaustive or "
            "exclusive list. If the AI answer provides ADDITIONAL correct, relevant detail "
            "beyond the expected answer (e.g. extra metrics, a direct yes/no, richer "
            "context), that is GOOD and must NOT be penalised as an 'unrequested addition'. "
            "Only penalise missing required facts, factual errors, refusals, or off-topic "
            "answers — never penalise a correct answer for being more complete."
        ),
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
        threshold=threshold,
        model=GrokJudge(),
    )

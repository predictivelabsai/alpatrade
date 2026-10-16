"""Judge / decision provider: TypeSafe "jev" System One model with Grok fallback.

Judging, decisioning and classification calls (pick one of N, yes/no, score a
level) do not need a generative LLM. TypeSafe's jev answers typed questions
(``choice`` / ``score`` / ``noul``) with calibrated probabilities, ~100x faster
and far cheaper than a chat model, and cannot answer outside the given options.

Switch with ``LLM_JUDGE_PROVIDER=typesafe`` (default ``grok`` = unchanged
behaviour). Every call site passes a Grok fallback; any TypeSafe error
(missing key, HTTP error, timeout, malformed answer) logs and falls back.

API: ``POST https://api.typesafe.ai/v1/systemone`` with ``Authorization: Bearer
$TYPESAFE_API_KEY``; body ``{model, state, questions}``; response
``{model, answers, usage}``. Price (jev-1.13.0): $0.042 per 1M input tokens,
output free.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

log = logging.getLogger("engine.ai.judge")

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
JEV_INPUT_USD_PER_M = float(os.getenv("JEV_INPUT_USD_PER_MILLION", "0.042"))


def judge_provider() -> str:
    """``typesafe`` or ``grok`` (anything else → ``grok``)."""
    v = (os.getenv("LLM_JUDGE_PROVIDER") or "grok").strip().lower()
    return "typesafe" if v in ("typesafe", "jev") else "grok"


def jev_model() -> str:
    return os.getenv("TYPESAFE_MODEL", "jev-latest")


def use_typesafe() -> bool:
    return judge_provider() == "typesafe" and bool(os.getenv("TYPESAFE_API_KEY"))


class JudgeError(RuntimeError):
    pass


def typesafe_decide(state: Any, questions: dict, *, model: Optional[str] = None,
                    timeout: float = 20.0, http=None) -> dict:
    """One System One call. Returns ``{"model", "answers", "usage", "latency_s"}``.

    Raises :class:`JudgeError` on any failure so callers can fall back.
    """
    key = os.getenv("TYPESAFE_API_KEY")
    if not key:
        raise JudgeError("TYPESAFE_API_KEY not set")
    if http is None:
        import requests as http  # noqa: N813
    t0 = time.perf_counter()
    try:
        r = http.post(TYPESAFE_URL, timeout=timeout,
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model or jev_model(), "state": state, "questions": questions})
    except Exception as exc:  # noqa: BLE001
        raise JudgeError(f"typesafe request failed: {type(exc).__name__}") from None
    if r.status_code != 200:
        raise JudgeError(f"typesafe HTTP {r.status_code}")
    try:
        body = r.json()
        answers = body["answers"]
    except Exception:  # noqa: BLE001
        raise JudgeError("typesafe malformed response") from None
    missing = set(questions) - set(answers or {})
    if missing:
        raise JudgeError(f"typesafe missing answers: {sorted(missing)}")
    return {"model": body.get("model") or (model or jev_model()), "answers": answers,
            "usage": body.get("usage") or {}, "latency_s": round(time.perf_counter() - t0, 3)}


def decide(state: Any, questions: dict, *, fallback: Callable[[], Any],
           site: str = "", http=None) -> tuple[str, Any]:
    """Run ``questions`` on jev when enabled, else / on error run ``fallback()``.

    Returns ``(provider, result)`` where provider is ``"typesafe"`` (result is the
    :func:`typesafe_decide` dict) or ``"grok"`` (result is whatever fallback returns).
    """
    if use_typesafe():
        try:
            res = typesafe_decide(state, questions, http=http)
            log.info("judge[%s] typesafe %s in %.2fs (%s in-tokens)", site, res["model"],
                     res["latency_s"], res["usage"].get("input_tokens"))
            return "typesafe", res
        except JudgeError as exc:
            log.warning("judge[%s] typesafe failed (%s); falling back to Grok", site, exc)
    return "grok", fallback()


def cost_usd(input_tokens: int) -> float:
    return input_tokens * JEV_INPUT_USD_PER_M / 1_000_000

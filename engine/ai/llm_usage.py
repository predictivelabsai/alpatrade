"""Shared, credential-safe LLM usage accounting and daily budget checks."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from engine.db.pool import get_pool

PLATFORM_DAILY_BUDGET_USD = Decimal(os.getenv("PLATFORM_LLM_DAILY_BUDGET_USD", "5"))
# Deployment may override prices without a release. Values are USD / 1M tokens.
DEFAULT_INPUT_USD_PER_M = Decimal(os.getenv("LLM_INPUT_USD_PER_MILLION", "1.25"))
DEFAULT_OUTPUT_USD_PER_M = Decimal(os.getenv("LLM_OUTPUT_USD_PER_MILLION", "2.50"))
HERMES_INPUT_USD_PER_M = Decimal(os.getenv("HERMES_INPUT_USD_PER_MILLION", "2"))
HERMES_OUTPUT_USD_PER_M = Decimal(os.getenv("HERMES_OUTPUT_USD_PER_MILLION", "6"))


class DailyBudgetExceeded(PermissionError):
    """Raised before a platform-funded call after the daily budget is exhausted."""


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    quality: str = "unavailable"


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def extract_usage(value: Any) -> TokenUsage:
    """Normalize OpenAI/LangChain usage objects without retaining prompts."""
    data = value or {}
    if not isinstance(data, dict):
        data = getattr(data, "usage_metadata", None) or getattr(data, "response_metadata", {}) or {}
    nested = data.get("usage") or data.get("token_usage") or data.get("usage_metadata") or data
    if not isinstance(nested, dict):
        return TokenUsage()
    inp = _int(nested.get("input_tokens", nested.get("prompt_tokens")))
    out = _int(nested.get("output_tokens", nested.get("completion_tokens")))
    total = _int(nested.get("total_tokens")) or inp + out
    return TokenUsage(inp, out, total, "measured" if total else "unavailable")


def estimate_usage(prompt: str, response: str) -> TokenUsage:
    # Provider-neutral fallback, clearly labeled estimated (roughly 4 chars/token).
    inp = max(math.ceil(len(prompt or "") / 4), 1)
    out = max(math.ceil(len(response or "") / 4), 1)
    return TokenUsage(inp, out, inp + out, "estimated")


def estimate_cost(usage: TokenUsage, *, agent: str = "", model: str = "") -> Decimal:
    hermes = agent.lower() == "hermes" or model.lower() == "hermes-agent"
    input_rate = HERMES_INPUT_USD_PER_M if hermes else DEFAULT_INPUT_USD_PER_M
    output_rate = HERMES_OUTPUT_USD_PER_M if hermes else DEFAULT_OUTPUT_USD_PER_M
    return (
        Decimal(usage.input_tokens) * input_rate
        + Decimal(usage.output_tokens) * output_rate
    ) / Decimal(1_000_000)


def daily_platform_cost(user_id: str | None = None) -> Decimal:
    owner = "AND user_id = CAST(:uid AS UUID)" if user_id else ""
    params = {"uid": user_id} if user_id else {}
    with get_pool().get_session() as session:
        value = session.execute(text(f"""
            SELECT COALESCE(SUM(estimated_cost_usd), 0)
            FROM alpatrade.llm_usage_logging
            WHERE funding_source = 'platform' AND status = 'completed'
              AND created_at >= date_trunc('day', NOW()) {owner}
        """), params).scalar()
    return Decimal(str(value or 0))


def enforce_daily_budget(*, funding_source: str) -> None:
    if funding_source != "platform":
        return
    try:
        spent = daily_platform_cost()
    except Exception:
        # Rolling deploy safety: query allowance remains active until migration 30 exists.
        return
    if spent >= PLATFORM_DAILY_BUDGET_USD:
        raise DailyBudgetExceeded(
            f"The platform's ${PLATFORM_DAILY_BUDGET_USD:.2f} daily AI budget is reached. "
            "Add your own provider key in Settings or try again tomorrow."
        )


def budget_warning(*, funding_source: str) -> str | None:
    """Warn platform-funded users at 80% and 90% of shared daily spend."""
    if funding_source != "platform":
        return None
    try:
        spent = daily_platform_cost()
    except Exception:
        return None
    if PLATFORM_DAILY_BUDGET_USD <= 0:
        return "The platform AI budget is disabled."
    ratio = spent / PLATFORM_DAILY_BUDGET_USD
    if ratio < Decimal("0.8"):
        return None
    level = "90%" if ratio >= Decimal("0.9") else "80%"
    return (
        f"Platform AI spending has reached the {level} warning level "
        f"(${spent:.2f} of ${PLATFORM_DAILY_BUDGET_USD:.2f} today). "
        "Add your own provider key in Settings to avoid interruption."
    )


def record_usage(*, user_id: str, thread_id: str | None, agent: str,
                 provider: str, model: str, funding_source: str,
                 prompt: str, response: str, usage: TokenUsage | None = None,
                 request_id: str | None = None, job_id: str | None = None) -> None:
    final = usage if usage and usage.total_tokens else estimate_usage(prompt, response)
    cost = estimate_cost(final, agent=agent, model=model)
    with get_pool().get_session() as session:
        session.execute(text("""
            INSERT INTO alpatrade.llm_usage_logging
              (user_id, thread_id, request_id, job_id, agent_framework, provider,
               model_name, funding_source, input_tokens, output_tokens, total_tokens,
               estimated_cost_usd, usage_quality, metadata)
            VALUES (CAST(:uid AS UUID), CAST(:thread AS UUID), :request_id, :job_id,
                    :agent, :provider, :model, :funding, :input, :output, :total,
                    :cost, :quality, CAST(:metadata AS JSONB))
        """), {"uid": user_id, "thread": thread_id, "request_id": request_id,
                 "job_id": job_id, "agent": agent, "provider": provider,
                 "model": model, "funding": funding_source,
                 "input": final.input_tokens, "output": final.output_tokens,
                 "total": final.total_tokens, "cost": cost,
                 "quality": final.quality,
                 "metadata": json.dumps({"pricing": "configured_estimate"})})


def list_usage(requester_id: str, *, is_admin: bool, email: str = "", limit: int = 100) -> list[dict]:
    owner = "" if is_admin else "AND l.user_id = CAST(:uid AS UUID)"
    email_clause = "AND u.email ILIKE :email" if is_admin and email.strip() else ""
    params: dict[str, Any] = {"uid": requester_id, "limit": min(max(limit, 1), 500)}
    if email_clause:
        params["email"] = f"%{email.strip()}%"
    with get_pool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT l.*, u.email FROM alpatrade.llm_usage_logging l
            LEFT JOIN alpatrade.users u ON u.user_id = l.user_id
            WHERE TRUE {owner} {email_clause}
            ORDER BY l.created_at DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(row) for row in rows]


def usage_summary(requester_id: str, *, is_admin: bool, email: str = "") -> list[dict]:
    owner = "" if is_admin else "AND l.user_id = CAST(:uid AS UUID)"
    email_clause = "AND u.email ILIKE :email" if is_admin and email.strip() else ""
    params: dict[str, Any] = {"uid": requester_id}
    if email_clause:
        params["email"] = f"%{email.strip()}%"
    with get_pool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT COALESCE(u.email, 'Unowned') email, l.agent_framework,
                   l.funding_source, COUNT(*) calls, SUM(l.total_tokens) total_tokens,
                   SUM(l.estimated_cost_usd) estimated_cost_usd
            FROM alpatrade.llm_usage_logging l
            LEFT JOIN alpatrade.users u ON u.user_id=l.user_id
            WHERE l.created_at >= date_trunc('day', NOW()) {owner} {email_clause}
            GROUP BY u.email,l.agent_framework,l.funding_source
            ORDER BY estimated_cost_usd DESC
        """), params).mappings().all()
    return [dict(row) for row in rows]

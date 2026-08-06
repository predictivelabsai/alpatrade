"""Minimal in-process Growth and Value research agents.

This module ports only the methodology themes from ``alpha-agents``.  It uses
AlpaTrade's existing research data and per-user model configuration, then saves
the rendered report in the shared PostgreSQL database.  It deliberately does
not import Alpha Agents or reproduce its API, worker, auth, or scoring stack.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from engine.config import build_chat_model, get_settings
from engine.db.pool import get_pool

logger = logging.getLogger(__name__)

METHODOLOGY_VERSION = "alpha-agents@66d236b-local-v1"
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,15}$")
_MAX_RUNS = 20

_METHODOLOGIES = {
    "growth": {
        "focus": (
            "growth durability, economic moats, management quality, strategic "
            "expansion, transformation potential, and downside risks"
        ),
        "criteria": (
            "Moat durability",
            "Growth drivers",
            "Management and execution",
            "Expansion optionality",
            "Risk and red flags",
        ),
    },
    "value": {
        "focus": (
            "cyclical versus structural undervaluation, capital efficiency, balance "
            "sheet resilience, shareholder alignment, rerating catalysts, moat "
            "protection, and value-trap risk"
        ),
        "criteria": (
            "Cause of undervaluation",
            "Capital efficiency",
            "Balance sheet resilience",
            "Shareholder alignment and catalysts",
            "Value-trap risk and red flags",
        ),
    },
}

_UNAVAILABLE_MARKERS = (
    "no data found",
    "no news found",
    "no results from",
    "\n\nerror:",
)


@dataclass(frozen=True)
class AlphaResearchResult:
    run_id: str
    mode: str
    ticker: str
    status: str
    report: str
    saved: bool
    persistence_warning: str | None = None

    def as_markdown(self) -> str:
        label = self.mode.title()
        run_label = "Saved run ID" if self.saved else "Run ID (not saved)"
        warning = (
            f"\n\n> **Not saved:** {self.persistence_warning}"
            if self.persistence_warning
            else ""
        )
        return (
            f"# Alpha {label} Agent — {self.ticker}\n\n"
            f"**{run_label}:** `{self.run_id}`  \n"
            f"**Status:** {self.status}\n\n"
            f"{self.report.strip()}"
            f"{warning}\n\n"
            "---\n"
            "Read-only research; no orders were placed. "
            "Use `alpha:runs` to list saved reports."
        )


def normalize_ticker(value: str) -> str:
    """Normalize one ticker or raise a user-facing validation error."""
    ticker = (value or "").strip().upper()
    if not ticker or not _TICKER_RE.fullmatch(ticker):
        raise ValueError(
            "ticker must be one symbol using letters, numbers, '.' or '-' (for example AAPL)"
        )
    return ticker


def _safe_failure(context: str, exc: BaseException) -> str:
    """Describe a failure without copying provider, request, or credential text."""
    return f"{context} failed ({type(exc).__name__})."


def _source_is_available(content: str) -> bool:
    lowered = content.lower()
    return bool(content.strip()) and not any(
        marker in lowered for marker in _UNAVAILABLE_MARKERS
    )


async def _collect_evidence(ticker: str) -> dict[str, dict[str, str]]:
    from utils.market_research_util import MarketResearch

    research = MarketResearch()
    calls: dict[str, Callable[[], str]] = {
        "Company profile": lambda: research.profile(ticker),
        "Annual financials": lambda: research.financials(ticker, "annual"),
        "Valuation": lambda: research.valuation([ticker]),
        "Analyst ratings": lambda: research.analysts(ticker),
        "Recent news": lambda: research.news(ticker, 5),
    }

    async def collect(label: str, call: Callable[[], str]):
        try:
            content = str(await asyncio.to_thread(call) or "").strip()
            if _source_is_available(content):
                return label, {"status": "available", "content": content}
        except Exception as exc:  # noqa: BLE001 - isolate each read-only source
            logger.warning(
                "Alpha research source unavailable: %s (%s)",
                label,
                type(exc).__name__,
            )
        return label, {
            "status": "unavailable",
            "content": f"{label} was unavailable for this run.",
        }

    pairs = await asyncio.gather(
        *(collect(label, call) for label, call in calls.items())
    )
    return dict(pairs)


def _prompt(
    mode: str, ticker: str, evidence: dict[str, dict[str, str]]
) -> tuple[str, str]:
    methodology = _METHODOLOGIES[mode]
    criteria = "\n".join(f"- {item}" for item in methodology["criteria"])
    system_prompt = f"""
You are the local Alpha {mode.title()} Agent, an evidence-led public-equity research analyst.
Evaluate {methodology["focus"]}.

Use only the supplied evidence. Never invent a fact, source, URL, date, or numeric value.
Clearly label missing evidence and separate observation from inference. This is read-only
research, not an instruction to trade.

Return concise Markdown beginning with ``## Thesis`` and use these sections in order:
1. ``## Thesis`` — the central case in 2-4 sentences.
2. ``## Methodology scorecard`` — a table with Criterion, Score (1-5 or N/A),
   Confidence (low/medium/high), and Evidence.
3. ``## Supporting evidence`` — the most decision-useful facts.
4. ``## Catalysts`` — evidence-backed potential catalysts, or state that none are established.
5. ``## Risks and red flags`` — concrete risks and missing information.
6. ``## Overall research view`` — one of strong_buy, buy, hold, or avoid, with a short rationale.
7. ``## Sources and limitations`` — identify only sources present in the evidence.

Score these criteria:
{criteria}
""".strip()
    user_prompt = json.dumps(
        {
            "ticker": ticker,
            "as_of": datetime.now(UTC).date().isoformat(),
            "methodology_version": METHODOLOGY_VERSION,
            "evidence": evidence,
        },
        ensure_ascii=False,
        default=str,
    )
    return system_prompt, user_prompt


def _response_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(getattr(item, "text", item)))
        return "".join(parts).strip()
    return str(content or "").strip()


def _fallback_report(
    mode: str,
    ticker: str,
    evidence: dict[str, dict[str, str]],
    *,
    failed: bool = False,
) -> str:
    available = [
        label for label, item in evidence.items() if item["status"] == "available"
    ]
    heading = (
        "Evidence could not be collected."
        if failed
        else (
            "Model synthesis was unavailable, so the collected evidence is shown without an "
            "investment conclusion."
        )
    )
    sections = ["## Research status", "", heading]
    if available:
        sections.extend(("", f"Available sources: {', '.join(available)}."))
    sections.extend(("", "## Collected evidence"))
    for label, item in evidence.items():
        sections.extend(("", f"### {label}", "", item["content"]))
    sections.extend(
        (
            "",
            "## Limitations",
            "",
            (
                f"No synthesized {mode} view was produced for {ticker}. "
                "Do not infer a rating from this evidence bundle."
            ),
        )
    )
    return "\n".join(sections)


def _create_run(
    run_id: str,
    user_id: str | None,
    mode: str,
    ticker: str,
    model_provider: str,
    model_name: str,
) -> None:
    with get_pool().get_session() as session:
        session.execute(
            text("""
            INSERT INTO alpatrade.alpha_research_runs
                (run_id, user_id, mode, ticker, status, methodology_version,
                 model_provider, model_name, evidence)
            VALUES
                (:rid, :uid, :mode, :ticker, 'running', :methodology,
                 :provider, :model, CAST(:evidence AS JSONB))
        """),
            {
                "rid": run_id,
                "uid": user_id,
                "mode": mode,
                "ticker": ticker,
                "methodology": METHODOLOGY_VERSION,
                "provider": model_provider,
                "model": model_name,
                "evidence": "{}",
            },
        )


def _finish_run(
    run_id: str,
    status: str,
    evidence: dict[str, dict[str, str]],
    report: str,
    error: str | None = None,
) -> None:
    with get_pool().get_session() as session:
        session.execute(
            text("""
            UPDATE alpatrade.alpha_research_runs
            SET status = :status,
                evidence = CAST(:evidence AS JSONB),
                report_markdown = :report,
                error = :error,
                completed_at = NOW()
            WHERE run_id = :rid
        """),
            {
                "rid": run_id,
                "status": status,
                "evidence": json.dumps(evidence, ensure_ascii=False, default=str),
                "report": report,
                "error": error,
            },
        )


async def run_alpha_research(
    mode: str,
    ticker: str,
    user_id: str | None = None,
) -> AlphaResearchResult:
    """Run one local Growth or Value analysis and persist the attempt."""
    if mode not in _METHODOLOGIES:
        raise ValueError("mode must be growth or value")
    ticker = normalize_ticker(ticker)
    run_id = str(uuid.uuid4())
    settings = get_settings(user_id)
    saved = True
    persistence_warning = None

    try:
        await asyncio.to_thread(
            _create_run,
            run_id,
            user_id,
            mode,
            ticker,
            settings.model_provider,
            settings.model_name,
        )
    except Exception as exc:  # noqa: BLE001 - analysis remains useful without storage
        logger.warning("Alpha research run was not persisted (%s)", type(exc).__name__)
        saved = False
        persistence_warning = (
            "apply `sql/17_alpha_research_runs.sql` and verify `DATABASE_URL`."
        )

    try:
        evidence = await _collect_evidence(ticker)
    except Exception as exc:  # noqa: BLE001 - record a terminal, sanitized failure
        logger.warning("Alpha research evidence unavailable (%s)", type(exc).__name__)
        evidence = {
            label: {
                "status": "unavailable",
                "content": f"{label} was unavailable for this run.",
            }
            for label in (
                "Company profile",
                "Annual financials",
                "Valuation",
                "Analyst ratings",
                "Recent news",
            )
        }
    has_evidence = any(item["status"] == "available" for item in evidence.values())
    failure = None

    if has_evidence:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system_prompt, user_prompt = _prompt(mode, ticker, evidence)
            model = build_chat_model(
                settings,
                streaming=False,
                temperature=0.1,
                max_tokens=2500,
            )
            response = await asyncio.to_thread(
                model.invoke,
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ],
            )
            report = _response_text(response.content)
            if not report:
                raise ValueError("model returned an empty report")
            status = "completed"
        except Exception as exc:  # noqa: BLE001 - return deterministic source bundle
            logger.warning(
                "Alpha research synthesis unavailable (%s)", type(exc).__name__
            )
            failure = _safe_failure("Model synthesis", exc)
            report = _fallback_report(mode, ticker, evidence)
            status = "partial"
    else:
        failure = "No research source returned usable evidence."
        report = _fallback_report(mode, ticker, evidence, failed=True)
        status = "failed"

    if saved:
        try:
            await asyncio.to_thread(
                _finish_run, run_id, status, evidence, report, failure
            )
        except Exception as exc:  # noqa: BLE001 - never discard a completed report
            logger.warning(
                "Alpha research result was not saved (%s)", type(exc).__name__
            )
            saved = False
            persistence_warning = (
                "the report completed but PostgreSQL could not update its saved record."
            )

    return AlphaResearchResult(
        run_id=run_id,
        mode=mode,
        ticker=ticker,
        status=status,
        report=report,
        saved=saved,
        persistence_warning=persistence_warning,
    )


def list_research_runs(user_id: str | None, limit: int = 10) -> list[dict[str, Any]]:
    """List only the current user's recent Alpha Research records."""
    limit = max(1, min(int(limit), _MAX_RUNS))
    where = "user_id = :uid" if user_id else "user_id IS NULL"
    params: dict[str, Any] = {"limit": limit}
    if user_id:
        params["uid"] = user_id
    with get_pool().get_session() as session:
        rows = session.execute(
            text(f"""
            SELECT run_id, mode, ticker, status, model_provider, model_name,
                   created_at, completed_at
            FROM alpatrade.alpha_research_runs
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit
        """),
            params,
        ).fetchall()
    return [
        {
            "run_id": str(row[0]),
            "mode": row[1],
            "ticker": row[2],
            "status": row[3],
            "model_provider": row[4],
            "model_name": row[5],
            "created_at": row[6],
            "completed_at": row[7],
        }
        for row in rows
    ]


def recent_runs_markdown(user_id: str | None, limit: int = 10) -> str:
    try:
        rows = list_research_runs(user_id, limit)
    except Exception as exc:  # noqa: BLE001 - migration/setup guidance is actionable
        logger.warning("Alpha research history unavailable (%s)", type(exc).__name__)
        return (
            "# Alpha Research Runs\n\n"
            "Saved reports are unavailable. Apply `sql/17_alpha_research_runs.sql` "
            "and verify `DATABASE_URL`."
        )
    if not rows:
        return (
            "# Alpha Research Runs\n\n"
            "No saved reports yet. Run `alpha:growth ticker:AAPL` or "
            "`alpha:value ticker:BBY`."
        )
    lines = [
        "# Alpha Research Runs",
        "",
        "| Run ID | Mode | Ticker | Status | Model | Created |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        created = row["created_at"]
        created_text = (
            created.isoformat(timespec="seconds")
            if hasattr(created, "isoformat")
            else str(created)
        )
        model = (
            "/".join(filter(None, (row["model_provider"], row["model_name"]))) or "—"
        )
        lines.append(
            f"| `{row['run_id']}` | {row['mode']} | {row['ticker']} | "
            f"{row['status']} | {model} | {created_text} |"
        )
    return "\n".join(lines)

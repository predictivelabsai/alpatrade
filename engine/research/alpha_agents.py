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


def _nested_markdown(report: str) -> str:
    """Demote report headings so a mode report nests under a combined view."""
    lines = []
    for line in report.strip().splitlines():
        if line.startswith(("## ", "### ")):
            line = f"#{line}"
        lines.append(line)
    return "\n".join(lines)


@dataclass(frozen=True)
class AlphaComparisonResult:
    ticker: str
    growth: AlphaResearchResult
    value: AlphaResearchResult

    @property
    def status(self) -> str:
        statuses = {self.growth.status, self.value.status}
        if statuses == {"completed"}:
            return "completed"
        if statuses == {"failed"}:
            return "failed"
        return "partial"

    def as_markdown(self) -> str:
        results = (("Growth", self.growth), ("Value", self.value))
        lines = [
            f"# Alpha Combined View — {self.ticker}",
            "",
            f"**Status:** {self.status}",
            "",
            "| Perspective | Run ID | Status | Persistence |",
            "|---|---|---|---|",
        ]
        for label, result in results:
            persistence = "saved" if result.saved else "not saved"
            lines.append(
                f"| {label} | `{result.run_id}` | {result.status} | {persistence} |"
            )
        for label, result in results:
            if result.persistence_warning:
                lines.extend(
                    (
                        "",
                        f"> **{label} not saved:** {result.persistence_warning}",
                    )
                )
        for label, result in results:
            lines.extend(
                (
                    "",
                    f"## {label} view",
                    "",
                    _nested_markdown(result.report),
                )
            )
        lines.extend(
            (
                "",
                "---",
                (
                    "Read-only research; no orders were placed. "
                    "Use `alpha:runs` to list both saved reports."
                ),
            )
        )
        return "\n".join(lines)


def normalize_ticker(value: str) -> str:
    """Normalize one ticker or raise a user-facing validation error."""
    ticker = (value or "").strip().upper()
    if not ticker or not _TICKER_RE.fullmatch(ticker):
        raise ValueError(
            "ticker must be one symbol using letters, numbers, '.' or '-' (for example AAPL)"
        )
    return ticker


def normalize_run_id(value: str) -> str:
    """Normalize one standard UUID or raise a user-facing validation error."""
    raw = (value or "").strip().lower()
    try:
        normalized = str(uuid.UUID(raw))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("run-id must be a standard UUID") from exc
    if raw != normalized:
        raise ValueError("run-id must be a standard UUID")
    return normalized


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
    mode: str,
    ticker: str,
    evidence: dict[str, dict[str, str]],
    *,
    compact: bool = False,
) -> tuple[str, str]:
    methodology = _METHODOLOGIES[mode]
    criteria = "\n".join(f"- {item}" for item in methodology["criteria"])
    if compact:
        output_instructions = """
Return Markdown under 450 words beginning with ``## Thesis`` and use these sections:
1. ``## Thesis`` — at most two sentences.
2. ``## Methodology scorecard`` — a compact table with Criterion, Score (1-5 or N/A),
   Confidence, and a short Evidence phrase.
3. ``## Top catalyst`` — exactly one evidence-backed bullet, or state none is established.
4. ``## Top risk`` — exactly one concrete risk or missing-data warning.
5. ``## Overall research view`` — one of strong_buy, buy, hold, or avoid, plus one sentence.
6. ``## Sources and limitations`` — at most five short bullets using only supplied sources.
""".strip()
    else:
        output_instructions = """
Return concise Markdown beginning with ``## Thesis`` and use these sections in order:
1. ``## Thesis`` — the central case in 2-4 sentences.
2. ``## Methodology scorecard`` — a table with Criterion, Score (1-5 or N/A),
   Confidence (low/medium/high), and Evidence.
3. ``## Supporting evidence`` — the most decision-useful facts.
4. ``## Catalysts`` — evidence-backed potential catalysts, or state that none are established.
5. ``## Risks and red flags`` — concrete risks and missing information.
6. ``## Overall research view`` — one of strong_buy, buy, hold, or avoid, with a short rationale.
7. ``## Sources and limitations`` — identify only sources present in the evidence.
""".strip()
    system_prompt = f"""
You are the local Alpha {mode.title()} Agent, an evidence-led public-equity research analyst.
Evaluate {methodology["focus"]}.

Use only the supplied evidence. Never invent a fact, source, URL, date, or numeric value.
Clearly label missing evidence and separate observation from inference. This is read-only
research, not an instruction to trade.

{output_instructions}

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
    compact: bool = False,
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
    if compact:
        sections = [
            "## Thesis",
            "",
            heading,
            "",
            "## Methodology scorecard",
            "",
            "| Criterion | Score | Confidence | Evidence |",
            "|---|---:|---|---|",
        ]
        for criterion in _METHODOLOGIES[mode]["criteria"]:
            sections.append(f"| {criterion} | N/A | low | Synthesis unavailable |")
        sections.extend(
            (
                "",
                "## Top catalyst",
                "",
                "- None established without model synthesis.",
                "",
                "## Top risk",
                "",
                "- The available evidence could not be synthesized into a research view.",
                "",
                "## Overall research view",
                "",
                "N/A — do not infer a rating from this evidence snapshot.",
                "",
                "## Sources and limitations",
            )
        )
        for label, item in evidence.items():
            excerpt = " ".join(item["content"].split())
            if len(excerpt) > 180:
                excerpt = f"{excerpt[:177]}..."
            sections.append(f"- **{label} ({item['status']}):** {excerpt}")
        return "\n".join(sections)

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


@dataclass(frozen=True)
class _StartedRun:
    run_id: str
    mode: str
    saved: bool
    persistence_warning: str | None = None


async def _start_run(
    mode: str,
    ticker: str,
    user_id: str | None,
    settings: Any,
) -> _StartedRun:
    run_id = str(uuid.uuid4())
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
        return _StartedRun(run_id=run_id, mode=mode, saved=True)
    except Exception as exc:  # noqa: BLE001 - analysis remains useful without storage
        logger.warning(
            "Alpha %s research run was not persisted (%s)",
            mode,
            type(exc).__name__,
        )
        return _StartedRun(
            run_id=run_id,
            mode=mode,
            saved=False,
            persistence_warning=(
                "apply `sql/17_alpha_research_runs.sql` and verify `DATABASE_URL`."
            ),
        )


def _unavailable_evidence() -> dict[str, dict[str, str]]:
    return {
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


async def _collect_evidence_safely(ticker: str) -> dict[str, dict[str, str]]:
    try:
        return await _collect_evidence(ticker)
    except Exception as exc:  # noqa: BLE001 - record a terminal, sanitized failure
        logger.warning("Alpha research evidence unavailable (%s)", type(exc).__name__)
        return _unavailable_evidence()


async def _complete_started_run(
    started: _StartedRun,
    ticker: str,
    evidence: dict[str, dict[str, str]],
    settings: Any,
    *,
    compact: bool = False,
) -> AlphaResearchResult:
    has_evidence = any(item["status"] == "available" for item in evidence.values())
    failure = None

    if has_evidence:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system_prompt, user_prompt = _prompt(
                started.mode,
                ticker,
                evidence,
                compact=compact,
            )
            model = build_chat_model(
                settings,
                streaming=False,
                temperature=0.1,
                max_tokens=1400 if compact else 2500,
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
                "Alpha %s research synthesis unavailable (%s)",
                started.mode,
                type(exc).__name__,
            )
            failure = _safe_failure("Model synthesis", exc)
            report = _fallback_report(
                started.mode,
                ticker,
                evidence,
                compact=compact,
            )
            status = "partial"
    else:
        failure = "No research source returned usable evidence."
        report = _fallback_report(
            started.mode,
            ticker,
            evidence,
            failed=True,
            compact=compact,
        )
        status = "failed"

    saved = started.saved
    persistence_warning = started.persistence_warning
    if saved:
        try:
            await asyncio.to_thread(
                _finish_run,
                started.run_id,
                status,
                evidence,
                report,
                failure,
            )
        except Exception as exc:  # noqa: BLE001 - never discard a completed report
            logger.warning(
                "Alpha %s research result was not saved (%s)",
                started.mode,
                type(exc).__name__,
            )
            saved = False
            persistence_warning = (
                "the report completed but PostgreSQL could not update its saved record."
            )

    return AlphaResearchResult(
        run_id=started.run_id,
        mode=started.mode,
        ticker=ticker,
        status=status,
        report=report,
        saved=saved,
        persistence_warning=persistence_warning,
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
    settings = get_settings(user_id)
    started = await _start_run(mode, ticker, user_id, settings)
    evidence = await _collect_evidence_safely(ticker)
    return await _complete_started_run(started, ticker, evidence, settings)


async def run_alpha_comparison(
    ticker: str,
    user_id: str | None = None,
) -> AlphaComparisonResult:
    """Run compact Growth and Value views from one shared evidence collection."""
    ticker = normalize_ticker(ticker)
    settings = get_settings(user_id)
    growth_start, value_start = await asyncio.gather(
        _start_run("growth", ticker, user_id, settings),
        _start_run("value", ticker, user_id, settings),
    )
    evidence = await _collect_evidence_safely(ticker)
    growth, value = await asyncio.gather(
        _complete_started_run(
            growth_start,
            ticker,
            evidence,
            settings,
            compact=True,
        ),
        _complete_started_run(
            value_start,
            ticker,
            evidence,
            settings,
            compact=True,
        ),
    )
    return AlphaComparisonResult(ticker=ticker, growth=growth, value=value)


def get_research_run(
    user_id: str | None,
    run_id: str,
) -> dict[str, Any] | None:
    """Load one saved Alpha Research row within the current user's scope."""
    run_id = normalize_run_id(run_id)
    where = "user_id = :uid" if user_id else "user_id IS NULL"
    params: dict[str, Any] = {"rid": run_id}
    if user_id:
        params["uid"] = user_id
    with get_pool().get_session() as session:
        row = session.execute(
            text(f"""
            SELECT run_id, mode, ticker, status, report_markdown
            FROM alpatrade.alpha_research_runs
            WHERE run_id = :rid AND {where}
        """),
            params,
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": str(row[0]),
        "mode": row[1],
        "ticker": row[2],
        "status": row[3],
        "report_markdown": row[4],
    }


def saved_run_markdown(user_id: str | None, run_id: str) -> str:
    """Render one user-scoped saved report without calling data or model providers."""
    try:
        row = get_research_run(user_id, run_id)
    except ValueError:
        return "# Alpha Research Run\n\nUsage: `alpha:show run-id:<uuid>`"
    except Exception as exc:  # noqa: BLE001 - migration/setup guidance is actionable
        logger.warning("Alpha research report unavailable (%s)", type(exc).__name__)
        return (
            "# Alpha Research Run\n\n"
            "Saved reports are unavailable. Apply `sql/17_alpha_research_runs.sql` "
            "and verify `DATABASE_URL`."
        )
    if row is None:
        return (
            "# Alpha Research Run\n\n"
            "No saved report was found for that run ID. "
            "Use `alpha:runs` to list accessible reports."
        )
    report = str(row["report_markdown"] or "").strip()
    if not report:
        report = "No report Markdown was saved for this run."
    return AlphaResearchResult(
        run_id=row["run_id"],
        mode=row["mode"],
        ticker=row["ticker"],
        status=row["status"],
        report=report,
        saved=True,
    ).as_markdown()


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
            "`alpha:value ticker:BBY`.\n\n"
            "Open a saved report with `alpha:show run-id:<uuid>`."
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
    lines.extend(("", "Open one with `alpha:show run-id:<uuid>`."))
    return "\n".join(lines)

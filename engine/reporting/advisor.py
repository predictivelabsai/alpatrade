"""Tenant-scoped daily paper-trading advisor.

The advisor deliberately separates deterministic facts/policy from language-model
wording.  Broker and database facts are collected into a bounded evidence document,
pure functions classify the account and construct the only actions the model may
recommend, and DeepAgents may then rank/explain those actions.  Scheduled reviews are
read-only; execution always requires a later, explicit user instruction.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import math
import os
import re
import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import text

from engine.db.pool import DatabasePool

logger = logging.getLogger("reporting.advisor")
EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class AdvisorThresholds:
    min_closed_trades: int = 5
    drift_ratio: float = 0.5
    losing_sessions: int = 3
    drawdown_pct: float = 5.0
    urgent_daily_loss_pct: float = 2.0

    @classmethod
    def from_env(cls) -> "AdvisorThresholds":
        return cls(
            min_closed_trades=max(1, int(os.getenv("ADVISOR_MIN_CLOSED_TRADES", "5"))),
            drift_ratio=max(0.0, float(os.getenv("ADVISOR_DRIFT_RATIO", "0.5"))),
            losing_sessions=max(1, int(os.getenv("ADVISOR_LOSING_SESSIONS", "3"))),
            drawdown_pct=max(0.0, float(os.getenv("ADVISOR_DRAWDOWN_PCT", "5"))),
            urgent_daily_loss_pct=max(
                0.0, float(os.getenv("ADVISOR_URGENT_DAILY_LOSS_PCT", "2"))
            ),
        )


class AdvisorSelection(BaseModel):
    candidate_id: str = Field(max_length=96)
    explanation: str = Field(max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=6)

    model_config = {"extra": "forbid"}


class AdvisorDraft(BaseModel):
    """The only model-controlled output: a validated ordering of known actions."""

    selections: list[AdvisorSelection] = Field(default_factory=list, max_length=5)

    model_config = {"extra": "forbid"}


class AdvisorOutputError(ValueError):
    """The model responded, but its structured advisor draft was invalid."""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


_RATIO_PERCENT_PARAMETERS = {
    "dip_threshold",
    "take_profit",
    "stop_loss",
    "position_size",
    "risk_pct",
    "contraction_threshold",
    "momentum_threshold",
    "vol_target",
}

_ALREADY_PERCENT_PARAMETERS = {
    "take_profit_threshold",
    "stop_loss_threshold",
}


def normalize_parameter(key: str, value: Any) -> Any:
    """Normalize ratio-like strategy parameters to display percentages.

    Raw job configuration is retained separately.  This function is only for
    comparisons and user-facing evidence, avoiding the historic 0.05-versus-5%
    ambiguity without changing the values sent to a backtest.
    """
    if key not in _RATIO_PERCENT_PARAMETERS | _ALREADY_PERCENT_PARAMETERS:
        return _json_value(value)
    parsed = _num(value, float("nan"))
    if not math.isfinite(parsed):
        return _json_value(value)
    if key in _RATIO_PERCENT_PARAMETERS and 0 < abs(parsed) < 1:
        parsed *= 100
    return round(parsed, 4)


def normalize_parameters(
    values: Optional[dict[str, Any]], *, paper_percent: bool = False
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (values or {}).items():
        name = str(key)
        if paper_percent and name == "dip_threshold":
            parsed = _num(value, float("nan"))
            normalized[name] = round(parsed, 4) if math.isfinite(parsed) else _json_value(value)
        else:
            normalized[name] = normalize_parameter(name, value)
    return normalized


def normalize_parameter_grid(values: Optional[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(key): (
            [normalize_parameter(str(key), item) for item in value]
            if isinstance(value, list) else normalize_parameter(str(key), value)
        )
        for key, value in (values or {}).items()
    }


def canonical_backtest_grid(
    values: Optional[dict[str, Any]], *, paper_percent: bool = False
) -> dict[str, list[Any]]:
    """Map a current paper config into the grid-search engine's raw units."""
    aliases = {
        "take_profit_threshold": "take_profit",
        "stop_loss_threshold": "stop_loss",
    }
    eligible = {
        "dip_threshold", "take_profit", "stop_loss", "position_size", "hold_days",
    }
    grid: dict[str, list[Any]] = {}
    for source_key, source_value in (values or {}).items():
        source_name = str(source_key)
        key = aliases.get(source_name, source_name)
        if key not in eligible or source_value is None:
            continue
        items = source_value if isinstance(source_value, list) else [source_value]
        normalized = []
        for item in items:
            if key in {"take_profit", "stop_loss"} and source_name in aliases:
                parsed = _num(item, float("nan"))
                item = parsed / 100 if math.isfinite(parsed) else item
            elif key == "dip_threshold" and paper_percent:
                parsed = _num(item, float("nan"))
                if math.isfinite(parsed):
                    item = parsed / 100
            elif key in {"dip_threshold", "position_size"}:
                parsed = _num(item, float("nan"))
                if math.isfinite(parsed) and abs(parsed) >= 1:
                    item = parsed / 100
            normalized.append(item)
        grid[key] = normalized
    return grid


def stored_backtest_candidate_grid(
    variations: list[dict[str, Any]], limit: int = 3
) -> dict[str, list[Any]]:
    """Build a grid using only values that occur in stored backtest candidates."""
    ranked = sorted(
        variations,
        key=lambda item: _num(item.get("_score"), float("-inf")),
        reverse=True,
    )[:max(1, limit)]
    grid: dict[str, list[Any]] = {}
    for variation in ranked:
        for key, items in canonical_backtest_grid(
            variation.get("params") if isinstance(variation, dict) else {}
        ).items():
            existing = grid.setdefault(key, [])
            for item in items:
                if item not in existing:
                    existing.append(item)
    return grid


def max_drawdown_pct(equity: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in equity:
        if value <= 0:
            continue
        peak = max(peak, value)
        if peak:
            worst = max(worst, (peak - value) / peak * 100)
    return round(worst, 4)


def consecutive_losing_sessions(pnls: list[float]) -> int:
    count = 0
    for value in reversed(pnls):
        if value < 0:
            count += 1
        else:
            break
    return count


def max_losing_streak(pnls: list[float]) -> int:
    current = worst = 0
    for value in pnls:
        current = current + 1 if value < 0 else 0
        worst = max(worst, current)
    return worst


def paper_sharpe(pnl_percentages: list[float]) -> Optional[float]:
    values = [value for value in pnl_percentages if math.isfinite(value)]
    if len(values) < 2:
        return None
    deviation = statistics.stdev(values)
    if deviation <= 0:
        return 0.0
    return round(statistics.mean(values) / deviation * math.sqrt(252), 4)


def _period_return(equity: list[float], sessions: int) -> float:
    if len(equity) < 2:
        return 0.0
    start_index = max(0, len(equity) - sessions - 1)
    start, end = equity[start_index], equity[-1]
    return round(((end / start) - 1) * 100, 4) if start else 0.0


def _period_pnl(equity: list[float], sessions: int) -> float:
    if len(equity) < 2:
        return 0.0
    start_index = max(0, len(equity) - sessions - 1)
    return round(equity[-1] - equity[start_index], 2)


def _flatten_keys(value: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys.update(_flatten_keys(item, path))
    return keys


def _path_value(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _numeric_values(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        parsed = _num(value, float("nan"))
        return [parsed] if math.isfinite(parsed) else []
    if isinstance(value, dict):
        return [number for item in value.values() for number in _numeric_values(item)]
    if isinstance(value, list):
        return [number for item in value for number in _numeric_values(item)]
    return []


def _validate_explanation_numbers(
    explanation: str, evidence: dict[str, Any], refs: list[str]
) -> bool:
    mentioned = [float(value) for value in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", explanation)]
    if not mentioned:
        return True
    supported = [
        value
        for ref in refs
        for value in _numeric_values(_path_value(evidence, ref))
    ]
    return all(
        any(math.isclose(number, value, rel_tol=1e-6, abs_tol=1e-6) for value in supported)
        for number in mentioned
    )


def select_latest_matching_backtest(
    strategy_slug: Optional[str], candidates: list[Any]
) -> Any:
    """Return the newest exact-slug candidate from an already newest-first list."""
    if not strategy_slug:
        return None
    for candidate in candidates:
        candidate_slug = (
            candidate.get("strategy_slug")
            if isinstance(candidate, dict) else candidate[9]
        )
        if candidate_slug == strategy_slug:
            return candidate
    return None


def classify_evidence(
    evidence: dict[str, Any], thresholds: AdvisorThresholds = AdvisorThresholds()
) -> tuple[str, dict[str, Any]]:
    """Return deterministic severity plus the exact trigger record."""
    broker = evidence.get("broker") or {}
    paper = evidence.get("paper") or {}
    backtest = evidence.get("backtest") or {}
    risk = evidence.get("risk") or {}
    closed = int(paper.get("closed_trades") or 0)
    daily_pct = _num(broker.get("daily_pct"))
    drawdown = abs(_num(broker.get("drawdown_20_pct")))
    streak = int(broker.get("consecutive_losing_sessions") or 0)
    p_sharpe = paper.get("sharpe")
    b_sharpe = backtest.get("sharpe")
    drift = False
    if p_sharpe is not None and b_sharpe is not None:
        p_value, b_value = _num(p_sharpe), _num(b_sharpe)
        drift = p_value < b_value * thresholds.drift_ratio
    loss_detected = (
        daily_pct < 0
        or _num(paper.get("session_realized_pnl")) < 0
        or _num(broker.get("unrealized_pnl")) < 0
    )
    triggers = {
        "loss_detected": loss_detected,
        "paper_backtest_drift": drift,
        "losing_session_streak": streak,
        "drawdown_20_pct": drawdown,
        "urgent_daily_loss": daily_pct <= -thresholds.urgent_daily_loss_pct,
        "risk_limit_breach": bool(risk.get("breaches")),
        "min_closed_trades_met": closed >= thresholds.min_closed_trades,
        "thresholds": {
            "min_closed_trades": thresholds.min_closed_trades,
            "drift_ratio": thresholds.drift_ratio,
            "losing_sessions": thresholds.losing_sessions,
            "drawdown_pct": thresholds.drawdown_pct,
            "urgent_daily_loss_pct": thresholds.urgent_daily_loss_pct,
        },
    }
    if triggers["urgent_daily_loss"] or triggers["risk_limit_breach"]:
        severity = "urgent"
    elif closed < thresholds.min_closed_trades:
        severity = "insufficient_data"
    elif drift or streak >= thresholds.losing_sessions or drawdown >= thresholds.drawdown_pct:
        severity = "review"
    else:
        severity = "monitor"
    return severity, triggers


def why_no_change(
    severity: str, evidence: dict[str, Any], thresholds: AdvisorThresholds
) -> str:
    paper = evidence.get("paper") or {}
    triggers = evidence.get("triggers") or {}
    closed = int(paper.get("closed_trades") or 0)
    if severity == "insufficient_data":
        return (
            f"No parameter change is recommended because only {closed} closed paper "
            f"trade{'s' if closed != 1 else ''} are available; at least "
            f"{thresholds.min_closed_trades} are required before treating performance "
            "as a strategy signal."
        )
    if severity == "monitor":
        if triggers.get("loss_detected"):
            return (
                "The loss is reported, but paper/backtest drift, the "
                f"{thresholds.losing_sessions}-session losing streak, and the "
                f"{thresholds.drawdown_pct:g}% rolling drawdown gates were not reached. "
                "Keep the current parameters and collect more evidence."
            )
        return "No loss or deterioration gate was reached, so the current paper parameters should remain unchanged."
    if severity in {"review", "urgent"}:
        return (
            "No parameter is changed from this report. Only stored candidate values may be "
            "tested, and any resulting configuration still requires a completed backtest, "
            "validation, and a separate explicit approval before paper use."
        )
    return ""


def candidate_actions(evidence: dict[str, Any], severity: str) -> list[dict[str, Any]]:
    """Construct the only actions the language model may recommend."""
    candidates: list[dict[str, Any]] = []
    strategy = evidence.get("strategy") or {}
    backtest = evidence.get("backtest") or {}
    triggers = evidence.get("triggers") or {}
    if severity == "urgent":
        candidates.append({
            "candidate_id": "pause-new-paper-entries",
            "kind": "risk",
            "title": "Pause new paper entries while the loss is reviewed",
            "rationale": "The urgent daily-loss or portfolio-risk gate was reached.",
            "evidence_refs": [
                "broker.daily_pct", "risk.breaches", "broker.drawdown_20_pct",
            ],
            "approval_required": True,
            "test_config": None,
        })

    if severity not in {"review", "urgent"}:
        return candidates

    if strategy.get("grid_backtest_compatible", True):
        raw_variations = backtest.get("refined_grid") or {}
        candidate_id = "retest-refined-grid"
        candidate_title = "Backtest the stored refined parameter grid"
        candidate_source = "backtest.refined_grid"
        candidate_display_source = "backtest.refined_grid_display"
        if not raw_variations:
            raw_variations = backtest.get("stored_candidate_grid") or {}
            candidate_id = "retest-stored-candidates"
            candidate_title = "Retest values from the strongest stored backtest candidates"
            candidate_source = "backtest.stored_candidate_grid"
            candidate_display_source = "backtest.stored_candidate_grid_display"
        if not raw_variations:
            raw_variations = (evidence.get("regime") or {}).get("preset_raw") or {}
            candidate_id = "test-regime-preset"
            candidate_title = "Backtest the stored preset for the current market regime"
            candidate_source = "regime.preset_raw"
            candidate_display_source = "regime.preset_display"
        if not raw_variations:
            current_params = strategy.get("params_raw") or {}
            raw_variations = (
                strategy.get("backtest_grid")
                or canonical_backtest_grid(current_params)
            )
            candidate_id = "retest-current-config"
            candidate_title = "Retest the current paper parameters before changing them"
            candidate_source = "strategy.params_raw"
            candidate_display_source = "strategy.params_display"
        if backtest.get("run_id") and raw_variations:
            job_config = {
                "strategy": strategy.get("name") or "buy_the_dip",
                "symbols": (strategy.get("symbols") or [])[:25],
                "lookback": strategy.get("lookback") or "3m",
                "variations": raw_variations,
                "source_advisor_report": evidence.get("report_id"),
            }
            if not job_config["symbols"]:
                job_config.pop("symbols")
            candidates.append({
                "candidate_id": candidate_id,
                "kind": "backtest",
                "title": candidate_title,
                "rationale": "Paper performance deteriorated relative to the matched backtest or loss gates.",
                "evidence_refs": [
                    "paper.sharpe", "backtest.sharpe",
                    "triggers.paper_backtest_drift",
                    "triggers.losing_session_streak",
                    "triggers.drawdown_20_pct",
                    "triggers.urgent_daily_loss",
                    candidate_display_source,
                ],
                "approval_required": True,
                "parameter_source": candidate_source,
                "proposed_parameters_display": normalize_parameter_grid(raw_variations),
                "test_config": job_config,
            })
        elif strategy.get("name") and raw_variations:
            candidates.append({
                "candidate_id": candidate_id,
                "kind": "backtest",
                "title": candidate_title,
                "rationale": "No exact matched baseline is available; test an existing eligible parameter set first.",
                "evidence_refs": [
                    "strategy.slug", "backtest.available",
                    "triggers.losing_session_streak",
                    "triggers.drawdown_20_pct",
                    "triggers.urgent_daily_loss",
                    candidate_display_source,
                ],
                "approval_required": True,
                "parameter_source": candidate_source,
                "proposed_parameters_display": normalize_parameter_grid(raw_variations),
                "test_config": {
                    "strategy": strategy.get("name"),
                    "symbols": (strategy.get("symbols") or [])[:25],
                    "lookback": strategy.get("lookback") or "3m",
                    "variations": raw_variations,
                    "source_advisor_report": evidence.get("report_id"),
                },
            })
            if not candidates[-1]["test_config"]["symbols"]:
                candidates[-1]["test_config"].pop("symbols")

    if triggers.get("risk_limit_breach"):
        candidates.append({
            "candidate_id": "restore-paper-risk-limits",
            "kind": "risk",
            "title": "Restore paper exposure to the configured risk limits",
            "rationale": "A deterministic position, count, or gross-exposure limit is breached.",
            "evidence_refs": ["risk.breaches", "risk.gross_exposure_pct"],
            "approval_required": True,
            "test_config": None,
        })
    return candidates


def deterministic_drivers(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    broker, paper = evidence.get("broker") or {}, evidence.get("paper") or {}
    backtest = evidence.get("backtest") or {}
    attribution = evidence.get("attribution") or {}
    risk = evidence.get("risk") or {}
    if broker.get("available"):
        account_detail = (
            f"Broker-reported daily P&L is {_num(broker.get('daily_pnl')):+,.2f} "
            f"({_num(broker.get('daily_pct')):+.2f}%)."
        )
        unrealized_detail = (
            f"broker unrealized P&L is {_num(broker.get('unrealized_pnl')):+,.2f}"
            if broker.get("positions_available")
            else "broker unrealized P&L was unavailable"
        )
        attribution_detail = (
            f"AlpaTrade-attributed session realized P&L is "
            f"{_num(attribution.get('alpatrade_session_realized_pnl')):+,.2f}; "
            f"{unrealized_detail}; the unattributed residual is "
            f"{_num(attribution.get('unattributed_residual')):+,.2f}."
        )
    else:
        account_detail = (
            "The broker snapshot was unavailable, so daily account P&L was not calculated."
        )
        attribution_detail = (
            f"AlpaTrade-attributed session realized P&L is "
            f"{_num(attribution.get('alpatrade_session_realized_pnl')):+,.2f}; "
            "broker unrealized P&L and the unattributed residual were not calculated."
        )
    drivers = [{
        "title": "Account performance",
        "detail": account_detail,
        "evidence_refs": ["broker.available", "broker.daily_pnl", "broker.daily_pct"],
    }]
    drivers.append({
        "title": "P&L attribution",
        "detail": attribution_detail,
        "evidence_refs": [
            "attribution.alpatrade_session_realized_pnl",
            "broker.unrealized_pnl",
            "attribution.unattributed_residual",
        ],
    })
    drivers.append({
        "title": "Tracked strategy outcomes",
        "detail": (
            f"AlpaTrade recorded {int(paper.get('closed_trades') or 0)} closed paper "
            f"trades, {_num(paper.get('win_rate')):.1f}% wins, and "
            f"{_num(paper.get('realized_pnl')):+,.2f} realized P&L in the evidence window."
        ),
        "evidence_refs": [
            "paper.closed_trades", "paper.win_rate", "paper.realized_pnl",
        ],
    })
    drivers.append({
        "title": "Exit outcomes and costs",
        "detail": (
            f"Tracked exits include {int(paper.get('target_exits') or 0)} targets and "
            f"{int(paper.get('stop_loss_exits') or 0)} stop losses, with "
            f"{_num(paper.get('total_fees')):,.2f} in recorded fees."
        ),
        "evidence_refs": [
            "paper.target_exits", "paper.stop_loss_exits", "paper.total_fees",
        ],
    })
    top_losses = paper.get("top_losses") or []
    if top_losses:
        loss_detail = "; ".join(
            f"{str(item.get('symbol') or '?')}: {_num(item.get('pnl')):+,.2f}"
            f" ({str(item.get('reason') or 'reason unavailable')[:80]})"
            for item in top_losses[:3]
        )
        drivers.append({
            "title": "Largest tracked realized losses",
            "detail": loss_detail + ".",
            "evidence_refs": ["paper.top_losses"],
        })
    if backtest.get("available") and paper.get("sharpe") is not None:
        drivers.append({
            "title": "Paper versus matched backtest",
            "detail": (
                f"Paper Sharpe is {_num(paper.get('sharpe')):.2f} versus "
                f"{_num(backtest.get('sharpe')):.2f} for the latest exact-slug backtest."
            ),
            "evidence_refs": ["paper.sharpe", "backtest.sharpe", "strategy.slug"],
        })
    exposure_detail = (
        f"Gross exposure is {_num(risk.get('gross_exposure_pct')):.1f}% of equity "
        f"across {int(risk.get('open_positions') or 0)} positions; the largest "
        f"position is {_num(risk.get('max_position_pct')):.1f}%."
        if broker.get("positions_available")
        else "Broker positions were unavailable, so exposure and concentration were not calculated."
    )
    drivers.append({
        "title": "Exposure and concentration",
        "detail": exposure_detail,
        "evidence_refs": [
            "risk.gross_exposure_pct", "risk.open_positions", "risk.max_position_pct",
        ],
    })
    if (evidence.get("quality") or {}).get("warnings"):
        drivers.append({
            "title": "Data quality",
            "detail": str(evidence["quality"]["warnings"][0])[:500],
            "evidence_refs": ["quality.warnings"],
        })
    return drivers


def finalize_advisory(
    evidence: dict[str, Any],
    candidates: list[dict[str, Any]],
    draft: Optional[AdvisorDraft],
    thresholds: AdvisorThresholds,
    fallback_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Validate model selections against deterministic evidence/candidates."""
    severity = str(evidence["severity"])
    candidate_map = {item["candidate_id"]: item for item in candidates}
    valid_refs = _flatten_keys(evidence)
    explanations = {}
    if draft:
        model_ids = [selection.candidate_id for selection in draft.selections]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("model duplicated an advisor candidate")
        for selection in draft.selections:
            if selection.candidate_id not in candidate_map:
                raise ValueError("model selected an unknown advisor candidate")
            allowed_refs = set(candidate_map[selection.candidate_id]["evidence_refs"])
            supplied_refs = set(selection.evidence_refs)
            if not supplied_refs or not supplied_refs <= allowed_refs:
                raise ValueError("model cited unsupported advisor evidence")
            if not supplied_refs <= valid_refs:
                raise ValueError("model cited missing advisor evidence")
            if not _validate_explanation_numbers(
                selection.explanation, evidence, selection.evidence_refs
            ):
                raise ValueError("model altered or invented an advisor metric")
            normalized_explanation = " ".join(selection.explanation.split())
            allowed_explanation = " ".join(
                str(candidate_map[selection.candidate_id]["rationale"]).split()
            )
            if normalized_explanation != allowed_explanation:
                raise ValueError("model made an unsupported advisor claim")
            explanations[selection.candidate_id] = selection.explanation
        if severity in {"review", "urgent"} and set(model_ids) != set(candidate_map):
            raise ValueError("model omitted an eligible advisor candidate")
    selected_ids = [key for key in explanations]
    if severity in {"review", "urgent"} and candidates and not selected_ids:
        selected_ids = [item["candidate_id"] for item in candidates]
    recommendations = []
    for candidate_id in selected_ids:
        item = dict(candidate_map[candidate_id])
        item["explanation"] = explanations.get(candidate_id) or item["rationale"]
        recommendations.append(item)

    # Metrics and performance-driver wording remain deterministic so unsupported
    # causal claims cannot enter the persisted cross-surface report.
    drivers = deterministic_drivers(evidence)

    parameter_changes = [
        item for item in recommendations if item.get("kind") == "parameter_change"
    ]
    no_change = "" if parameter_changes else why_no_change(
        severity, evidence, thresholds
    )
    unsupported = (evidence.get("strategy") or {}).get(
        "unsupported_backtest_parameters"
    ) or []
    if unsupported:
        no_change += (
            " No parameter test is recommended because the grid-search engine cannot "
            f"reproduce: {', '.join(str(item) for item in unsupported)}."
        )
    elif severity in {"review", "urgent"} and not any(
        item.get("kind") == "backtest" for item in candidates
    ):
        no_change += (
            " No eligible values were available from the current configuration, an "
            "existing refit grid, a regime preset, or stored backtest candidates."
        )
    broker = evidence.get("broker") or {}
    if broker.get("available"):
        if broker.get("history_available"):
            window_summary = (
                f"5-session return is {_num(broker.get('return_5_pct')):+.2f}% "
                f"and 20-session return is {_num(broker.get('return_20_pct')):+.2f}%."
            )
        else:
            window_summary = "Multi-session broker returns were unavailable."
        broker_summary = (
            f"Broker P&L is {_num(broker.get('daily_pnl')):+,.2f}; {window_summary}"
        )
    else:
        broker_summary = "Broker account P&L was unavailable for this report."
    fallback_summary = (
        f"Daily paper-account review is {severity.replace('_', ' ')}. "
        f"{broker_summary} AlpaTrade-attributed realized P&L is "
        f"{_num((evidence.get('paper') or {}).get('session_realized_pnl')):+,.2f}."
    )
    if fallback_reason == "invalid_model_output":
        generation_note = (
            "DeepAgents output failed application validation; this is a deterministic fallback."
        )
    elif fallback_reason == "model_unavailable":
        generation_note = (
            "DeepAgents or the configured model was unavailable; this is a deterministic fallback."
        )
    elif draft and candidates:
        generation_note = (
            "DeepAgents ranked eligible next steps; deterministic evidence and policy remain authoritative."
        )
    elif draft:
        generation_note = (
            "DeepAgents reviewed the evidence; no eligible candidate action was available."
        )
    else:
        generation_note = "No AI draft was produced; this is a deterministic fallback."
    return {
        "schema_version": 1,
        "report_id": evidence.get("report_id"),
        "session_date": evidence.get("session_date"),
        "severity": severity,
        "headline": f"Daily paper review: {severity.replace('_', ' ')}",
        "summary": fallback_summary,
        "drivers": drivers,
        "recommendations": recommendations,
        "why_no_change": no_change,
        "approval_required": bool(recommendations),
        "data_warnings": list((evidence.get("quality") or {}).get("warnings") or []),
        "ai_status": "available" if draft else "unavailable",
        "generation_note": generation_note,
        "disclaimer": (
            "Paper trading is simulated. Recommendations are strategy research, not "
            "live orders or personalized investment advice. Every action requires approval."
        ),
    }


def _report_dict(row: Any) -> Optional[dict[str, Any]]:
    if not row:
        return None
    keys = (
        "report_id", "user_id", "account_id", "session_date", "status", "severity",
        "evidence", "advisory", "narrative", "model_provider", "model_name",
        "error_code", "created_at", "updated_at", "completed_at",
    )
    result = dict(zip(keys, row))
    for key in ("report_id", "user_id", "account_id"):
        result[key] = str(result[key])
    result["session_date"] = result["session_date"].isoformat()
    return result


def reserve_report(user_id: str, account_id: str, session_date: date) -> dict[str, Any]:
    with DatabasePool().get_session() as session:
        row = session.execute(text("""
            INSERT INTO alpatrade.advisor_reports
                (user_id, account_id, session_date, status)
            SELECT ua.user_id, ua.account_id, :day, 'generating'
            FROM alpatrade.user_accounts ua
            WHERE ua.user_id = CAST(:uid AS UUID)
              AND ua.account_id = CAST(:aid AS UUID)
              AND ua.is_active = TRUE
            ON CONFLICT (user_id, account_id, session_date) DO UPDATE
            SET updated_at = NOW()
            RETURNING report_id, user_id, account_id, session_date, status, severity,
                      evidence, advisory, narrative, model_provider, model_name,
                      error_code, created_at, updated_at, completed_at
        """), {"uid": user_id, "aid": account_id, "day": session_date}).fetchone()
    return _report_dict(row) or {}


def save_report(
    report_id: str,
    *,
    status: str,
    severity: str,
    evidence: dict[str, Any],
    advisory: dict[str, Any],
    provider: Optional[str],
    model_name: Optional[str],
    error_code: Optional[str] = None,
) -> None:
    narrative = str(advisory.get("summary") or "")
    with DatabasePool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.advisor_reports
            SET status = :status, severity = :severity, evidence = :evidence,
                advisory = :advisory, narrative = :narrative,
                model_provider = :provider, model_name = :model,
                error_code = :error_code, updated_at = NOW(), completed_at = NOW()
            WHERE report_id = :rid
        """), {
            "rid": report_id,
            "status": status,
            "severity": severity,
            "evidence": json.dumps(evidence, default=_json_value),
            "advisory": json.dumps(advisory, default=_json_value),
            "narrative": narrative,
            "provider": provider,
            "model": model_name,
            "error_code": error_code,
        })


def fail_report(report_id: str, error_code: str = "generation_failed") -> None:
    with DatabasePool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.advisor_reports
            SET status = 'failed', error_code = :code, updated_at = NOW(), completed_at = NOW()
            WHERE report_id = :rid
        """), {"rid": report_id, "code": error_code[:64]})


def get_report_for_user(report_id: str, user_id: str) -> Optional[dict[str, Any]]:
    with DatabasePool().get_session() as session:
        row = session.execute(text("""
            SELECT report_id, user_id, account_id, session_date, status, severity,
                   evidence, advisory, narrative, model_provider, model_name,
                   error_code, created_at, updated_at, completed_at
            FROM alpatrade.advisor_reports
            WHERE report_id = :rid AND user_id = :uid
        """), {"rid": report_id, "uid": user_id}).fetchone()
    return _report_dict(row)


def list_reports_for_user(
    user_id: str, account_id: Optional[str] = None, limit: int = 20
) -> list[dict[str, Any]]:
    clauses = ["user_id = :uid"]
    params: dict[str, Any] = {"uid": user_id, "limit": max(1, min(int(limit), 100))}
    if account_id:
        clauses.append("account_id = CAST(:aid AS UUID)")
        params["aid"] = account_id
    with DatabasePool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT report_id, user_id, account_id, session_date, status, severity,
                   evidence, advisory, narrative, model_provider, model_name,
                   error_code, created_at, updated_at, completed_at
            FROM alpatrade.advisor_reports
            WHERE {' AND '.join(clauses)}
            ORDER BY session_date DESC, created_at DESC LIMIT :limit
        """), params).fetchall()
    return [_report_dict(row) for row in rows if row]


def active_advisor_users() -> list[dict[str, str]]:
    """Active users with at least one encrypted linked account."""
    with DatabasePool().get_session() as session:
        rows = session.execute(text("""
            SELECT DISTINCT u.user_id, u.email
            FROM alpatrade.users u
            JOIN alpatrade.user_accounts a ON a.user_id = u.user_id
            WHERE u.is_active = TRUE AND a.is_active = TRUE
              AND a.alpaca_api_key_enc IS NOT NULL
              AND a.alpaca_secret_key_enc IS NOT NULL
            ORDER BY u.user_id
        """)).fetchall()
    return [{"user_id": str(row[0]), "email": str(row[1])} for row in rows]


def usable_paper_accounts(user_id: str) -> list[dict[str, Any]]:
    """Return linked accounts whose credentials authenticate against Alpaca paper."""
    from engine.auth import get_alpaca_keys, get_user_accounts
    from engine.brokers.alpaca import AlpacaAPI

    usable = []
    for account in get_user_accounts(user_id):
        keys = get_alpaca_keys(user_id, account["account_id"])
        if not keys:
            continue
        try:
            client = AlpacaAPI(keys[0], keys[1], paper=True)
            snapshot = client.get_account()
            if client.is_paper and isinstance(snapshot, dict) and not snapshot.get("error"):
                usable.append(account)
        except Exception:  # noqa: BLE001
            continue
    return usable


def _account_history(client: Any, session_date: date) -> dict[str, Any]:
    from alpaca.trading.requests import GetPortfolioHistoryRequest

    start = datetime.combine(session_date - timedelta(days=45), time.min, tzinfo=EASTERN)
    end = datetime.combine(session_date + timedelta(days=1), time.min, tzinfo=EASTERN)
    request = GetPortfolioHistoryRequest(
        start=start, end=end, timeframe="1D", extended_hours=True, pnl_reset="per_day"
    )
    raw = client.trading_client.get_portfolio_history(request)
    data = raw if isinstance(raw, dict) else (
        raw.model_dump() if hasattr(raw, "model_dump") else raw.dict()
    )
    timestamps = list(data.get("timestamp") or [])
    equities = [_num(value) for value in (data.get("equity") or [])]
    pnls = [_num(value) for value in (data.get("profit_loss") or [])]
    sessions = []
    for index, stamp in enumerate(timestamps):
        observed = datetime.fromtimestamp(int(stamp), tz=timezone.utc).astimezone(EASTERN)
        if observed.date() <= session_date:
            sessions.append({
                "date": observed.date().isoformat(),
                "equity": equities[index] if index < len(equities) else 0.0,
                "pnl": pnls[index] if index < len(pnls) else 0.0,
            })
    # Twenty session changes require up to twenty-one closing-equity points.
    return {"sessions": sessions[-21:]}


def _broker_evidence(user_id: str, account_id: str, session_date: date) -> dict[str, Any]:
    from engine.auth import get_alpaca_keys
    from engine.brokers.alpaca import AlpacaAPI

    keys = get_alpaca_keys(user_id, account_id)
    if not keys:
        raise PermissionError("paper credentials unavailable")
    client = AlpacaAPI(keys[0], keys[1], paper=True)
    if not client.is_paper:
        raise PermissionError("advisor is paper-only")
    account = client.get_account()
    if not isinstance(account, dict) or account.get("error"):
        raise RuntimeError("paper account unavailable")
    positions = client.get_positions()
    positions_available = isinstance(positions, list)
    if not positions_available:
        positions = []
    try:
        history = _account_history(client, session_date)
    except Exception:  # noqa: BLE001
        history = {"sessions": []}
    equity = _num(account.get("equity"))
    last_equity = _num(account.get("last_equity")) or equity
    daily_pnl = equity - last_equity
    daily_pct = daily_pnl / last_equity * 100 if last_equity else 0.0
    sessions = history["sessions"]
    history_available = bool(sessions)
    equity_values = [row["equity"] for row in sessions if row["equity"] > 0]
    daily_pnls = [row["pnl"] for row in sessions]
    if not sessions:
        sessions = [{"date": session_date.isoformat(), "equity": equity, "pnl": daily_pnl}]
        equity_values = [equity]
        daily_pnls = [daily_pnl]
    position_rows = []
    unrealized = 0.0
    gross_exposure = 0.0
    for position in positions:
        market_value = abs(_num(position.get("market_value")))
        pnl = _num(position.get("unrealized_pl"))
        unrealized += pnl
        gross_exposure += market_value
        position_rows.append({
            "symbol": str(position.get("symbol") or "")[:16],
            "qty": _num(position.get("qty")),
            "side": str(position.get("side") or ""),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(pnl, 2),
            "unrealized_pct": round(_num(position.get("unrealized_plpc")) * 100, 4),
            "weight_pct": round(market_value / equity * 100, 4) if equity else 0.0,
        })
    position_rows.sort(key=lambda row: abs(row["unrealized_pnl"]), reverse=True)
    return {
        "available": True,
        "paper_only": True,
        "equity": round(equity, 2),
        "cash": round(_num(account.get("cash")), 2),
        "buying_power": round(_num(account.get("buying_power")), 2),
        "daily_pnl": round(daily_pnl, 2),
        "daily_pct": round(daily_pct, 4),
        "return_5_pct": _period_return(equity_values, 5),
        "pnl_5": _period_pnl(equity_values, 5),
        "return_20_pct": _period_return(equity_values, 20),
        "pnl_20": _period_pnl(equity_values, 20),
        "drawdown_20_pct": max_drawdown_pct(equity_values),
        "consecutive_losing_sessions": consecutive_losing_sessions(daily_pnls),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": None,
        "realized_pnl_available": False,
        "gross_exposure": round(gross_exposure, 2),
        "daytrade_count": int(account.get("daytrade_count") or 0),
        "history_available": history_available,
        "positions_available": positions_available,
        "sessions": sessions,
        "positions": position_rows[:25],
    }


def _local_day(value: Any) -> Optional[date]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(EASTERN).date()


def _database_evidence(
    user_id: str, account_id: str, session_date: date, broker_sessions: list[dict]
) -> dict[str, Any]:
    start = datetime.combine(session_date - timedelta(days=60), time.min, tzinfo=EASTERN)
    end = datetime.combine(session_date + timedelta(days=1), time.min, tzinfo=EASTERN)
    with DatabasePool().get_session() as session:
        current = session.execute(text("""
            SELECT run_id, strategy, strategy_slug, config, results, status, started_at
            FROM alpatrade.runs
            WHERE user_id = :uid AND account_id = CAST(:aid AS UUID)
              AND mode IN ('paper', 'full')
            ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id, "aid": account_id}).fetchone()

        current_slug = current[2] if current else None
        trades = session.execute(text("""
            SELECT t.run_id, t.symbol, t.pnl, t.pnl_pct, t.total_fees, t.reason,
                   t.hit_target, t.hit_stop, t.exit_time, t.created_at
            FROM alpatrade.trades t
            JOIN alpatrade.runs r ON r.run_id = t.run_id
            WHERE t.user_id = :uid AND t.account_id = CAST(:aid AS UUID)
              AND r.user_id = :uid
              AND (r.account_id = CAST(:aid AS UUID) OR r.account_id IS NULL)
              AND t.trade_type = 'paper' AND t.pnl IS NOT NULL
              AND (:slug IS NULL OR r.strategy_slug = :slug)
              AND COALESCE(t.exit_time, t.created_at) >= :start
              AND COALESCE(t.exit_time, t.created_at) < :end
            ORDER BY COALESCE(t.exit_time, t.created_at)
        """), {
            "uid": user_id,
            "aid": account_id,
            "slug": current_slug,
            "start": start,
            "end": end,
        }).fetchall()

        matched = None
        variations: list[dict[str, Any]] = []
        if current and current[2]:
            matched_rows = session.execute(text("""
                SELECT r.run_id, bs.total_return, bs.total_pnl, bs.win_rate,
                       bs.total_trades, bs.sharpe_ratio, bs.max_drawdown,
                       bs.annualized_return, bs.params, bs.strategy_slug, r.created_at
                FROM alpatrade.backtest_summaries bs
                JOIN alpatrade.runs r ON r.run_id = bs.run_id
                WHERE r.user_id = :uid
                  AND (r.account_id = CAST(:aid AS UUID) OR r.account_id IS NULL)
                  AND bs.strategy_slug = :slug AND bs.is_best = TRUE
                ORDER BY r.created_at DESC LIMIT 20
            """), {"uid": user_id, "aid": account_id, "slug": current[2]}).fetchall()
            matched = select_latest_matching_backtest(current[2], list(matched_rows))
            if matched:
                rows = session.execute(text("""
                    SELECT params, sharpe_ratio, annualized_return, max_drawdown,
                           total_trades
                    FROM alpatrade.backtest_summaries
                    WHERE run_id = :rid ORDER BY variation_index LIMIT 50
                """), {"rid": matched[0]}).fetchall()
                variations = [{
                    "params": row[0] or {},
                    "sharpe_ratio": _num(row[1]),
                    "annualized_return": _num(row[2]),
                    "max_drawdown": _num(row[3]),
                    "total_trades": int(row[4] or 0),
                    "_score": _num(row[2]) - abs(_num(row[3])),
                } for row in rows]

        backtest_validation = None
        if matched:
            backtest_validation = session.execute(text("""
                SELECT source, status, anomalies_found, anomalies_corrected, created_at
                FROM alpatrade.validations
                WHERE run_id = :rid AND user_id = :uid
                  AND (source = 'backtest' OR source IS NULL)
                ORDER BY created_at DESC LIMIT 1
            """), {"rid": matched[0], "uid": user_id}).fetchone()

        validation = None
        if current:
            validation = session.execute(text("""
                SELECT source, status, anomalies_found, anomalies_corrected, suggestions,
                       created_at
                FROM alpatrade.validations
                WHERE run_id = :rid AND user_id = :uid
                ORDER BY created_at DESC LIMIT 1
            """), {"rid": current[0], "uid": user_id}).fetchone()

        reconciliation = session.execute(text("""
            SELECT status, results, completed_at
            FROM alpatrade.runs
            WHERE user_id = :uid AND account_id = CAST(:aid AS UUID)
              AND mode IN ('reconcile', 'full') AND completed_at IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
        """), {"uid": user_id, "aid": account_id}).fetchone()

    session_dates = {date.fromisoformat(row["date"]) for row in broker_sessions if row.get("date")}
    if session_dates:
        oldest_session = min(session_dates)
        trades = [row for row in trades if (_local_day(row[8] or row[9]) or date.min) >= oldest_session]
    pnls = [_num(row[2]) for row in trades]
    pnl_pcts = [_num(row[3]) for row in trades if row[3] is not None]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    session_rows = [row for row in trades if _local_day(row[8] or row[9]) == session_date]
    by_reason: dict[str, int] = defaultdict(int)
    for row in trades:
        reason = str(row[5] or "unknown").split("(")[0].strip().lower() or "unknown"
        by_reason[reason] += 1
    top_losses = sorted((
        {"symbol": str(row[1] or ""), "pnl": _num(row[2]), "reason": str(row[5] or "")[:120]}
        for row in trades if _num(row[2]) < 0
    ), key=lambda item: item["pnl"])[:5]

    run_config = (current[3] or {}) if current and isinstance(current[3], dict) else {}
    run_results = (current[4] or {}) if current and isinstance(current[4], dict) else {}
    best_params = (matched[8] or {}) if matched and isinstance(matched[8], dict) else {}
    params = run_config.get("params") if isinstance(run_config.get("params"), dict) else {}
    params_are_paper_percent = bool(params)
    if not params:
        full_best = (
            ((run_results.get("phases") or {}).get("backtest") or {}).get("best_config")
            or {}
        )
        params = full_best.get("params") if isinstance(full_best.get("params"), dict) else {}
        params_are_paper_percent = False
    if not params:
        # Compatibility for paper runs created before resolved parameters were
        # persisted under config.params.
        parameter_keys = {
            "dip_threshold", "take_profit_threshold", "stop_loss_threshold",
            "hold_days", "min_hold_days", "capital_per_trade", "position_size",
        }
        params = {
            key: run_config[key]
            for key in parameter_keys
            if run_config.get(key) is not None
        }
        params_are_paper_percent = bool(params)
    raw_symbols = params.get("symbols") or run_config.get("symbols") or []
    if isinstance(raw_symbols, str):
        raw_symbols = [item.strip() for item in raw_symbols.split(",") if item.strip()]
    strategy = {
        "run_id": str(current[0]) if current else None,
        "name": current[1] if current else None,
        "slug": current[2] if current else None,
        "status": current[5] if current else None,
        "started_at": _json_value(current[6]) if current else None,
        "params_raw": params,
        "params_display": normalize_parameters(
            params, paper_percent=params_are_paper_percent
        ),
        "parameter_units": (
            "paper_percent" if params_are_paper_percent else "backtest_ratio"
        ),
        "backtest_grid": canonical_backtest_grid(
            params, paper_percent=params_are_paper_percent
        ),
        "symbols": list(raw_symbols)[:25],
        "lookback": str(run_config.get("lookback") or "3m")[:16],
    }
    unsupported_backtest_parameters = []
    if _num(params.get("min_hold_days")) > 0:
        unsupported_backtest_parameters.append("min_hold_days")
    if strategy["name"] and strategy["name"] != "buy_the_dip":
        # The legacy grid engine accepts these strategy names, but their
        # runners do not consume an arbitrary parameter grid. Do not present a
        # stored-grid action that would silently ignore the proposed values.
        unsupported_backtest_parameters.append(
            f"{strategy['name']}_parameter_grid"
        )
    strategy["unsupported_backtest_parameters"] = unsupported_backtest_parameters
    strategy["grid_backtest_compatible"] = (
        strategy["name"] == "buy_the_dip"
        and not unsupported_backtest_parameters
    )
    backtest = {
        "available": bool(matched),
        "run_id": str(matched[0]) if matched else None,
        "return_pct": _num(matched[1]) if matched else None,
        "pnl": _num(matched[2]) if matched else None,
        "win_rate": _num(matched[3]) if matched else None,
        "trades": int(matched[4] or 0) if matched else 0,
        "sharpe": (
            _num(matched[5]) if matched and matched[5] is not None else None
        ),
        "max_drawdown_pct": _num(matched[6]) if matched else None,
        "annualized_return_pct": _num(matched[7]) if matched else None,
        "params_raw": best_params,
        "params_display": normalize_parameters(best_params),
        "refined_grid": canonical_backtest_grid(
            run_config.get("refined_grid")
            if isinstance(run_config.get("refined_grid"), dict) else {}
        ),
        "stored_candidate_grid": stored_backtest_candidate_grid(variations),
        "validation": {
            "available": bool(backtest_validation),
            "source": backtest_validation[0] if backtest_validation else None,
            "status": backtest_validation[1] if backtest_validation else None,
            "anomalies_found": int(backtest_validation[2] or 0)
            if backtest_validation else 0,
            "anomalies_corrected": int(backtest_validation[3] or 0)
            if backtest_validation else 0,
            "as_of": _json_value(backtest_validation[4])
            if backtest_validation else None,
        },
    }
    backtest["refined_grid_display"] = normalize_parameter_grid(
        backtest["refined_grid"]
    )
    backtest["stored_candidate_grid_display"] = normalize_parameter_grid(
        backtest["stored_candidate_grid"]
    )
    reconciliation_result = (
        reconciliation[1] if reconciliation and isinstance(reconciliation[1], dict) else {}
    )
    reconciliation_phase = (
        (reconciliation_result.get("phases") or {}).get("reconciliation") or {}
        if isinstance(reconciliation_result, dict) else {}
    )
    return {
        "strategy": strategy,
        "paper": {
            "trade_scope": "exact_strategy_slug" if current and current[2] else "all_alpatrade_paper_trades",
            "strategy_slug": current[2] if current else None,
            "window_start": min(session_dates).isoformat() if session_dates else start.date().isoformat(),
            "window_end": session_date.isoformat(),
            "closed_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 4) if trades else 0.0,
            "realized_pnl": round(sum(pnls), 2),
            "session_realized_pnl": round(sum(_num(row[2]) for row in session_rows), 2),
            "total_fees": round(sum(_num(row[4]) for row in trades), 2),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
            "sharpe": paper_sharpe(pnl_pcts),
            "current_losing_trade_streak": consecutive_losing_sessions(pnls),
            "max_losing_trade_streak": max_losing_streak(pnls),
            # Older paper-session rows encoded the exit only in ``reason``;
            # newer/backtest rows may also carry the explicit hit flags.
            "target_exits": sum(
                1 for row in trades
                if row[6] or str(row[5] or "").strip().upper().startswith("TAKE_PROFIT")
            ),
            "stop_loss_exits": sum(
                1 for row in trades
                if row[7] or str(row[5] or "").strip().upper().startswith("STOP_LOSS")
            ),
            "exit_reasons": dict(sorted(by_reason.items())),
            "top_losses": top_losses,
        },
        "backtest": backtest,
        "validation": {
            "available": bool(validation),
            "source": validation[0] if validation else None,
            "status": validation[1] if validation else None,
            "anomalies_found": int(validation[2] or 0) if validation else 0,
            "anomalies_corrected": int(validation[3] or 0) if validation else 0,
            "suggestions": list(validation[4] or [])[:10] if validation else [],
            "as_of": _json_value(validation[5]) if validation else None,
        },
        "reconciliation": {
            "available": bool(reconciliation),
            "status": (
                reconciliation_phase.get("status")
                or reconciliation_phase.get("reconciliation_status")
                or (reconciliation[0] if reconciliation else None)
            ),
            "total_issues": int(reconciliation_phase.get("total_issues") or 0),
            "as_of": _json_value(reconciliation[2]) if reconciliation else None,
        },
    }


def collect_evidence(
    report_id: str,
    user_id: str,
    account: dict[str, Any],
    session_date: date,
    thresholds: AdvisorThresholds,
) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        broker = _broker_evidence(user_id, account["account_id"], session_date)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Advisor broker evidence unavailable (%s)", type(exc).__name__)
        broker = {
            "available": False, "paper_only": True, "daily_pnl": None,
            "daily_pct": None, "drawdown_20_pct": None,
            "consecutive_losing_sessions": 0, "unrealized_pnl": None,
            "gross_exposure": 0.0, "equity": 0.0, "positions": [], "sessions": [],
            "history_available": False, "positions_available": False,
        }
        warnings.append("The paper broker snapshot was unavailable; account-level P&L may be incomplete.")
    db = _database_evidence(
        user_id,
        account["account_id"],
        session_date,
        (broker.get("sessions") or []) if broker.get("history_available") else [],
    )
    broker_session_count = len(broker.get("sessions") or [])
    if broker.get("available") and broker_session_count < 21:
        warnings.append(
            f"Only {broker_session_count} broker session snapshot(s) were available; "
            "the 20-session metrics use the shorter available window."
        )
    if broker.get("available") and not broker.get("positions_available"):
        warnings.append(
            "The broker position list was unavailable; exposure and concentration may be incomplete."
        )
    unsupported_backtest_parameters = db["strategy"].get(
        "unsupported_backtest_parameters"
    ) or []
    if unsupported_backtest_parameters:
        warnings.append(
            "The current paper strategy uses parameters the grid-search backtester "
            "cannot reproduce, so this report will not queue an incomplete comparison."
        )
    equity = _num(broker.get("equity"))
    positions = broker.get("positions") or []
    gross_pct = _num(broker.get("gross_exposure")) / equity * 100 if equity else 0.0
    from engine.autonomy.policy import RiskLimits

    limits = RiskLimits()
    breaches = []
    max_open = limits.max_open_positions
    max_gross_pct = limits.max_gross_exposure_pct * 100
    max_position_pct = limits.max_position_pct * 100
    if len(positions) > max_open:
        breaches.append("open_positions_limit_breached")
    if gross_pct > max_gross_pct:
        breaches.append("gross_exposure_limit_breached")
    if any(_num(position.get("weight_pct")) > max_position_pct for position in positions):
        breaches.append("position_size_limit_breached")
    try:
        from engine.regime import classify_regime_cached, regime_variations
        regime_value = classify_regime_cached(session_date.isoformat())
        preset = regime_variations(
            str(db["strategy"].get("name") or ""), regime_value.state
        )
        regime = {
            "state": regime_value.state,
            "trend": regime_value.trend,
            "vol_percentile": regime_value.vol_percentile,
            "vix": regime_value.vix,
            "realised_vol": regime_value.realised_vol,
            "as_of": regime_value.as_of,
            "preset_raw": preset,
            "preset_display": normalize_parameter_grid(preset),
        }
    except Exception:  # noqa: BLE001
        regime = {"state": "unknown", "as_of": session_date.isoformat()}
        warnings.append("Market regime classification was unavailable.")
    if not db["backtest"].get("available"):
        warnings.append("No exact strategy-slug backtest baseline was found for this paper run.")
    elif db["backtest"].get("sharpe") is None:
        warnings.append("The exact matched backtest did not contain a Sharpe value.")
    if (
        int(db["paper"].get("closed_trades") or 0) >= thresholds.min_closed_trades
        and db["paper"].get("sharpe") is None
    ):
        warnings.append(
            "Closed paper trades were present, but too few contained usable percentage returns to calculate Sharpe."
        )
    if db["paper"].get("trade_scope") != "exact_strategy_slug":
        warnings.append(
            "The current paper run has no exact strategy slug; tracked strategy P&L "
            "therefore includes all AlpaTrade paper trades for this account and window."
        )
    strategy_session_pnl = _num(db["paper"].get("session_realized_pnl"))
    broker_available = bool(broker.get("available"))
    attribution_residual = (
        _num(broker.get("daily_pnl")) - strategy_session_pnl
        if broker_available else None
    )
    if attribution_residual is not None and abs(attribution_residual) >= 0.01:
        warnings.append(
            "Broker daily P&L includes unrealized, manual, or unmatched activity; "
            "the residual is not attributed to the AlpaTrade strategy."
        )
    evidence = {
        "schema_version": 1,
        "report_id": report_id,
        "session_date": session_date.isoformat(),
        "account": {
            "account_id": str(account["account_id"]),
            "account_name": str(account.get("account_name") or "Paper account")[:255],
            "paper_only": True,
        },
        "broker": broker,
        **db,
        "regime": regime,
        "risk": {
            "open_positions": len(positions),
            "gross_exposure_pct": round(gross_pct, 4),
            "max_position_pct": max(
                [_num(position.get("weight_pct")) for position in positions] or [0.0]
            ),
            "limits": {
                "max_open_positions": max_open,
                "max_gross_exposure_pct": max_gross_pct,
                "max_position_pct": max_position_pct,
                "allow_live": False,
            },
            "breaches": breaches,
        },
        "attribution": {
            "broker_daily_pnl": (
                _num(broker.get("daily_pnl")) if broker_available else None
            ),
            "alpatrade_session_realized_pnl": strategy_session_pnl,
            "alpatrade_trade_scope": db["paper"].get("trade_scope"),
            "strategy_slug": db["paper"].get("strategy_slug"),
            "unattributed_residual": (
                round(attribution_residual, 2)
                if attribution_residual is not None else None
            ),
            "residual_may_include": [
                "unrealized_pnl", "manual_trades", "unmatched_trades",
            ],
        },
        "quality": {
            "broker_and_strategy_pnl_are_separate": True,
            "warnings": warnings,
        },
    }
    severity, triggers = classify_evidence(evidence, thresholds)
    evidence["severity"] = severity
    evidence["triggers"] = triggers
    return evidence


async def _deepagent_draft(
    user_id: str, account_id: str, evidence: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[AdvisorDraft, str, str]:
    """Generate structured prose through a locked-down, read-only DeepAgent."""
    from deepagents import create_deep_agent
    from deepagents.profiles import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
    from langchain_core.messages import HumanMessage

    from engine.ai.deepagent_tools import DeepAgentContext, advisor_subagent_spec
    from engine.ai.deepagents import BLOCKED_TOOLS, BlockedToolMiddleware
    from engine.config import build_chat_model, get_settings

    settings = get_settings(user_id)
    model = build_chat_model(settings, streaming=False, temperature=0.2, max_tokens=800)
    actual_name = str(getattr(model, "model_name", None) or getattr(model, "model", None)
                      or settings.model_name)
    harness_provider = "anthropic" if settings.model_provider == "anthropic" else "openai"
    register_harness_profile(
        f"{harness_provider}:{actual_name}",
        HarnessProfile(
            excluded_tools=BLOCKED_TOOLS,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    graph = create_deep_agent(
        model=model,
        tools=[],
        system_prompt=(
            "You coordinate a read-only daily paper-trading review. Delegate the review "
            "to trading-advisor. Use only supplied JSON facts and candidate IDs. Never "
            "invent a metric, parameter, cause, symbol, or action. Every selected candidate "
            "must cite one or more of that candidate's evidence_refs, and any number in its "
            "explanation must occur in those referenced evidence values. Copy the selected "
            "candidate's rationale exactly into explanation; additional claims are rejected. "
            "For review or urgent reports, include every allowed candidate exactly once and "
            "use selection order to rank them. "
            "If no candidates are supplied, return an empty selections list; the application "
            "will supply the deterministic no-change explanation."
        ),
        middleware=[BlockedToolMiddleware()],
        subagents=[advisor_subagent_spec(include_report_tools=False)],
        response_format=AdvisorDraft,
        context_schema=DeepAgentContext,
        checkpointer=None,
        name="alpatrade-daily-advisor",
    )
    context = DeepAgentContext(
        user_id=user_id,
        account_id=account_id,
        thread_id=str(uuid.uuid4()),
        request_message_id=str(uuid.uuid4()),
        response_id=str(uuid.uuid4()),
        auth_type="scheduled",
        request_id=str(uuid.uuid4()),
        current_user_text="Generate a read-only daily paper advisor report.",
    )
    payload = json.dumps({"evidence": evidence, "allowed_candidates": candidates}, default=_json_value)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=payload)]},
        context=context,
        config={"configurable": {"thread_id": f"advisor:{user_id}:{account_id}:{evidence['session_date']}"}},
    )
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if isinstance(structured, dict):
        try:
            structured = AdvisorDraft.model_validate(structured)
        except Exception as exc:  # noqa: BLE001
            raise AdvisorOutputError("structured advisor response was invalid") from exc
    if not isinstance(structured, AdvisorDraft):
        raise AdvisorOutputError("structured advisor response was unavailable")
    return structured, settings.model_provider, actual_name


async def generate_account_report(
    user_id: str,
    account: dict[str, Any],
    session_date: date,
    thresholds: Optional[AdvisorThresholds] = None,
) -> dict[str, Any]:
    thresholds = thresholds or AdvisorThresholds.from_env()
    record = reserve_report(user_id, account["account_id"], session_date)
    if record.get("status") in {"completed", "partial"} and record.get("advisory"):
        return record
    report_id = str(record["report_id"])
    try:
        evidence = await asyncio.to_thread(
            collect_evidence, report_id, user_id, account, session_date, thresholds
        )
        candidates = candidate_actions(evidence, evidence["severity"])
        provider = model_name = None
        try:
            # Retain the attempted provider/model on deterministic fallbacks as
            # well as successful generations. The DeepAgent call may replace
            # ``model_name`` with a self-healed model that actually responded.
            from engine.config import get_settings

            settings = get_settings(user_id)
            provider = settings.model_provider
            model_name = settings.model_name
        except Exception:  # noqa: BLE001
            pass
        draft = None
        status = "completed"
        error_code = None
        try:
            draft, provider, model_name = await _deepagent_draft(
                user_id, account["account_id"], evidence, candidates
            )
        except AdvisorOutputError:
            logger.warning("Scheduled DeepAgent advisor returned invalid structured output")
            status = "partial"
            error_code = "invalid_model_output"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scheduled DeepAgent advisor fallback (%s)", type(exc).__name__)
            status = "partial"
            error_code = "model_unavailable"
        try:
            advisory = finalize_advisory(
                evidence,
                candidates,
                draft,
                thresholds,
                fallback_reason=error_code,
            )
        except ValueError as exc:
            logger.warning("Scheduled DeepAgent advisor output rejected (%s)", str(exc))
            status = "partial"
            error_code = "invalid_model_output"
            draft = None
            advisory = finalize_advisory(
                evidence,
                candidates,
                None,
                thresholds,
                fallback_reason=error_code,
            )
        await asyncio.to_thread(
            save_report,
            report_id,
            status=status,
            severity=evidence["severity"],
            evidence=evidence,
            advisory=advisory,
            provider=provider,
            model_name=model_name,
            error_code=error_code,
        )
        return get_report_for_user(report_id, user_id) or {
            **record, "status": status, "severity": evidence["severity"],
            "evidence": evidence, "advisory": advisory,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Advisor report failed (%s)", type(exc).__name__)
        await asyncio.to_thread(fail_report, report_id)
        return get_report_for_user(report_id, user_id) or {**record, "status": "failed"}


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def render_advisor_email(user: dict[str, Any], reports: list[dict[str, Any]]) -> str:
    sections = []
    for report in reports:
        advisory = report.get("advisory") or {}
        evidence = report.get("evidence") or {}
        account = evidence.get("account") or {}
        broker = evidence.get("broker") or {}
        paper = evidence.get("paper") or {}
        tone = "#b33b32" if report.get("severity") in {"review", "urgent"} else "#1F5D43"
        broker_day = (
            f"Broker day P&amp;L ${_num(broker.get('daily_pnl')):+,.2f} "
            f"({_num(broker.get('daily_pct')):+.2f}%)"
            if broker.get("available") else "Broker day P&amp;L unavailable"
        )
        recs = advisory.get("recommendations") or []
        driver_html = "".join(
            f"<li><b>{_escape(item.get('title') or 'Evidence')}</b> — "
            f"{_escape(item.get('detail') or '')}</li>"
            for item in advisory.get("drivers") or []
        )
        rec_html = "".join(
            f"<li><b>{_escape(item.get('title'))}</b> — {_escape(item.get('explanation') or item.get('rationale'))}"
            " <i>(approval required)</i></li>"
            for item in recs
        )
        if not rec_html:
            rec_html = f"<li>{_escape(advisory.get('why_no_change') or 'No parameter change recommended.')}</li>"
        warnings = "".join(f"<li>{_escape(item)}</li>" for item in advisory.get("data_warnings") or [])
        parameter_guard = ""
        if recs and advisory.get("why_no_change"):
            parameter_guard = (
                f"<p><b>Parameter-change guard:</b> "
                f"{_escape(advisory.get('why_no_change'))}</p>"
            )
        sections.append(f"""
        <section style="border:1px solid #DDD9CB;border-radius:8px;padding:14px;margin:12px 0">
          <h3 style="margin:0 0 6px">{_escape(account.get('account_name') or 'Paper account')}</h3>
          <p style="margin:4px 0;color:#7A867E;font-size:12px">Session {_escape(report.get('session_date'))}
             · evidence {_escape(paper.get('window_start') or 'n/a')} to
             {_escape(paper.get('window_end') or report.get('session_date'))}</p>
          <p style="margin:4px 0;color:{tone}"><b>{_escape(str(report.get('severity','')).replace('_',' ').title())}</b>
             · status {_escape(report.get('status') or 'unknown')}
             · {broker_day}</p>
          <p>{_escape(advisory.get('summary'))}</p>
          <p style="color:#7A867E;font-size:12px">{_escape(advisory.get('generation_note'))}</p>
          <h4>Performance drivers and evidence</h4>
          <ul>{driver_html or '<li>No detailed drivers were available.</li>'}</ul>
          <h4>What should change</h4><ul>{rec_html}</ul>
          {parameter_guard}
          {f'<h4>Data notes</h4><ul>{warnings}</ul>' if warnings else ''}
        </section>""")
    day = reports[0].get("session_date") if reports else ""
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;color:#14231B;max-width:760px">
      <h2>AlpaTrade Daily Paper Advisor · {_escape(day)}</h2>
      <p>{_escape(user.get('display_name') or user.get('email') or '')}, here is the consolidated
      post-close review for your linked paper accounts.</p>
      {''.join(sections) or '<p>No paper-account report was available.</p>'}
      <p style="color:#7A867E;font-size:12px">Paper trading is simulated. No strategy was changed
      and no order was placed. Recommendations require explicit approval and are not live investment advice.</p>
    </div>"""


def _reserve_delivery(
    user_id: str, session_date: date, recipient: str, report_ids: list[str]
) -> dict[str, Any]:
    with DatabasePool().get_session() as session:
        row = session.execute(text("""
            INSERT INTO alpatrade.advisor_deliveries AS existing
                (user_id, session_date, channel, recipient, report_ids, status)
            VALUES (:uid, :day, 'email', :recipient, :reports, 'pending')
            ON CONFLICT (user_id, session_date, channel, recipient) DO UPDATE
            SET report_ids = CASE
                    WHEN existing.status IN ('sent', 'sending', 'unknown')
                    THEN existing.report_ids
                    ELSE EXCLUDED.report_ids
                END,
                updated_at = CASE
                    WHEN existing.status IN ('sent', 'sending', 'unknown')
                    THEN existing.updated_at
                    ELSE NOW()
                END
            RETURNING delivery_id, status, attempts, report_ids, sent_at
        """), {
            "uid": user_id, "day": session_date, "recipient": recipient,
            "reports": json.dumps(report_ids),
        }).fetchone()
    return {
        "delivery_id": str(row[0]), "status": row[1], "attempts": int(row[2] or 0),
        "report_ids": row[3] or [], "sent_at": row[4],
    }


def _set_delivery(delivery_id: str, status: str, error_code: Optional[str] = None) -> None:
    with DatabasePool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.advisor_deliveries
            SET status = :status,
                attempts = attempts + CASE WHEN :status = 'sending' THEN 1 ELSE 0 END,
                error_code = :error_code, updated_at = NOW(),
                sent_at = CASE WHEN :status = 'sent' THEN NOW() ELSE sent_at END
            WHERE delivery_id = :did
        """), {"did": delivery_id, "status": status, "error_code": error_code})


def _claim_delivery(delivery_id: str) -> bool:
    """Atomically acquire the right to call the external email provider once."""
    with DatabasePool().get_session() as session:
        changed = session.execute(text("""
            UPDATE alpatrade.advisor_deliveries
            SET status = 'sending', attempts = attempts + 1,
                error_code = NULL, updated_at = NOW()
            WHERE delivery_id = :did
              AND status IN ('pending', 'failed', 'disabled')
        """), {"did": delivery_id}).rowcount
    return bool(changed)


async def run_user_batch(
    user_id: str,
    session_date: date,
    account_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    from engine.auth import get_user_accounts, get_user_by_id

    user = await asyncio.to_thread(get_user_by_id, user_id)
    if not user:
        return {"status": "skipped", "reason": "inactive_user"}
    if account_ids is None:
        accounts = await asyncio.to_thread(usable_paper_accounts, user_id)
    else:
        requested = {str(account_id) for account_id in account_ids}
        owned = await asyncio.to_thread(get_user_accounts, user_id)
        accounts = [
            account for account in owned
            if str(account.get("account_id")) in requested
        ]
    if not accounts:
        return {"status": "skipped", "reason": "no_usable_paper_account"}
    reports = []
    for account in accounts:
        reports.append(await generate_account_report(user_id, account, session_date))
    usable = [report for report in reports if report.get("status") in {"completed", "partial"}]
    failed = [report for report in reports if report.get("status") == "failed"]
    if not usable:
        return {"status": "failed", "reports": reports}
    if failed:
        # Keep the user-level delivery atomic: retry the failed account report
        # before composing the one consolidated email. Otherwise the first send
        # could permanently omit an account because delivery itself is deduped.
        return {
            "status": "partial",
            "reason": "account_report_failed",
            "reports": reports,
        }
    recipient = str(user.get("email") or "")
    delivery = await asyncio.to_thread(
        _reserve_delivery, user_id, session_date, recipient,
        [str(report["report_id"]) for report in usable],
    )
    if delivery["status"] == "sent":
        return {"status": "completed", "reports": usable, "delivery": delivery}
    if delivery["status"] in {"sending", "unknown"}:
        # A worker may have died after Postmark accepted the message but before
        # the sent timestamp committed. Do not risk a duplicate consolidated email.
        if delivery["status"] == "sending":
            await asyncio.to_thread(
                _set_delivery, delivery["delivery_id"], "unknown",
                "delivery_outcome_unknown",
            )
            delivery["status"] = "unknown"
        return {"status": "completed", "reports": usable, "delivery": delivery}
    if os.getenv("ADVISOR_EMAIL_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        await asyncio.to_thread(_set_delivery, delivery["delivery_id"], "disabled")
        delivery["status"] = "disabled"
        return {"status": "completed", "reports": usable, "delivery": delivery}
    claimed = await asyncio.to_thread(_claim_delivery, delivery["delivery_id"])
    if not claimed:
        # Another worker already owns the unique delivery row. It may be inside
        # the external provider call, so do not convert it to unknown or send a
        # duplicate from this process.
        delivery["status"] = "sending"
        return {"status": "completed", "reports": usable, "delivery": delivery}
    delivery["status"] = "sending"
    delivery["attempts"] = int(delivery.get("attempts") or 0) + 1
    body = render_advisor_email(user, usable)
    subject = f"AlpaTrade Daily Paper Advisor — {session_date.isoformat()}"
    try:
        from utils.email_util import send_email_to
        sent = await asyncio.to_thread(send_email_to, recipient, subject, body)
    except Exception:  # noqa: BLE001
        sent = False
    final_status = "sent" if sent else "failed"
    await asyncio.to_thread(
        _set_delivery, delivery["delivery_id"], final_status,
        None if sent else "delivery_failed",
    )
    delivery["status"] = final_status
    return {"status": "completed" if sent else "partial", "reports": usable, "delivery": delivery}


def run_user_batch_sync(
    user_id: str,
    session_date: str | date,
    account_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    parsed = date.fromisoformat(session_date) if isinstance(session_date, str) else session_date
    return asyncio.run(run_user_batch(user_id, parsed, account_ids=account_ids))


def recommendation_config(
    report_id: str,
    recommendation_id: str,
    user_id: str,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    report = get_report_for_user(report_id, user_id)
    if not report:
        raise ValueError("advisor report not found")
    if account_id and report.get("account_id") != str(account_id):
        raise ValueError("advisor report not found")
    for recommendation in (report.get("advisory") or {}).get("recommendations") or []:
        if recommendation.get("candidate_id") == recommendation_id:
            if recommendation.get("kind") != "backtest" or not recommendation.get("test_config"):
                raise ValueError("recommendation is not a backtest action")
            config = dict(recommendation["test_config"])
            config["_advisor_account_id"] = str(report["account_id"])
            return config
    raise ValueError("advisor recommendation not found")


def scheduler_dedupe_key(user_id: str, session_date: date) -> str:
    raw = f"daily-advisor:{user_id}:{session_date.isoformat()}"
    return "advisor:" + hashlib.sha256(raw.encode()).hexdigest()[:48]


def market_session_close(session_date: date) -> Optional[datetime]:
    """Return Alpaca's actual close for a trading date, or None on holidays/errors."""
    from engine.auth import get_alpaca_keys, get_user_accounts
    from engine.brokers.alpaca import AlpacaAPI

    for user in active_advisor_users():
        for account in get_user_accounts(user["user_id"]):
            try:
                keys = get_alpaca_keys(user["user_id"], account["account_id"])
                if not keys:
                    continue
                calendar = AlpacaAPI(keys[0], keys[1], paper=True).get_calendar(
                    session_date.isoformat(), session_date.isoformat()
                )
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(calendar, list) or not calendar:
                continue
            close_value = calendar[0].get("close")
            if isinstance(close_value, datetime):
                close_dt = close_value
            elif close_value:
                close_dt = datetime.fromisoformat(str(close_value).replace("Z", "+00:00"))
            else:
                continue
            if close_dt.tzinfo is None:
                close_dt = close_dt.replace(tzinfo=EASTERN)
            return close_dt.astimezone(timezone.utc)
    return None


__all__ = [
    "AdvisorDraft",
    "AdvisorThresholds",
    "canonical_backtest_grid",
    "candidate_actions",
    "classify_evidence",
    "collect_evidence",
    "consecutive_losing_sessions",
    "finalize_advisory",
    "generate_account_report",
    "get_report_for_user",
    "list_reports_for_user",
    "market_session_close",
    "max_drawdown_pct",
    "max_losing_streak",
    "normalize_parameter",
    "normalize_parameter_grid",
    "normalize_parameters",
    "recommendation_config",
    "render_advisor_email",
    "run_user_batch",
    "run_user_batch_sync",
    "scheduler_dedupe_key",
    "select_latest_matching_backtest",
    "stored_backtest_candidate_grid",
    "usable_paper_accounts",
]

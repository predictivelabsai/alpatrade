"""Strict validation shared by realtime ingestion and historical backfill."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

REQUIRED_TEXT_FIELDS = ("company", "language", "title_en", "content_en", "reason")
REQUIRED_FIELDS = (*REQUIRED_TEXT_FIELDS, "predicted_side", "predicted_move")
INVALID_TEXT = {"", "nan", "n/a", "na", "none", "null", "error", "error in summarization"}
VALID_SIDES = {"UP", "DOWN", "NEUTRAL"}
VALID_COMPANY_TYPES = {"public", "private"}


def invalid_text(value: Any) -> bool:
    return value is None or str(value).strip().lower() in INVALID_TEXT


def finite_move(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_company_type(value: Any, *, ticker: Any = None,
                           yf_ticker: Any = None) -> str | None:
    """Normalize XAI output, using a stored listing symbol as safe evidence."""
    normalized = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "public company": "public", "publicly traded": "public",
        "listed": "public", "listed company": "public",
        "private company": "private", "privately held": "private",
    }
    normalized = aliases.get(normalized, normalized)
    if not invalid_text(ticker) or not invalid_text(yf_ticker):
        return "public"
    if normalized in VALID_COMPANY_TYPES:
        return normalized
    return None


def missing_enrichment_fields(row: Mapping[str, Any]) -> list[str]:
    missing = [name for name in REQUIRED_TEXT_FIELDS if invalid_text(row.get(name))]
    if normalize_company_type(row.get("company_type"), ticker=row.get("ticker"),
                              yf_ticker=row.get("yf_ticker")) is None:
        missing.append("company_type")
    if str(row.get("predicted_side") or "").strip().upper() not in VALID_SIDES:
        missing.append("predicted_side")
    if finite_move(row.get("predicted_move")) is None:
        missing.append("predicted_move")
    return missing


def normalized_enrichment(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["predicted_side"] = str(result.get("predicted_side") or "").strip().upper()
    result["predicted_move"] = finite_move(result.get("predicted_move"))
    result["company_type"] = normalize_company_type(
        result.get("company_type"), ticker=result.get("ticker"),
        yf_ticker=result.get("yf_ticker"),
    )
    return result

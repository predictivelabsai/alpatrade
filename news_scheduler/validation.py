"""Strict validation shared by realtime ingestion and historical backfill."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

REQUIRED_TEXT_FIELDS = ("company", "language", "title_en", "content_en", "reason")
REQUIRED_FIELDS = (*REQUIRED_TEXT_FIELDS, "predicted_side", "predicted_move")
INVALID_TEXT = {"", "nan", "n/a", "na", "none", "null", "error", "error in summarization"}
VALID_SIDES = {"UP", "DOWN", "NEUTRAL"}


def invalid_text(value: Any) -> bool:
    return value is None or str(value).strip().lower() in INVALID_TEXT


def finite_move(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def missing_enrichment_fields(row: Mapping[str, Any]) -> list[str]:
    missing = [name for name in REQUIRED_TEXT_FIELDS if invalid_text(row.get(name))]
    if str(row.get("predicted_side") or "").strip().upper() not in VALID_SIDES:
        missing.append("predicted_side")
    if finite_move(row.get("predicted_move")) is None:
        missing.append("predicted_move")
    return missing


def normalized_enrichment(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["predicted_side"] = str(result.get("predicted_side") or "").strip().upper()
    result["predicted_move"] = finite_move(result.get("predicted_move"))
    return result

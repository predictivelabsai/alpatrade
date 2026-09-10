"""Validation for news rows before they are persisted."""

import math

import pandas as pd


REQUIRED_TEXT_COLUMNS = (
    "company",
    "language",
    "title_en",
    "content_en",
    "reason",
)
INVALID_TEXT_VALUES = {"", "nan", "n/a", "none", "error in summarization"}
VALID_PREDICTED_SIDES = {"UP", "DOWN", "NEUTRAL"}


def missing_enrichment_fields(row):
    """Return fields that are not safe to save for a fully enriched news row."""
    missing = []
    for column in REQUIRED_TEXT_COLUMNS:
        value = row.get(column)
        if value is None or pd.isna(value) or str(value).strip().lower() in INVALID_TEXT_VALUES:
            missing.append(column)

    side = row.get("predicted_side")
    if side is None or pd.isna(side) or str(side).strip().upper() not in VALID_PREDICTED_SIDES:
        missing.append("predicted_side")

    move = row.get("predicted_move")
    try:
        if move is None or pd.isna(move) or not math.isfinite(float(move)):
            missing.append("predicted_move")
    except (TypeError, ValueError):
        missing.append("predicted_move")

    return missing


def partition_fully_enriched(df):
    """Split a DataFrame into rows safe to persist and incomplete rows with reasons."""
    if df.empty:
        return df.copy(), []

    valid_indices = []
    rejected = []
    for index, row in df.iterrows():
        missing = missing_enrichment_fields(row)
        if missing:
            rejected.append({
                "index": index,
                "link": row.get("link"),
                "missing": missing,
            })
        else:
            valid_indices.append(index)
    return df.loc[valid_indices].copy(), rejected

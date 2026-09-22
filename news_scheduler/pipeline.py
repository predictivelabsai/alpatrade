"""One enrichment path shared by realtime articles and backfill rows."""
from __future__ import annotations

from typing import Any

from news_scheduler.events import normalize_event
from news_scheduler.models import MissingEventModel, ModelRegistry, predict
from news_scheduler.validation import (
    VALID_SIDES,
    finite_move,
    invalid_text,
    missing_enrichment_fields,
    normalized_enrichment,
)


class IncompleteArticle(RuntimeError):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__("incomplete enrichment: " + ", ".join(fields))


class NewsPipeline:
    def __init__(self, models: ModelRegistry, xai):
        self.models, self.xai = models, xai

    def enrich(self, article: dict[str, Any]) -> dict[str, Any]:
        allowed = self.models.available_events() if hasattr(self.models, "available_events") else ()
        row = (self.xai.metadata(dict(article), allowed_events=allowed)
               if allowed else self.xai.metadata(dict(article)))
        row["event_standardized"] = normalize_event(row.get("event"))
        if allowed and row["event_standardized"] not in allowed:
            raise MissingEventModel("XAI event is outside the trained model registry")
        row = predict(row, self.models.for_event(row["event_standardized"]))
        row["reason"] = self.xai.reason(row)
        row = normalized_enrichment(row)
        missing = missing_enrichment_fields(row)
        if missing:
            raise IncompleteArticle(missing)
        return row

    def enrich_best_effort(self, article: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
        """Run every enrichment stage and retain successful fields.

        This mirrors the original Finespresso scheduler: a failure in one stage
        does not discard the downloaded article or prevent later stages from
        being attempted. Exceptions are returned as sanitized type names so the
        worker can persist a retryable row without logging article content.
        """
        row = dict(article)
        original_ticker = row.get("ticker")
        original_yf_ticker = row.get("yf_ticker")
        issues: list[str] = []
        try:
            allowed = self.models.available_events() if hasattr(self.models, "available_events") else ()
            metadata = (self.xai.metadata(dict(row), allowed_events=allowed)
                        if allowed else self.xai.metadata(dict(row)))
            row.update(metadata or {})
            # Never let an empty model response erase deterministic listing
            # evidence already stored by a publisher or an earlier pass.
            if invalid_text(row.get("ticker")) and not invalid_text(original_ticker):
                row["ticker"] = original_ticker
            if invalid_text(row.get("yf_ticker")) and not invalid_text(original_yf_ticker):
                row["yf_ticker"] = original_yf_ticker
        except Exception as exc:  # each stage is independent by design
            issues.append(f"metadata:{type(exc).__name__}")

        row["event_standardized"] = normalize_event(row.get("event"))
        has_prediction = (
            str(row.get("predicted_side") or "").strip().upper() in VALID_SIDES
            and finite_move(row.get("predicted_move")) is not None
        )
        if not has_prediction:
            try:
                row = predict(row, self.models.for_event(row["event_standardized"]))
            except Exception as exc:
                issues.append(f"prediction:{type(exc).__name__}")

        if invalid_text(row.get("reason")):
            try:
                row["reason"] = self.xai.reason(row)
            except Exception as exc:
                issues.append(f"reason:{type(exc).__name__}")

        row = normalized_enrichment(row)
        return row, missing_enrichment_fields(row), issues

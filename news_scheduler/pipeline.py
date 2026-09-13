"""One enrichment path shared by realtime articles and backfill rows."""
from __future__ import annotations

from typing import Any

from news_scheduler.events import normalize_event
from news_scheduler.models import MissingEventModel, ModelRegistry, predict
from news_scheduler.validation import missing_enrichment_fields, normalized_enrichment


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
        issues: list[str] = []
        try:
            allowed = self.models.available_events() if hasattr(self.models, "available_events") else ()
            metadata = (self.xai.metadata(dict(row), allowed_events=allowed)
                        if allowed else self.xai.metadata(dict(row)))
            row.update(metadata or {})
        except Exception as exc:  # each stage is independent by design
            issues.append(f"metadata:{type(exc).__name__}")

        row["event_standardized"] = normalize_event(row.get("event"))
        try:
            row = predict(row, self.models.for_event(row["event_standardized"]))
        except Exception as exc:
            issues.append(f"prediction:{type(exc).__name__}")

        try:
            row["reason"] = self.xai.reason(row)
        except Exception as exc:
            issues.append(f"reason:{type(exc).__name__}")

        row = normalized_enrichment(row)
        return row, missing_enrichment_fields(row), issues

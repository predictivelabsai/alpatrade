"""One enrichment path shared by realtime articles and backfill rows."""
from __future__ import annotations

from typing import Any

from engine.news_pipeline.events import normalize_event
from engine.news_pipeline.models import ModelRegistry, predict
from engine.news_pipeline.validation import missing_enrichment_fields, normalized_enrichment


class IncompleteArticle(RuntimeError):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__("incomplete enrichment: " + ", ".join(fields))


class NewsPipeline:
    def __init__(self, models: ModelRegistry, xai):
        self.models, self.xai = models, xai

    def enrich(self, article: dict[str, Any]) -> dict[str, Any]:
        row = self.xai.metadata(dict(article))
        row["event_standardized"] = normalize_event(row.get("event"))
        row = predict(row, self.models.for_event(row["event_standardized"]))
        row["reason"] = self.xai.reason(row)
        row = normalized_enrichment(row)
        missing = missing_enrichment_fields(row)
        if missing:
            raise IncompleteArticle(missing)
        return row

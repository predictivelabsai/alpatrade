"""DB-free coverage for public/private news classification and filtering."""
from pathlib import Path

from fastcore.xml import to_xml

from news_scheduler.validation import (
    missing_enrichment_fields,
    normalize_company_type,
    normalized_enrichment,
)


def test_company_type_normalizes_xai_variants_and_ticker_evidence():
    assert normalize_company_type("Publicly Traded") == "public"
    assert normalize_company_type("privately-held") == "private"
    assert normalize_company_type(None, ticker="AAPL") == "public"
    assert normalize_company_type("unknown") is None


def test_missing_company_type_remains_retryable_without_listing_evidence():
    row = {
        "company": "Example", "language": "en", "title_en": "Title",
        "content_en": "Body", "reason": "Reason", "predicted_side": "UP",
        "predicted_move": 1.2,
    }
    assert "company_type" in missing_enrichment_fields(row)
    assert normalized_enrichment({**row, "yf_ticker": "EX"})["company_type"] == "public"


def test_xai_metadata_requests_exact_company_type():
    source = (Path(__file__).parents[1] / "news_scheduler" / "xai.py").read_text()
    assert "company_type MUST be exactly public" in source
    assert "or private for a privately held issuer" in source


def test_company_type_only_backfill_reuses_existing_prediction_and_reason(monkeypatch):
    from unittest.mock import MagicMock
    from news_scheduler.pipeline import NewsPipeline

    models = MagicMock()
    models.available_events.return_value = ("earnings",)
    xai = MagicMock()
    existing = {
        "company": "Apple", "ticker": "AAPL", "language": "en",
        "title_en": "Title", "content_en": "Body", "event": "earnings",
        "predicted_side": "UP", "predicted_move": 1.2,
        "reason": "Existing model rationale",
    }
    xai.metadata.return_value = {**existing, "company_type": "public"}
    monkeypatch.setattr(
        "news_scheduler.pipeline.predict",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prediction reran")),
    )

    row, missing, issues = NewsPipeline(models, xai).enrich_best_effort(existing)

    assert row["company_type"] == "public"
    assert missing == [] and issues == []
    xai.reason.assert_not_called()
    models.for_event.assert_not_called()


def test_existing_ticker_overrides_empty_xai_ticker_and_private_guess(monkeypatch):
    from unittest.mock import MagicMock
    from news_scheduler.pipeline import NewsPipeline

    models = MagicMock()
    models.available_events.return_value = ("earnings",)
    xai = MagicMock()
    existing = {
        "company": "Listed Co", "ticker": "LIST", "language": "en",
        "title_en": "Title", "content_en": "Body", "event": "earnings",
        "predicted_side": "UP", "predicted_move": 1.2, "reason": "Reason",
    }
    xai.metadata.return_value = {
        **existing, "ticker": "", "company_type": "private",
    }
    row, missing, issues = NewsPipeline(models, xai).enrich_best_effort(existing)

    assert row["ticker"] == "LIST"
    assert row["company_type"] == "public"
    assert missing == [] and issues == []


def test_migration_adds_constrained_indexed_company_type():
    sql = (Path(__file__).parents[1] / "sql" / "34_news_company_type.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS company_type TEXT" in sql
    assert "company_type IN ('public', 'private')" in sql
    assert "idx_news_company_type_id" in sql


def test_repository_backfill_and_writes_include_company_type():
    source = (Path(__file__).parents[1] / "news_scheduler" / "repository.py").read_text()
    assert "company_type IS NULL" in source
    assert "company_type=COALESCE(:company_type,company_type)" in source
    assert ":company,:company_type,:language" in source
    assert "def incomplete_company_type" in source
    assert "def remaining_company_type" in source


def test_company_backfill_has_independent_checkpoint_and_targeted_query():
    from unittest.mock import MagicMock
    from news_scheduler.worker import Worker, parse_args

    repository = MagicMock()
    repository.checkpoint.return_value = {
        "last_processed_news_id": 0, "processed_count": 0, "failed_count": 0,
    }
    repository.incomplete_company_type.return_value = []
    repository.remaining_company_type.return_value = 0
    worker = Worker("company-backfill", 5, 1, 0, 1, repository=repository,
                    pipeline=MagicMock(), publishers=MagicMock())

    assert worker.job_name == "news-company-backfill"
    assert worker._backfill_cycle() is False
    repository.incomplete_company_type.assert_called_once()
    repository.incomplete.assert_not_called()
    assert parse_args(["--mode", "company-backfill"]).mode == "company-backfill"


def test_scheduler_renders_filter_type_column_and_preserves_pagination(monkeypatch):
    from engine.web import ph_news_scheduler as page

    monkeypatch.setattr(page, "_load_dashboard", lambda *args, **kwargs: {
        "jobs": [], "enrichment": {}, "latest": [{
            "id": 1, "company": "Example", "ticker": "EX",
            "company_type": "private", "publisher": "test", "event": "launch",
            "title_en": "Launch", "predicted_side": "UP", "predicted_move": 1.0,
        }], "total_articles": 6, "sides": [], "events": [], "companies": [],
        "company_types": [{"label": "private", "count": 1}],
        "company_type": "private", "publishers": [], "activity": [],
    })
    html = to_xml(page._dashboard({"email": "user@example.com"}, 1, "private"))
    assert "Public companies" in html and "Private companies" in html
    assert "Filter by public or private company" in html
    assert ">Type<" in html and ">Private<" in html
    assert "company_type=private" in html

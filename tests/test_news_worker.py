from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from engine.news_pipeline.events import normalize_event
from engine.news_pipeline.models import EventModels, MissingEventModel, ModelRegistry
from engine.news_pipeline.pipeline import IncompleteArticle, NewsPipeline
from engine.news_pipeline.repository import NewsRepository
from engine.news_pipeline.validation import finite_move, missing_enrichment_fields
from engine.news_pipeline.worker import Worker


VALID = {"company": "Apple", "language": "en", "title_en": "Title", "content_en": "Body",
         "predicted_side": "UP", "predicted_move": 1.2, "reason": "Model rationale"}


@pytest.mark.parametrize("value", [None, "", "NaN", "N/A", "Error in summarization"])
def test_missing_value_and_placeholder_validation(value):
    row = {**VALID, "reason": value}
    assert "reason" in missing_enrichment_fields(row)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "Infinity", "nope"])
def test_prediction_move_must_be_finite(value):
    assert finite_move(value) is None
    assert "predicted_move" in missing_enrichment_fields({**VALID, "predicted_move": value})


def test_event_name_normalization_matches_finespresso_registry():
    assert normalize_event("press_releases") == "press_release"
    assert normalize_event("Mergers Acquisitions") == "merger_acquisition"
    assert normalize_event(None) == "no_event"


def test_model_registry_selects_classifier_and_regressor_per_event():
    registry = ModelRegistry(MagicMock())
    registry.load = MagicMock(side_effect=lambda event, kind: {"model_id": f"{event}-{kind}"})
    models = registry.for_event("press_releases")
    assert models.classifier["model_id"] == "press_release-classifier"
    assert models.regressor["model_id"] == "press_release-regressor"
    assert registry.load.call_args_list[0].args == ("press_release", "classifier")
    assert registry.load.call_args_list[1].args == ("press_release", "regressor")


def test_missing_model_is_not_silently_replaced():
    registry = ModelRegistry(MagicMock())
    registry._model_id = MagicMock(side_effect=MissingEventModel("missing classifier"))
    with pytest.raises(MissingEventModel):
        registry.load("earnings", "classifier")


class FakeXAI:
    def metadata(self, row):
        return {**row, "company": "Apple", "language": "en", "title_en": row["title"],
                "content_en": row["content"], "event": "earnings"}

    def reason(self, row):
        return "Earnings information supports the event model output."


class FakeModels:
    def for_event(self, event):
        return EventModels(event, {}, {})


def test_realtime_pipeline_returns_only_fully_enriched(monkeypatch):
    monkeypatch.setattr("engine.news_pipeline.pipeline.predict", lambda row, models: {
        **row, "predicted_side": "UP", "predicted_move": 2.5})
    row = NewsPipeline(FakeModels(), FakeXAI()).enrich({"title": "Results", "content": "Revenue rose"})
    assert missing_enrichment_fields(row) == []


def test_incomplete_article_remains_retryable(monkeypatch):
    monkeypatch.setattr("engine.news_pipeline.pipeline.predict", lambda row, models: {
        **row, "predicted_side": "UP", "predicted_move": 2.5})
    xai = FakeXAI()
    xai.reason = lambda row: "N/A"
    with pytest.raises(IncompleteArticle):
        NewsPipeline(FakeModels(), xai).enrich({"title": "Results", "content": "Revenue rose"})


class FakeRepo:
    def __init__(self, acquired=True):
        self.acquired, self.saved, self.inserted, self.updates = acquired, 0, 0, []
        self.state = {"last_processed_news_id": 4, "processed_count": 2, "failed_count": 0}

    def checkpoint(self, *args): return dict(self.state)
    @contextmanager
    def lock(self, *args): yield self.acquired
    def incomplete(self, after, limit, shard, count): return []
    def update_checkpoint(self, *args, **values): self.state.update(values); self.updates.append(values)


class RealtimeRepo(FakeRepo):
    def insert_enriched(self, row):
        self.inserted += 1
        return 99


def test_realtime_worker_inserts_fully_enriched_article():
    repo = RealtimeRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [{"title": "News"}]
    pipeline = MagicMock()
    pipeline.enrich.return_value = dict(VALID)
    worker = Worker("realtime", 5, 60, 0, 1, repository=repo, pipeline=pipeline, publishers=publishers)
    assert worker._realtime_cycle() is True
    assert repo.inserted == 1 and repo.state["last_inserted_news_id"] == 99


def test_realtime_worker_does_not_insert_incomplete_article():
    repo = RealtimeRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [{"title": "News"}]
    pipeline = MagicMock()
    pipeline.enrich.side_effect = IncompleteArticle(["reason"])
    worker = Worker("realtime", 5, 60, 0, 1, repository=repo, pipeline=pipeline, publishers=publishers)
    worker._realtime_cycle()
    assert repo.inserted == 0 and repo.state["failed_count"] == 1


def test_durable_checkpoint_resume_uses_saved_cursor():
    repo = FakeRepo()
    worker = Worker("backfill", 10, 1, 0, 2, repository=repo, pipeline=MagicMock(), publishers=MagicMock())
    assert worker._backfill_cycle() is False
    assert repo.state["last_processed_news_id"] == 4


def test_duplicate_worker_lock_returns_without_work():
    worker = Worker("backfill", 10, 1, 0, 1, repository=FakeRepo(False), pipeline=MagicMock(), publishers=MagicMock())
    assert worker.run() == 2


def test_shards_use_disjoint_modulo_predicate():
    assert NewsRepository.lock_key("news-backfill", 0) != NewsRepository.lock_key("news-backfill", 1)
    source = open("engine/news_pipeline/repository.py", encoding="utf-8").read()
    assert "mod(id,:count)=:shard" in source and "event='press_releases'" in source


def test_realtime_insert_is_idempotent_at_repository_contract():
    source = open("engine/news_pipeline/repository.py", encoding="utf-8").read()
    assert "WHERE NOT EXISTS" in source
    assert "link=:link AND publisher=:publisher" in source


def test_migration_contains_durable_checkpoint_and_unique_shard_key():
    sql = open("sql/31_news_worker_jobs.sql", encoding="utf-8").read()
    assert "PRIMARY KEY (job_name, shard_index, shard_count)" in sql
    assert "last_processed_news_id" in sql and "failed_count" in sql


def test_existing_press_release_query_returns_enriched_fields(monkeypatch):
    import engine.publicmarkets.news as news
    db_row = ("English title", "https://example.test/1", "AAPL", "AAPL", "Apple", None,
              "earnings", "Publisher", "summary", "UP", 1.25, "en", "XAI reason")
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [db_row]
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    pool = MagicMock()
    pool.get_session.return_value = context
    monkeypatch.setattr(news, "DatabasePool", lambda: pool)
    result = news.search_news(company="Apple", event="earn", predicted_side="UP",
                              date_from="2026-01-01", date_to="2026-12-31")
    assert result[0]["reason"] == "XAI reason"
    assert result[0]["predicted_move"] == 1.25
    statement = str(session.execute.call_args.args[0])
    assert "company ILIKE" in statement and "published_date >=" in statement


def test_monitoring_status_calculates_completion(monkeypatch):
    import engine.publicmarkets.observability as monitoring
    session = MagicMock()
    session.execute.side_effect = [MagicMock(scalar=lambda: 100), MagicMock(scalar=lambda: 25),
                                   MagicMock(mappings=lambda: MagicMock(all=lambda: [{
                                       "job_name": "news-backfill", "status": "running"}] ))]
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    pool = MagicMock()
    pool.get_session.return_value = context
    monkeypatch.setattr(monitoring, "DatabasePool", lambda: pool)
    row = monitoring.news_worker_snapshot()[0]
    assert row["mode"] == "backfill" and row["completion_percentage"] == 75.0

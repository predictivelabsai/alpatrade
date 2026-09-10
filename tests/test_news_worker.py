from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from news_scheduler.events import normalize_event
from news_scheduler.models import EventModels, MissingEventModel, ModelRegistry
from news_scheduler.pipeline import IncompleteArticle, NewsPipeline
from news_scheduler.publishers import FinespressoPublishers, finespresso_feed_inventory
from news_scheduler.repository import NewsRepository
from news_scheduler.validation import finite_move, missing_enrichment_fields
from news_scheduler.worker import Worker


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


def test_model_loader_accepts_postgres_hex_encoded_artifact():
    import pickle
    value = {"working": True}
    encoded = b"x" + pickle.dumps(value).hex().encode("ascii")
    assert ModelRegistry._load(encoded) == value


def test_available_events_requires_both_event_models():
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value.all.return_value = ["earnings", "annual_events"]
    assert ModelRegistry(engine).available_events() == ("earnings", "annual_events")


def test_pipeline_constrains_xai_to_model_backed_events(monkeypatch):
    models = FakeModels()
    models.available_events = lambda: ("earnings",)
    xai = MagicMock()
    xai.metadata.return_value = {"title": "T", "content": "C", "company": "A",
                                 "language": "en", "title_en": "T", "content_en": "C",
                                 "event": "unknown_event"}
    with pytest.raises(MissingEventModel):
        NewsPipeline(models, xai).enrich({"title": "T", "content": "C"})
    xai.metadata.assert_called_once_with({"title": "T", "content": "C"},
                                         allowed_events=("earnings",))


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
    monkeypatch.setattr("news_scheduler.pipeline.predict", lambda row, models: {
        **row, "predicted_side": "UP", "predicted_move": 2.5})
    row = NewsPipeline(FakeModels(), FakeXAI()).enrich({"title": "Results", "content": "Revenue rose"})
    assert missing_enrichment_fields(row) == []


def test_incomplete_article_remains_retryable(monkeypatch):
    monkeypatch.setattr("news_scheduler.pipeline.predict", lambda row, models: {
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


def test_finespresso_inventory_is_default_without_new_environment_variable(monkeypatch):
    monkeypatch.delenv("NEWS_PUBLISHER_FEEDS", raising=False)
    publishers = FinespressoPublishers()
    names = {publisher for publisher, _, _ in publishers.feeds}
    assert {"baltics", "prnewswire", "globenewswire_sector",
            "globenewswire_industry", "globenewswire_country_dk"} <= names
    assert len(finespresso_feed_inventory()) > 100


def test_realtime_skips_existing_links_before_enrichment():
    repo = RealtimeRepo()
    repo.article_exists = lambda publisher, link: link == "existing"
    publishers = MagicMock()
    publishers.collect.return_value = [
        {"title": "Old", "publisher": "p", "link": "existing"},
        {"title": "New", "publisher": "p", "link": "new"},
    ]
    pipeline = MagicMock()
    pipeline.enrich.return_value = dict(VALID)
    Worker("realtime", 5, 60, 0, 1, repository=repo, pipeline=pipeline,
           publishers=publishers)._realtime_cycle()
    pipeline.enrich.assert_called_once()
    assert pipeline.enrich.call_args.args[0]["link"] == "new"


def test_realtime_failures_cannot_exceed_batch_cost_ceiling():
    repo = RealtimeRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [
        {"title": str(i), "publisher": "p", "link": str(i)} for i in range(20)
    ]
    pipeline = MagicMock()
    pipeline.enrich.side_effect = MissingEventModel("missing")
    Worker("realtime", 3, 60, 0, 1, repository=repo, pipeline=pipeline,
           publishers=publishers)._realtime_cycle()
    assert pipeline.enrich.call_count == 1
    assert repo.state["failed_count"] == 1


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
    assert repo.state["status"] == "error"
    assert repo.state["last_error"] == "IncompleteArticle: missing=['reason']"


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
    source = open("news_scheduler/repository.py", encoding="utf-8").read()
    assert "mod(id,:count)=:shard" in source and "event='press_releases'" in source


def test_realtime_insert_is_idempotent_at_repository_contract():
    source = open("news_scheduler/repository.py", encoding="utf-8").read()
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

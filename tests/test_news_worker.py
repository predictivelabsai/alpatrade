from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from news_scheduler.events import normalize_event
from news_scheduler.models import EventModels, MissingEventModel, ModelRegistry
from news_scheduler.pipeline import IncompleteArticle, NewsPipeline
from news_scheduler.publishers import FinespressoPublishers, finespresso_feed_inventory
from news_scheduler.repository import NewsRepository
from news_scheduler.validation import finite_move, missing_enrichment_fields
from news_scheduler.worker import STOP, Worker


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


def test_best_effort_pipeline_retains_partial_fields_for_database_retry(monkeypatch):
    models = FakeModels()
    models.available_events = lambda: ("earnings",)
    xai = MagicMock()
    xai.metadata.side_effect = RuntimeError("provider unavailable")
    xai.reason.side_effect = RuntimeError("provider unavailable")
    row, missing, issues = NewsPipeline(models, xai).enrich_best_effort({
        "title": "Original title", "content": "Original content",
        "publisher": "test", "link": "https://example.test/news",
    })
    assert row["title"] == "Original title" and row["content"] == "Original content"
    assert "company" in missing and "reason" in missing
    assert issues == ["metadata:RuntimeError", "prediction:KeyError",
                      "reason:RuntimeError"]


class FakeRepo:
    def __init__(self, acquired=True):
        self.acquired, self.saved, self.inserted, self.updates = acquired, 0, 0, []
        self.state = {"last_processed_news_id": 4, "processed_count": 2, "failed_count": 0}

    def checkpoint(self, *args): return dict(self.state)
    @contextmanager
    def lock(self, *args): yield self.acquired
    def incomplete(self, after, limit, shard, count): return []
    def remaining(self, shard=0, count=1): return 0
    def update_checkpoint(self, *args, **values): self.state.update(values); self.updates.append(values)


class RealtimeRepo(FakeRepo):
    def insert_pending(self, row):
        self.inserted += 1
        return 99

    def update_partial(self, article_id, row, missing):
        self.saved += 1
        self.last_missing = missing


def test_finespresso_inventory_is_default_without_new_environment_variable(monkeypatch):
    monkeypatch.delenv("NEWS_PUBLISHER_FEEDS", raising=False)
    publishers = FinespressoPublishers()
    names = {publisher for publisher, _, _ in publishers.feeds}
    assert {"baltics", "prnewswire", "globenewswire_sector",
            "globenewswire_industry", "globenewswire_country_dk"} <= names
    assert len(finespresso_feed_inventory()) > 100


def test_finespresso_scheduler_exposes_all_original_publisher_jobs(monkeypatch):
    monkeypatch.delenv("NEWS_PUBLISHER_FEEDS", raising=False)
    publishers = FinespressoPublishers()
    monkeypatch.setattr(publishers, "_euronext", lambda: iter(()))
    monkeypatch.setattr(publishers, "_omx", lambda: iter(()))
    assert [name for name, _ in publishers.groups()] == [
        "baltics", "euronext", "omx", "globenewswire_sector",
        "globenewswire_country", "globenewswire_industry", "prnewswire",
    ]


def test_publisher_collection_round_robins_instead_of_starving_later_jobs(monkeypatch):
    publishers = FinespressoPublishers("https://example.test/feed")
    publishers.groups = lambda: [
        ("busy", iter([{"publisher": "busy", "link": str(i)} for i in range(5)])),
        ("quiet", iter([{"publisher": "quiet", "link": "q"}])),
        ("last", iter([{"publisher": "last", "link": "z"}])),
    ]
    rows = list(publishers.collect())
    assert [row["publisher"] for row in rows[:3]] == ["busy", "quiet", "last"]
    assert len(rows) == 7


def test_failed_publisher_does_not_block_remaining_publishers():
    def broken():
        raise RuntimeError("publisher unavailable")
        yield

    publishers = FinespressoPublishers("https://example.test/feed")
    publishers.groups = lambda: [
        ("broken", broken()),
        ("healthy", iter([{"publisher": "healthy", "link": "ok"}])),
    ]
    assert list(publishers.collect()) == [{"publisher": "healthy", "link": "ok"}]


def test_omx_collector_preserves_original_source_fields(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"results": {"item": [{
        "published": "2026-09-13 08:00:00 +0000", "languages": ["en"],
        "language": "en", "company": "Issuer", "headline": "Notice",
        "messageUrl": "https://example.test/omx", "cnsCategory": "Company news",
        "market": "Main Market",
    }]}}
    monkeypatch.setattr("news_scheduler.publishers.requests.get", lambda *a, **k: response)
    monkeypatch.setattr("news_scheduler.publishers._content", lambda *a, **k: "Body")
    row = next(FinespressoPublishers._omx())
    assert row["publisher"] == "omx" and row["company"] == "Issuer"
    assert row["publisher_topic"] == "Company news" and row["content"] == "Body"


def test_euronext_collector_preserves_original_source_fields(monkeypatch):
    response = MagicMock(text="""<table class='table'><tbody><tr>
      <td>13 Sep 2026 08:00 CEST</td><td>Issuer SA</td>
      <td><a href='/news/1'>Results</a></td><td>Technology</td><td>Earnings</td>
      </tr></tbody></table>""")
    monkeypatch.setattr("news_scheduler.publishers.requests.get", lambda *a, **k: response)
    monkeypatch.setattr("news_scheduler.publishers._content", lambda *a, **k: "Body")
    row = next(FinespressoPublishers._euronext())
    assert row["publisher"] == "euronext" and row["company"] == "Issuer SA"
    assert row["link"].startswith("https://live.euronext.com/")
    assert row["industry"] == "Technology" and row["publisher_topic"] == "Earnings"


def test_realtime_skips_existing_links_before_enrichment():
    repo = RealtimeRepo()
    repo.article_exists = lambda publisher, link: link == "existing"
    publishers = MagicMock()
    publishers.collect.return_value = [
        {"title": "Old", "publisher": "p", "link": "existing"},
        {"title": "New", "publisher": "p", "link": "new"},
    ]
    pipeline = MagicMock()
    pipeline.enrich_best_effort.return_value = (dict(VALID), [], [])
    Worker("realtime", 5, 60, 0, 1, repository=repo, pipeline=pipeline,
           publishers=publishers)._realtime_cycle()
    pipeline.enrich_best_effort.assert_called_once()
    assert pipeline.enrich_best_effort.call_args.args[0]["link"] == "new"


def test_realtime_failures_cannot_exceed_batch_cost_ceiling():
    repo = RealtimeRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [
        {"title": str(i), "publisher": "p", "link": str(i)} for i in range(20)
    ]
    pipeline = MagicMock()
    pipeline.enrich_best_effort.return_value = (
        {"title": "partial"}, ["company", "predicted_side"],
        ["metadata:RuntimeError", "prediction:MissingEventModel"],
    )
    Worker("realtime", 3, 60, 0, 1, repository=repo, pipeline=pipeline,
           publishers=publishers)._realtime_cycle()
    assert pipeline.enrich_best_effort.call_count == 3
    assert repo.state["failed_count"] == 3
    assert repo.inserted == 3


def test_realtime_worker_inserts_fully_enriched_article():
    repo = RealtimeRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [{"title": "News"}]
    pipeline = MagicMock()
    pipeline.enrich_best_effort.return_value = (dict(VALID), [], [])
    worker = Worker("realtime", 5, 60, 0, 1, repository=repo, pipeline=pipeline, publishers=publishers)
    assert worker._realtime_cycle() is True
    assert repo.inserted == 1 and repo.state["last_inserted_news_id"] == 99


def test_realtime_worker_saves_incomplete_article_and_continues():
    repo = RealtimeRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [{"title": "News"}, {"title": "Next"}]
    pipeline = MagicMock()
    pipeline.enrich_best_effort.side_effect = [
        ({"title": "News"}, ["reason"], ["reason:RuntimeError"]),
        (dict(VALID), [], []),
    ]
    worker = Worker("realtime", 5, 60, 0, 1, repository=repo, pipeline=pipeline, publishers=publishers)
    worker._realtime_cycle()
    assert repo.inserted == 2 and repo.saved == 2
    assert pipeline.enrich_best_effort.call_count == 2
    assert repo.state["failed_count"] == 1
    assert repo.state["status"] == "running"
    assert repo.state["last_error"] is None


def test_repository_converts_placeholders_to_database_nulls():
    values = NewsRepository._values({
        "title": "Headline", "company": "N/A", "reason": "Error in summarization",
        "predicted_side": "NaN", "predicted_move": float("inf"),
    })
    assert values["title"] == "Headline"
    assert values["company"] is None and values["reason"] is None
    assert values["predicted_side"] is None and values["predicted_move"] is None


def test_backfill_retains_partial_result_and_advances_to_later_rows():
    repo = RealtimeRepo()
    repo.incomplete = lambda *args: [
        {"id": 5, "publisher": "p", "title": "First"},
        {"id": 7, "publisher": "p", "title": "Second"},
    ]
    pipeline = MagicMock()
    pipeline.enrich_best_effort.side_effect = [
        ({"title": "First"}, ["company"], ["metadata:RuntimeError"]),
        ({**VALID, "title": "Second"}, [], []),
    ]
    worker = Worker("backfill", 10, 60, 0, 1, repository=repo,
                    pipeline=pipeline, publishers=MagicMock())
    assert worker._backfill_cycle() is True
    assert pipeline.enrich_best_effort.call_count == 2
    assert repo.saved == 2 and repo.state["last_processed_news_id"] == 7


def test_durable_checkpoint_resume_uses_saved_cursor():
    repo = FakeRepo()
    worker = Worker("backfill", 10, 1, 0, 2, repository=repo, pipeline=MagicMock(), publishers=MagicMock())
    assert worker._backfill_cycle() is False
    assert repo.state["last_processed_news_id"] == 4


def test_duplicate_worker_lock_returns_without_work():
    worker = Worker("backfill", 10, 1, 0, 1, repository=FakeRepo(False), pipeline=MagicMock(), publishers=MagicMock())
    assert worker.run() == 2


def test_realtime_worker_survives_cycle_exception_until_shutdown():
    repo = FakeRepo()
    worker = Worker("realtime", 1, 1, 0, 1, repository=repo,
                    pipeline=MagicMock(), publishers=MagicMock())
    def fail_cycle():
        STOP.set()
        raise RuntimeError("bad publisher cycle")
    worker._realtime_cycle = fail_cycle
    try:
        assert worker.run() == 0
        assert any(update.get("last_error") for update in repo.updates)
    finally:
        STOP.clear()


def test_shards_use_disjoint_modulo_predicate():
    assert NewsRepository.lock_key("news-backfill", 0) != NewsRepository.lock_key("news-backfill", 1)
    source = open("news_scheduler/repository.py", encoding="utf-8").read()
    assert "mod(id,:count)=:shard" in source
    assert "event='press_releases'" not in source


def test_realtime_insert_is_idempotent_at_repository_contract():
    source = open("news_scheduler/repository.py", encoding="utf-8").read()
    assert "WHERE NOT EXISTS" in source
    assert "link=:link AND publisher=:publisher" in source
    assert "pending_enrichment" in source and "retryable" in source


def test_migration_contains_durable_checkpoint_and_unique_shard_key():
    sql = open("sql/31_news_worker_jobs.sql", encoding="utf-8").read()
    assert "PRIMARY KEY (job_name, shard_index, shard_count)" in sql
    assert "last_processed_news_id" in sql and "failed_count" in sql


def test_worker_event_migration_is_sanitized_and_durable():
    sql = open("sql/32_news_worker_events.sql", encoding="utf-8").read()
    assert "alpatrade.news_worker_events" in sql
    assert "details JSONB" in sql


def test_news_scheduler_is_registered_in_research_navigation():
    source = open("engine/web/ph_news_scheduler.py", encoding="utf-8").read()
    assert '"News Scheduler", "/research/news-scheduler"' in source
    assert "Fully enriched articles" in source
    assert "Top companies" in source and "Top publishers" in source
    assert "LIMIT :limit OFFSET :offset" in source
    assert "Page {page_number} of {total_pages}" in source
    assert "news_worker_events" in source


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

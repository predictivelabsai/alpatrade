"""Real PostgreSQL parity, deduplication, leases and accounting transactions.

PREMARKET_TEST_DATABASE_URL must name a loopback PostgreSQL instance with
CREATE DATABASE permission. Every run owns a new database and drops only that
database. It never migrates or truncates the URL's existing database.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from engine import premarket_data as data, premarket_jobs as jobs, premarket_analysis as analysis
from engine.ai import llm_usage
from engine.db.pool import DatabasePool

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 8, 7)
USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def isolated_pool():
    value = os.getenv("PREMARKET_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set PREMARKET_TEST_DATABASE_URL for isolated PostgreSQL tests.")
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("The premarket integration suite only accepts a loopback database server.")
    name = "premarket_test_" + uuid.uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    pool = DatabasePool(url.set(database=name).render_as_string(hide_password=False))
    try:
        with pool.get_session() as session:
            session.execute(text("""
                CREATE SCHEMA alpatrade;
                CREATE TABLE alpatrade.users (user_id UUID PRIMARY KEY);
                CREATE SCHEMA premarket_screener;
                CREATE TABLE premarket_screener.regions (region_id INT PRIMARY KEY, abbrev TEXT);
                CREATE TABLE premarket_screener.exchanges (
                    exchange_id INT PRIMARY KEY, region_id INT, name TEXT, code TEXT);
                CREATE TABLE premarket_screener.sectors (sector_id INT PRIMARY KEY, name TEXT);
                CREATE TABLE premarket_screener.industries (industry_id INT PRIMARY KEY, sector_id INT, name TEXT);
                CREATE TABLE premarket_screener.companies (company_id INT PRIMARY KEY,
                    primary_ticker TEXT, name TEXT, exchange_id INT, industry_id INT);
                CREATE TABLE premarket_screener.snapshots (snapshot_id INT PRIMARY KEY, company_id INT,
                    date DATE, premarket_price_at_nine DOUBLE PRECISION, accumulated_volume DOUBLE PRECISION);
                CREATE TABLE premarket_screener.previous_closes (company_id INT, date DATE, price DOUBLE PRECISION);
                CREATE TABLE premarket_screener.llm_analysis (analysis_id INT PRIMARY KEY, company_id INT,
                    date DATE, model_provider TEXT, analysis TEXT);
                CREATE TABLE premarket_screener.calendars (exchange_id INT, date DATE, is_open BOOLEAN,
                    open TIME, close TIME, after_hour_close TIME);
                INSERT INTO premarket_screener.regions VALUES (1,'US');
                INSERT INTO premarket_screener.exchanges VALUES (1,1,'Nasdaq','NASDAQ');
                INSERT INTO premarket_screener.sectors VALUES (1,'Technology'),(2,'Energy');
                INSERT INTO premarket_screener.industries VALUES (1,1,'Software'),(2,2,'Energy');
                INSERT INTO premarket_screener.companies VALUES
                    (1,'AAA','Alpha Incorporated',1,1),(2,'BBB','Beta Incorporated',1,1),
                    (3,'CCC','Charlie Energy',1,2),(4,'DDD','Delta Energy',1,2),(5,'EEE','Empty Energy',1,2);
                INSERT INTO premarket_screener.snapshots VALUES
                    (10,1,'2026-08-07',110,1000),(11,1,'2026-08-07',115,1100),
                    (12,2,'2026-08-07',90,2000),(13,3,'2026-08-07',100,3000),
                    (14,4,'2026-08-07',200,4000),(15,5,'2026-08-07','NaN',0);
                INSERT INTO premarket_screener.previous_closes VALUES
                    (1,'2026-08-07',100),(2,'2026-08-07',100),(3,'2026-08-07',100),
                    (3,'2026-08-07',100),(4,'2026-08-07',100),(4,'2026-08-07',110);
                INSERT INTO premarket_screener.llm_analysis VALUES
                    (1,1,'2026-08-07','grok','Saved Grok'),(2,1,'2026-08-07','gemini','Saved Gemini');
            """))
            for migration in ["16_premarket_scans.sql", "28_xai_byok_query_gate.sql",
                              "30_llm_usage_logging.sql", "31_premarket_migration.sql"]:
                session.execute(text((ROOT / "sql" / migration).read_text()))
            session.execute(text((ROOT / "sql/31_premarket_migration.sql").read_text()))
            session.execute(text("INSERT INTO alpatrade.users VALUES (:uid)"), {"uid": USER})
        yield pool
    finally:
        pool.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def db(isolated_pool, monkeypatch):
    for module in [data, jobs, llm_usage]:
        monkeypatch.setattr(module, "get_pool", lambda: isolated_pool)
    monkeypatch.setattr("engine.db.pool.get_pool", lambda: isolated_pool)
    monkeypatch.setenv("PREMARKET_V2_ENABLED", "true")
    monkeypatch.setenv("PREMARKET_WORKER_ENABLED", "true")
    data._cache.clear()
    with isolated_pool.get_session() as session:
        session.execute(text("""TRUNCATE alpatrade.premarket_jobs, alpatrade.premarket_observations,
            alpatrade.premarket_analyses, alpatrade.premarket_scan_runs, alpatrade.llm_usage_logging,
            alpatrade.user_ai_query_allowances"""))
    yield isolated_pool
    data._cache.clear()


def test_source_parity_uses_highest_snapshot_and_preserves_duplicate_rows(db):
    report = data.dashboard(DAY, include_earnings=False)
    assert report["summary"] == {"total_sectors": 2, "total_stocks_attempted": 5, "total_stocks_scanned": 3,
        "total_stocks_failed": 2, "total_up_movements": 1, "total_down_movements": 1, "total_unchanged": 1}
    assert report["sectors"]["Technology"]["up"][0]["premarket_close"] == 115
    assert report["sectors"]["Technology"]["up"][0]["snapshot_id"] == "legacy:11"
    assert report["sectors"]["Technology"]["up"][0]["analysis_preview"] == "Saved Grok"
    assert data.query("SELECT COUNT(*) AS n FROM premarket_screener.snapshots")[0]["n"] == 6
    assert data.observations(DAY)[4]["prev_close"] is None
    assert {row["provider"] for row in analysis.saved_for_date(DAY, 1)[1]} == {"grok", "gemini"}


def test_new_prior_close_does_not_mask_legacy_snapshot_and_finalized_rows_are_immutable(db):
    data.persist_observations(DAY, [{"company_id": 1, "prev_close": 100}], finalized=False)
    assert data.observations(DAY)[1]["premarket_close"] == 115
    row = {"company_id": 1, "prev_close": 100, "premarket_close": 120,
           "as_of": datetime(2026, 8, 7, 9, tzinfo=data.ET)}
    data.persist_observations(DAY, [row], finalized=True)
    data.persist_observations(DAY, [{**row, "premarket_close": 900}], finalized=False)
    assert data.observations(DAY)[1]["premarket_close"] == 120
    assert data.query("SELECT COUNT(*) AS n FROM alpatrade.premarket_observations")[0]["n"] == 1


def test_previous_close_remains_available_when_snapshot_is_missing(db):
    with db.get_session() as session:
        session.execute(text("INSERT INTO premarket_screener.previous_closes VALUES (1,'2026-08-06',98)"))
    found = data.observations(date(2026, 8, 6))[1]
    assert found["prev_close"] == 98 and found["premarket_close"] is None
    assert found["snapshot_id"] is None and not found["finalized"]


def test_concurrent_enqueue_and_claim_have_one_owner(db):
    with ThreadPoolExecutor(max_workers=6) as executor:
        requests = list(executor.map(lambda _: jobs.enqueue("analysis", DAY, company_id=2, user_id=USER), range(12)))
    assert len({row["job_id"] for row in requests}) == 1
    with ThreadPoolExecutor(max_workers=6) as executor:
        claimed = list(executor.map(lambda i: jobs.claim(f"worker-{i}"), range(6)))
    assert len([row for row in claimed if row]) == 1
    public = jobs.public_job(requests[0]["job_id"])
    assert not {"user_id", "funding_source", "payload", "claimed_by"} & public.keys()


def test_request_reuses_active_research_without_another_key_or_allowance(db, monkeypatch):
    request = jobs.enqueue("analysis", DAY, company_id=2, user_id=USER)
    def no_credentials(*args):
        raise AssertionError("Active public research must be reused before key resolution.")
    monkeypatch.setattr(analysis, "credentials", no_credentials)
    repeated = jobs.request_analysis("BBB", DAY.isoformat(), USER)
    assert repeated["job_id"] == request["job_id"]
    assert not data.query("SELECT * FROM alpatrade.user_ai_query_allowances")


def test_platform_reservation_retries_and_refund_are_atomic(db):
    jobs.enqueue("analysis", DAY, company_id=2, user_id=USER)
    job = jobs.claim("first")
    assert jobs.reserve(job, False) == jobs.reserve(job, False) == "platform"
    assert data.query("SELECT platform_queries_used AS n FROM alpatrade.user_ai_query_allowances")[0]["n"] == 1
    jobs.fail(job, "provider offline")
    with db.get_session() as session:
        session.execute(text("UPDATE alpatrade.premarket_jobs SET available_at=NOW()"))
    job = jobs.claim("retry")
    assert jobs.reserve(job, False) == "platform"
    jobs.fail(job, "provider offline", terminal=True)
    assert data.query("SELECT platform_queries_used AS n FROM alpatrade.user_ai_query_allowances")[0]["n"] == 0
    retry = jobs.enqueue("analysis", DAY, company_id=2, user_id=USER, retry_failed=True)
    assert retry["status"] == "queued"
    assert jobs.reserve(jobs.claim("new-attempt"), False) == "platform"
    assert data.query("SELECT platform_queries_used AS n FROM alpatrade.user_ai_query_allowances")[0]["n"] == 1


def test_restart_recovery_reuses_funding_and_rejects_expired_worker(db):
    jobs.enqueue("analysis", DAY, company_id=2, user_id=USER)
    job = jobs.claim("dead-worker")
    jobs.reserve(job, False)
    with db.get_session() as session:
        session.execute(text("UPDATE alpatrade.premarket_jobs SET heartbeat_at=NOW()-INTERVAL '10 minutes'"))
    assert jobs.recover() == 1
    with pytest.raises(RuntimeError, match="lease expired"):
        jobs.complete(job)
    recovered = jobs.claim("replacement")
    assert jobs.reserve(recovered, False) == "platform"
    assert data.query("SELECT platform_queries_used AS n FROM alpatrade.user_ai_query_allowances")[0]["n"] == 1
    with db.get_session() as session:
        session.execute(text("UPDATE alpatrade.premarket_jobs SET attempt=3,heartbeat_at=NOW()-INTERVAL '10 minutes'"))
    assert jobs.recover() == 1
    assert data.query("SELECT platform_queries_used AS n FROM alpatrade.user_ai_query_allowances")[0]["n"] == 0


def result():
    return {"model_name": "grok-test", "text": "No specific news catalyst found.", "sources": [],
        "retrospective": True, "prompt": "public prices", "raw_text": "public analysis",
        "usage": llm_usage.extract_usage({"input_tokens": 100, "output_tokens": 25, "cost_in_usd_ticks": 10000000})}


@pytest.mark.parametrize("byok", [True, False])
def test_completion_atomically_persists_public_research_and_attributed_usage(db, byok):
    jobs.enqueue("analysis", DAY, company_id=2, user_id=USER)
    job = jobs.claim("writer")
    jobs.reserve(job, byok)
    observation = data.normalize(data.company("BBB"), data.observations(DAY)[2], DAY)
    jobs.complete(job, result(), observation)
    saved = analysis.saved_for_date(DAY, 2)[2][0]
    assert saved["observation_identity"] == data.observation_identity(observation)
    assert saved["retrospective"] and saved["generated_at"]
    usage = data.query("SELECT * FROM alpatrade.llm_usage_logging")[0]
    assert usage["total_tokens"] == 125 and str(usage["user_id"]) == USER
    assert float(usage["estimated_cost_usd"]) == 0.001
    assert usage["metadata"]["pricing"] == "provider_reported"
    assert usage["funding_source"] == ("user_byok" if byok else "platform")
    assert data.query("SELECT user_id FROM alpatrade.premarket_analyses")[0]["user_id"] is None
    assert jobs.public_job(str(job["job_id"]))["status"] == "completed"
    if byok:
        assert not data.query("SELECT * FROM alpatrade.user_ai_query_allowances")


def test_accounting_failure_rolls_back_research_and_job_completion(db, monkeypatch):
    jobs.enqueue("analysis", DAY, company_id=2, user_id=USER)
    job = jobs.claim("writer")
    jobs.reserve(job, False)
    monkeypatch.setattr(llm_usage, "record_usage", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        jobs.complete(job, result(), {"company_id": 2, "scan_date": DAY.isoformat()})
    assert not data.query("SELECT * FROM alpatrade.premarket_analyses")
    assert jobs.public_job(str(job["job_id"]))["status"] == "running"
    jobs.fail(job, "accounting unavailable", terminal=True)
    assert data.query("SELECT platform_queries_used AS n FROM alpatrade.user_ai_query_allowances")[0]["n"] == 0


def test_exhausted_allowance_cannot_reserve_another_job(db):
    with db.get_session() as session:
        session.execute(text("INSERT INTO alpatrade.user_ai_query_allowances(user_id,platform_queries_used) VALUES (:uid,5)"), {"uid": USER})
    jobs.enqueue("analysis", DAY, company_id=2, user_id=USER)
    job = jobs.claim("writer")
    with pytest.raises(PermissionError):
        jobs.reserve(job, False)
    assert data.query("SELECT funding_source FROM alpatrade.premarket_jobs")[0]["funding_source"] is None


def test_daily_pipeline_saves_cutoff_report_and_schedules_both_movers_with_autonomy_off(db, monkeypatch, tmp_path):
    from engine import premarket_providers as provider
    day = date(2026, 8, 10)
    current = datetime(2026, 8, 10, 9, 16, 20, tzinfo=data.ET)
    real_now = data.now_et
    monkeypatch.setattr(data, "now_et", lambda value=None: real_now(value or current))
    monkeypatch.setenv("DATABASE_URL", db.database_url)
    monkeypatch.setenv("AUTONOMY_ENABLED", "false")
    monkeypatch.setenv("PREMARKET_REPORTS_DIR", str(tmp_path))
    monkeypatch.setattr(provider, "previous_closes", lambda previous, companies: [
        {"company_id": row["company_id"], "prev_close": 100} for row in companies])
    monkeypatch.setattr(provider, "live_observations", lambda *args: {})
    def final(meta, selected, prior):
        if meta["company_id"] > 3:
            return None
        return {"company_id": meta["company_id"], "prev_close": prior,
                "premarket_close": {1: 110, 2: 90, 3: 100}[meta["company_id"]],
                "quote_timestamp": datetime(2026, 8, 10, 9, tzinfo=data.ET),
                "as_of": datetime(2026, 8, 10, 9, tzinfo=data.ET)}
    monkeypatch.setattr(provider, "final_observation", final)
    monkeypatch.setattr(jobs.time, "sleep", lambda _: None)
    jobs.schedule(current)
    jobs._collect(jobs.claim("collector"))
    jobs._collect(jobs.claim("collector"))
    jobs.schedule(current)  # duplicates cannot reset completed collection
    queued = data.query("SELECT kind,status,company_id FROM alpatrade.premarket_jobs")
    assert len(queued) == 4
    assert {row["company_id"] for row in queued if row["kind"] == "analysis"} == {1, 2}
    assert all(row["status"] == "completed" for row in queued if row["kind"] != "analysis")
    saved = data.query("SELECT report FROM alpatrade.premarket_scan_runs")[0]["report"]
    assert saved["trading_date"] == day.isoformat()
    assert saved["summary"]["total_stocks_scanned"] == 3
    assert saved["scan_timestamp"] == "2026-08-10T09:00:00-04:00"
    assert len(list(tmp_path.glob("*.json"))) == 1

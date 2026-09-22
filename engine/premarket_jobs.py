"""Durable premarket collection and analysis, independent of trading autonomy."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text

from engine.db.pool import get_pool
from engine import premarket_data as data

log = logging.getLogger(__name__)
_started = False
_start_lock = threading.Lock()


def worker_enabled() -> bool:
    return data.enabled() and os.getenv("PREMARKET_WORKER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def enqueue(kind: str, day: date, *, company_id: int | None = None,
            user_id: str | None = None, payload: dict | None = None, retry_failed: bool = False) -> dict:
    key = f"{kind}:{day}:{company_id or 'market'}"
    with get_pool().get_session() as session:
        row = session.execute(text("""
            INSERT INTO alpatrade.premarket_jobs(kind,dedupe_key,trading_date,company_id,user_id,payload)
            VALUES (:kind,:key,:day,:company,:uid,CAST(:payload AS JSONB))
            ON CONFLICT(dedupe_key) DO UPDATE SET dedupe_key=EXCLUDED.dedupe_key
            RETURNING job_id::text, status, error
        """), {"kind": kind, "key": key, "day": day, "company": company_id,
                "uid": user_id, "payload": json.dumps(payload or {})}).mappings().one()
        if retry_failed and row["status"] == "failed":
            row = session.execute(text("""UPDATE alpatrade.premarket_jobs SET status='queued',
                attempt=0,error=NULL,user_id=:uid,funding_source=NULL,platform_slot=FALSE,refunded=FALSE,
                available_at=NOW(),updated_at=NOW() WHERE job_id=:id AND status='failed'
                RETURNING job_id::text,status,error"""),
                {"id": row["job_id"], "uid": user_id}).mappings().one()
        return dict(row)


def request_analysis(ticker: str, selected_date: str, user_id: str) -> dict:
    if not user_id:
        raise PermissionError("Sign in to generate commentary.")
    day = data.trading_date(selected_date)
    current = data.now_et()
    meta = data.company(ticker)
    if not data.session_hours(day, meta["exchange_id"]):
        raise ValueError("Select an open trading session.")
    if day == current.date() and current.time() < data.FINALIZE_AT:
        raise ValueError("Today's analysis is available after 09:16:20 ET.")
    from engine.premarket_analysis import saved_for_date, credentials
    saved = saved_for_date(day, meta["company_id"]).get(meta["company_id"], [])
    existing = next((row for row in saved if row["provider"] == "grok"), None)
    if existing:
        return {"status": "completed", "analysis": existing}
    if not worker_enabled():
        raise RuntimeError("Commentary generation is not enabled. Saved research is still available.")
    obs = data.observations(day).get(meta["company_id"])
    row = data.normalize(meta, obs, day)
    if not row["available"]:
        raise ValueError("A usable premarket snapshot and previous close are required.")
    active = data.query("""SELECT job_id::text,status,error FROM alpatrade.premarket_jobs
        WHERE dedupe_key=:key AND status IN ('queued','running')""",
        {"key": f"analysis:{day}:{meta['company_id']}"})
    if active:
        return active[0]
    credentials(user_id)  # Fail quickly, without persisting a key or consuming a query.
    return enqueue("analysis", day, company_id=meta["company_id"], user_id=user_id, retry_failed=True)


def public_job(job_id: str) -> dict:
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        raise LookupError("Premarket job not found.") from None
    rows = data.query("""SELECT job_id::text,status,kind,trading_date,company_id,error,
        updated_at FROM alpatrade.premarket_jobs WHERE job_id=:id""", {"id": job_id})
    if not rows:
        raise LookupError("Premarket job not found.")
    row = rows[0]
    row["trading_date"] = data.iso(row["trading_date"])
    row["updated_at"] = data.iso(row["updated_at"])
    # Public job status deliberately omits requester, keys, funding, and payload.
    return row


def claim(worker_id: str) -> dict | None:
    with get_pool().get_session() as session:
        row = session.execute(text("""
            UPDATE alpatrade.premarket_jobs SET status='running',claimed_by=:worker,
                heartbeat_at=NOW(),updated_at=NOW(),attempt=attempt+1
            WHERE job_id=(SELECT job_id FROM alpatrade.premarket_jobs
                WHERE status='queued' AND available_at<=NOW()
                ORDER BY CASE kind WHEN 'analysis' THEN 0 WHEN 'previous_closes' THEN 1 ELSE 2 END,
                         created_at FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING *
        """), {"worker": worker_id}).mappings().first()
        return dict(row) if row else None


def _locked(session, job: dict) -> dict:
    row = session.execute(text("""SELECT * FROM alpatrade.premarket_jobs
        WHERE job_id=:id AND status='running' AND claimed_by=:worker FOR UPDATE"""),
        {"id": job["job_id"], "worker": job["claimed_by"]}).mappings().first()
    if not row:
        raise RuntimeError("Premarket job lease expired.")
    return dict(row)


def _refund(session, row: dict) -> None:
    if row["platform_slot"] and not row["refunded"]:
        from engine.ai.query_gate import QueryAuthorization, refund_query
        refund_query(str(row["user_id"]), QueryAuthorization("platform", platform_slot=True), session=session)
        session.execute(text("UPDATE alpatrade.premarket_jobs SET refunded=TRUE WHERE job_id=:id"),
                        {"id": row["job_id"]})


def fail(job: dict, reason: str, *, terminal: bool = False) -> None:
    with get_pool().get_session() as session:
        row = _locked(session, job)
        final = terminal or row["attempt"] >= 3
        if final:
            _refund(session, row)
        session.execute(text("""UPDATE alpatrade.premarket_jobs SET status=:status,
            error=:error, claimed_by=NULL,heartbeat_at=NULL,updated_at=NOW(),
            available_at=NOW()+(:seconds * INTERVAL '1 second') WHERE job_id=:id"""),
            {"status": "failed" if final else "queued", "error": reason[:500],
             "seconds": min(300, 30 * 2 ** row["attempt"]), "id": row["job_id"]})


def recover() -> int:
    recovered = 0
    with get_pool().get_session() as session:
        rows = session.execute(text("""SELECT * FROM alpatrade.premarket_jobs
            WHERE status='running' AND heartbeat_at < NOW()-INTERVAL '5 minutes'
            FOR UPDATE SKIP LOCKED""")).mappings().all()
        for raw in rows:
            row = dict(raw)
            final = row["attempt"] >= 3
            if final:
                _refund(session, row)
            session.execute(text("""UPDATE alpatrade.premarket_jobs SET status=:status,
                claimed_by=NULL,heartbeat_at=NULL,updated_at=NOW(),
                error='Worker restarted before the job finished.' WHERE job_id=:id"""),
                {"status": "failed" if final else "queued", "id": row["job_id"]})
            recovered += 1
    return recovered


def reserve(job: dict, has_byok: bool) -> str:
    from engine.ai.query_gate import authorize_query
    from engine.ai.llm_usage import enforce_daily_budget
    with get_pool().get_session() as session:
        row = _locked(session, job)
        if row["funding_source"]:
            return row["funding_source"]
        if row["user_id"]:
            auth = authorize_query(str(row["user_id"]), has_byok=has_byok, session=session)
            source, slot = auth.funding_source, auth.platform_slot
        else:
            enforce_daily_budget(funding_source="platform")
            source, slot = "platform", False
        session.execute(text("""UPDATE alpatrade.premarket_jobs SET funding_source=:source,
            platform_slot=:slot WHERE job_id=:id"""),
                        {"source": source, "slot": slot, "id": row["job_id"]})
        return source


def complete(job: dict, result: dict | None = None, observation: dict | None = None) -> None:
    from engine.ai.llm_usage import record_usage
    with get_pool().get_session() as session:
        row = _locked(session, job)
        if result is not None:
            session.execute(text("""INSERT INTO alpatrade.premarket_analyses
                (company_id,trading_date,model_name,narrative,sources,observation_identity,retrospective)
                VALUES (:company,:day,:model,:narrative,CAST(:sources AS JSONB),:identity,:retrospective)
                ON CONFLICT(company_id,trading_date,provider) DO NOTHING"""),
                {"company": row["company_id"], "day": row["trading_date"], "model": result["model_name"],
                 "narrative": result["text"], "sources": json.dumps(result["sources"]),
                 "identity": data.observation_identity(observation), "retrospective": result["retrospective"]})
            record_usage(user_id=str(row["user_id"]) if row["user_id"] else None,
                         thread_id=None, agent="premarket", provider="xai", model=result["model_name"],
                         funding_source="user_byok" if row["funding_source"] == "byok" else "platform",
                         prompt=result["prompt"], response=result["raw_text"], usage=result["usage"],
                         request_id=str(row["job_id"]), job_id=str(row["job_id"]), session=session)
        elif row["kind"] == "analysis":
            _refund(session, row)  # another writer produced the saved result while this job waited
        session.execute(text("""UPDATE alpatrade.premarket_jobs SET status='completed',
            error=NULL,updated_at=NOW(),heartbeat_at=NULL,claimed_by=NULL WHERE job_id=:id"""),
                        {"id": row["job_id"]})


def _analysis(job: dict) -> None:
    from engine.premarket_analysis import credentials, generate, saved_for_date
    day = job["trading_date"]
    saved = saved_for_date(day, job["company_id"]).get(job["company_id"], [])
    if any(row["provider"] == "grok" for row in saved):
        complete(job)
        return
    meta = next((row for row in data.catalog() if row["company_id"] == job["company_id"]), None)
    if not meta:
        raise ValueError("Company is no longer in the US catalog.")
    observation = data.normalize(meta, data.observations(day).get(job["company_id"]), day)
    if not observation["available"]:
        raise ValueError("A usable snapshot is required for commentary.")
    uid = str(job["user_id"]) if job["user_id"] else None
    key, models, has_byok = credentials(uid)
    funding = reserve(job, has_byok)
    # If a BYOK key was removed while retrying, do not silently switch funding.
    if (funding == "byok") != has_byok:
        raise PermissionError("The funding key changed. Restore the original xAI key to retry.")
    result = generate(observation, day, key, models)
    complete(job, result, observation)


def _continue(job: dict, payload: dict) -> None:
    with get_pool().get_session() as session:
        _locked(session, job)
        session.execute(text("""UPDATE alpatrade.premarket_jobs SET payload=CAST(:payload AS JSONB),
            status='queued',attempt=0,claimed_by=NULL,heartbeat_at=NULL,available_at=NOW(),updated_at=NOW()
            WHERE job_id=:id"""), {"payload": json.dumps(payload), "id": job["job_id"]})


def _collect(job: dict) -> None:
    from engine import premarket_providers as provider
    day = job["trading_date"]
    companies = data.catalog()
    if not companies:
        raise ValueError("The shared US company catalog is empty.")
    if not data.session_hours(day):
        raise ValueError("Collection requires an open trading session.")
    if job["kind"] == "previous_closes":
        rows = provider.previous_closes(data.previous_session(day), companies)
        if not rows:
            raise RuntimeError("No previous-close prices were returned.")
        data.persist_observations(day, rows, finalized=False)
        complete(job)
        return
    if data.now_et() < datetime.combine(day, data.FINALIZE_AT, tzinfo=data.ET):
        raise ValueError("The 09:00 snapshot is not available until 09:16:20 ET.")
    payload = dict(job["payload"] or {})
    cursor = int(payload.get("cursor", 0))
    # A frozen list makes catalog changes harmless while catch-up spans jobs.
    ids = payload.get("companies", [row["company_id"] for row in companies])
    payload["companies"] = ids
    by_id = {row["company_id"]: row for row in companies}
    observations = data.observations(day)
    if cursor == 0:
        closes = provider.previous_closes(data.previous_session(day), companies)
        data.persist_observations(day, closes, finalized=False)
        observations = data.observations(day)
        # The delayed full-market snapshot is the fast path during the normal
        # morning run. Reject bars beyond 09:00, then reconstruct only gaps.
        if day == data.now_et().date():
            candidates = provider.live_observations(companies, datetime.combine(day, data.OBSERVATION_AT, tzinfo=data.ET))
            rows = [{**row, "as_of": datetime.combine(day, data.OBSERVATION_AT, tzinfo=data.ET)}
                    for row in candidates.values()]
            data.persist_observations(day, rows, finalized=True)
            observations = data.observations(day)
        ids = [company_id for company_id in ids if not observations.get(company_id, {}).get("finalized")]
        payload["companies"] = ids
    batch = ids[cursor:cursor + 25]
    # Batch checkpoints make late-start reconstruction resumable and allow
    # interactive analysis jobs to run between collection batches.
    interval = 60 / max(1, int(os.getenv("PREMARKET_REQUESTS_PER_MINUTE", "60")))
    for company_id in batch:
        meta = by_id.get(company_id)
        if not meta:
            continue
        existing = observations.get(company_id, {})
        if existing.get("finalized"):
            continue
        started = time.monotonic()
        row = provider.final_observation(meta, day, data.finite(existing.get("prev_close")))
        if row:
            data.persist_observations(day, [row], finalized=True)
        time.sleep(max(0, interval - (time.monotonic() - started)))
    payload["cursor"] = cursor + len(batch)
    if payload["cursor"] < len(ids):
        _continue(job, payload)
        return
    report = data.dashboard(day, include_earnings=False)
    if not report["summary"]["total_stocks_scanned"]:
        raise RuntimeError("No 09:00 observations were available. Regular-session prices were not substituted.")
    from engine.premarket import save_report, top_movers
    report["run_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"premarket:{day}"))
    save_report(report)
    top = top_movers(report, 1)
    for mover in top["gainers"] + top["fallers"]:
        enqueue("analysis", day, company_id=mover["company_id"])
    complete(job)


def schedule(now: datetime | None = None) -> list[dict]:
    if not worker_enabled():
        return []
    current = data.now_et(now)
    if not data.session_hours(current.date()) or current.time() < data.AVAILABLE_AT:
        return []
    jobs = [enqueue("previous_closes", current.date())]
    if current.time() >= data.FINALIZE_AT:
        jobs.append(enqueue("finalize", current.date()))
    return jobs


def run_one(worker_id: str) -> bool:
    job = claim(worker_id)
    if not job:
        return False
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(20):
            try:
                with get_pool().get_session() as session:
                    session.execute(text("""UPDATE alpatrade.premarket_jobs SET heartbeat_at=NOW()
                        WHERE job_id=:id AND claimed_by=:worker AND status='running'"""),
                        {"id": job["job_id"], "worker": worker_id})
            except Exception:
                log.warning("Premarket heartbeat failed for job %s", job["job_id"])

    pulse = threading.Thread(target=heartbeat, name="premarket-heartbeat", daemon=True)
    pulse.start()
    try:
        _analysis(job) if job["kind"] == "analysis" else _collect(job)
    except Exception as exc:
        # Provider errors and arbitrary exception messages may contain credentials.
        # Store only reviewed messages for validation and otherwise the class name.
        from engine.premarket_providers import ProviderUnavailable
        from engine.ai.query_gate import QueryLimitExceeded
        from engine.ai.llm_usage import DailyBudgetExceeded
        reason = str(exc) if isinstance(exc, (ProviderUnavailable, QueryLimitExceeded, DailyBudgetExceeded)) else f"Premarket {job['kind']} failed ({type(exc).__name__})."
        log.warning("Premarket job %s failed (%s)", job["job_id"], type(exc).__name__)
        fail(job, reason, terminal=isinstance(exc, PermissionError))
    finally:
        stopped.set()
        pulse.join(timeout=1)
    return True


def _loop() -> None:
    worker_id = f"premarket-{uuid.uuid4()}"
    while worker_enabled():
        try:
            recover()
            schedule()
            if not run_one(worker_id):
                time.sleep(10)
        except Exception as exc:
            log.warning("Premarket worker tick failed (%s)", type(exc).__name__)
            time.sleep(30)


def start() -> None:
    global _started
    if not worker_enabled():
        return
    with _start_lock:
        if not _started:
            threading.Thread(target=_loop, name="premarket-worker", daemon=True).start()
            _started = True

"""Resumable backfill for XAI enrichment and local ML news predictions."""

import argparse
import json
import math
import os
import tempfile
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

from tasks.ai.predict import predict
from utils.ai.xai_util import _invoke_llm, detect_language, translate_to_english


MISSING_SIDE_SQL = "(predicted_side IS NULL OR btrim(predicted_side) = '' OR upper(btrim(predicted_side)) IN ('NAN', 'N/A'))"
MISSING_MOVE_SQL = "(predicted_move IS NULL OR predicted_move::text = 'NaN')"
CHECKPOINT = Path(os.getenv(
    "FINESPRESSO_BACKFILL_CHECKPOINT",
    Path(tempfile.gettempdir()) / "finespresso_xai_ml_backfill.json",
))


def valid_side(value):
    if value is None or pd.isna(value):
        return None
    value = str(value).strip().upper()
    return value if value in {"UP", "DOWN", "NEUTRAL"} else None


def valid_move(value):
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def parse_json_response(value):
    value = value.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return json.loads(value.strip())


def extract_companies_batch(items):
    if not items:
        return {}, True
    payload = [{"key": key, "text": source[:1200]} for key, source in items]
    prompt = (
        "Extract the company or issuer for each news item. Return only a JSON object "
        "mapping every key to a concise company name, or null when unknown. Items: "
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        result = parse_json_response(_invoke_llm("", prompt))
        if not isinstance(result, dict) or any(key not in result for key, _ in items):
            raise ValueError("company response did not contain every requested key")
        return result, True
    except Exception as exc:
        print(json.dumps({"warning": "company_batch_failed", "error": str(exc)[:200]}), flush=True)
        if len(items) > 1:
            midpoint = len(items) // 2
            left, left_ok = extract_companies_batch(items[:midpoint])
            right, right_ok = extract_companies_batch(items[midpoint:])
            if left_ok and right_ok:
                return {**left, **right}, True
        return {}, False


def generate_reasons_batch(items):
    if not items:
        return {}, True
    prompt = (
        "For each item, explain in at most 40 words why the stated ML side and percentage "
        "move could follow from the news. Return only a JSON object mapping every key to "
        "its explanation. Items: " + json.dumps(items, ensure_ascii=False)
    )
    try:
        result = parse_json_response(_invoke_llm("", prompt, max_tokens=max(300, len(items) * 80)))
        requested_keys = {item["key"] for item in items}
        if not isinstance(result, dict) or not requested_keys.issubset(result):
            raise ValueError("reason response did not contain every requested key")
        return result, True
    except Exception as exc:
        print(json.dumps({"warning": "reason_batch_failed", "error": str(exc)[:200]}), flush=True)
        if len(items) > 1:
            midpoint = len(items) // 2
            left, left_ok = generate_reasons_batch(items[:midpoint])
            right, right_ok = generate_reasons_batch(items[midpoint:])
            if left_ok and right_ok:
                return {**left, **right}, True
        return {}, False


def load_cursor(checkpoint=CHECKPOINT, reset=False, start_id=0):
    if reset or not checkpoint.exists():
        return start_id
    try:
        return max(start_id, int(json.loads(checkpoint.read_text(encoding="utf-8")).get("last_id", 0)))
    except Exception:
        return start_id


def save_cursor(last_id, stats, checkpoint=CHECKPOINT):
    temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"last_id": last_id, "stats": stats}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, checkpoint)


def checkpoint_for_shard(shard_index, shard_count):
    if shard_count == 1:
        return CHECKPOINT
    return CHECKPOINT.with_name(f"{CHECKPOINT.stem}.shard-{shard_index}-of-{shard_count}{CHECKPOINT.suffix}")


def fetch_batch(conn, cursor, batch_size, shard_index=0, shard_count=1):
    return conn.execute(text(f"""
        SELECT * FROM news
        WHERE id > :cursor
          AND mod(id, :shard_count) = :shard_index
          AND event = 'press_releases'
          AND (
            company IS NULL OR btrim(company) = '' OR upper(btrim(company)) = 'NAN'
            OR language IS NULL OR btrim(language) = ''
            OR title_en IS NULL OR btrim(title_en) = ''
            OR content_en IS NULL OR btrim(content_en) = ''
            OR {MISSING_SIDE_SQL} OR {MISSING_MOVE_SQL}
            OR reason IS NULL OR btrim(reason) = '' OR upper(btrim(reason)) IN ('NAN', 'N/A')
          )
        ORDER BY id
        LIMIT :batch_size
    """), {"cursor": cursor, "batch_size": batch_size, "shard_index": shard_index, "shard_count": shard_count}).mappings().all()


def _legacy_cursor_helpers_removed():
    """Kept as a marker for checkpoint-format compatibility."""
    return None


def backfill_batch(engine, rows, stats):
    frame = pd.DataFrame([dict(row) for row in rows])

    # Company: one XAI call per link and propagation to every duplicate row.
    company_by_link = {}
    company_requests = {}
    for _, row in frame.iterrows():
        company = row.get("company")
        if pd.isna(company) or not str(company).strip():
            link = str(row.get("link") or "")
            source = row.get("title") or row.get("content") or ""
            if link not in company_requests and source:
                company_requests[link] = source

    extracted_companies, company_ok = extract_companies_batch(list(company_requests.items()))
    if not company_ok:
        raise RuntimeError("XAI company batch failed; retrying without advancing checkpoint")
    company_by_link.update(extracted_companies)
    for idx, row in frame.iterrows():
        company = row.get("company")
        if pd.isna(company) or not str(company).strip():
            link = str(row.get("link") or "")
            company = company_by_link.get(link)
            if company:
                frame.at[idx, "company"] = company
                stats["company"] += 1

    # Missing language/translations only.
    for idx, row in frame.iterrows():
        language = row.get("language")
        if pd.isna(language) or not str(language).strip():
            language = detect_language(f"{row.get('title') or ''} {row.get('content') or ''}")
            frame.at[idx, "language"] = language
            stats["language"] += 1
        language = str(language or "en").lower()
        if pd.isna(row.get("title_en")) or not str(row.get("title_en") or "").strip():
            frame.at[idx, "title_en"] = row.get("title") if language in {"en", "eng", "english"} else translate_to_english(row.get("title") or "", language)
            stats["title_en"] += 1
        if pd.isna(row.get("content_en")) or not str(row.get("content_en") or "").strip():
            frame.at[idx, "content_en"] = row.get("content") if language in {"en", "eng", "english"} else translate_to_english(row.get("content") or "", language)
            stats["content_en"] += 1

    # Normalize legacy NaN placeholders so predict() treats them as missing.
    frame.loc[
        frame["predicted_side"].isna()
        | frame["predicted_side"].astype(str).str.strip().str.upper().isin({"NAN", "N/A", ""}),
        "predicted_side",
    ] = None
    frame.loc[
        frame["predicted_move"].isna()
        | frame["predicted_move"].astype(str).str.strip().str.upper().eq("NAN"),
        "predicted_move",
    ] = None

    # ML predicts only missing/invalid values; existing valid predictions survive.
    frame = predict(frame)

    reason_requests = []
    normalized = {}
    for _, row in frame.iterrows():
        side = valid_side(row.get("predicted_side"))
        move = valid_move(row.get("predicted_move"))
        reason = row.get("reason")
        if (pd.isna(reason) or not str(reason or "").strip() or str(reason).strip().upper() in {"NAN", "N/A"}) and move is not None:
            reason_requests.append({"key": str(int(row["id"])), "side": side, "move": move, "text": (row.get("content") or row.get("title") or "")[:1200]})
        normalized[int(row["id"])] = (side, move, reason)

    generated_reasons, reasons_ok = generate_reasons_batch(reason_requests)
    if not reasons_ok:
        raise RuntimeError("XAI reason batch failed; retrying without advancing checkpoint")
    updates = []
    for _, row in frame.iterrows():
        row_id = int(row["id"])
        side, move, reason = normalized[row_id]
        generated_reason = generated_reasons.get(str(row_id))
        if generated_reason:
            reason = generated_reason
            stats["reason"] += 1
        if side is not None:
            stats["predicted_side"] += 1
        if move is not None:
            stats["predicted_move"] += 1
        updates.append({
            "id": int(row["id"]), "company": None if pd.isna(row.get("company")) else row.get("company"),
            "language": None if pd.isna(row.get("language")) else row.get("language"),
            "title_en": None if pd.isna(row.get("title_en")) else row.get("title_en"),
            "content_en": None if pd.isna(row.get("content_en")) else row.get("content_en"),
            "side": side, "move": move,
            "reason": None if pd.isna(reason) else reason,
        })

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE news SET
              company = COALESCE(NULLIF(:company, ''), company),
              language = COALESCE(NULLIF(:language, ''), language),
              title_en = COALESCE(NULLIF(:title_en, ''), title_en),
              content_en = COALESCE(NULLIF(:content_en, ''), content_en),
              predicted_side = COALESCE(:side, NULLIF(predicted_side, 'NaN')),
              predicted_move = CASE WHEN :move IS NOT NULL THEN :move WHEN predicted_move::text = 'NaN' THEN NULL ELSE predicted_move END,
              reason = COALESCE(NULLIF(:reason, ''), reason)
            WHERE id = :id
        """), updates)
        for link, company in company_by_link.items():
            if link and company:
                conn.execute(text("""
                    UPDATE news SET company = :company
                    WHERE link = :link AND (company IS NULL OR btrim(company) = '' OR upper(btrim(company)) = 'NAN')
                """), {"link": link, "company": company})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows for this run; zero means all")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--start-id", type=int, default=0)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("shard-index must be between 0 and shard-count - 1")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    checkpoint = checkpoint_for_shard(args.shard_index, args.shard_count)
    cursor = load_cursor(checkpoint, args.reset, args.start_id)
    processed = 0
    stats = {"company": 0, "language": 0, "title_en": 0, "content_en": 0, "predicted_side": 0, "predicted_move": 0, "reason": 0}
    while True:
        size = args.batch_size if not args.limit else min(args.batch_size, args.limit - processed)
        if size <= 0:
            break
        try:
            with engine.connect() as conn:
                rows = fetch_batch(conn, cursor, size, args.shard_index, args.shard_count)
        except SQLAlchemyError as exc:
            print(json.dumps({"warning": "fetch_retry", "last_id": cursor, "error": str(exc)[:500]}), flush=True)
            engine.dispose()
            time.sleep(15)
            continue
        if not rows:
            break
        try:
            backfill_batch(engine, rows, stats)
        except (RuntimeError, SQLAlchemyError) as exc:
            print(json.dumps({"warning": "batch_retry", "last_id": cursor, "error": str(exc)}), flush=True)
            time.sleep(15)
            continue
        cursor = int(rows[-1]["id"])
        processed += len(rows)
        save_cursor(cursor, stats, checkpoint)
        print(json.dumps({"shard": args.shard_index, "processed": processed, "last_id": cursor, **stats}), flush=True)
    engine.dispose()
    print(json.dumps({"complete": not bool(args.limit), "processed": processed, "last_id": cursor, **stats}), flush=True)


if __name__ == "__main__":
    main()

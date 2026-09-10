"""Process one real unseen article and verify public.news persistence."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from sqlalchemy import text

from engine.db.pool import DatabasePool
from news_scheduler.models import ModelRegistry
from news_scheduler.pipeline import NewsPipeline
from news_scheduler.publishers import FinespressoPublishers
from news_scheduler.repository import NewsRepository
from news_scheduler.validation import missing_enrichment_fields
from news_scheduler.xai import XAIEnricher


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file")
    args = parser.parse_args()
    load_dotenv(args.env_file or None)

    engine = DatabasePool().engine
    repo = NewsRepository(engine)
    pipeline = NewsPipeline(ModelRegistry(engine), XAIEnricher())
    article = next(
        row for row in FinespressoPublishers().collect()
        if row.get("link") and not repo.article_exists(row.get("publisher", ""), row["link"])
    )
    enriched = pipeline.enrich(article)
    missing = missing_enrichment_fields(enriched)
    if missing:
        print({"valid": False, "missing_fields": missing})
        return 1
    inserted_id = repo.insert_enriched(enriched)
    if inserted_id is None:
        print({"valid": True, "inserted": False, "reason": "concurrent duplicate"})
        return 1
    with engine.connect() as connection:
        saved = connection.execute(text("""
            SELECT company, language, title_en, content_en, predicted_side,
                   predicted_move, reason
            FROM public.news WHERE id=:id
        """), {"id": inserted_id}).mappings().one()
    second = repo.insert_enriched(enriched)
    print({
        "valid": not missing_enrichment_fields(saved),
        "inserted_id": inserted_id,
        "publisher": article.get("publisher"),
        "predicted_side": saved["predicted_side"],
        "predicted_move_finite": saved["predicted_move"] is not None,
        "second_insert_idempotent": second is None,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

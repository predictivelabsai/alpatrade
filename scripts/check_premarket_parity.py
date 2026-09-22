"""Read-only comparison of a fixed legacy snapshot with the migrated service.

Run: python scripts/check_premarket_parity.py --date 2026-08-07
Uses DATABASE_URL from the service environment. No provider calls or writes.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from engine import premarket_data as data, premarket_analysis as analysis
from engine.db.pool import get_pool


def check(day: date) -> dict:
    if day >= data.now_et().date():
        raise ValueError("Choose a completed historical session for an offline parity comparison.")
    pool = get_pool()

    @contextmanager
    def read_only():
        with pool.get_session() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout='30s'"))
            yield session

    def read(sql, params=None):
        with read_only() as session:
            return [dict(row) for row in session.execute(text(sql), params or {}).mappings()]

    # Each service query gets an explicit read-only transaction. No scheduler,
    # earnings, chart or LLM generation code is invoked by this comparison.
    original_data_query, original_analysis_query = data.query, analysis.query
    data.query = analysis.query = read
    data._cache.clear()
    try:
        source = read("""
            WITH closes AS (
                SELECT company_id, CASE WHEN COUNT(DISTINCT price)=1 THEN MIN(price) END AS prior
                FROM premarket_screener.previous_closes WHERE date=:day GROUP BY company_id
            )
            SELECT DISTINCT ON (c.company_id) c.company_id, s.snapshot_id,
                   UPPER(c.primary_ticker) AS ticker, s.premarket_price_at_nine AS price,
                   s.accumulated_volume, sec.name AS sector,
                   closes.prior
            FROM premarket_screener.companies c
            JOIN premarket_screener.exchanges e USING (exchange_id)
            JOIN premarket_screener.regions r USING (region_id)
            JOIN premarket_screener.industries i USING (industry_id)
            JOIN premarket_screener.sectors sec USING (sector_id)
            LEFT JOIN premarket_screener.snapshots s ON s.company_id=c.company_id AND s.date=:day
            LEFT JOIN closes ON closes.company_id=c.company_id
            WHERE r.abbrev='US' ORDER BY c.company_id,s.snapshot_id DESC
        """, {"day": day})
        if data.table_exists("alpatrade.premarket_observations") and read(
            "SELECT 1 FROM alpatrade.premarket_observations WHERE trading_date=:day AND finalized LIMIT 1", {"day": day}):
            raise ValueError("Choose a source-only date; this date already contains finalized AlpaTrade observations.")
        report = data.dashboard(day, include_earnings=False)
        actual = {row["company_id"]: row for row in report["rows"]}
        expected_sectors = {}
        for row in source:
            found = actual[row["company_id"]]
            price, prior = data.finite(row["price"]), data.finite(row["prior"])
            assert found["premarket_close"] == price, f"Price mismatch for {row['ticker']}"
            assert found["prev_close"] == prior, f"Previous-close mismatch for {row['ticker']}"
            valid = price is not None and prior is not None and price > 0 and prior > 0
            assert found["available"] is valid, f"Availability mismatch for {row['ticker']}"
            counts = expected_sectors.setdefault(row["sector"], {"up": 0, "down": 0, "unchanged": 0, "missing": 0})
            group = "missing" if not valid else "up" if price > prior else "down" if price < prior else "unchanged"
            counts[group] += 1
            if valid:
                assert math.isclose(found["movement_pct"], (price / prior - 1) * 100, abs_tol=1e-8)
        for sector, counts in expected_sectors.items():
            found = report["sectors"][sector]
            for source_key, target_key in {"up": "total_gainers", "down": "total_losers",
                "unchanged": "total_unchanged", "missing": "total_unavailable"}.items():
                assert counts[source_key] == found[target_key], f"Sector count mismatch: {sector}"
        saved = analysis.saved_for_date(day)
        legacy = read("""SELECT DISTINCT ON(company_id,model_provider) company_id,
            model_provider::text AS provider,analysis FROM premarket_screener.llm_analysis
            WHERE date=:day ORDER BY company_id,model_provider,analysis_id DESC""", {"day": day})
        for row in legacy:
            found = next(item for item in saved[row["company_id"]] if item["provider"] == row["provider"])
            assert found["text"] == row["analysis"], "Saved commentary mismatch"
        return {"date": day.isoformat(), "companies_compared": len(source), "sectors_compared": len(expected_sectors),
                "analyses_compared": len(legacy), "summary": report["summary"], "result": "passed"}
    finally:
        data.query, analysis.query = original_data_query, original_analysis_query
        data._cache.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.date), indent=2))
    except Exception as exc:
        # Database exceptions can contain connection strings. Keep credentials
        # out of operator output even on a failed comparison.
        print(f"Premarket parity check failed ({type(exc).__name__}).", file=sys.stderr)
        raise SystemExit(1)

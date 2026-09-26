#!/usr/bin/env python
"""13F pipeline for /hedge-funds: EDGAR ingest -> CUSIP map -> 13F-implied returns.

    python run_migration.py sql/38_hedge_fund_13f.sql        # once
    python scripts/hedge_fund_13f.py ingest --since 2020-12-31
    python scripts/hedge_fund_13f.py map --top 3000          # + widely held CUSIPs
    python scripts/hedge_fund_13f.py compute
    python scripts/hedge_fund_13f.py all                     # all three

Quarterly cadence is enough (13F-HRs are due 45 days after quarter end); rerun
`compute` any time to refresh YTD / TTM with the latest prices.
Requires DATABASE_URL; set SEC_USER_AGENT to a real contact (SEC fair access).
"""
from __future__ import annotations

import argparse
from datetime import date
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from engine.publicmarkets import hf13f, hf13f_store  # noqa: E402


def _fmt(v):
    return "  n/a " if v is None else f"{v * 100:+6.1f}%"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ingest", "map", "compute", "all"])
    ap.add_argument("--since", default="2020-12-31", help="earliest 13F period to ingest")
    ap.add_argument("--cik", action="append", help="limit to CIK(s) (default: starter set)")
    ap.add_argument("--top", type=int, default=0, help="also map the N most widely held CUSIPs")
    ap.add_argument("--refresh", action="store_true", help="re-download filings already stored")
    ap.add_argument("--price-cache", help="optional pickle path to cache Yahoo prices between runs")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    funds = hf13f.STARTER_FUNDS
    if args.cik:
        want = {str(int(c)).zfill(10) for c in args.cik}
        funds = [f for f in funds if f[0] in want] + [(c, c) for c in want - {f[0] for f in funds}]
    if args.cmd in ("ingest", "all"):
        since = date.fromisoformat(args.since)
        for cik, name in funds:
            print("ingest", hf13f_store.ingest_fund(cik, name, since, refresh=args.refresh), flush=True)
    if args.cmd in ("map", "all"):
        print("map", hf13f_store.map_cusips(extra_top_n=args.top), flush=True)
    if args.cmd in ("compute", "all"):
        ciks = [f[0] for f in funds] if args.cik else None
        report = hf13f_store.compute_performance(ciks, price_cache=args.price_cache)
        for name, rows in report.items():
            print(f"\n{name}")
            for label, (fund, spy) in rows.items():
                print(f"  {label:9s} fund {_fmt(fund)}  SPY {_fmt(spy)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

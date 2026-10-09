#!/usr/bin/env python3
"""Publish (or refresh) the Semi 7 backtest entry on the public leaderboard.

    python scripts/seed_semi7_backtest.py [--report docs/walk_forward_btd_semi7_<ts>.json]

Idempotent on seed_key 'semi7-btd-backtest' (owner kaljuvee@gmail.com, shown as Predictive
Labs Ltd). SPY closes from yfinance. DATABASE_URL from env or .env.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from engine.leaderboard import semi7  # noqa: E402
from engine.leaderboard.skill import front_matter  # noqa: E402

MD = ROOT / "engine" / "leaderboard" / "seeds" / "semi7-btd-backtest.md"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=semi7.latest_report(ROOT))
    a = ap.parse_args(argv)
    wf = json.loads(Path(a.report).read_text())
    first = date.fromisoformat(wf["rows"][0]["test_period"][:10])
    import yfinance as yf
    px = yf.download("SPY", start=(first - timedelta(days=7)).isoformat(), auto_adjust=True,
                     progress=False)["Close"].squeeze().dropna()
    spy = {d.date().isoformat(): float(v) for d, v in px.items()}
    bm = semi7.build_metrics(wf, spy, source=str(Path(a.report).relative_to(ROOT)))
    md = MD.read_text(encoding="utf-8")
    fm = front_matter(md)
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    with DatabasePool().get_session() as s:
        uid = s.execute(text("SELECT user_id FROM alpatrade.users WHERE lower(email)=lower(:e)"),
                        {"e": "kaljuvee@gmail.com"}).scalar()
        if not uid:
            sys.exit("owner not found")
        rid = s.execute(text("""
            INSERT INTO alpatrade.user_strategies
                (user_id, name, author_name, description, skill_md, is_public, seed_key, kind,
                 source, source_url, backtest_metrics)
            VALUES (CAST(:uid AS UUID), :name, 'Predictive Labs Ltd', :desc, :md, TRUE, :key,
                    'backtest', 'AlpaTrade walk-forward', :url, CAST(:bm AS JSONB))
            ON CONFLICT (seed_key) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                skill_md = EXCLUDED.skill_md, backtest_metrics = EXCLUDED.backtest_metrics,
                source = EXCLUDED.source, source_url = EXCLUDED.source_url, updated_at = NOW()
            RETURNING id"""), {"uid": str(uid), "name": fm.get("title"), "desc": fm.get("description") or "",
                               "md": md, "key": semi7.SEED_KEY, "bm": json.dumps(bm, default=float),
                               "url": "https://github.com/predictivelabsai/alpatrade/blob/main/" + bm["source_report"].replace(".json", ".md")}).scalar()
        s.commit()
    print(f"semi7 backtest strategy id {rid}: CAGR {bm['annualised_pct']:.1f}% vs SPY "
          f"{bm['spy_annualised_pct']:.1f}%, alpha {bm['alpha_annualised_pct']:.1f}% (annualised), "
          f"total {bm['total_return_pct']:.1f}% vs SPY {bm['spy_return_pct']:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Seed Julian Kaljuvee's live Mag-7 BTD strategy as his public Leaderboard strategy.

Idempotent (``seed_key``): re-running never overwrites later edits unless ``--update``.
Its live figures come from his live runner run (``live_strategy_slug``), computed at
request time by :mod:`engine.leaderboard.perf`.

    python -m engine.leaderboard.seed            # insert if missing
    python -m engine.leaderboard.seed --update   # refresh name/description/skill text
"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.leaderboard.skill import front_matter

SEEDS = [{
    "seed_key": "mag7-btd-live",
    "email": "kaljuvee@gmail.com",
    "author_name": "Julian Kaljuvee",
    "file": Path(__file__).resolve().parent / "seeds" / "mag7-btd-live.md",
    "live_strategy_slug": "buy_the_dip_mag7_minhold_live",
    "is_public": True,
}]


def seed(update: bool = False) -> list[str]:
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    done = []
    with DatabasePool().get_session() as session:
        for s in SEEDS:
            md = s["file"].read_text(encoding="utf-8")
            fm = front_matter(md)
            uid = session.execute(text(
                "SELECT user_id FROM alpatrade.users WHERE lower(email) = lower(:e)"),
                {"e": s["email"]}).scalar()
            if not uid:
                done.append(f"{s['seed_key']}: owner {s['email']} not found — skipped")
                continue
            params = {"uid": str(uid), "name": fm.get("title") or s["seed_key"],
                      "author": s["author_name"], "desc": fm.get("description") or "",
                      "md": md, "pub": s["is_public"], "slug": s["live_strategy_slug"],
                      "key": s["seed_key"]}
            conflict = ("DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, "
                        "skill_md = EXCLUDED.skill_md, author_name = EXCLUDED.author_name, "
                        "live_strategy_slug = EXCLUDED.live_strategy_slug, updated_at = NOW()"
                        if update else "DO NOTHING")
            r = session.execute(text(f"""
                INSERT INTO alpatrade.user_strategies
                    (user_id, name, author_name, description, skill_md, is_public,
                     live_strategy_slug, seed_key)
                VALUES (CAST(:uid AS UUID), :name, :author, :desc, :md, :pub, :slug, :key)
                ON CONFLICT (seed_key) {conflict}
                RETURNING id
            """), params).scalar()
            done.append(f"{s['seed_key']}: " + (f"id {r}" if r else "already present"))
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed Leaderboard strategies")
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    for line in seed(a.update):
        print(line)


if __name__ == "__main__":
    main()

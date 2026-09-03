"""Press-release / news tool — reads the shared public.news feed (391k+ rows).

Each item has a headline + link + a modeled predicted side/move (the 'finespresso'
feed). AlpaTrade consumes it read-only.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text

from engine.db.pool import DatabasePool


def _clean_float(value: Any) -> float | None:
    """Postgres float8 can hold NaN/Infinity; map those to None (JSON-safe)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_side(value: Any) -> str | None:
    """The feed stores unknown sides as the literal text 'NaN'."""
    if value is None:
        return None
    text_value = str(value).strip()
    return None if text_value.lower() == "nan" else text_value


def news_category(event: str = "", title: str = "") -> str:
    """Normalize Finespresso event labels into compact premarket categories."""
    text_value = f"{event} {title}".lower()
    groups = (
        ("Earnings & guidance", ("earning", "financial result", "guidance", "operating result")),
        ("M&A & partnerships", ("merger", "acquisition", "partnership", "business contract")),
        ("Clinical & regulatory", ("clinical", "fda", "regulatory", "patent")),
        ("Capital & ownership", ("financing", "share capital", "dividend", "shareholder", "13d")),
        ("Management", ("management change", "appoint", "resign", "chief executive")),
        ("Products & expansion", ("product", "service announcement", "geographic expansion", "launch")),
    )
    return next((label for label, terms in groups if any(term in text_value for term in terms)),
                "Other catalysts")


def categorized_news(limit: int = 60) -> dict[str, list[dict]]:
    """Return recent press releases grouped into premarket catalyst categories."""
    categories: dict[str, list[dict]] = {}
    for row in search_news(limit=limit):
        category = news_category(row.get("event", ""), row.get("title", ""))
        categories.setdefault(category, []).append(row)
    return categories


def search_news(query: str = "", ticker: str = "", limit: int = 30) -> list[dict]:
    """Recent press releases, optionally filtered by headline query and/or ticker."""
    where, params = ["1=1"], {"lim": min(limit, 60)}
    if ticker:
        where.append("(upper(ticker) = :tk OR upper(yf_ticker) = :tk)")
        params["tk"] = ticker.upper()
    if query:
        where.append("title ILIKE :q")
        params["q"] = f"%{query}%"
    with DatabasePool().get_session() as s:
        rows = s.execute(text(f"""
            SELECT title, link, ticker, company, published_date, event, publisher,
                   publisher_summary, predicted_side, predicted_move
            FROM public.news
            WHERE {' AND '.join(where)}
            ORDER BY published_date DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [{"title": r[0], "link": r[1], "ticker": r[2], "company": r[3],
             "published": str(r[4]) if r[4] else "", "event": r[5], "publisher": r[6],
             "summary": r[7], "predicted_side": _clean_side(r[8]),
             "predicted_move": _clean_float(r[9])} for r in rows]


def news_summary(query: str = "", ticker: str = "", limit: int = 15) -> str:
    rows = search_news(query, ticker, limit)
    label = f" — {ticker.upper()}" if ticker else (f" — “{query}”" if query else "")
    if not rows:
        return f"# Press releases{label}\n\nNo results."
    md = [f"# Press releases{label}", "",
          "| Date | Ticker | Headline | Side |", "|---|---|---|---|"]
    for r in rows:
        side = r["predicted_side"] or ""
        title = (r["title"] or "")[:70]
        if r["link"]:
            title = f"[{title}]({r['link']})"
        md.append(f"| {r['published'][:10]} | {r['ticker'] or ''} | {title} | {side} |")
    return "\n".join(md)

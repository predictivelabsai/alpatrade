"""News Intelligence — live market headlines enriched with the Finespresso models.

Pipeline (all read-only over the shared ``finespresso_db`` the app already
points at):

1. **Live feed** — multi-source RSS via ``utils.news_feed`` (FT, Bloomberg, WSJ,
   CNBC, MarketWatch, Yahoo, Nasdaq, Seeking Alpha, Investing, GlobeNewswire,
   Reuters), fetched on demand with a short TTL cache.
2. **Ticker & sector attribution** — headlines are scanned for known symbols
   (``$TICKER`` and bare uppercase mentions); the symbol universe and the
   ticker → sector mapping come from ``premarket_screener.companies`` →
   ``industries`` → ``sectors`` (~4.8k companies).
3. **Historical analog evidence** — for detected tickers, the most recent
   press releases in ``public.news`` (joined to ``public.price_moves_data``)
   supply what the Finespresso models predicted and what actually happened
   next day for similar news.
4. **AI sector-impact analysis** (on demand) — the configured chat model
   receives the current headlines and returns strict-JSON sector impacts
   (direction, expected move %, confidence, thesis) which are aggregated into
   a sector impact board.

Nothing here places orders or writes to the shared feed.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text

from engine.db.pool import DatabasePool

logger = logging.getLogger(__name__)

_MAP_TTL = 6 * 3600
_ANALYSIS_TTL = 600
_MAX_ANALYZE_ITEMS = 25

_ticker_map_cache: dict[str, Any] = {"at": 0.0, "map": {}}
_analysis_cache: dict[str, Any] = {"key": None, "at": 0.0, "data": None}

_TICKER_RE = re.compile(r"\$([A-Z]{1,6})\b|\b([A-Z]{2,5})\b")

# Real symbols that collide with everyday uppercase words; only match with a
# "$" prefix (e.g. "$AI" for C3.ai) so headlines about "AI" don't skew the data.
_BARE_EXCLUDE = {
    "AI", "ALL", "BE", "BIG", "DO", "GET", "GO", "IT", "KEY", "MAX",
    "NEW", "NOW", "ON", "TOP",
}


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def ticker_map() -> dict[str, dict[str, str]]:
    """Known symbols → {company, sector}, cached for a few hours."""
    now = time.time()
    if _ticker_map_cache["map"] and now - _ticker_map_cache["at"] < _MAP_TTL:
        return _ticker_map_cache["map"]
    mapping: dict[str, dict[str, str]] = {}
    try:
        with DatabasePool().get_session() as session:
            rows = session.execute(text("""
                SELECT upper(c.primary_ticker) AS ticker, c.name AS company,
                       s.name AS sector
                FROM premarket_screener.companies c
                JOIN premarket_screener.industries i ON i.industry_id = c.industry_id
                JOIN premarket_screener.sectors s ON s.sector_id = i.sector_id
                WHERE c.primary_ticker IS NOT NULL AND c.primary_ticker <> ''
            """)).fetchall()
        for ticker, company, sector in rows:
            mapping[ticker] = {"company": company or ticker, "sector": sector or "Unknown"}
        if mapping:
            _ticker_map_cache["map"] = mapping
            _ticker_map_cache["at"] = now
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ticker map unavailable: %s", exc)
    return _ticker_map_cache["map"]


def extract_tickers(headline: str, summary: str = "") -> list[str]:
    """Known symbols mentioned in a headline/summary ($AAPL, bare AAPL)."""
    known = ticker_map()
    found: list[str] = []
    for match in _TICKER_RE.finditer(f"{headline} {summary}"):
        symbol, bare = (match.group(1) or match.group(2) or "").upper(), match.group(1) is None
        if symbol in known and symbol not in found and not (bare and symbol in _BARE_EXCLUDE):
            found.append(symbol)
    return found


def analog_evidence(tickers: list[str], per_ticker: int = 5) -> dict[str, dict[str, Any]]:
    """Recent Finespresso history per ticker: modeled call vs realized next-day move."""
    tickers = [t for t in tickers if t][:12]
    if not tickers:
        return {}
    try:
        with DatabasePool().get_session() as session:
            rows = session.execute(text("""
                SELECT upper(COALESCE(n.ticker, n.yf_ticker)) AS ticker,
                       n.predicted_side, n.predicted_move,
                       pm.nextday_price_change_percentage
                FROM public.news n
                JOIN public.price_moves_data pm ON pm.news_id = n.id
                WHERE upper(COALESCE(n.ticker, n.yf_ticker)) = ANY(:tickers)
                ORDER BY COALESCE(n.published_date_gmt, n.published_date) DESC
                LIMIT 400
            """), {"tickers": tickers}).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Analog evidence unavailable: %s", exc)
        return {}

    per: dict[str, list[tuple]] = {ticker: [] for ticker in tickers}
    for ticker, side, move, realized in rows:
        bucket = per.get(ticker)
        if bucket is not None and len(bucket) < per_ticker:
            bucket.append((side, _finite(move), _finite(realized)))

    evidence: dict[str, dict[str, Any]] = {}
    for ticker, samples in per.items():
        if not samples:
            continue
        sides = [s for s, _, _ in samples if s and str(s).lower() != "nan"]
        modeled = [_finite(move) for _, move, _ in samples]
        modeled = [m for m in modeled if m is not None]
        realized = [r for _, _, r in samples if r is not None]
        evidence[ticker] = {
            "samples": len(samples),
            "model_side": (max(set(sides), key=sides.count) if sides else None),
            "model_avg_move": (round(sum(modeled) / len(modeled), 2) if modeled else None),
            "realized_avg_move": (round(sum(realized) / len(realized), 2) if realized else None),
        }
    return evidence


def collect(source: str = "", query: str = "", limit: int = 60,
            fetch: Callable[[], list[dict]] | None = None) -> dict[str, Any]:
    """Live headlines + ticker/sector attribution + deterministic sector counts."""
    from utils.news_feed import fetch_news_sync, time_ago

    fetch = fetch or fetch_news_sync
    articles = fetch() or []
    query_lower = query.strip().lower()

    rows: list[dict[str, Any]] = []
    known = ticker_map()
    for article in articles:
        if source and article.get("source") != source:
            continue
        haystack = f"{article.get('title', '')} {article.get('summary', '')}".lower()
        if query_lower and query_lower not in haystack:
            continue
        tickers = extract_tickers(article.get("title", ""), article.get("summary", ""))
        sectors = sorted({known[t]["sector"] for t in tickers if t in known})
        rows.append({**article, "tickers": tickers, "sectors": sectors,
                     "sector_map": {t: known[t]["sector"] for t in tickers if t in known},
                     "published_ago": time_ago(article.get("published", ""))})
        if len(rows) >= max(1, min(limit, 200)):
            break

    ticker_counts: dict[str, int] = {}
    for row in rows:
        for ticker in row["tickers"]:
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    sector_counts: dict[str, int] = {}
    for row in rows:
        for sector in row["sectors"]:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

    return {
        "rows": rows,
        "sources": sorted({row["source"] for row in rows if row.get("source")}),
        "total_fetched": len(articles),
        "top_tickers": sorted(ticker_counts.items(), key=lambda kv: -kv[1])[:15],
        "sector_counts": dict(sorted(sector_counts.items(), key=lambda kv: -kv[1])),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _sector_board(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate AI impacts per sector: mention counts and blended expected move."""
    board: dict[str, dict[str, Any]] = {}
    for item in items:
        for impact in (item.get("ai") or {}).get("sectors", []) or []:
            name = impact.get("sector") or "Unknown"
            cell = board.setdefault(name, {"sector": name, "mentions": 0,
                                           "up": 0, "down": 0,
                                           "expected_move_pct": None, "driver": None})
            cell["mentions"] += 1
            if impact.get("direction") == "up":
                cell["up"] += 1
            elif impact.get("direction") == "down":
                cell["down"] += 1
            move = _finite(impact.get("move_pct"))
            if move is not None:
                current = cell["expected_move_pct"]
                cell["expected_move_pct"] = (move if current is None
                                             else round(current * 0.7 + move * 0.3, 2))
            if cell["driver"] is None and item.get("title"):
                cell["driver"] = item["title"][:110]
    return sorted(board.values(), key=lambda c: -c["mentions"])


def _parse_llm_json(raw: str) -> dict[str, Any]:
    blob = raw.strip()
    start, end = blob.find("{"), blob.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("model response contained no JSON object")
    return json.loads(blob[start:end + 1])


def analyze_with_ai(items: list[dict[str, Any]],
                    model: Any | None = None) -> dict[str, Any]:
    """Ask the configured chat model for per-headline sector impacts (cached)."""
    items = items[:_MAX_ANALYZE_ITEMS]
    if not items:
        return {"items": [], "sectors": [], "model": None, "cached": False}
    key = tuple(row.get("url") or row.get("title", "") for row in items)
    now = time.time()
    if (_analysis_cache["key"] == key and _analysis_cache["data"]
            and now - _analysis_cache["at"] < _ANALYSIS_TTL):
        return {**_analysis_cache["data"], "cached": True}

    model = model or _build_model()
    digest = [{"i": index, "title": row.get("title", ""), "summary": row.get("summary", ""),
               "tickers": row.get("tickers", []), "sector": (row.get("sectors") or [None])[0]}
              for index, row in enumerate(items)]
    prompt = (
        "You are a market-news analyst for a trading desk. For each headline, "
        "predict which market sectors it impacts and how.\n"
        "Rules: use these sectors when they apply: Technology, Healthcare, "
        "Financials, Industrials, Consumer Discretionary, Consumer Staples, "
        "Energy, Materials, Real Estate, Utilities, Communication Services.\n"
        "Respond with ONLY a JSON object, no markdown, shaped exactly as:\n"
        '{"items": [{"i": <headline index>, "sectors": [{"sector": "<name>", '
        '"direction": "up"|"down"|"neutral", "move_pct": <expected absolute move in '
        'percent, number>, "confidence": <0-1 number>}], "tickers": ["<affected '
        'symbols>"], "thesis": "<one short sentence>"}]}\n'
        "Headlines:\n" + json.dumps(digest, ensure_ascii=False)
    )
    response = model.invoke([("system",
                              "You return strict JSON only. Never add commentary."),
                             ("human", prompt)])
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(block.get("text", "") if isinstance(block, dict) else str(block)
                          for block in content)
    parsed = _parse_llm_json(str(content))

    by_index = {entry.get("i"): entry for entry in parsed.get("items", [])
                if isinstance(entry, dict)}
    enriched: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        entry = by_index.get(index) or {}
        thesis = str(entry.get("thesis") or "").strip()
        impacts = []
        for impact in entry.get("sectors", []) or []:
            if not isinstance(impact, dict) or not impact.get("sector"):
                continue
            direction = str(impact.get("direction") or "neutral").lower()
            impacts.append({"sector": str(impact["sector"]),
                            "direction": direction if direction in ("up", "down", "neutral")
                            else "neutral",
                            "move_pct": _finite(impact.get("move_pct")),
                            "confidence": _finite(impact.get("confidence"))})
        enriched.append({**row, "ai": {"sectors": impacts, "thesis": thesis,
                                       "tickers": [str(t) for t in entry.get("tickers", [])]}})

    data = {"items": enriched, "sectors": _sector_board(enriched),
            "model": getattr(model, "model_name", None) or "chat-model"}
    _analysis_cache.update({"key": key, "at": now, "data": data})
    return {**data, "cached": False}


def _build_model():
    from engine.config import build_chat_model, get_settings
    return build_chat_model(get_settings(), streaming=False, temperature=0.2,
                            max_tokens=4000)

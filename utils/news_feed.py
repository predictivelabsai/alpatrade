"""Multi-source market-news RSS ingester for the right-pane news panel.

Ported from the LiquidRound ingester and retargeted at markets / trading sources
(FT, Bloomberg, WSJ, CNBC, MarketWatch, Yahoo Finance, GlobeNewswire, Seeking
Alpha, Nasdaq, Reuters). Fetches every feed concurrently, dedupes by URL, sorts by
publish time, and caches the merged list for a short TTL.

Returns a list of dicts: {title, url, summary, source, icon, published, image}.
Dead / rate-limited feeds are skipped silently, so the panel degrades gracefully.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from time import mktime

import feedparser
import requests

log = logging.getLogger(__name__)

_FETCH_TIMEOUT = int(os.getenv("NEWS_FETCH_TIMEOUT", "8"))
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36 AlpaTrade/1.0")

# name, url, short icon/badge. Order is not significant (results are date-sorted).
FEEDS: list[dict] = [
    {"name": "Financial Times",   "url": "https://www.ft.com/markets?format=rss",                         "icon": "FT"},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss",                  "icon": "BBG"},
    {"name": "WSJ Markets",       "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",                 "icon": "WSJ"},
    {"name": "CNBC Markets",      "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "icon": "CNBC"},
    {"name": "CNBC Top News",     "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "icon": "CNBC"},
    {"name": "MarketWatch",       "url": "http://feeds.marketwatch.com/marketwatch/topstories/",          "icon": "MW"},
    {"name": "MarketWatch Pulse", "url": "http://feeds.marketwatch.com/marketwatch/marketpulse/",         "icon": "MW"},
    {"name": "Yahoo Finance",     "url": "https://finance.yahoo.com/news/rssindex",                       "icon": "YF"},
    {"name": "Nasdaq Markets",    "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",      "icon": "NDQ"},
    {"name": "Seeking Alpha",     "url": "https://seekingalpha.com/market_currents.xml",                  "icon": "SA"},
    {"name": "Investing.com",     "url": "https://www.investing.com/rss/news_25.rss",                     "icon": "INV"},
    {"name": "GlobeNewswire",     "url": "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies", "icon": "GNW"},
    {"name": "Reuters Business",  "url": "https://ir.thomsonreuters.com/rss/news-releases.xml?items=15",  "icon": "RTR"},
]

NEWS_TTL = int(os.getenv("NEWS_TTL_SECONDS", "300"))
_PER_FEED = int(os.getenv("NEWS_PER_FEED", "8"))
_MAX_ITEMS = int(os.getenv("NEWS_MAX_ITEMS", "60"))

_cache: dict = {"articles": [], "fetched_at": None}


def _parse_date(entry) -> datetime:
    for field in ("published_parsed", "updated_parsed"):
        val = getattr(entry, field, None) or (entry.get(field) if hasattr(entry, "get") else None)
        if val:
            try:
                return datetime.fromtimestamp(mktime(val), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
    return datetime.now(tz=timezone.utc)


def _extract_image(entry) -> str | None:
    for media in getattr(entry, "media_thumbnail", []) or []:
        if isinstance(media, dict) and media.get("url"):
            return media["url"]
    for media in getattr(entry, "media_content", []) or []:
        if isinstance(media, dict) and media.get("url"):
            return media["url"]
    for enc in getattr(entry, "enclosures", []) or []:
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")
    return None


def _clean_summary(entry) -> str:
    import re
    summary = entry.get("summary", "") or ""
    summary = re.sub(r"<[^>]+>", "", summary).strip()  # strip HTML tags
    if len(summary) > 240:
        summary = summary[:237] + "…"
    return summary


def _fetch_one(feed: dict) -> list[dict]:
    try:
        # Fetch with a bounded timeout + browser UA (feedparser.parse alone can hang
        # and some feeds 403 the default UA), then parse the bytes.
        resp = requests.get(feed["url"], timeout=_FETCH_TIMEOUT,
                            headers={"User-Agent": _UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as e:  # noqa: BLE001
        log.warning("RSS fetch failed for %s: %s", feed["name"], repr(e)[:120])
        return []
    out = []
    for entry in getattr(parsed, "entries", [])[:_PER_FEED]:
        url = (entry.get("link", "") or "").strip()
        title = (entry.get("title", "") or "").strip()
        if not url or not title:
            continue
        out.append({
            "title": title,
            "url": url,
            "summary": _clean_summary(entry),
            "source": feed["name"],
            "icon": feed["icon"],
            "published": _parse_date(entry).isoformat(),
            "image": _extract_image(entry),
        })
    return out


async def fetch_news(force: bool = False) -> list[dict]:
    """Fetch every feed concurrently; return merged, deduped, date-sorted list (cached)."""
    now = datetime.now(tz=timezone.utc)
    if (not force and _cache["fetched_at"]
            and (now - _cache["fetched_at"]).total_seconds() < NEWS_TTL):
        return _cache["articles"]

    results = await asyncio.gather(
        *[asyncio.to_thread(_fetch_one, f) for f in FEEDS],
        return_exceptions=True,
    )

    articles, seen = [], set()
    for result in results:
        if isinstance(result, Exception):
            log.warning("RSS feed error: %s", result)
            continue
        for a in result:
            if a["url"] not in seen:
                seen.add(a["url"])
                articles.append(a)

    articles.sort(key=lambda a: a["published"], reverse=True)
    articles = articles[:_MAX_ITEMS]
    _cache["articles"] = articles
    _cache["fetched_at"] = now
    log.info("Fetched %d market-news articles from %d feeds", len(articles), len(FEEDS))
    return articles


def fetch_news_sync(force: bool = False) -> list[dict]:
    """Blocking wrapper around :func:`fetch_news` for non-async callers."""
    try:
        return asyncio.run(fetch_news(force=force))
    except RuntimeError:  # already in an event loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fetch_news(force=force))
        finally:
            loop.close()


def time_ago(iso_str: str) -> str:
    """Human 'Xm/h/d ago' from an ISO timestamp."""
    try:
        d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        mins = int((datetime.now(timezone.utc) - d).total_seconds() / 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except Exception:  # noqa: BLE001
        return ""

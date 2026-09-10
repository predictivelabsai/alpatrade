"""Publisher collection adapter for realtime worker cycles."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable

import feedparser


class RSSPublishers:
    """Collect configured publisher RSS feeds without writing to the database.

    Feed URLs are deployment configuration, allowing the same Finespresso feed
    inventory to be mounted in Coolify without embedding operational URLs here.
    """

    def __init__(self, feeds: str | None = None):
        raw = feeds if feeds is not None else os.getenv("NEWS_PUBLISHER_FEEDS", "")
        self.feeds = [item.strip() for item in raw.split(",") if item.strip()]

    def collect(self) -> Iterable[dict]:
        if not self.feeds:
            raise RuntimeError("NEWS_PUBLISHER_FEEDS is not configured")
        for url in self.feeds:
            parsed = feedparser.parse(url)
            publisher = parsed.feed.get("title") or "publisher-rss"
            for item in parsed.entries:
                yield {
                    "title": item.get("title") or "",
                    "content": item.get("content", [{}])[0].get("value") if item.get("content") else item.get("summary") or "",
                    "link": item.get("link") or "",
                    "publisher": publisher,
                    "published_date": item.get("published") or datetime.now(timezone.utc),
                    "ticker": "", "yf_ticker": "", "event": "",
                }

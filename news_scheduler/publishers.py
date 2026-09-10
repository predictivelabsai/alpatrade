"""Publisher collection ported from the Finespresso scheduler inventory."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser

from news_scheduler.utils.scrape.web_util import fetch_url_content


_CONFIG = Path(__file__).resolve().parent / "config"
_BALTICS = "https://nasdaqbaltic.com/statistics/en/news?rss=1&num=100"


def _named_urls(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        name, url = raw.split(": ", 1) if ": " in raw else (path.stem, raw)
        rows.append((name.strip(), url.strip()))
    return rows


def finespresso_feed_inventory() -> list[tuple[str, str, str]]:
    """Load the same checked-in publisher inventory used by finespresso-admin."""
    feeds: list[tuple[str, str, str]] = [("baltics", "", _BALTICS)]
    feeds.extend(("prnewswire", name, url) for name, url in _named_urls(_CONFIG / "prnewswire_rss_urls.txt"))
    countries = json.loads((_CONFIG / "gnw_countries.json").read_text(encoding="utf-8"))
    feeds.extend((f"globenewswire_country_{code}", code, value["rss_url"])
                 for code, value in countries.items())
    feeds.extend(("globenewswire_sector", name, url)
                 for name, url in _named_urls(_CONFIG / "gnw_subject_rss_urls.txt"))
    feeds.extend(("globenewswire_industry", name, url)
                 for name, url in _named_urls(_CONFIG / "gnw_industry_rss_urls.txt"))
    return feeds


class FinespressoPublishers:
    """Yield raw articles; enrichment and persistence stay in AlpaTrade."""

    def __init__(self, feeds: str | None = None):
        raw = feeds if feeds is not None else os.getenv("NEWS_PUBLISHER_FEEDS", "")
        self.feeds = ([('configured_rss', '', item.strip()) for item in raw.split(',') if item.strip()]
                      if raw.strip() else finespresso_feed_inventory())

    def collect(self) -> Iterable[dict]:
        for publisher, topic, url in self.feeds:
            parsed = feedparser.parse(url)
            for item in parsed.entries:
                content = (item.get("content", [{}])[0].get("value")
                           if item.get("content") else item.get("summary") or "")
                link = item.get("link") or ""
                if not str(content).strip() and link:
                    fetched = fetch_url_content(
                        link, timeout=15,
                        use_improved_extraction=publisher in {"prnewswire", "euronext"},
                    )
                    content = "" if str(fetched).lower().startswith("failed to") else fetched
                yield {
                    "title": item.get("title") or "",
                    "content": content,
                    "link": link,
                    "publisher": publisher,
                    "publisher_topic": topic,
                    "published_date": item.get("published") or datetime.now(timezone.utc),
                    "ticker": "", "yf_ticker": "", "event": topic,
                }


# Backward-compatible import for the first PR revision.
RSSPublishers = FinespressoPublishers

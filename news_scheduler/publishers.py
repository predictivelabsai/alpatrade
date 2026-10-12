"""Publisher collection ported from the Finespresso scheduler inventory."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

from news_scheduler.utils.scrape.web_util import fetch_url_content


_CONFIG = Path(__file__).resolve().parent / "config"
_BALTICS = "https://nasdaqbaltic.com/statistics/en/news?rss=1&num=100"
# The former company-news page now returns an anti-bot 202/empty response to
# server-side clients. This official list view serves the same five-column table.
_EURONEXT = "https://live.euronext.com/en/listview/company-press-releases/404/all?page=0"
_EURONEXT_ROOT = "https://live.euronext.com"
_OMX = "https://api.news.eu.nasdaq.com/news/query.action"
LOGGER = logging.getLogger("alpatrade.news_worker")

# GlobeNewswire's www host started answering every non-browser client with an Akamai
# 403 on Fri 9 Oct 2026 (~13:37 UTC); its official RSS host still serves the same feeds.
_GNW_WWW_RSS = re.compile(r"^https?://(?:www\.)?globenewswire\.com/RssFeed/", re.I)
_GNW_RSS_ROOT = "https://rss.globenewswire.com/RssFeed/"
FEED_HEADERS = {
    "User-Agent": os.getenv("NEWS_FEED_USER_AGENT",
                            "AlpaTrade-NewsWorker/1.0 (+https://alpatrade.ai; RSS reader)"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
    "Accept-Language": "en",
}
_BLOCK_BASE_SECONDS = float(os.getenv("NEWS_FEED_BLOCK_BACKOFF_SECONDS", "900"))
_BLOCK_MAX_SECONDS = 6 * 3600.0
_BLOCKED: dict[str, tuple[float, int]] = {}   # host -> (retry_after_monotonic, strikes)
# Drained by the worker into alpatrade.news_worker_events (publisher_feed_blocked).
FEED_ALERTS: list[dict] = []


def gnw_rss_url(url: str) -> str:
    """Rewrite GlobeNewswire www RSS URLs to the RSS host (idempotent)."""
    return _GNW_WWW_RSS.sub(_GNW_RSS_ROOT, url or "")


def _host(url: str) -> str:
    return (re.match(r"^https?://([^/]+)", url or "") or [None, ""])[1].lower()


def fetch_feed(url: str, publisher: str = "", *, get=None, now=None):
    """Fetch an RSS feed with real headers; on 403/429 back off the whole host
    (exponential, capped) and raise an alert instead of silently parsing an error page."""
    get = get or requests.get
    now = now if now is not None else time.monotonic()
    host = _host(url)
    until, strikes = _BLOCKED.get(host, (0.0, 0))
    if until > now:
        return feedparser.parse(b"")
    response = get(url, headers=FEED_HEADERS, timeout=30)
    status = int(getattr(response, "status_code", 200) or 200)
    if status in (403, 429):
        strikes += 1
        wait = min(_BLOCK_MAX_SECONDS, _BLOCK_BASE_SECONDS * 2 ** (strikes - 1))
        _BLOCKED[host] = (now + wait, strikes)
        alert = {"event": "publisher_feed_blocked", "publisher": publisher, "host": host,
                 "status": status, "backoff_seconds": int(wait), "strikes": strikes}
        FEED_ALERTS.append(alert)
        LOGGER.error(json.dumps(alert))
        return feedparser.parse(b"")
    _BLOCKED.pop(host, None)
    if status >= 400:
        LOGGER.warning(json.dumps({"event": "publisher_feed_http_error", "publisher": publisher,
                                   "host": host, "status": status}))
        return feedparser.parse(b"")
    return feedparser.parse(response.content)


def _content(link: str, *, improved: bool = False) -> str:
    """Match the original per-article fallback without aborting a publisher."""
    if not link:
        return ""
    try:
        value = fetch_url_content(link, timeout=15, use_improved_extraction=improved)
        return "" if str(value).lower().startswith("failed to") else str(value or "")
    except Exception as exc:
        LOGGER.warning(json.dumps({"event": "publisher_article_fetch_failed",
                                   "error_type": type(exc).__name__}))
        return ""


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
    feeds.extend(("prnewswire_uk", name, url)
                 for name, url in _named_urls(_CONFIG / "prnewswire_uk_rss_urls.txt"))
    countries = json.loads((_CONFIG / "gnw_countries.json").read_text(encoding="utf-8"))
    feeds.extend((f"globenewswire_country_{code}", code, gnw_rss_url(value["rss_url"]))
                 for code, value in countries.items())
    feeds.extend(("globenewswire_sector", name, gnw_rss_url(url))
                 for name, url in _named_urls(_CONFIG / "gnw_subject_rss_urls.txt"))
    feeds.extend(("globenewswire_industry", name, gnw_rss_url(url))
                 for name, url in _named_urls(_CONFIG / "gnw_industry_rss_urls.txt"))
    return feeds


class FinespressoPublishers:
    """Yield raw articles; enrichment and persistence stay in AlpaTrade."""

    def __init__(self, feeds: str | None = None):
        raw = feeds if feeds is not None else os.getenv("NEWS_PUBLISHER_FEEDS", "")
        self.feeds = ([('configured_rss', '', item.strip()) for item in raw.split(',') if item.strip()]
                      if raw.strip() else finespresso_feed_inventory())

    @staticmethod
    def _rss(feeds: list[tuple[str, str, str]]) -> Iterable[dict]:
        """Yield one original-style row at a time from a related feed group."""
        for publisher, topic, url in feeds:
            stored_publisher = (f"globenewswire_{topic}"
                                if publisher in {"globenewswire_sector",
                                                 "globenewswire_industry"}
                                else publisher)
            parsed = fetch_feed(url, publisher)
            if getattr(parsed, "bozo_exception", None):
                LOGGER.warning(json.dumps({"event": "publisher_feed_warning",
                                           "publisher": publisher,
                                           "error_type": type(parsed.bozo_exception).__name__}))
            for item in parsed.entries:
                content = (item.get("content", [{}])[0].get("value")
                           if item.get("content") else item.get("summary") or "")
                link = item.get("link") or ""
                if not str(content).strip() and link:
                    content = _content(link, improved=publisher in {"prnewswire", "euronext"})
                yield {
                    "title": item.get("title") or "", "content": content,
                    "link": link, "publisher": stored_publisher,
                    "publisher_job": publisher,
                    "publisher_topic": topic,
                    "published_date": item.get("published") or datetime.now(timezone.utc),
                    "company": item.get("issuer") or "",
                    "ticker": "", "yf_ticker": "", "event": topic,
                    "language": item.get("dc_language") or "",
                    **(_uk_ticker(item) if publisher in {"prnewswire_uk", "globenewswire_country_uk"} else {}),
                }

    @staticmethod
    def _rns_nsm() -> Iterable[dict]:
        """FCA NSM public archive headlines (noise-filtered) as ``rns_nsm``."""
        from news_scheduler import uk_nsm
        hours = int(os.getenv("NEWS_NSM_LOOKBACK_HOURS", "26"))
        records = uk_nsm.fetch_records(hours, headers=FEED_HEADERS)
        yield from uk_nsm.rows(records, content=_content)

    @staticmethod
    def _euronext() -> Iterable[dict]:
        """Port the Euronext company-news table used by the original task."""
        response = requests.get(_EURONEXT, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", class_="table")
        if not table or not table.find("tbody"):
            return
        for row in table.find("tbody").find_all("tr"):
            columns = row.find_all("td")
            if len(columns) < 5:
                continue
            anchor = columns[2].find("a")
            if not anchor:
                continue
            link = str(anchor.get("href") or "")
            if link.startswith("/"):
                link = _EURONEXT_ROOT + link
            content = _content(link, improved=True)
            yield {
                "published_date": columns[0].get_text(" ", strip=True),
                "company": columns[1].get_text(" ", strip=True),
                "title": anchor.get_text(" ", strip=True), "link": link,
                "industry": columns[3].get_text(" ", strip=True),
                "publisher_topic": columns[4].get_text(" ", strip=True),
                "publisher": "euronext", "content": content,
                "publisher_job": "euronext",
                "ticker": "", "yf_ticker": "", "event": "", "language": "",
            }

    @staticmethod
    def _omx() -> Iterable[dict]:
        """Port the Nasdaq OMX JSON source used by the original task."""
        response = requests.get(_OMX, timeout=30)
        response.raise_for_status()
        for item in response.json().get("results", {}).get("item", []):
            languages = item.get("languages") or []
            if languages and "en" not in languages:
                continue
            link = item.get("messageUrl") or ""
            content = _content(link)
            yield {
                "published_date": item.get("published") or datetime.now(timezone.utc),
                "company": item.get("company") or "",
                "title": item.get("headline") or "", "link": link,
                "publisher_topic": item.get("cnsCategory") or "",
                "content": content, "publisher": "omx",
                "publisher_job": "omx",
                "ticker": "", "yf_ticker": "", "event": "",
                "language": item.get("language") or "",
                "market": item.get("market") or "",
            }

    def groups(self) -> list[tuple[str, Iterable[dict]]]:
        """Return the seven independently scheduled Finespresso publisher jobs."""
        if self.feeds and self.feeds[0][0] == "configured_rss":
            return [("configured_rss", self._rss(self.feeds))]
        by_name: dict[str, list[tuple[str, str, str]]] = {}
        for feed in self.feeds:
            by_name.setdefault(feed[0], []).append(feed)
        return [
            ("baltics", self._rss(by_name.get("baltics", []))),
            ("euronext", self._euronext()),
            ("omx", self._omx()),
            ("globenewswire_sector", self._rss(by_name.get("globenewswire_sector", []))),
            ("globenewswire_country", self._rss([
                feed for name, rows in by_name.items()
                if name.startswith("globenewswire_country_") for feed in rows])),
            ("globenewswire_industry", self._rss(by_name.get("globenewswire_industry", []))),
            ("prnewswire", self._rss(by_name.get("prnewswire", []))),
            ("prnewswire_uk", self._rss(by_name.get("prnewswire_uk", []))),
            ("rns_nsm", self._rns_nsm()),
        ]

    def collect(self, allow=None) -> Iterable[dict]:
        """Round-robin over publisher jobs. ``allow(job) -> bool`` is the worker's
        per-publisher quota: a job that has used its share is dropped from the
        rotation *before* its next article (and its content fetch) is pulled."""
        # Round-robin is the bounded equivalent of the original seven-task
        # scheduler: every healthy publisher gets a turn before any busy one
        # (notably PR Newswire) can consume the whole XAI budget.
        active = deque((name, iter(rows)) for name, rows in self.groups())
        while active:
            name, rows = active.popleft()
            if allow is not None and not allow(name):
                LOGGER.info(json.dumps({"event": "publisher_quota_reached", "publisher": name}))
                continue
            try:
                article = next(rows)
            except StopIteration:
                LOGGER.info(json.dumps({"event": "publisher_completed", "publisher": name}))
                continue
            except Exception as exc:
                LOGGER.error(json.dumps({"event": "publisher_failed", "publisher": name,
                                         "error_type": type(exc).__name__}))
                continue
            yield article
            active.append((name, rows))


_LSE_TICKER = re.compile(r"\((?:LSE|LON|AIM|London Stock Exchange)\s*:\s*([A-Z0-9]{1,5}(?:\.[A-Z])?)\)")


def _uk_ticker(item) -> dict:
    """``(LSE: VOD)`` in a UK release -> ticker VOD / yf_ticker VOD.L (dot -> dash)."""
    from news_scheduler.uk_nsm import tidm_to_yahoo
    text = f"{item.get('title') or ''} {item.get('summary') or ''}"
    m = _LSE_TICKER.search(text)
    if not m:
        return {}
    return {"ticker": m.group(1), "yf_ticker": tidm_to_yahoo(m.group(1)) or ""}


# Backward-compatible import for the first PR revision.
RSSPublishers = FinespressoPublishers

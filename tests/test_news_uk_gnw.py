"""GNW host fix + 403 backoff, per-publisher quotas, and the UK jobs (offline)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from news_scheduler import publishers as pubs
from news_scheduler import uk_nsm
from news_scheduler.publishers import FinespressoPublishers, finespresso_feed_inventory, gnw_rss_url
from news_scheduler.worker import Worker

RSS = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
       b'<item><title>Acme plc (LSE: BT.A) results</title><link>https://x/1</link>'
       b'<description>Body</description><pubDate>Fri, 09 Oct 2026 22:00 GMT</pubDate></item>'
       b'</channel></rss>')


class Resp:
    def __init__(self, status=200, content=RSS):
        self.status_code, self.content = status, content


@pytest.fixture(autouse=True)
def _clean():
    pubs._BLOCKED.clear()
    pubs.FEED_ALERTS.clear()
    yield
    pubs._BLOCKED.clear()
    pubs.FEED_ALERTS.clear()


def test_gnw_urls_use_rss_host():
    assert gnw_rss_url("https://www.globenewswire.com/RssFeed/country/Denmark/x") == \
        "https://rss.globenewswire.com/RssFeed/country/Denmark/x"
    assert gnw_rss_url("https://rss.globenewswire.com/RssFeed/a") == "https://rss.globenewswire.com/RssFeed/a"
    gnw = [u for p, _, u in finespresso_feed_inventory() if p.startswith("globenewswire")]
    assert gnw and all(u.startswith("https://rss.globenewswire.com/RssFeed/") for u in gnw)


def test_inventory_has_uk_sources():
    inv = finespresso_feed_inventory()
    names = {p for p, _, _ in inv}
    assert {"globenewswire_country_uk", "prnewswire_uk"} <= names
    assert all("prnewswire.co.uk" in u for p, _, u in inv if p == "prnewswire_uk")


def test_feed_403_backs_off_host_and_alerts():
    calls = []
    get = lambda url, **kw: calls.append(kw["headers"]["User-Agent"]) or Resp(403, b"Access Denied")
    assert pubs.fetch_feed("https://rss.globenewswire.com/RssFeed/a", "globenewswire_country", get=get, now=0).entries == []
    assert pubs.FEED_ALERTS[-1]["status"] == 403 and pubs.FEED_ALERTS[-1]["backoff_seconds"] == 900
    # same host inside the backoff window: no request at all
    pubs.fetch_feed("https://rss.globenewswire.com/RssFeed/b", "globenewswire_country", get=get, now=10)
    assert len(calls) == 1 and "AlpaTrade-NewsWorker" in calls[0]
    pubs.fetch_feed("https://rss.globenewswire.com/RssFeed/b", "x", get=get, now=1000)
    assert pubs.FEED_ALERTS[-1]["backoff_seconds"] == 1800  # exponential
    ok = pubs.fetch_feed("https://rss.globenewswire.com/RssFeed/c", "x", get=lambda *a, **k: Resp(), now=99999)
    assert len(ok.entries) == 1 and "rss.globenewswire.com" not in pubs._BLOCKED


def test_prnewswire_uk_rows_link_lse_ticker(monkeypatch):
    monkeypatch.setattr(pubs, "fetch_feed", lambda url, publisher="": pubs.feedparser.parse(RSS))
    row = next(FinespressoPublishers._rss([("prnewswire_uk", "all", "https://www.prnewswire.co.uk/rss/x.rss")]))
    assert row["publisher"] == "prnewswire_uk" and row["yf_ticker"] == "BT-A.L" and row["ticker"] == "BT.A"


def test_collect_respects_quota_and_skips_exhausted_job():
    p = FinespressoPublishers("https://example.test/feed")
    pulled = []

    def gen(name, n):
        for i in range(n):
            pulled.append(name)
            yield {"publisher": name, "link": f"{name}{i}"}
    p.groups = lambda: [("prnewswire", gen("prnewswire", 50)), ("globenewswire_country", gen("globenewswire_country", 3))]
    used = {}

    def allow(job):
        return used.get(job, 0) < 2
    rows = []
    for r in p.collect(allow=allow):
        used[r["publisher"]] = used.get(r["publisher"], 0) + 1
        rows.append(r["publisher"])
    assert rows.count("prnewswire") == 2 and rows.count("globenewswire_country") == 2
    assert pulled.count("prnewswire") == 2  # no content fetch beyond the quota


def test_worker_quota_keeps_prnewswire_from_starving_gnw(monkeypatch):
    monkeypatch.delenv("NEWS_WORKER_PUBLISHER_QUOTAS", raising=False)
    articles = [{"publisher": "prnewswire", "publisher_job": "prnewswire", "link": f"p{i}"} for i in range(40)]
    articles += [{"publisher": "globenewswire_country_dk", "publisher_job": "globenewswire_country", "link": f"g{i}"} for i in range(5)]
    publishers = MagicMock()
    publishers.collect.side_effect = lambda allow=None: iter(articles)
    repo = MagicMock()
    repo.checkpoint.return_value = {"processed_count": 0, "failed_count": 0}
    repo.article_exists.return_value = False
    repo.insert_pending.side_effect = range(1, 100)
    pipeline = MagicMock()
    pipeline.enrich_best_effort.return_value = ({}, [], [])
    w = Worker("realtime", 25, 60, 0, 1, repository=repo, pipeline=pipeline, publishers=publishers)
    assert w.publisher_quota("prnewswire") == 9
    w._realtime_cycle()
    jobs = [c.args[0]["publisher_job"] for c in repo.insert_pending.call_args_list]
    assert jobs.count("prnewswire") == 9 and jobs.count("globenewswire_country") == 5
    monkeypatch.setenv("NEWS_WORKER_PUBLISHER_QUOTAS", "prnewswire=3,default=4")
    assert (w.publisher_quota("prnewswire"), w.publisher_quota("rns_nsm")) == (3, 4)


def test_worker_records_feed_block_event():
    repo = MagicMock()
    w = Worker("realtime", 25, 60, 0, 1, repository=repo, pipeline=MagicMock(), publishers=MagicMock())
    pubs.FEED_ALERTS.append({"event": "publisher_feed_blocked", "publisher": "globenewswire_country",
                             "host": "www.globenewswire.com", "status": 403, "backoff_seconds": 900})
    w._drain_feed_alerts()
    args, kwargs = repo.record_event.call_args
    assert args[2:4] == ("publisher_feed_blocked", "error") and kwargs["details"]["status"] == 403
    assert pubs.FEED_ALERTS == []


def test_nsm_noise_filter_and_rows():
    recs = [
        {"type": "Trading Statement", "headline": "Q3 trading update", "source": "RNS", "company": "TESCO PLC;",
         "html_link": "NSM/RNS/a.html", "publication_date": "2026-10-08T07:00:00.000Z"},
        {"type": "Form 8.3", "headline": "Form 8.3 - Tesco", "source": "RNS", "company": "X", "html_link": "NSM/RNS/b.html"},
        {"type": "Form 8.5 (EPT/NON-RI)", "headline": "x", "source": "RNS", "company": "X", "html_link": "NSM/RNS/c.html"},
        {"type": "Transaction in Own Shares", "headline": "Transaction in Own Shares", "source": "RNS",
         "company": "X", "html_link": "NSM/RNS/d.html"},
        {"type": "Final Terms", "headline": "Final Terms", "source": "Direct Upload", "company": "X",
         "download_link": "NSM/DirectUpload/e.pdf"},
    ]
    out = list(uk_nsm.rows(recs, content=lambda link: "Full text"))
    assert len(out) == 1
    r = out[0]
    assert r["link"] == "https://data.fca.org.uk/artefacts/NSM/RNS/a.html"
    assert (r["publisher"], r["publisher_job"], r["yf_ticker"], r["ticker"]) == ("rns_nsm", "rns_nsm", "TSCO.L", "TSCO")
    assert r["content"] == "Full text" and r["company"] == "TESCO PLC"


def test_nsm_query_shape_and_paging():
    body = uk_nsm.query(datetime(2026, 10, 8, tzinfo=timezone.utc), datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert body["criteriaObj"]["dateCriteria"][0]["name"] == "publication_date"
    assert uk_nsm.NSM_SEARCH.endswith("index=nsm-search")
    pages = [{"hits": {"hits": [{"_source": {"i": i}} for i in range(500)]}}, {"hits": {"hits": [{"_source": {"i": 1}}]}}]
    seen = []
    got = uk_nsm.fetch_records(24, post=lambda b: seen.append(b["from"]) or pages[len(seen) - 1])
    assert len(got) == 501 and seen == [0, 500]


def test_tidm_to_yahoo():
    assert [uk_nsm.tidm_to_yahoo(t) for t in ("VOD", "BT.A", "BP.", "rr.l")] == ["VOD.L", "BT-A.L", "BP.L", "RR.L"]

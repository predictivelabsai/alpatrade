#!/usr/bin/env python3
"""Download + cache Alpaca 5-min bars incl. extended hours (SIP pre/post since 2016) and the
BOATS overnight feed (20:00-04:00 ET, available from ~2024-10). Cache: data/intraday/<feed>/<SYM>.pkl.gz
(one file per symbol/feed, appended incrementally). Read-only market data; no orders.

  python scripts/fetch_intraday_bars.py AAPL MSFT --start 2016-01-01 [--feeds sip,boats]
"""
from __future__ import annotations
import argparse, os, time
import pandas as pd, requests
from dotenv import dotenv_values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "intraday")
URL = "https://data.alpaca.markets/v2/stocks/{sym}/bars"


def _hdr():
    e = {**dotenv_values(os.path.join(ROOT, ".env")), **os.environ}
    return {"APCA-API-KEY-ID": e["ALPACA_PAPER_API_KEY"], "APCA-API-SECRET-KEY": e["ALPACA_PAPER_SECRET_KEY"]}


def path(sym: str, feed: str) -> str:
    return os.path.join(CACHE, feed, f"{sym}.pkl.gz")


def load(sym: str, feed: str = "sip") -> pd.DataFrame:
    p = path(sym, feed)
    return pd.read_pickle(p) if os.path.exists(p) else pd.DataFrame(columns=["t", "o", "h", "l", "c", "v"])


def fetch(sym: str, start: str, end: str | None = None, feed: str = "sip", tf: str = "5Min") -> pd.DataFrame:
    old = load(sym, feed)
    if len(old):
        start = (pd.Timestamp(old["t"].max()) + pd.Timedelta(minutes=5)).isoformat()
    if end and pd.Timestamp(start) >= pd.Timestamp(end):
        return old
    rows, tok, h = [], None, _hdr()
    while True:
        q = {"timeframe": tf, "start": start, "feed": feed, "limit": 10000, "adjustment": "all", "sort": "asc"}
        if end: q["end"] = end
        if tok: q["page_token"] = tok
        for i in range(12):
            r = requests.get(URL.format(sym=sym), headers=h, params=q, timeout=60)
            if r.status_code == 429: time.sleep(min(60, 5 * (i + 1))); continue
            break
        r.raise_for_status()        # never cache a silently truncated history
        j = r.json(); rows += j.get("bars") or []; tok = j.get("next_page_token")
        if not tok: break
    new = pd.DataFrame(rows)
    if len(new):
        new = new[["t", "o", "h", "l", "c", "v"]]; new["t"] = pd.to_datetime(new["t"], utc=True)
    df = pd.concat([old, new]).drop_duplicates("t").sort_values("t").reset_index(drop=True) if len(new) else old
    os.makedirs(os.path.dirname(path(sym, feed)), exist_ok=True)
    df.to_pickle(path(sym, feed))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("syms", nargs="+"); ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end"); ap.add_argument("--feeds", default="sip,boats")
    a = ap.parse_args()
    for f in a.feeds.split(","):
        for s in a.syms:
            d = fetch(s, a.start if f == "sip" else max(a.start, "2024-09-01"), a.end, f)
            print(f, s, len(d), d["t"].min() if len(d) else None, d["t"].max() if len(d) else None, flush=True)

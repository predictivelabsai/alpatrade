#!/usr/bin/env python3
"""Chat With Traders -> backtested Leaderboard strategy pipeline.

Steps (run one at a time, or chained):
    catalogue   scrape chatwithtraders.com stock-topic episodes -> data/cwt/episodes.csv
                (+ alpatrade.cwt_episodes with --db), incl. mp3 + YouTube URL
    transcribe  YouTube auto-captions via yt-dlp (free) -> data/cwt/<ep>/transcript.txt;
                --gemini also asks Gemini to summarise the strategy from the YouTube URL
    extract     Grok (XAI_API_KEY) turns the transcript into a structured spec JSON
                -> data/cwt/<ep>/spec.json (the skill.md is written by `backtest`)
    backtest    daily-bar backtest of the spec (scripts/cwt_backtest.py engine)
                -> data/cwt/<ep>/backtest.json + skill.md
    publish     upsert a public kind='backtest' row in alpatrade.user_strategies

Usage:
    python scripts/cwt_pipeline.py catalogue [--db] [--no-youtube]
    python scripts/cwt_pipeline.py transcribe --episode 318 [--gemini]
    python scripts/cwt_pipeline.py extract    --episode 318
    python scripts/cwt_pipeline.py backtest   --episode 318
    python scripts/cwt_pipeline.py publish    --episode 318
    python scripts/cwt_pipeline.py all        --episode 318      # every step for one episode
    python scripts/cwt_pipeline.py transcribe --all              # bulk (not run yet)

Secrets are read from the environment only (never printed).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "cwt"
CSV_PATH = DATA / "episodes.csv"
SITE = "https://chatwithtraders.com"
YTDLP = str(Path(sys.executable).with_name("yt-dlp")) if Path(sys.executable).with_name("yt-dlp").exists() else "yt-dlp"
UA = {"User-Agent": "Mozilla/5.0 (AlpaTrade research; cwt_pipeline)"}
FIELDS = ["episode_number", "slug", "title", "guest", "page_url", "audio_url", "youtube_url",
          "youtube_id", "pub_date", "duration_sec", "categories", "tags"]
_NGSTATE = re.compile(r'<script id="ng-state" type="application/json">(.*?)</script>', re.S)


# ---------------------------------------------------------------- catalogue
def _ng_state(html: str) -> dict:
    m = _NGSTATE.search(html)
    return json.loads(m.group(1)) if m else {}


def _episode(url: str) -> dict | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    else:
        return None
    for v in _ng_state(r.text).values():
        b = v.get("b") if isinstance(v, dict) else None
        if isinstance(b, dict) and "/api/episode/slug/" in str(v.get("u", "")):
            return b
    return None


def _guest(title: str) -> str:
    t = re.sub(r"^\s*\d+\s*[·.\-:]\s*", "", title or "")
    return re.split(r"\s+[-–—]\s+", t, maxsplit=1)[0].strip()


_STOP = {"the", "a", "an", "and", "of", "to", "in", "on", "for", "with", "how", "from", "is",
         "pt", "part", "trader", "trading", "traders", "my", "your", "you"}


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2 and w not in _STOP}


def youtube_lookup(number: str, guest: str, title: str = "") -> tuple[str, str, int]:
    """Best YouTube match on the Chat With Traders channel via yt-dlp ytsearch.

    Score = guest surname in the video title (required) + 3 if the episode number appears +
    1 per shared subtitle word, so repeat guests get the right episode. Returns (url, id, score).
    """
    subtitle = re.split(r"\s+[-–—]\s+", title, maxsplit=1)[-1] if title else ""
    q = f"ytsearch8:Chat With Traders {guest} {subtitle}"[:200]
    try:
        out = subprocess.run([YTDLP, "--flat-playlist", "-J", q], capture_output=True,
                             text=True, timeout=90).stdout
        entries = json.loads(out or "{}").get("entries") or []
    except Exception:
        return "", "", 0
    last = guest.replace(",", " ").split()[-1].lower() if guest else ""
    sub = _words(subtitle) - _words(guest)
    best = ("", "", 0)
    for e in entries:
        ch = (e.get("channel") or e.get("uploader") or "").lower()
        vt = (e.get("title") or "").lower()
        if "chat with traders" not in ch or not last or last not in vt:
            continue
        score = 1 + (3 if number and re.search(rf"\b{int(number)}\b", vt) else 0) + len(sub & _words(vt))
        if score > best[2]:
            best = (f"https://www.youtube.com/watch?v={e['id']}", e["id"], score)
    return best


def catalogue(topic: str = "stocks", youtube: bool = True, db: bool = False) -> list[dict]:
    sm = requests.get(f"{SITE}/sitemap.xml", headers=UA, timeout=30).text
    urls = sorted(set(re.findall(r"<loc>([^<]*/episode/[^<]+)</loc>", sm)))
    with ThreadPoolExecutor(8) as ex:
        eps = [e for e in ex.map(_episode, urls) if e]
    rows = []
    for e in eps:
        cats = [c.get("slug") for c in (e.get("categories") or []) if isinstance(c, dict)]
        if topic not in cats:
            continue
        rows.append({
            "episode_number": e.get("episodeNumber") or "",
            "slug": e.get("slug"), "title": e.get("title"), "guest": _guest(e.get("title")),
            "page_url": f"{SITE}/episode/{e.get('slug')}",
            "audio_url": (e.get("soundLink") or "").split("?")[0],
            "youtube_url": e.get("videoUrl") or "", "youtube_id": "",
            "pub_date": (e.get("pubDate") or "")[:10], "duration_sec": e.get("duration") or "",
            "categories": ";".join(c for c in cats if c),
            "tags": ";".join(t.get("name", "") for t in (e.get("tags") or []) if isinstance(t, dict)),
        })
    rows.sort(key=lambda r: int(r["episode_number"] or 0), reverse=True)
    if youtube:
        def yt(r):
            r["_score"] = 9
            if not r["youtube_url"]:
                r["youtube_url"], r["youtube_id"], r["_score"] = youtube_lookup(
                    r["episode_number"], r["guest"], r["title"])
            return r
        with ThreadPoolExecutor(4) as ex:
            rows = list(ex.map(yt, rows))
        # one video belongs to one episode: keep the best-scoring claim, blank the others
        best: dict[str, dict] = {}
        for r in rows:
            u = r["youtube_url"]
            if u and (u not in best or r["_score"] > best[u]["_score"]):
                best[u] = r
        for r in rows:
            if r["youtube_url"] and best[r["youtube_url"]] is not r:
                r["youtube_url"] = r["youtube_id"] = ""
            r.pop("_score", None)
    DATA.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if db:
        save_db(rows)
    print(f"catalogue: {len(rows)} '{topic}' episodes of {len(eps)} -> {CSV_PATH.relative_to(ROOT)}; "
          f"{sum(1 for r in rows if r['youtube_url'])} with a YouTube URL")
    return rows


def save_db(rows: list[dict]) -> None:
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    sql = (ROOT / "sql" / "43_cwt_episodes.sql").read_text()
    with DatabasePool().get_session() as s:
        s.execute(text(sql))
        for r in rows:
            s.execute(text("""
                INSERT INTO alpatrade.cwt_episodes (slug, episode_number, title, guest, page_url,
                    audio_url, youtube_url, pub_date, duration_sec, categories, tags, updated_at)
                VALUES (:slug, :n, :title, :guest, :page_url, :audio_url, :youtube_url,
                    CAST(NULLIF(:pub_date,'') AS DATE), CAST(NULLIF(:duration_sec,'') AS INT),
                    :categories, :tags, NOW())
                ON CONFLICT (slug) DO UPDATE SET episode_number = EXCLUDED.episode_number,
                    title = EXCLUDED.title, guest = EXCLUDED.guest, audio_url = EXCLUDED.audio_url,
                    youtube_url = EXCLUDED.youtube_url, pub_date = EXCLUDED.pub_date,
                    duration_sec = EXCLUDED.duration_sec, categories = EXCLUDED.categories,
                    tags = EXCLUDED.tags, updated_at = NOW()
            """), {**r, "n": int(r["episode_number"] or 0) or None})
    print(f"catalogue: upserted {len(rows)} rows into alpatrade.cwt_episodes")


def load_catalogue() -> list[dict]:
    with CSV_PATH.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_episode(key: str) -> dict:
    for r in load_catalogue():
        if key in (r["episode_number"], r["slug"]):
            return r
    raise SystemExit(f"episode {key!r} not in {CSV_PATH}")


def ep_dir(ep: dict) -> Path:
    d = DATA / ep["slug"]
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- transcribe
def _hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def captions_to_text(json3: dict, para_sec: int = 30) -> str:
    """yt-dlp json3 auto-captions -> '[hh:mm:ss] text' paragraphs of ~para_sec seconds."""
    out, buf, start = [], [], None
    for ev in json3.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t = ev.get("tStartMs", 0) / 1000.0
        if start is None:
            start = t
        buf.append("".join(s.get("utf8", "") for s in segs).replace("\n", " "))
        if t - start >= para_sec:
            out.append(f"[{_hms(start)}] " + re.sub(r"\s+", " ", " ".join(buf)).strip())
            buf, start = [], None
    if buf:
        out.append(f"[{_hms(start or 0)}] " + re.sub(r"\s+", " ", " ".join(buf)).strip())
    return "\n".join(x for x in out if x.split("] ", 1)[-1])


def transcribe_youtube(ep: dict) -> Path | None:
    vid = (ep.get("youtube_url") or "").rsplit("v=", 1)[-1]
    if not vid:
        return None
    d = ep_dir(ep)
    for lang in ("en-orig", "en"):
        subprocess.run([YTDLP, "--skip-download", "--ignore-no-formats-error", "--write-auto-subs", "--write-subs",
                        "--sub-langs", lang, "--sub-format", "json3", "-o", str(d / "captions"),
                        f"https://www.youtube.com/watch?v={vid}"], capture_output=True, timeout=180)
        f = d / f"captions.{lang}.json3"
        if f.exists():
            txt = captions_to_text(json.loads(f.read_text(encoding="utf-8")))
            out = d / "transcript.txt"
            out.write_text(f"# {ep['title']}\n# source: YouTube auto-captions ({lang}) "
                           f"https://www.youtube.com/watch?v={vid}\n\n{txt}\n", encoding="utf-8")
            return out
    return None


def transcribe_whisper(ep: dict, model: str = "small") -> Path | None:
    """Fallback when there are no captions: faster-whisper on the episode mp3 (CPU int8)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed (pip install faster-whisper)")
        return None
    d = ep_dir(ep)
    mp3 = d / "audio.mp3"
    if not mp3.exists():
        with requests.get(ep["audio_url"], headers=UA, stream=True, timeout=120) as r:
            r.raise_for_status()
            with mp3.open("wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
    segs, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(str(mp3))
    txt = "\n".join(f"[{_hms(s.start)}] {s.text.strip()}" for s in segs)
    out = d / "transcript.txt"
    out.write_text(f"# {ep['title']}\n# source: faster-whisper {model}\n\n{txt}\n", encoding="utf-8")
    return out


GEMINI_PROMPT = (
    "You are a quantitative trading researcher. This is a Chat With Traders podcast episode "
    "with {guest}. Extract the guest's trading strategy as precisely as possible so it can be "
    "backtested on DAILY bars of US stocks: universe and screens, setup and entry rules, stop "
    "loss, exits (partials, trailing rules), position sizing and risk per trade, timeframe and "
    "holding period, market-regime filters. For every rule give a short verbatim quote and its "
    "timestamp (mm:ss or hh:mm:ss). Then list what is ambiguous or not testable on daily bars. "
    "Answer in Markdown.")


def gemini_summary(ep: dict, model: str = "gemini-2.5-flash") -> Path | None:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or not ep.get("youtube_url"):
        return None
    body = {"contents": [{"parts": [
        {"file_data": {"file_uri": ep["youtube_url"]}},
        {"text": GEMINI_PROMPT.format(guest=ep["guest"])}]}],
        # LOW media resolution (~100 tokens/s of video) keeps a 90-min episode under 1M tokens
        "generationConfig": {"mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      params={"key": key}, json=body, timeout=900)
    if not r.ok:
        print(f"gemini: HTTP {r.status_code} {r.text[:300]}")
        return None
    j = r.json()
    text = "".join(p.get("text", "") for c in j.get("candidates", [])
                   for p in (c.get("content") or {}).get("parts", []))
    usage = j.get("usageMetadata") or {}
    out = ep_dir(ep) / "gemini_strategy.md"
    out.write_text(f"<!-- model: {model}; source: {ep['youtube_url']}; usage: "
                   f"{json.dumps(usage)} -->\n\n{text}\n", encoding="utf-8")
    return out


def transcribe(ep: dict, gemini: bool = False) -> None:
    out = transcribe_youtube(ep) or transcribe_whisper(ep)
    print(f"transcribe {ep['episode_number']}: {out.relative_to(ROOT) if out else 'FAILED'}")
    if gemini:
        g = gemini_summary(ep)
        print(f"gemini {ep['episode_number']}: {g.relative_to(ROOT) if g else 'skipped/failed'}")


# ---------------------------------------------------------------- extract
SPEC_SCHEMA = {
    "trader": "str", "style": "str", "timeframe": "str",
    "universe": {"description": "str", "min_price": "float", "min_dollar_volume_20d": "float"},
    "setup": [{"rule": "str", "quote": "str", "timestamp": "hh:mm:ss"}],
    "entry": [{"rule": "str", "quote": "str", "timestamp": "hh:mm:ss"}],
    "stop": [{"rule": "str", "quote": "str", "timestamp": "hh:mm:ss"}],
    "exits": [{"rule": "str", "quote": "str", "timestamp": "hh:mm:ss"}],
    "sizing": [{"rule": "str", "quote": "str", "timestamp": "hh:mm:ss"}],
    "market_filter": [{"rule": "str", "quote": "str", "timestamp": "hh:mm:ss"}],
    "ambiguities": [{"issue": "str", "assumption": "str"}],
    "daily_bar_params": {
        "momentum_lookback_days": "int", "momentum_min_pct": "float",
        "consolidation_days": "int", "consolidation_max_range_pct": "float",
        "volume_mult": "float", "stop": "str", "partial_after_days": "int",
        "partial_frac": "float", "trail_ma": "int", "risk_per_trade_pct": "float",
        "max_position_pct": "float", "max_positions": "int"},
}

EXTRACT_PROMPT = """You turn a trading-podcast transcript into a precise, testable strategy spec.
Trader: {guest}. Episode: {title}.
Rules:
- Use ONLY what the guest says (quote verbatim, with the [hh:mm:ss] timestamp of the transcript
  paragraph the quote is in). Do not invent quotes. If a rule is common knowledge about this
  trader but not said in this episode, put it in "ambiguities" with your assumption.
- "daily_bar_params" must be concrete numbers that approximate the rules on DAILY bars.
Return ONLY a JSON object with this shape:
{schema}

Transcript:
{transcript}
"""


def grok(prompt: str, model: str = "grok-4.3") -> str:
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise SystemExit("XAI_API_KEY not set")
    r = requests.post("https://api.x.ai/v1/chat/completions", timeout=900,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "temperature": 0.1,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def extract(ep: dict, model: str = "grok-4.3") -> Path:
    d = ep_dir(ep)
    transcript = (d / "transcript.txt").read_text(encoding="utf-8")
    raw = grok(EXTRACT_PROMPT.format(guest=ep["guest"], title=ep["title"],
                                     schema=json.dumps(SPEC_SCHEMA, indent=1),
                                     transcript=transcript), model=model)
    spec = json.loads(raw)
    spec["_meta"] = {"model": model, "episode": ep["episode_number"], "page_url": ep["page_url"],
                     "youtube_url": ep["youtube_url"]}
    out = d / "spec.json"
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"extract {ep['episode_number']}: {out.relative_to(ROOT)}")
    return out


# ---------------------------------------------------------------- backtest
BARS = DATA / "bars"
BT_START, BT_END = "2016-01-01", None  # Alpaca SIP daily history starts 2016
TRAIN_END = "2021-12-31"               # train 2016-2021, test 2022 -> latest


def universe() -> list[str]:
    """Current S&P 500 members (Wikipedia). Survivorship-biased: today's members only."""
    import io
    import pandas as pd
    f = BARS / "universe_sp500.csv"
    if f.exists():
        return pd.read_csv(f)["symbol"].tolist()
    html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                        headers=UA, timeout=30).text
    syms = sorted(pd.read_html(io.StringIO(html))[0]["Symbol"])
    BARS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": syms}).to_csv(f, index=False)
    return syms


def load_bars(symbols: list[str], start: str = BT_START, end: str | None = BT_END) -> dict:
    """Daily bars from Alpaca (alpaca-py, the same source as engine.backtest.data), cached as
    CSV under data/cwt/bars/. adjustment='all' (splits + dividends) for strategy and SPY."""
    import pandas as pd
    from datetime import datetime
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from engine.backtest.data import _paper_keys
    BARS.mkdir(parents=True, exist_ok=True)
    out, missing = {}, []
    for s in symbols:
        f = BARS / f"{s.replace('/', '_')}.csv"
        if f.exists():
            out[s] = pd.read_csv(f, index_col=0, parse_dates=True)
        else:
            missing.append(s)
    if missing:
        client = StockHistoricalDataClient(*_paper_keys())
        for i in range(0, len(missing), 50):
            chunk = missing[i:i + 50]
            req = StockBarsRequest(symbol_or_symbols=chunk, timeframe=TimeFrame.Day,
                                   start=datetime.fromisoformat(start),
                                   end=datetime.fromisoformat(end) if end else None,
                                   feed=DataFeed(os.getenv("CWT_FEED", "sip")),
                                   adjustment=Adjustment.ALL)
            data = client.get_stock_bars(req).data
            for s in chunk:
                rows = [b.model_dump() for b in data.get(s, [])]
                if not rows:
                    continue
                df = pd.DataFrame(rows)
                df["t"] = pd.to_datetime(df["timestamp"]).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
                df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c",
                                        "volume": "v"})[["t", "o", "h", "l", "c", "v"]].set_index("t")
                df.to_csv(BARS / f"{s.replace('/', '_')}.csv")
                out[s] = df
            print(f"  bars: {min(i + 50, len(missing))}/{len(missing)}", flush=True)
    return out


def _fmt(m: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()
            if k not in ("equity", "trips")}


GRID = {"mom_min": [0.2, 0.3, 0.5], "cons_days": [10, 20], "trail_ma": [10, 20],
        "partial_days": [3, 5]}


def backtest(ep: dict, grid: bool = True) -> Path:
    """Fixed spec params on train / test / full, plus a train-optimised (by Sharpe) grid
    config traded out-of-sample on the test window (anti-over-fit check)."""
    import itertools
    from engine.backtest.breakout import BreakoutParams, run
    d = ep_dir(ep)
    spec = json.loads((d / "spec.json").read_text(encoding="utf-8"))
    bars = load_bars(universe() + ["SPY"])
    spy = bars.pop("SPY")
    end = str(spy.index[-1].date())
    test_start = str((spy.index[spy.index > TRAIN_END][0]).date())
    base = spec_params(spec)
    res = {"universe": f"S&P 500 current members ({len(bars)} with data)",
           "data": "Alpaca SIP daily bars, adjustment=all (splits+dividends)",
           "spec_params": base.to_dict()}
    for name, (a, b) in {"train": (BT_START, TRAIN_END), "test": (test_start, end),
                         "full": (BT_START, end)}.items():
        r = run(bars, spy, a, b, base)
        res[name] = _fmt(r)
        if name == "full":
            r["equity"].to_csv(d / "equity_full.csv", header=["equity"])
            with (d / "trades_full.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(r["trips"][0].keys()) if r["trips"] else ["symbol"])
                w.writeheader()
                w.writerows(r["trips"])
        print(f"  {name}: CAGR {r['annualised_pct']:.1f}% Sharpe {r['sharpe']:.2f} "
              f"MDD {r['max_drawdown_pct']:.1f}% trades {r['trades']} vs SPY "
              f"{r['spy_annualised_pct']:.1f}%", flush=True)
    if grid:
        best, rows = None, []
        for combo in itertools.product(*GRID.values()):
            pp = BreakoutParams(**{**base.to_dict(), **dict(zip(GRID, combo))})
            r = run(bars, spy, BT_START, TRAIN_END, pp)
            rows.append({**dict(zip(GRID, combo)), "train_sharpe": round(r["sharpe"], 3),
                         "train_cagr": round(r["annualised_pct"], 2)})
            if best is None or r["sharpe"] > best[0]:
                best = (r["sharpe"], pp)
        oos = run(bars, spy, test_start, end, best[1])
        res["grid"] = {"objective": "train Sharpe", "n_configs": len(rows), "rows": rows,
                       "best_params": {k: getattr(best[1], k) for k in GRID},
                       "test_oos": _fmt(oos)}
        print(f"  grid best {res['grid']['best_params']} -> test CAGR "
              f"{oos['annualised_pct']:.1f}% Sharpe {oos['sharpe']:.2f}", flush=True)
    out = d / "backtest.json"
    out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    (d / "skill.md").write_text(skill_md(ep, spec, res), encoding="utf-8")
    print(f"backtest {ep['episode_number']}: {out.relative_to(ROOT)} + skill.md")
    return out


def spec_params(spec: dict):
    """Map the LLM's daily_bar_params onto BreakoutParams (clamped to sane ranges)."""
    from engine.backtest.breakout import BreakoutParams
    q = spec.get("daily_bar_params") or {}

    def num(k, default, lo, hi, cast=float):
        try:
            return cast(min(max(float(q.get(k, default)), lo), hi))
        except (TypeError, ValueError):
            return default
    mom_days = num("momentum_lookback_days", 63, 20, 252, int)
    return BreakoutParams(
        mom_days=mom_days, mom_min=num("momentum_min_pct", 30, 10, 200) / 100,
        cons_days=num("consolidation_days", 15, 5, 60, int),
        cons_max_range=num("consolidation_max_range_pct", 15, 5, 40) / 100,
        trail_ma=10 if int(q.get("trail_ma") or 20) <= 10 else 20,
        partial_days=num("partial_after_days", 4, 2, 10, int),
        partial_frac=num("partial_frac", 0.33, 0.1, 0.5),
        risk_pct=num("risk_per_trade_pct", 1.0, 0.25, 2.0) / 100,
        max_pos_pct=num("max_position_pct", 20, 5, 25) / 100,
        max_positions=num("max_positions", 10, 3, 20, int))


# ---------------------------------------------------------------- skill.md
def _rules(items) -> str:
    out = []
    for it in items or []:
        q = (it.get("quote") or "").strip()
        ts = it.get("timestamp") or ""
        out.append(f"- {it.get('rule', '').strip()}"
                   + (f"  \n  > \"{q}\" — [{ts}]" if q else ""))
    return "\n".join(out) or "- (not stated in the episode)"


def _pct(v) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def skill_md(ep: dict, spec: dict, res: dict) -> str:
    trader = spec.get("trader") or ep["guest"]
    full, train, test = res["full"], res["train"], res["test"]
    p = res["spec_params"]
    g = res.get("grid") or {}
    title = f"{trader} · Momentum breakout (backtest)"
    desc = (f"Daily-bar backtest of the breakout swing method {trader} describes on Chat With "
            f"Traders ep. {ep['episode_number']}: strong prior momentum, tight consolidation, "
            f"breakout entry, low-of-day stop, partial after {p['partial_days']} days, trail "
            f"on the {p['trail_ma']}-day MA. S&P 500, cash only. Backtest, not live.")
    yt = ep.get("youtube_url") or ""
    rows = [("Annualised return (CAGR)", "annualised_pct", "spy_annualised_pct"),
            ("Total return", "total_return_pct", "spy_return_pct"),
            ("Sharpe (daily, N-1)", "sharpe", "spy_sharpe"),
            ("Max drawdown", "max_drawdown_pct", "spy_max_drawdown_pct")]

    def table(m):
        lines = ["| Metric | Strategy | SPY |", "|---|---|---|"]
        for label, a, b in rows:
            fa = f"{m[a]:.2f}" if "sharpe" in a else _pct(m[a])
            fb = f"{m[b]:.2f}" if "sharpe" in b else _pct(m[b])
            lines.append(f"| {label} | {fa} | {fb} |")
        lines += [f"| Alpha vs SPY (total return) | {_pct(m['alpha_pct'])} | |",
                  f"| Alpha vs SPY (annualised) | {_pct(m['alpha_annualised_pct'])} | |",
                  f"| CAPM alpha (ann.) / beta | {_pct(m['capm_alpha_ann_pct'])} / {m['beta']:.2f} | |",
                  f"| Trades / win rate | {m['trades']} / {m['win_rate_pct']:.1f}% | |",
                  f"| Avg win / avg loss | {_pct(m['avg_win_pct'])} / {_pct(m['avg_loss_pct'])} | |",
                  f"| Time invested | {m['exposure_pct']:.0f}% | 100% |"]
        return "\n".join(lines)

    amb = "\n".join(f"- **{a.get('issue')}** → assumption: {a.get('assumption')}"
                    for a in spec.get("ambiguities") or [])
    params = {
        "schema": "alpatrade.strategy_config/v1", "name": f"cwt_{ep['episode_number']}_breakout",
        "display_name": title, "kind": "backtest",
        "params": {**p, "universe": "sp500_current", "timeframe": "1d",
                   "entry": "buy_stop_at_consolidation_high", "stop": "entry_day_low_capped_adr",
                   "market_filter_rule": "SPY SMA10 > SMA20 (prior close)"},
        "execution": {"sizing": "risk_pct of equity / (ADR x price), capped at max_pos_pct, cash only",
                      "slippage_bps_per_side": p["slippage_bps"], "fill": "stop price or open if gapped"},
        "backtest": {"engine": "engine.backtest.breakout", "data": res["data"],
                     "universe": res["universe"], "train": [train["period_start"], train["period_end"]],
                     "test": [test["period_start"], test["period_end"]],
                     "full": [full["period_start"], full["period_end"]], "benchmark": "SPY"},
        "source": {"site": "chatwithtraders.com", "episode": ep["episode_number"],
                   "url": ep["page_url"], "youtube": yt},
    }
    grid_txt = ""
    if g:
        o = g["test_oos"]
        grid_txt = (f"\n### Train-optimised check\nA {g['n_configs']}-config grid "
                    f"({', '.join(GRID)}) was optimised on the train window by Sharpe; the best "
                    f"({json.dumps(g['best_params'])}) then traded the unseen test window: CAGR "
                    f"{_pct(o['annualised_pct'])} vs SPY {_pct(o['spy_annualised_pct'])}, Sharpe "
                    f"{o['sharpe']:.2f}, max drawdown {_pct(o['max_drawdown_pct'])}, {o['trades']} trades.\n")
    return f"""---
title: {title}
description: {desc}
kind: backtest
author: {trader}
source: chatwithtraders.com
source_url: {ep['page_url']}
tags: breakout, momentum, swing, chat-with-traders, backtest
license: MIT
---

# {title}

*For research and education only. This is not investment advice. This is AlpaTrade's
interpretation of rules {trader} described in a podcast interview, backtested on daily bars.
It is **not** {trader}'s own code, account or track record, and it has **never been traded
live** on AlpaTrade.*

Source: Chat With Traders ep. {ep['episode_number']}, "{ep['title']}" — {ep['page_url']}
{('(YouTube: ' + yt + ')') if yt else ''}

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this whole file into a new chat, then ask, for example:
  "Re-run this backtest on a small/mid-cap universe", "Write pandas code for the signals",
  or "Which assumption would you stress-test first?"
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (with quotes from the episode)
Timestamps refer to the YouTube auto-caption transcript.

### Universe
{spec.get('universe', {}).get('description', '')}. **Backtested on:** {res['universe']}, price
≥ ${p['min_price']:.0f}, long only.

### Setup
{_rules(spec.get('setup'))}

Daily-bar version: return over the last {p['mom_days']} sessions ≥ {p['mom_min'] * 100:.0f}%,
the last {p['cons_days']} sessions' high-low range ≤ {p['cons_max_range'] * 100:.0f}% of the high,
close above the {p['trail_ma']}-day SMA — all measured at the prior close.

### Entry
{_rules(spec.get('entry'))}

Daily-bar version: buy-stop at the consolidation high; fill at that level, or at the open if
the stock gaps above it, plus {p['slippage_bps']:.0f} bps slippage.

### Stop
{_rules(spec.get('stop'))}

Daily-bar version: low of the entry day, never more than {p['max_stop_adr']:.1f}× the 20-day
average daily range below the entry; stops fill at the stop or at the open on a gap.

### Exits
{_rules(spec.get('exits'))}

Daily-bar version: after {p['partial_days']} sessions sell {p['partial_frac'] * 100:.0f}% at the
close if in profit and move the stop to break-even; exit the rest at the first close below the
{p['trail_ma']}-day SMA.

### Position sizing
{_rules(spec.get('sizing'))}

Daily-bar version: risk {p['risk_pct'] * 100:.1f}% of equity per trade (stop distance ≈ 1 ADR),
capped at {p['max_pos_pct'] * 100:.0f}% of equity per name and at most {p['max_positions']}
positions. **Cash only** (no margin, unlike the trader).

### Market filter
{_rules(spec.get('market_filter'))}

Daily-bar version: new entries only when SPY's 10-day SMA is above its 20-day SMA (prior close).

### Ambiguities and assumptions
{amb or '- none recorded'}
- The opening-range-high entry (1/5/60-minute candles) is intraday; daily bars approximate it
  with a buy-stop at the prior consolidation high, so the stop is the whole day's low.
- Same-day volume confirmation is not used (the day's volume is only known at the close).
- Earnings are not avoided (no earnings calendar in the backtest).

## Backtest results
Engine `engine.backtest.breakout` (cash only, {p['slippage_bps']:.0f} bps slippage per side,
no look-ahead: signals use the prior close). Data: {res['data']}.

### Full period {full['period_start']} → {full['period_end']}
{table(full)}

### Train {train['period_start']} → {train['period_end']} (same fixed rules)
{table(train)}

### Test {test['period_start']} → {test['period_end']} (same fixed rules, out-of-sample)
{table(test)}
{grid_txt}
### Caveats
- **Survivorship bias:** the universe is *today's* S&P 500, which flatters any long strategy in
  the past; the trader focuses on smaller, faster stocks that are not in this universe.
- Daily bars cannot reproduce intraday entries, stops or the trader's discretion.
- The rule spec was extracted by an LLM from auto-captions and checked by hand; quotes may
  contain caption errors.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Use daily bars, signals from the prior close, one position per symbol, cash only.
3. Report against SPY over the same period: CAGR, Sharpe, max drawdown, alpha, trades, win rate.
4. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{json.dumps(params, indent=2, ensure_ascii=False)}
```
"""


# ---------------------------------------------------------------- publish
OWNER_EMAIL = "kaljuvee@gmail.com"


def publish(ep: dict) -> int:
    """Upsert a public kind='backtest' strategy owned by OWNER_EMAIL, shown as the trader."""
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    from engine.leaderboard.skill import front_matter
    d = ep_dir(ep)
    md = (d / "skill.md").read_text(encoding="utf-8")
    res = json.loads((d / "backtest.json").read_text(encoding="utf-8"))
    fm = front_matter(md)
    f = res["full"]
    metrics = {k: f[k] for k in ("period_start", "period_end", "trading_days", "total_return_pct",
                                 "annualised_pct", "spy_return_pct", "spy_annualised_pct",
                                 "alpha_pct", "alpha_annualised_pct", "sharpe", "max_drawdown_pct",
                                 "win_rate_pct", "trades", "capm_alpha_ann_pct", "beta")}
    metrics["test"] = {k: res["test"][k] for k in ("period_start", "period_end", "annualised_pct",
                                                   "spy_annualised_pct", "sharpe", "max_drawdown_pct",
                                                   "trades")}
    metrics["universe"] = res["universe"]
    key = f"cwt-{ep['slug']}"[:96]
    with DatabasePool().get_session() as s:
        for f_ in ("44_user_strategies_backtest.sql",):
            s.execute(text((ROOT / "sql" / f_).read_text()))
        uid = s.execute(text("SELECT user_id FROM alpatrade.users WHERE lower(email)=lower(:e)"),
                        {"e": OWNER_EMAIL}).scalar()
        if not uid:
            raise SystemExit(f"owner {OWNER_EMAIL} not found")
        sid = s.execute(text("""
            INSERT INTO alpatrade.user_strategies (user_id, name, author_name, description,
                skill_md, is_public, seed_key, kind, source, source_url, backtest_metrics)
            VALUES (CAST(:uid AS UUID), :name, :author, :desc, :md, TRUE, :key, 'backtest',
                'chatwithtraders.com', :url, CAST(:m AS JSONB))
            ON CONFLICT (seed_key) DO UPDATE SET name = EXCLUDED.name,
                author_name = EXCLUDED.author_name, description = EXCLUDED.description,
                skill_md = EXCLUDED.skill_md, kind = 'backtest', source = EXCLUDED.source,
                source_url = EXCLUDED.source_url, backtest_metrics = EXCLUDED.backtest_metrics,
                updated_at = NOW()
            RETURNING id"""), {"uid": str(uid), "name": fm["title"][:160],
                               "author": (fm.get("author") or ep["guest"])[:60],
                               "desc": fm.get("description", ""), "md": md, "key": key,
                               "url": ep["page_url"], "m": json.dumps(metrics)}).scalar()
        s.execute(text("CREATE TABLE IF NOT EXISTS alpatrade.cwt_episodes (slug VARCHAR(160) PRIMARY KEY)"))
        s.execute(text("UPDATE alpatrade.cwt_episodes SET strategy_id = :sid WHERE slug = :slug"),
                  {"sid": sid, "slug": ep["slug"]})
    print(f"publish {ep['episode_number']}: alpatrade.user_strategies id {sid} -> /strategies/{sid}")
    return int(sid)


# ---------------------------------------------------------------- CLI
STEPS = ("catalogue", "transcribe", "extract", "backtest", "publish")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=STEPS + ("all",))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--episode", help="episode number or slug")
    g.add_argument("--all", action="store_true", help="every catalogued episode (bulk)")
    ap.add_argument("--db", action="store_true", help="catalogue: also upsert alpatrade.cwt_episodes")
    ap.add_argument("--no-youtube", action="store_true")
    ap.add_argument("--gemini", action="store_true", help="transcribe: also Gemini strategy summary")
    ap.add_argument("--no-grid", action="store_true")
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    if a.step == "catalogue":
        catalogue(youtube=not a.no_youtube, db=a.db)
        return
    if not (a.episode or a.all):
        ap.error("--episode or --all is required for this step")
    eps = load_catalogue() if a.all else [find_episode(a.episode)]
    steps = STEPS[1:] if a.step == "all" else (a.step,)
    for ep in eps:
        try:
            for st in steps:
                if st == "transcribe":
                    transcribe(ep, gemini=a.gemini)
                elif st == "extract":
                    extract(ep)
                elif st == "backtest":
                    backtest(ep, grid=not a.no_grid)
                elif st == "publish":
                    publish(ep)
        except Exception as exc:  # noqa: BLE001 — keep going in bulk mode
            print(f"{ep['episode_number']} {st}: FAILED {type(exc).__name__}: {exc}")
            if not a.all:
                raise


if __name__ == "__main__":
    main()

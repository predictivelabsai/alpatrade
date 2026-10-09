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
                        "--sub-langs", lang, "--sub-format", "json3", "--sleep-requests", "1", "-o", str(d / "captions"),
                        f"https://www.youtube.com/watch?v={vid}"], capture_output=True, timeout=180)
        f = d / f"captions.{lang}.json3"
        if f.exists():
            txt = captions_to_text(json.loads(f.read_text(encoding="utf-8")))
            out = d / "transcript.txt"
            out.write_text(f"# {ep['title']}\n# source: YouTube auto-captions ({lang}) "
                           f"https://www.youtube.com/watch?v={vid}\n\n{txt}\n", encoding="utf-8")
            return out
    return None


WHISPER_PY = os.getenv("CWT_WHISPER_PY", str(Path.home() / ".venvs" / "cwt-whisper" / "bin" / "python"))
_WHISPER_CODE = r"""
import sys
from faster_whisper import WhisperModel
mp3, out, model, threads = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
segs, _ = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads).transcribe(mp3)
def hms(t):
    t = int(t); return f"{t//3600:02d}:{t%3600//60:02d}:{t%60:02d}"
with open(out, "w", encoding="utf-8") as f:
    for s in segs:
        f.write(f"[{hms(s.start)}] {s.text.strip()}\n")
"""


def transcribe_whisper(ep: dict, model: str = "small", threads: int = 4) -> Path | None:
    """Fallback when there are no captions: faster-whisper (CPU int8) on the episode mp3, run in
    a separate venv (CWT_WHISPER_PY, default ~/.venvs/cwt-whisper) so the app venv is untouched."""
    if not Path(WHISPER_PY).exists():
        print(f"faster-whisper venv not found at {WHISPER_PY}")
        return None
    d = ep_dir(ep)
    mp3 = d / "audio.mp3"
    if not mp3.exists() or mp3.stat().st_size < 100_000:
        with requests.get(ep["audio_url"], headers=UA, stream=True, timeout=120) as r:
            r.raise_for_status()
            with mp3.open("wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
    raw = d / "whisper_raw.txt"
    subprocess.run([WHISPER_PY, "-c", _WHISPER_CODE, str(mp3), str(raw), model, str(threads)],
                   check=True, timeout=4 * 3600)
    out = d / "transcript.txt"
    out.write_text(f"# {ep['title']}\n# source: faster-whisper {model} (CPU int8) {ep['audio_url']}\n\n"
                   + raw.read_text(encoding="utf-8"), encoding="utf-8")
    raw.unlink(missing_ok=True)
    mp3.unlink(missing_ok=True)
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


def _mark(ep: dict, step: str, **info) -> None:
    """Per-episode resumable state in data/cwt/<slug>/state.json."""
    f = ep_dir(ep) / "state.json"
    st = json.loads(f.read_text()) if f.exists() else {}
    st[step] = {**info, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    f.write_text(json.dumps(st, indent=1))


def state(ep: dict) -> dict:
    f = DATA / ep["slug"] / "state.json"
    return json.loads(f.read_text()) if f.exists() else {}


def transcribe(ep: dict, gemini: bool = False, mode: str = "auto") -> str:
    """mode: auto (captions, then whisper) | captions | whisper. Skips finished episodes.
    Returns 'skip' | 'captions' | 'whisper' | 'failed'."""
    if (DATA / ep["slug"] / "transcript.txt").exists():
        return "skip"
    out, how = None, "failed"
    if mode in ("auto", "captions") and ep.get("youtube_url"):
        try:
            out = transcribe_youtube(ep)
            how = "captions" if out else "failed"
        except Exception as exc:  # noqa: BLE001
            print(f"  captions error: {type(exc).__name__}")
    if not out and mode in ("auto", "whisper"):
        out = transcribe_whisper(ep)
        how = "whisper" if out else "failed"
    _mark(ep, "transcribe", result=how)
    print(f"transcribe {ep['episode_number']} {ep['slug'][:40]}: {how}", flush=True)
    if gemini:
        g = gemini_summary(ep)
        print(f"gemini {ep['episode_number']}: {g.relative_to(ROOT) if g else 'skipped/failed'}")
    return how


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


CATEGORIES = ("daily_testable", "intraday_only", "options", "futures_fx", "discretionary",
              "no_concrete_rules", "macro_commentary")

BULK_PROMPT = """You turn a trading-podcast transcript into a precise, testable strategy spec.
Trader(s): {guest}. Episode: {title}.

1) Classify the guest's MAIN trading method for US stocks:
   category = one of {categories}
   - daily_testable: concrete long-side rules for US stocks that can be approximated on DAILY
     bars (swing / position / trend / mean-reversion / gap / relative-strength rotation).
   - intraday_only: the edge lives inside the day (scalping, day trading, order flow, ORB on
     1-5 min bars) and does not survive a daily-bar approximation.
   - options / futures_fx: the method is mainly options, futures or FX.
   - discretionary / no_concrete_rules: no rules concrete enough to code; macro_commentary:
     market views, career story, psychology, interviews without a method.
   A short-selling-only method counts as not testable (our engine is long only): use
   "discretionary" with reason "short-only".
2) If daily_testable, choose the closest template and fill its params (numbers only):
   - breakout: momentum_lookback_days, momentum_min_pct, consolidation_days,
     consolidation_max_range_pct, trail_ma (10|20), partial_after_days, partial_frac,
     risk_per_trade_pct, max_position_pct, max_positions
   - dip: dip (fraction, e.g. 0.05), ref_days (high lookback), rsi_max (0 = none),
     trend_ma (0|50|200), target (fraction, 0 = none), stop (fraction, 0 = none),
     max_hold (sessions), sma5_exit (bool), pos_pct, max_positions
   - trend_ma: fast, slow, exit_ma, atr_stop (ATR multiple, 0 = none), pos_pct, max_positions
   - gap: gap_min (fraction), stop (fraction), max_hold (sessions), trail_ma (0|10|20|50),
     pos_pct, max_positions
   - relative_strength: lookback (sessions), top_n, rebalance_days, trend_ma (0|50|200)
3) Name the method in <= 6 words (method_name), e.g. "Momentum breakout swing".
Use ONLY what the guest says; quote verbatim with the [hh:mm:ss] timestamp of the transcript
paragraph. Never invent quotes. Put guesses in "ambiguities" with your assumption.
Return ONLY one JSON object:
{{"trader": str, "category": str, "testable": bool, "reason": str (one sentence),
  "template": "breakout|dip|trend_ma|gap|relative_strength|none", "method_name": str,
  "style": str, "timeframe": str,
  "universe": {{"description": str}},
  "setup": [{{"rule": str, "quote": str, "timestamp": str}}], "entry": [...], "stop": [...],
  "exits": [...], "sizing": [...], "market_filter": [...],
  "ambiguities": [{{"issue": str, "assumption": str}}],
  "params": {{...template params...}}}}

Transcript:
{transcript}
"""


def grok(prompt: str, model: str = "grok-4.3", retries: int = 5) -> str:
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise SystemExit("XAI_API_KEY not set")
    for attempt in range(retries):
        try:
            r = requests.post("https://api.x.ai/v1/chat/completions", timeout=900,
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": model, "temperature": 0.1,
                                    "response_format": {"type": "json_object"},
                                    "messages": [{"role": "user", "content": prompt}]})
        except requests.RequestException:
            r = None
        if r is not None and r.ok:
            return r.json()["choices"][0]["message"]["content"]
        code = r.status_code if r is not None else 0
        if code and code not in (408, 429, 500, 502, 503, 504):
            raise RuntimeError(f"xAI HTTP {code}")
        time.sleep(min(120, 10 * 2 ** attempt))  # back off on rate limits / transient errors
    raise RuntimeError("xAI: retries exhausted")


def extract(ep: dict, model: str = "grok-4.3", force: bool = False) -> Path | None:
    d = ep_dir(ep)
    out = d / "spec.json"
    if out.exists() and not force:
        spec = json.loads(out.read_text(encoding="utf-8"))
        if "category" in spec:
            return out
    tf = d / "transcript.txt"
    if not tf.exists():
        return None
    transcript = tf.read_text(encoding="utf-8")[:240_000]
    raw = grok(BULK_PROMPT.format(guest=ep["guest"], title=ep["title"], categories=CATEGORIES,
                                  transcript=transcript), model=model)
    spec = json.loads(raw)
    if spec.get("category") not in CATEGORIES:
        spec["category"] = "no_concrete_rules"
    if spec.get("template") not in ("breakout", "dip", "trend_ma", "gap", "relative_strength"):
        spec["template"] = "none"
    spec["testable"] = bool(spec.get("category") == "daily_testable" and spec["template"] != "none")
    spec["_meta"] = {"model": model, "episode": ep["episode_number"], "page_url": ep["page_url"],
                     "youtube_url": ep["youtube_url"]}
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    _mark(ep, "extract", category=spec["category"], template=spec["template"])
    print(f"extract {ep['episode_number']} {ep['slug'][:40]}: {spec['category']} / {spec['template']}", flush=True)
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
    q = dict(spec.get("daily_bar_params") or {})
    np_ = spec.get("params") or {}
    for k in ("momentum_lookback_days", "momentum_min_pct", "consolidation_days",
              "consolidation_max_range_pct", "trail_ma", "partial_after_days", "partial_frac",
              "risk_per_trade_pct", "max_position_pct", "max_positions"):
        if np_.get(k) is not None:
            q[k] = np_[k]

    def num(k, default, lo, hi, cast=float, frac_to_pct=False):
        """The LLM writes 0 for 'not stated' (it used to be clamped up to the lower bound,
        e.g. a 5% consolidation range and a 2-day 10% partial). <= 0 / missing -> default.
        ``frac_to_pct``: a value in (0, 1] is a fraction (0.1 = 10%) for a percent field."""
        try:
            v = float(q.get(k))
        except (TypeError, ValueError):
            return cast(default)
        if v != v or v <= 0:
            return cast(default)
        if frac_to_pct and v <= 1:
            v *= 100
        return cast(min(max(v, lo), hi))
    cons_days = num("consolidation_days", 15, 5, 60, int)
    # the momentum window must reach >= 20 sessions back before the consolidation: when it
    # does not (e.g. 20-day momentum >= 10% AND a 20-day range <= 5%) the two rules contradict
    # each other and the scan finds nothing (Marsten Parker / Christian Carreon had 0 trades)
    mom_days = max(num("momentum_lookback_days", 63, 20, 252, int), min(cons_days + 20, 252))
    pf = q.get("partial_frac")
    if isinstance(pf, (int, float)) and pf > 1:  # percent given for a fraction
        q["partial_frac"] = pf / 100
    return BreakoutParams(
        mom_days=mom_days, mom_min=num("momentum_min_pct", 30, 10, 200, frac_to_pct=True) / 100,
        cons_days=cons_days,
        cons_max_range=num("consolidation_max_range_pct", 15, 5, 40, frac_to_pct=True) / 100,
        trail_ma=10 if int(q.get("trail_ma") or 20) <= 10 else 20,
        partial_days=num("partial_after_days", 4, 2, 10, int),
        partial_frac=num("partial_frac", 0.33, 0.1, 0.5),
        risk_pct=num("risk_per_trade_pct", 1.0, 0.25, 2.0) / 100,
        max_pos_pct=num("max_position_pct", 20, 5, 25, frac_to_pct=True) / 100,
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


# ---------------------------------------------------------------- bulk: group / backtest / publish
STRAT = DATA / "strategies"
MIN_TRADES = 10
TEMPLATE_TEXT = {
    "breakout": "momentum breakout: strong prior run-up, tight consolidation, buy-stop at the "
                "consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on "
                "the 10/20-day SMA",
    "dip": "mean reversion: buy the next open after the close is a set % below its recent high "
           "(optional RSI(2) and long-term trend filter), exit on target / stop / close above "
           "the 5-day SMA / time",
    "trend_ma": "trend following: buy the next open after the fast SMA crosses above the slow "
                "SMA, exit on a close below the exit SMA or an ATR stop",
    "gap": "gap continuation: buy at the open on a gap up of at least the set % in an uptrend, "
           "fixed stop below the open, exit after N sessions or on a close below the trail SMA",
    "relative_strength": "relative-strength rotation: every N sessions (at most weekly) hold the "
                         "strongest names by trailing return (above their trend SMA), equal "
                         "weight, a holding is kept while it still ranks in the top 2N "
                         "(hysteresis against churn), cash when SPY < SMA200",
}


# Hand-reviewed corrections to the LLM classification (episode number -> spec fields).
# Applied on load, so re-extraction can't silently re-publish a wrong call.
CLASSIFICATION_OVERRIDES = {
    "171": {"category": "intraday_only", "testable": False, "template": "none",
            "reason": "manual review: intraday small-cap gap fader / scalper (tape, level 2, "
                      "flat by noon, no overnight holds); not testable on daily bars"},
    "211": {"category": "intraday_only", "testable": False, "template": "none",
            "reason": "manual review: Stan Gluzman is an intraday scalper (ep. 171/211: tape, "
                      "level 2, 1-5 min charts, mostly short); the swing breakouts he mentions "
                      "are a side book, so the breakout backtest misrepresents his method"},
}


def load_spec(ep: dict) -> dict:
    f = DATA / ep["slug"] / "spec.json"
    if not f.exists():
        return {}
    spec = json.loads(f.read_text(encoding="utf-8"))
    o = CLASSIFICATION_OVERRIDES.get(str(ep.get("episode_number") or ""))
    if o and "category" in spec:
        spec = {**spec, **o, "_override": True}
    return spec


def _slug(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def trader_name(ep: dict, spec: dict) -> str:
    name = (spec.get("trader") or "").strip()
    g = ep["guest"].strip()
    # prefer the catalogue guest when the LLM name is a sub/superstring (handles '@handles')
    if not name or len(name) > 60:
        name = g
    return re.sub(r"\s+", " ", name)


def group_key(ep: dict, spec: dict) -> str:
    return f"{_slug(ep['guest'])[:60]}-{spec['template']}"


def build_groups() -> dict:
    """One Leaderboard strategy per (trader, template): merges repeat guests' episodes."""
    groups: dict[str, dict] = {}
    for ep in load_catalogue():
        spec = load_spec(ep)
        if not spec.get("testable"):
            continue
        k = group_key(ep, spec)
        g = groups.setdefault(k, {"key": k, "template": spec["template"], "members": []})
        g["members"].append({"ep": ep, "spec": spec})
    for g in groups.values():
        g["members"].sort(key=lambda m: int(m["ep"]["episode_number"] or 0), reverse=True)
        g["trader"] = trader_name(g["members"][0]["ep"], g["members"][0]["spec"])
        g["hash"] = "|".join(m["ep"]["slug"] for m in g["members"])
    return groups


_BARS_CACHE: dict = {}


def _bars():
    if not _BARS_CACHE:
        b = load_bars(universe() + ["SPY"])
        _BARS_CACHE["spy"] = b.pop("SPY")
        _BARS_CACHE["bars"] = b
    return _BARS_CACHE["bars"], _BARS_CACHE["spy"]


NONZERO_KEYS = ("pos_pct", "max_positions", "top_n", "lookback", "rebalance_days", "ref_days",
                "dip", "gap_min", "fast", "slow", "exit_ma")
# bump when an engine / parameter-mapping change must invalidate cached group backtests
ENGINE_REV = {"breakout": 2, "dip": 2, "trend_ma": 2, "gap": 2, "relative_strength": 2}


def group_params(g: dict):
    from engine.backtest.templates import RuleParams
    spec = g["members"][0]["spec"]  # most recent episode's numbers
    if g["template"] == "breakout":
        return spec_params(spec)
    raw = {**(spec.get("params") or {}), "template": g["template"]}
    # 0 is meaningful for trend_ma / target / stop / max_hold / rsi_max / atr_stop ("none"),
    # but not for these: the LLM's 0 = "not stated" (Rob Hanna had pos_pct 0 -> 2%, 1 position)
    for k in NONZERO_KEYS:
        if not raw.get(k) or (isinstance(raw[k], (int, float)) and raw[k] <= 0):
            raw.pop(k, None)
    for k in ("pos_pct",):
        if raw.get(k) and raw[k] > 1:
            raw[k] = raw[k] / 100
    for k in ("dip", "target", "stop", "gap_min"):
        if raw.get(k) and raw[k] >= 1:  # LLM gave percent instead of fraction
            raw[k] = raw[k] / 100
    return RuleParams.from_dict(raw)


def backtest_group(g: dict, force: bool = False) -> dict | None:
    from engine.backtest import breakout, templates
    d = STRAT / g["key"]
    d.mkdir(parents=True, exist_ok=True)
    out = d / "backtest.json"
    p = group_params(g)
    rev = ENGINE_REV.get(g["template"], 1)
    if out.exists() and not force:
        old = json.loads(out.read_text())
        if (old.get("members_hash") == g["hash"] and old.get("engine_rev") == rev
                and old.get("spec_params") == json.loads(json.dumps(p.to_dict(), default=str))):
            return old
    bars, spy = _bars()
    end = str(spy.index[-1].date())
    test_start = str(spy.index[spy.index > TRAIN_END][0].date())
    full = (breakout.run(bars, spy, BT_START, end, p) if g["template"] == "breakout"
            else templates.run(bars, spy, BT_START, end, p))
    res = {"key": g["key"], "template": g["template"], "members_hash": g["hash"], "engine_rev": rev,
           "universe": f"S&P 500 current members ({len(bars)} with data)",
           "data": "Alpaca SIP daily bars, adjustment=all (splits+dividends)",
           "spec_params": p.to_dict(), "full": _fmt(full),
           "train": _fmt(templates.slice_metrics(full, spy, BT_START, TRAIN_END)),
           "test": _fmt(templates.slice_metrics(full, spy, test_start, end))}
    out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    full["equity"].to_csv(d / "equity_full.csv", header=["equity"])
    (d / "skill.md").write_text(skill_md_group(g, res), encoding="utf-8")
    f = res["full"]
    print(f"backtest {g['key']}: CAGR {f['annualised_pct']:.1f}% vs SPY {f['spy_annualised_pct']:.1f}% "
          f"trades {f['trades']} | test {res['test']['annualised_pct']:.1f}%", flush=True)
    return res


def _tbl(m: dict) -> str:
    def v(x, sharpe=False):
        return "—" if x is None else (f"{x:.2f}" if sharpe else f"{x:+.1f}%")
    return "\n".join([
        "| Metric | Strategy | SPY |", "|---|---|---|",
        f"| Annualised return (CAGR) | {v(m['annualised_pct'])} | {v(m['spy_annualised_pct'])} |",
        f"| Total return | {v(m['total_return_pct'])} | {v(m['spy_return_pct'])} |",
        f"| Sharpe (daily, N-1) | {v(m['sharpe'], True)} | {v(m['spy_sharpe'], True)} |",
        f"| Max drawdown | {v(m['max_drawdown_pct'])} | {v(m['spy_max_drawdown_pct'])} |",
        f"| Alpha vs SPY (annualised, CAGR − SPY CAGR) | {v(m['alpha_annualised_pct'])} | |",
        f"| CAPM alpha (ann.) / beta | {v(m['capm_alpha_ann_pct'])} / {m['beta']:.2f} | |",
        f"| Trades / win rate | {m['trades']} / {m['win_rate_pct']:.1f}% | |"])


def skill_md_group(g: dict, res: dict) -> str:
    trader, t = g["trader"], g["template"]
    lead = g["members"][0]["spec"]
    method = (lead.get("method_name") or t.replace("_", " ")).strip()
    eps = [m["ep"] for m in g["members"]]
    full, train, test, p = res["full"], res["train"], res["test"], res["spec_params"]
    title = f"{trader} · {method} (backtest)"[:150]
    ep_list = ", ".join(f"ep. {e['episode_number'] or '?'}" for e in eps)
    desc = (f"Daily-bar backtest of the {method.lower()} method {trader} describes on Chat With "
            f"Traders ({ep_list}). Template: {t.replace('_', ' ')}. S&P 500, cash only, 10 bps "
            f"slippage. Backtest, not live.")
    sections = []
    for name in ("setup", "entry", "stop", "exits", "sizing", "market_filter"):
        lines = []
        for m in g["members"]:
            for it in m["spec"].get(name) or []:
                q = (it.get("quote") or "").strip().replace("\n", " ")
                lines.append(f"- {it.get('rule', '').strip()}" + (
                    f"  \n  > \"{q}\" — ep. {m['ep']['episode_number']} [{it.get('timestamp', '')}]" if q else ""))
        sections.append(f"### {name.replace('_', ' ').title()}\n" + ("\n".join(lines) or "- (not stated)"))
    amb = []
    for m in g["members"]:
        for a in m["spec"].get("ambiguities") or []:
            amb.append(f"- **{a.get('issue')}** → assumption: {a.get('assumption')}")
    links = "\n".join(f"- Ep. {e['episode_number']} — [{e['title']}]({e['page_url']})"
                      + (f" · [YouTube]({e['youtube_url']})" if e.get("youtube_url") else "")
                      for e in eps)
    params = {"schema": "alpatrade.strategy_config/v1", "name": f"cwt_{g['key']}"[:96],
              "display_name": title, "kind": "backtest", "template": t,
              "params": {**p, "universe": "sp500_current", "timeframe": "1d"},
              "execution": {"cash_only": True, "slippage_bps_per_side": p.get("slippage_bps", 10)},
              "backtest": {"engine": "engine.backtest.breakout" if t == "breakout" else "engine.backtest.templates",
                           "data": res["data"], "universe": res["universe"],
                           "train": [train["period_start"], train["period_end"]],
                           "test": [test["period_start"], test["period_end"]], "benchmark": "SPY"},
              "source": {"site": "chatwithtraders.com",
                         "episodes": [{"episode": e["episode_number"], "url": e["page_url"]} for e in eps]}}
    return f"""---
title: {title}
description: {desc}
kind: backtest
author: {trader}
source: chatwithtraders.com
source_url: {eps[0]['page_url']}
tags: {t.replace('_', '-')}, chat-with-traders, backtest
license: MIT
---

# {title}

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules {trader} described in a podcast interview. It is **not**
{trader}'s own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
{links}

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode{'s' if len(eps) > 1 else ''})
Style: {lead.get('style', '')}; timeframe: {lead.get('timeframe', '')}. Universe described:
{(lead.get('universe') or {}).get('description', '')}.

{chr(10).join(sections)}

## How it was backtested
Template **{t}** — {TEMPLATE_TEXT[t]}. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
{chr(10).join(amb) or '- none recorded'}
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe {res['universe']}; {res['data']}; 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period {full['period_start']} → {full['period_end']}
{_tbl(full)}

### Train {train['period_start']} → {train['period_end']}
{_tbl(train)}

### Test {test['period_start']} → {test['period_end']} (out-of-sample, same rules)
{_tbl(test)}

### Caveats
- **Survivorship bias:** today's S&P 500 members, which flatters long strategies historically.
- Rules were extracted by an LLM from auto-captions / Whisper transcripts; quotes may contain
  transcription errors. Parameters were not optimised.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Daily bars, signals from the prior close, cash only; report CAGR, Sharpe, max drawdown,
   alpha vs SPY, trades and win rate over the same period.
3. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{json.dumps(params, indent=2, ensure_ascii=False, default=str)}
```
"""


def _db():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def publish_group(g: dict, res: dict) -> int | None:
    from sqlalchemy import text
    from engine.leaderboard.skill import front_matter
    d = STRAT / g["key"]
    md = (d / "skill.md").read_text(encoding="utf-8")
    fm = front_matter(md)
    f = res["full"]
    eps = [m["ep"] for m in g["members"]]
    metrics = {k: f[k] for k in ("period_start", "period_end", "trading_days", "total_return_pct",
                                 "annualised_pct", "spy_return_pct", "spy_annualised_pct",
                                 "alpha_pct", "alpha_annualised_pct", "sharpe", "max_drawdown_pct",
                                 "win_rate_pct", "trades", "capm_alpha_ann_pct", "beta")}
    metrics["test"] = {k: res["test"][k] for k in ("period_start", "period_end", "annualised_pct",
                                                   "spy_annualised_pct", "sharpe", "max_drawdown_pct",
                                                   "trades")}
    metrics.update({"universe": res["universe"], "template": g["template"],
                    "episodes": [{"episode": e["episode_number"], "title": e["title"],
                                  "url": e["page_url"]} for e in eps]})
    key = f"cwt-{g['key']}"[:96]
    with _db().get_session() as s:
        uid = s.execute(text("SELECT user_id FROM alpatrade.users WHERE lower(email)=lower(:e)"),
                        {"e": OWNER_EMAIL}).scalar()
        # the pilot row (seed_key cwt-<episode slug>) is re-keyed to the merged strategy key
        for e in eps:
            s.execute(text("UPDATE alpatrade.user_strategies SET seed_key = :new WHERE seed_key = :old "
                           "AND NOT EXISTS (SELECT 1 FROM alpatrade.user_strategies WHERE seed_key = :new)"),
                      {"new": key, "old": f"cwt-{e['slug']}"[:96]})
        args = {"uid": str(uid), "name": fm["title"][:160], "author": g["trader"][:60],
                "desc": fm.get("description", "")[:2000], "md": md, "key": key,
                "url": eps[0]["page_url"], "m": json.dumps(metrics, default=str)}
        # UPDATE first: INSERT .. ON CONFLICT DO UPDATE consumes a sequence value even when it
        # only updates, which is what left id gaps (10, 18-27) between published strategies
        sid = s.execute(text("""
            UPDATE alpatrade.user_strategies SET name = :name, author_name = :author,
                description = :desc, skill_md = :md, kind = 'backtest', source = 'chatwithtraders.com',
                source_url = :url, backtest_metrics = CAST(:m AS JSONB), is_public = TRUE,
                updated_at = NOW()
            WHERE seed_key = :key RETURNING id"""), args).scalar()
        if sid is None:
            sid = s.execute(text("""
                INSERT INTO alpatrade.user_strategies (user_id, name, author_name, description,
                    skill_md, is_public, seed_key, kind, source, source_url, backtest_metrics)
                VALUES (CAST(:uid AS UUID), :name, :author, :desc, :md, TRUE, :key, 'backtest',
                    'chatwithtraders.com', :url, CAST(:m AS JSONB))
                RETURNING id"""), args).scalar()
    return int(sid)


def unpublish_stale(published_keys: set[str], reasons: dict[str, str]) -> dict:
    """Hide (is_public = FALSE, never delete) every Chat With Traders backtest row this run did
    not publish, e.g. a group now below MIN_TRADES or re-classified as not testable."""
    from sqlalchemy import text
    out = {}
    with _db().get_session() as s:
        rows = s.execute(text("""SELECT id, seed_key FROM alpatrade.user_strategies
            WHERE kind = 'backtest' AND source = 'chatwithtraders.com' AND is_public
              AND seed_key LIKE 'cwt-%'""")).fetchall()
        for sid, key in rows:
            gk = key[4:]
            if gk in published_keys:
                continue
            s.execute(text("UPDATE alpatrade.user_strategies SET is_public = FALSE, updated_at = NOW() "
                           "WHERE id = :id"), {"id": sid})
            out[gk] = {"id": int(sid), "reason": reasons.get(gk, "no longer a testable group")}
            print(f"unpublish {gk}: id {sid} ({out[gk]['reason']})", flush=True)
    return out


def set_status(rows: list[dict]) -> None:
    from sqlalchemy import text
    with _db().get_session() as s:
        for r in rows:
            s.execute(text("""UPDATE alpatrade.cwt_episodes SET status = :status,
                status_reason = :reason, category = :category, template = :template,
                transcript_source = :src, strategy_key = :key, strategy_id = :sid,
                updated_at = NOW() WHERE slug = :slug"""), r)


def bulk_finish(publish: bool = True) -> dict:
    """Group testable specs, backtest each group (resumable), publish, record every episode's
    status in alpatrade.cwt_episodes. Returns counts."""
    groups = build_groups()
    results, status, reasons = {}, {}, {}
    for k, g in groups.items():
        try:
            res = backtest_group(g)
        except Exception as exc:  # noqa: BLE001
            print(f"backtest {k}: FAILED {type(exc).__name__}: {exc}", flush=True)
            for m in g["members"]:
                status[m["ep"]["slug"]] = ("failed", f"backtest error: {type(exc).__name__}", k, None)
            continue
        if res["full"]["trades"] < MIN_TRADES:
            why = (f"too few trades ({res['full']['trades']}) with the {g['template']} template "
                   f"(< {MIN_TRADES} in 2016-2026 on the S&P 500; not meaningful)")
            reasons[k] = why
            for m in g["members"]:
                status[m["ep"]["slug"]] = ("skipped", why, k, None)
            continue
        sid = publish_group(g, res) if publish else None
        results[k] = {"id": sid, "res": res, "trader": g["trader"], "n_eps": len(g["members"])}
        for m in g["members"]:
            status[m["ep"]["slug"]] = ("published" if sid else "testable", f"{g['template']} backtest",
                                       k, sid)
        print(f"publish {k}: id {sid}", flush=True)
    rows = []
    for ep in load_catalogue():
        st = state(ep)
        src = (st.get("transcribe") or {}).get("result")
        spec = load_spec(ep)
        if spec.get("_override"):
            reasons.setdefault(group_key(ep, {"template": json.loads(
                (DATA / ep["slug"] / "spec.json").read_text(encoding="utf-8")).get("template")}),
                f"{spec['category']}: {spec.get('reason', '')}"[:300])
        if ep["slug"] in status:
            stt, reason, key, sid = status[ep["slug"]]
        elif not (DATA / ep["slug"] / "transcript.txt").exists():
            stt, reason, key, sid = "no_transcript", "transcription failed or pending", None, None
        elif "category" not in spec:
            stt, reason, key, sid = "transcribed", "extraction pending or failed", None, None
        else:
            stt, reason, key, sid = ("not_testable", f"{spec['category']}: {spec.get('reason', '')}"[:500],
                                     None, None)
        rows.append({"slug": ep["slug"], "status": stt, "reason": reason,
                     "category": spec.get("category"), "template": spec.get("template"),
                     "src": src, "key": key, "sid": sid})
    unpublished = {}
    if publish:
        set_status(rows)
        unpublished = unpublish_stale(set(results), reasons)
    summary = {"groups": len(groups), "published": len(results),
               "testable_episodes": sum(1 for r in rows if r["status"] in ("published", "skipped",
                                                                         "testable", "failed"))}
    from collections import Counter
    summary["status"] = dict(Counter(r["status"] for r in rows))
    (DATA / "bulk_summary.json").write_text(json.dumps(
        {"summary": summary, "episodes": rows, "unpublished": unpublished,
         "skipped_groups": {k: v for k, v in reasons.items() if k in groups},
         "strategies": {k: {"id": v["id"], "trader": v["trader"], "episodes": v["n_eps"],
                            "template": v["res"]["template"], "params": v["res"]["spec_params"],
                            "full": v["res"]["full"], "test": v["res"]["test"]}
                        for k, v in results.items()}}, indent=1, default=str))
    print("BULK", summary, flush=True)
    return summary


# ---------------------------------------------------------------- CLI
STEPS = ("catalogue", "transcribe", "extract", "backtest", "publish", "finish")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=STEPS + ("all",))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--episode", help="episode number or slug")
    g.add_argument("--all", action="store_true", help="every catalogued episode (bulk, resumable)")
    ap.add_argument("--db", action="store_true", help="catalogue: also upsert alpatrade.cwt_episodes")
    ap.add_argument("--no-youtube", action="store_true")
    ap.add_argument("--gemini", action="store_true", help="transcribe: also Gemini strategy summary")
    ap.add_argument("--mode", choices=("auto", "captions", "whisper"), default="auto",
                    help="transcribe: captions only, whisper only, or captions then whisper")
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between YouTube / xAI calls")
    ap.add_argument("--no-grid", action="store_true")
    ap.add_argument("--no-publish", action="store_true", help="finish: backtest only")
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    if a.step == "catalogue":
        catalogue(youtube=not a.no_youtube, db=a.db)
        return
    if a.step == "finish":  # group + backtest + publish every testable episode (bulk)
        bulk_finish(publish=not a.no_publish)
        return
    if not (a.episode or a.all):
        ap.error("--episode or --all is required for this step")
    eps = load_catalogue() if a.all else [find_episode(a.episode)]
    if a.all and a.step in ("backtest", "publish", "all"):
        ap.error("bulk backtest/publish: use the 'finish' step (merges repeat guests)")
    steps = STEPS[1:5] if a.step == "all" else (a.step,)
    for ep in eps:
        st = "?"
        try:
            for st in steps:
                if st == "transcribe":
                    r = transcribe(ep, gemini=a.gemini, mode=a.mode)
                    if a.all and r in ("captions",):
                        time.sleep(a.sleep)
                elif st == "extract":
                    before = (DATA / ep["slug"] / "spec.json").exists()
                    if extract(ep) and a.all and not before:
                        time.sleep(a.sleep / 2)
                elif st == "backtest":
                    backtest(ep, grid=not a.no_grid)
                elif st == "publish":
                    publish(ep)
        except Exception as exc:  # noqa: BLE001 — keep going in bulk mode
            print(f"{ep['episode_number']} {st}: FAILED {type(exc).__name__}: {exc}", flush=True)
            if ep.get("slug"):
                _mark(ep, f"{st}_error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
            if not a.all:
                raise


if __name__ == "__main__":
    main()

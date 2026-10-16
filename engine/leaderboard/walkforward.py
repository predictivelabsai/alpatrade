"""Walk-forward backtest of a strategy param version on the PARITY backtester (v0.51.0).

Engine: ``utils.btd_event_backtest.run`` — the same rules module (utils/btd_rules) and event
schedule as the paper / live runners, so a version that looks good here trades the same way.

Windows (fixed params, nothing is re-fitted; "fit" is the in-sample window shown for decay):
  * rolling folds: fit = 3 calendar years, test = the next calendar year, test years 2016 → now
  * segments: 2016-2022 and 2023+ (today)
Each window starts fresh with $10,000. The out-of-sample curve chains the test years.
Every window is compared with SPY buy-and-hold and with the CURRENT LIVE version of the strategy.

``run_wf(params, live_params, bars, progress)`` is pure (bars injected) for tests; ``load_bars``
fetches split-adjusted daily bars from yfinance with a per-day disk cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("leaderboard.walkforward")
ET = ZoneInfo("America/New_York")
CAPITAL = 10_000.0
FIRST_TEST_YEAR = 2016
FIT_YEARS = 3
DATA_START = "2012-06-01"
SEGMENTS = {"2016-2022": ("2016-01-01", "2022-12-31"), "2023+": ("2023-01-01", None)}
INDEX_SYMBOLS = ("SPY", "SMH", "QQQ")
ENGINE = "utils.btd_event_backtest (parity with paper/live runners)"
SPEC_VERSION = 1


def data_asof(now: Optional[datetime] = None) -> str:
    """Last session whose daily bar is complete (ET): today after 16:15, else the day before."""
    n = (now or datetime.now(ET)).astimezone(ET)
    d = n.date() if n.hour * 60 + n.minute >= 16 * 60 + 15 else n.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def windows(asof: str) -> Dict[str, Any]:
    end_year = int(asof[:4])
    folds = []
    for y in range(FIRST_TEST_YEAR, end_year + 1):
        test_end = min(f"{y}-12-31", asof)
        if test_end < f"{y}-01-15":
            continue
        folds.append({"fit": [f"{y - FIT_YEARS}-01-01", f"{y - 1}-12-31"], "test": [f"{y}-01-01", test_end]})
    segs = {k: [a, b or asof] for k, (a, b) in SEGMENTS.items()}
    return {"folds": folds, "segments": segs}


def cache_key(params: Dict[str, Any], live_params: Optional[Dict[str, Any]], asof: str) -> str:
    blob = json.dumps({"p": params, "l": live_params, "asof": asof, "spec": SPEC_VERSION,
                       "w": [FIRST_TEST_YEAR, FIT_YEARS, SEGMENTS]}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def stats(eq: List[float]) -> Dict[str, Any]:
    eq = [float(x) for x in eq if x is not None]
    if len(eq) < 2 or eq[0] <= 0:
        return {"total_pct": None, "cagr_pct": None, "sharpe": None, "max_dd_pct": None}
    r = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    n = len(r)
    mu = sum(r) / n if n else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (n - 1)) if n > 1 else 0.0
    pk, mdd = eq[0], 0.0
    for x in eq:
        pk = max(pk, x)
        mdd = min(mdd, x / pk - 1)
    tot = eq[-1] / eq[0] - 1
    yrs = max(n, 1) / 252
    return {"total_pct": round(tot * 100, 3),
            "cagr_pct": round(((1 + tot) ** (1 / yrs) - 1) * 100, 3) if tot > -1 else -100.0,
            "sharpe": round(mu / sd * math.sqrt(252), 3) if sd else None,
            "max_dd_pct": round(mdd * 100, 3)}


def _bt(bars: Dict[str, List[Dict[str, Any]]], P: Dict[str, Any], a: str, b: str) -> Dict[str, Any]:
    from utils import btd_event_backtest as BT
    syms = [s for s in P["symbols"] if bars.get(s)]
    if not syms:
        return {"stats": stats([]), "trades": 0, "curve": []}
    reg = {k: bars[k] for k in INDEX_SYMBOLS if bars.get(k)}
    r = BT.run({s: bars[s] for s in syms}, {**P, "symbols": syms}, a, b, CAPITAL, regime_bars=reg,
               vol_bars=bars.get("SPY"))
    curve = sorted(r.equity)
    st = stats([CAPITAL] + [e for _, e in curve])
    wins = [t for t in r.trades if t.pnl > 0]
    return {"stats": st, "trades": len(r.trades), "win_rate_pct": round(len(wins) / len(r.trades) * 100, 1) if r.trades else None,
            "blocked_days": len(r.blocked), "curve": curve}


def _spy(bars, a, b):
    px = [(x["t"][:10], float(x["c"])) for x in bars.get("SPY", []) if a <= x["t"][:10] <= b]
    return {"stats": stats([p for _, p in px]), "curve": px}


def run_wf(params: Dict[str, Any], live_params: Optional[Dict[str, Any]], bars: Dict[str, List[Dict[str, Any]]],
           progress: Callable[[str, Dict[str, Any]], None] = lambda m, partial: None,
           asof: Optional[str] = None) -> Dict[str, Any]:
    """Walk-forward result dict (JSON-safe). ``progress(message, partial_result)`` after each window."""
    asof = asof or max((x["t"][:10] for x in bars.get("SPY", [])), default=data_asof())
    W = windows(asof)
    out: Dict[str, Any] = {"engine": ENGINE, "asof": asof, "capital": CAPITAL, "params": params,
                           "live_params": live_params, "folds": [], "segments": {}, "windows": W}
    same = live_params is None or live_params == params
    oos = {"cand": [], "live": [], "spy": []}
    for i, f in enumerate(W["folds"]):
        (fa, fb), (ta, tb) = f["fit"], f["test"]
        cand_t = _bt(bars, params, ta, tb)
        live_t = cand_t if same else _bt(bars, live_params, ta, tb)
        spy_t = _spy(bars, ta, tb)
        cand_f = _bt(bars, params, fa, fb)
        row = {"fit": [fa, fb], "test": [ta, tb], "fit_cand": cand_f["stats"],
               "cand": {**cand_t["stats"], "trades": cand_t["trades"]},
               "live": {**live_t["stats"], "trades": live_t["trades"]}, "spy": spy_t["stats"]}
        out["folds"].append(row)
        for k, c in (("cand", cand_t["curve"]), ("live", live_t["curve"]), ("spy", spy_t["curve"])):
            oos[k].append(c)
        progress(f"Fold {i + 1}/{len(W['folds'])}: test {ta[:4]} done", out)
    for name, (a, b) in W["segments"].items():
        c = _bt(bars, params, a, b)
        lv = c if same else _bt(bars, live_params, a, b)
        out["segments"][name] = {"period": [a, b], "cand": {**c["stats"], "trades": c["trades"],
                                                            "win_rate_pct": c.get("win_rate_pct")},
                                 "live": {**lv["stats"], "trades": lv["trades"]}, "spy": _spy(bars, a, b)["stats"]}
        progress(f"Segment {name} done", out)
    curve = {k: _chain(v) for k, v in oos.items()}
    out["oos"] = {k: stats([x for _, x in curve[k]]) for k in curve}
    out["curve"] = _thin(curve)
    out["same_as_live"] = same
    return out


def _chain(curves: List[List[tuple]]) -> List[tuple]:
    """Chain window curves into one growth-of-$10k series (each window rescaled to the last value)."""
    out: List[tuple] = []
    level = CAPITAL
    for c in curves:
        if not c:
            continue
        base = c[0][1] if c[0][1] else 1.0
        start_level = level
        for d, v in c:
            out.append((d, start_level * v / base))
        level = out[-1][1]
    return out


def _thin(curve: Dict[str, List[tuple]], max_points: int = 400) -> Dict[str, Any]:
    dates = sorted({d for c in curve.values() for d, _ in c})
    step = max(1, len(dates) // max_points)
    keep = dates[::step] + ([dates[-1]] if dates and dates[-1] not in dates[::step] else [])
    res: Dict[str, Any] = {"dates": keep}
    for k, c in curve.items():
        m = dict(c)
        last = None
        vals = []
        for d in keep:
            last = m.get(d, last)
            vals.append(round(last, 2) if last is not None else None)
        res[k] = vals
    return res


# ── data ────────────────────────────────────────────────────────────────────
def _cache_dir() -> Path:
    p = Path(os.getenv("WF_CACHE_DIR") or "/tmp/alpatrade_wf_cache")
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_bars(symbols: List[str], asof: Optional[str] = None,
              fetch: Optional[Callable[[List[str], str, str], Dict[str, List[Dict[str, Any]]]]] = None
              ) -> Dict[str, List[Dict[str, Any]]]:
    """Daily OHLC (split/dividend adjusted) from DATA_START to ``asof`` for the symbols + indices,
    cached on disk per (symbol, asof)."""
    asof = asof or data_asof()
    want = list(dict.fromkeys([s.upper() for s in symbols] + list(INDEX_SYMBOLS)))
    out: Dict[str, List[Dict[str, Any]]] = {}
    missing = []
    for s in want:
        f = _cache_dir() / f"{s}_{asof}.json"
        if f.exists():
            try:
                out[s] = json.loads(f.read_text())
                continue
            except Exception:  # noqa: BLE001
                pass
        missing.append(s)
    if missing:
        got = (fetch or _yf_fetch)(missing, DATA_START, asof)
        for s, rows in got.items():
            out[s] = rows
            try:
                (_cache_dir() / f"{s}_{asof}.json").write_text(json.dumps(rows))
            except Exception:  # noqa: BLE001
                pass
    return out


def _yf_fetch(symbols: List[str], start: str, end: str) -> Dict[str, List[Dict[str, Any]]]:
    import yfinance as yf
    end_x = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    df = yf.download(symbols, start=start, end=end_x, auto_adjust=True, progress=False, group_by="ticker",
                     threads=True)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for s in symbols:
        try:
            d = df[s] if len(symbols) > 1 else df
            if hasattr(d.columns, "levels") and len(symbols) == 1:
                d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
            d = d[["Open", "High", "Low", "Close"]].dropna()
            out[s] = [{"t": i.date().isoformat(), "o": float(r.Open), "h": float(r.High), "l": float(r.Low),
                       "c": float(r.Close)} for i, r in d.iterrows()]
        except Exception as exc:  # noqa: BLE001
            log.warning("wf: no bars for %s: %s", s, type(exc).__name__)
    return out

#!/usr/bin/env python3
"""v0.55.0 comparison: regular-hours stops vs always-on (24/5) stops vs full 24/5 trading, for the
live sleeves (strategy_configs #1 Mag-7, #3 Semi-7), on cached Alpaca 5-min bars incl. extended
hours (SIP pre/post 04:00-20:00 ET since 2016; BOATS overnight 20:00-04:00 ET since 2024-09).

Read-only: reads the DB rows (no writes), Alpaca market data + calendar (paper keys). Places no
orders. The rule set is the DB row; keys sql/57 adds are applied IN MEMORY exactly as the migration
would (seed || stored) until the migration is run, and the recorded version says so.

  python scripts/btd_overnight_compare.py --out /tmp/overnight_stops
"""
from __future__ import annotations

import argparse, json, math, os, sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

import utils.btd_event_backtest as BT  # noqa: E402
import utils.btd_rules as R  # noqa: E402
from scripts.fetch_intraday_bars import load  # noqa: E402
from utils.live_btd_config import REQUIRED_PARAM_KEYS, coerce_params, fetch_row, make_engine, merge_execution  # noqa: E402

ET = ZoneInfo("America/New_York")
SQL57 = os.path.join(ROOT, "sql", "57_rules_db_only.sql")


def sql57_seed():
    import re
    t = open(SQL57).read()
    b = [json.loads(x) for x in re.findall(r"'(\{.*?\})'::jsonb", t, re.S) if x != "{}"]
    return b[0], b[1], b[2]           # operator params seed, regular_hours_exit, extended_hours_exit


def rule_set(eng, cid):
    rid, name, rp, rx, ver, active = fetch_row(eng, str(cid))[:6]
    rp = json.loads(rp) if isinstance(rp, str) else rp; rx = json.loads(rx) if isinstance(rx, str) else rx
    ps, reg, ext = sql57_seed()
    applied = not all(k in rp for k in REQUIRED_PARAM_KEYS)
    P = coerce_params({**ps, **rp})
    X = merge_execution({"regular_hours_exit": {**reg, **(rx.get("regular_hours_exit") or {})},
                         "extended_hours_exit": {**ext, **(rx.get("extended_hours_exit") or {})}})
    return name, P, X, f"strategy_configs#{rid} v{ver}" + (" + sql/57 seed in memory (migration not yet applied)" if applied else "")


def calendar(start, end):
    e = dotenv_values(os.path.join(ROOT, ".env"))
    h = {"APCA-API-KEY-ID": e["ALPACA_PAPER_API_KEY"], "APCA-API-SECRET-KEY": e["ALPACA_PAPER_SECRET_KEY"]}
    r = requests.get("https://paper-api.alpaca.markets/v2/calendar", headers=h, params={"start": start, "end": end}, timeout=60)
    r.raise_for_status()
    return [(c["date"], c["open"], c["close"]) for c in r.json()]


def build(sym, cal):
    """(daily bars from the regular session, ext windows {day: [(ts_end_et, o, h, l, c)]})."""
    sip = load(sym, "sip"); bo = load(sym, "boats")
    df = pd.concat([sip.assign(src=0), bo.assign(src=1)]).sort_values(["t", "src"]).drop_duplicates("t", keep="first")
    df["et"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(ET)
    df["end"] = df["et"] + pd.Timedelta(minutes=5)
    sess = {d: (datetime.fromisoformat(f"{d}T{o}").replace(tzinfo=ET), datetime.fromisoformat(f"{d}T{c}").replace(tzinfo=ET))
            for d, o, c in cal}
    days = [d for d, _, _ in cal]
    daily, xw = [], {}
    et = df["et"].values; ends = df["end"].tolist()
    rows = df[["o", "h", "l", "c"]].to_numpy()
    import bisect
    ets = df["et"].tolist()
    for i, d in enumerate(days):
        o, c = sess[d]
        a, b = bisect.bisect_left(ets, o), bisect.bisect_left(ets, c)
        if b > a:
            seg = rows[a:b]
            daily.append({"t": d, "o": float(seg[0][0]), "h": float(seg[:, 1].max()), "l": float(seg[:, 2].min()),
                          "c": float(seg[-1][3])})
        if i + 1 < len(days):
            no = sess[days[i + 1]][0]
            a2, b2 = bisect.bisect_left(ets, c), bisect.bisect_left(ets, no)
            xw[d] = [(ends[k].to_pydatetime(), *map(float, rows[k])) for k in range(a2, b2)]
    return daily, xw


def metrics(eq, spy_daily, trades, ext_exits, start, end):
    s = pd.Series({d: v for d, v in eq}).sort_index()
    r = s.pct_change().dropna()
    n = len(s)
    tot = s.iloc[-1] / s.iloc[0] - 1
    cagr = (1 + tot) ** (252 / max(1, n - 1)) - 1
    dd = (s / s.cummax() - 1).min()
    sh = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else float("nan")
    sp = pd.Series({b["t"]: b["c"] for b in spy_daily if start <= b["t"] <= end}).sort_index()
    spr = sp.pct_change().dropna()
    return {"return_pct": round(tot * 100, 2), "cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(dd * 100, 2),
            "sharpe": round(sh, 2), "trades": len(trades),
            "overnight_exits": sum(1 for t in trades if "_ext" in t.reason and not t.reason.endswith("_open")),
            "open_fallback_exits": sum(1 for t in trades if t.reason.endswith("_ext_open")),
            "ext_entries": 0,
            "spy_return_pct": round((sp.iloc[-1] / sp.iloc[0] - 1) * 100, 2),
            "spy_max_dd_pct": round(((sp / sp.cummax()) - 1).min() * 100, 2),
            "spy_sharpe": round(spr.mean() / spr.std() * math.sqrt(252), 2)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="/tmp/overnight_stops")
    ap.add_argument("--start", default="2016-01-04"); ap.add_argument("--end", default="2026-10-20")
    ap.add_argument("--overnight-start", default="2024-09-17")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    e = dotenv_values(os.path.join(ROOT, ".env")); eng = make_engine(e["DATABASE_URL"])
    cal = calendar("2015-11-01", a.end)
    out = {"periods": {}, "rule_sets": {}}
    cache = {}
    for cid in (1, 3):
        name, P, X, ver = rule_set(eng, cid)
        out["rule_sets"][cid] = {"name": name, "version": ver, "params": P, "execution": X}
        syms = list(P["symbols"]); need = set(syms) | set(R.regime_symbols(P)) | {"SPY"}
        for s in need:
            if s not in cache:
                cache[s] = build(s, cal); print("built", s, len(cache[s][0]), flush=True)
        bars = {s: cache[s][0] for s in syms}
        rb = {s: cache[s][0] for s in R.regime_symbols(P)}
        xw = {s: cache[s][1] for s in need}
        for label, (st, en) in {"full_history": (a.start, a.end), "with_overnight": (a.overnight_start, a.end)}.items():
            res = {}
            for mode in ("regular", "stops_24_5", "full_24_5"):
                Pm = {**P, "session_mode": mode}
                r = BT.run(bars, Pm, st, en, 10_000.0, regime_bars=rb, ext_windows=xw if mode != "regular" else None,
                           execution=X, config_version=f"{ver}; session_mode={mode} (comparison override)")
                m = metrics(r.equity, cache["SPY"][0], r.trades, r.ext_exits, st, en)
                m["ext_entries"] = sum(1 for t in r.trades if t.ext_entry)
                m["open_positions_end"] = len(r.open_positions)
                res[mode] = m
                pd.DataFrame(r.equity, columns=["date", "equity"]).to_csv(os.path.join(a.out, f"eq_{cid}_{label}_{mode}.csv"), index=False)
                pd.DataFrame([t.__dict__ for t in r.trades]).to_csv(os.path.join(a.out, f"trades_{cid}_{label}_{mode}.csv"), index=False)
                print(name, label, mode, m, flush=True)
            out["periods"].setdefault(label, {})[cid] = res
        spy = pd.DataFrame([b for b in cache["SPY"][0]])[["t", "c"]]
        spy.to_csv(os.path.join(a.out, "spy_daily.csv"), index=False)
    json.dump(out, open(os.path.join(a.out, "results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()

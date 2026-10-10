#!/usr/bin/env python3
"""Re-run buy_the_dip on the EXACT live rules (strategy_configs buy_the_dip_*_minhold_live:
dip 3% vs 20-day high, TP 8%, SL 1.5%, min = max hold 3 calendar days, 1/7 of equity per
position, cash only) after the v0.33.6 backtester fixes (true equity curve, stop-before-target,
10 bps slippage per side).

    python scripts/btd_live_rules_wf.py [--basket semi7|mag7|both] [--old /tmp/old_btd.py]

For each basket: (a) the 8 × 30-day out-of-sample windows used by the Semi 7 walk-forward
(fresh $10k each; no parameter search — the rules are fixed), (b) one continuous run over the
same span, (c) one continuous run 2016-01-04 → 2026-10-09. Metrics vs SPY on the same days.
Writes docs/btd_live_rules_wf_<ts>.json (+ .md).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import utils.buy_the_dip as btd  # noqa: E402
from engine.reporting.annualize import annualize, trading_days_between  # noqa: E402

BASKETS = {"semi7": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"],
           "mag7": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]}
LIVE = dict(dip_threshold=0.03, take_profit=0.08, stop_loss=0.015, hold_days=3, min_hold_days=3,
            position_size=1 / 7)
FOLDS = [("2026-02-11", "2026-03-13"), ("2026-03-13", "2026-04-12"), ("2026-04-12", "2026-05-12"),
         ("2026-05-12", "2026-06-11"), ("2026-06-11", "2026-07-11"), ("2026-07-11", "2026-08-10"),
         ("2026-08-10", "2026-09-09"), ("2026-09-09", "2026-10-09")]
SPAN = ("2026-02-11", "2026-10-09")
LONG = ("2016-01-04", "2026-10-09")
CAP = 10_000.0
_spy = None


def spy_close():
    global _spy
    if _spy is None:
        import yfinance as yf
        px = yf.download("SPY", start="2015-12-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
        _spy = {d.date().isoformat(): float(v) for d, v in px.items()}
    return _spy


def spy_ret(a, b):
    s = spy_close(); ks = sorted(s)
    pa = [k for k in ks if k <= a] or [k for k in ks if k >= a]
    pb = [k for k in ks if k <= b]
    return (s[pb[-1]] / s[pa[-1] if pa[-1] <= a else pa[0]] - 1) * 100


def spy_daily_stats(a, b):
    s = spy_close(); v = [s[k] for k in sorted(s) if a <= k <= b]
    return _curve_stats(v)


def _curve_stats(eq):
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    n = len(rets)
    mu = sum(rets) / n if n else 0.0
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1)) if n > 1 else 0.0
    peak, mdd = eq[0], 0.0
    for x in eq:
        peak = max(peak, x); mdd = min(mdd, x / peak - 1)
    return {"sharpe": (mu / sd * math.sqrt(252)) if sd else None, "max_drawdown_pct": mdd * 100}


def run(mod, syms, a, b, **kw):
    res = mod.backtest_buy_the_dip(syms, datetime.fromisoformat(a), datetime.fromisoformat(b),
                                   initial_capital=CAP, data_source="yfinance", **LIVE, **kw)
    if res is None:
        return {"total_return_pct": 0.0, "trades": 0}
    t, m, e = res
    eq = [float(x) for x in e["equity"]] if len(e) else [CAP]
    days = trading_days_between(datetime.fromisoformat(a).date(), datetime.fromisoformat(b).date())
    tot = (eq[-1] / CAP - 1) * 100
    an = annualize(tot, days, min_days=1)
    sp = spy_ret(a, b); sa = annualize(sp, days, min_days=1)
    st = _curve_stats([CAP] + eq)
    return {"period": [a, b], "trading_days": days, "total_return_pct": tot,
            "reported_total_return_pct": float(m["total_return"]),
            "simple_ann_pct": an["simple_pct"], "cagr_pct": an["compound_pct"], **st,
            "trades": int(len(t)), "win_rate_pct": float((t["pnl"] > 0).mean() * 100) if len(t) else None,
            "tp": int(t["TP"].sum()), "sl": int(t["SL"].sum()),
            "spy_return_pct": sp, "spy_simple_ann_pct": sa["simple_pct"], "spy_cagr_pct": sa["compound_pct"],
            "spy": spy_daily_stats(a, b),
            "alpha_simple_ann_pct": an["simple_pct"] - sa["simple_pct"],
            "curve": _curve(e, a)}


def _curve(e, start):
    """Daily equity curve (weekly when > 400 points) + SPY on the same dates."""
    if e is None or not len(e):
        return {}
    s = spy_close(); ks = sorted(s)
    rows = [(str(ts)[:10], float(v)) for ts, v in zip(e["timestamp"], e["equity"])]
    if len(rows) > 400:
        rows = rows[::5] + ([rows[-1]] if (len(rows) - 1) % 5 else [])
    def sp(d):
        prior = [k for k in ks if k <= d]
        return s[prior[-1]] if prior else None
    return {"dates": [d for d, _ in rows], "equity": [round(v, 2) for _, v in rows],
            "spy": [sp(d) for d, _ in rows]}


def to_md(out) -> str:
    L = ["# buy_the_dip on the live rules after the v0.33.6 backtester fixes", "",
         f"_Generated {out['generated'][:16]} UTC · rules: dip 3% vs 20-day high, TP 8%, SL 1.5%, "
         "min = max hold 3 calendar days, 1/7 of equity per position, cash only · daily bars "
         "(yfinance, adjusted), entry at the signal close + 10 bps, stop before target when both are "
         "touched, stop fills at the open when gapped through, 10 bps per side._", "",
         "Annualised = simple total × 252 / trading days (CAGR alongside). Sharpe from daily equity, rf 0.", ""]
    hdr = ("| Basket | Run | Period | Total | Simple ann. | CAGR | Sharpe | Max DD | Trades | Win | "
           "SPY total | SPY simple | SPY Sharpe | SPY max DD | Alpha (simple) |")
    L += [hdr, "|" + "---|" * 15]
    for b, r in out["baskets"].items():
        for k, lab in (("span_old", "pre-fix code (reported total)"), ("span", "fixed"), ("long", "fixed")):
            x = r.get(k)
            if not x:
                continue
            tot = x["reported_total_return_pct"] if k == "span_old" else x["total_return_pct"]
            L.append(f"| {b} | {lab} | {x['period'][0]} → {x['period'][1]} ({x['trading_days']}d) | "
                     f"{tot:+.1f}% | {x['simple_ann_pct']:+.1f}% | {x['cagr_pct']:+.1f}% | "
                     f"{(x['sharpe'] or 0):.2f} | {x['max_drawdown_pct']:.1f}% | {x['trades']} | "
                     f"{(x['win_rate_pct'] or 0):.0f}% | {x['spy_return_pct']:+.1f}% | "
                     f"{x['spy_simple_ann_pct']:+.1f}% | {(x['spy']['sharpe'] or 0):.2f} | "
                     f"{x['spy']['max_drawdown_pct']:.1f}% | {x['alpha_simple_ann_pct']:+.1f}% |")
        L.append("")
        L.append(f"{b} 30-day folds (fresh $10k, fixed): " + ", ".join(f"{f['total_return_pct']:+.1f}%" for f in r["folds"])
                 + f" — sum {r['fold_sum_pct']:+.1f}%")
        if r.get("folds_old"):
            L.append(f"{b} folds, pre-fix code as reported: " + ", ".join(f"{f['reported_total_return_pct']:+.1f}%" for f in r["folds_old"]))
        L.append("")
    L += ["Caveat: the baskets are today's largest names (survivorship / selection bias flatters "
          "any long-only rule over 2016–2026). Hypothetical; not financial advice.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--basket", default="both", choices=["semi7", "mag7", "both"])
    ap.add_argument("--old", help="path to the pre-fix utils/buy_the_dip.py for a before/after")
    ap.add_argument("--no-long", action="store_true")
    a = ap.parse_args(argv)
    old = None
    if a.old:
        spec = importlib.util.spec_from_file_location("old_btd", a.old)
        old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    out = {"rules": LIVE, "generated": datetime.now(timezone.utc).isoformat(), "baskets": {}}
    for name in (["semi7", "mag7"] if a.basket == "both" else [a.basket]):
        syms = BASKETS[name]; r = {}
        r["folds"] = [run(btd, syms, x, y) for x, y in FOLDS]
        r["span"] = run(btd, syms, *SPAN)
        if old:
            r["folds_old"] = [run(old, syms, x, y, conservative_execution=False, slippage_bps=0.0) for x, y in FOLDS]
            r["span_old"] = run(old, syms, *SPAN, conservative_execution=False, slippage_bps=0.0)
        if not a.no_long:
            r["long"] = run(btd, syms, *LONG)
        r["fold_sum_pct"] = sum(f["total_return_pct"] for f in r["folds"])
        out["baskets"][name] = r
        print(name, json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in r.items()}, default=str)[:2000], flush=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    p = ROOT / "docs" / f"btd_live_rules_wf_{ts}.json"
    p.write_text(json.dumps(out, indent=1, default=float))
    p.with_suffix(".md").write_text(to_md(out))
    print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

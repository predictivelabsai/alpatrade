#!/usr/bin/env python3
"""Risk-overlay walk-forward on the PARITY backtester (v0.50.0: utils/btd_event_backtest, the
same rules module and event schedule as the live runner — stops during the min-hold, gap fills,
fractional dollar sizing at the 15:45 entry, whole/fraction stop split, DAY-stop expiry,
same-day-buy stop timing, 10 bps/side + TAF + CAT).

Variants: base | cap60 (max_exposure = $6,000 per $10k sleeve) | regime (regime_filter SPY,SMH) |
cap60+regime | halt_d2_w4 (research overlay, not a live rule).  Mag-7 and Semi-7 are separate
$10k sleeves; "both" = the summed account.

    python scripts/btd_risk_overlay_wf.py   -> docs/btd_risk_overlay_wf_<ts>.{json,md}
"""
from __future__ import annotations
import json, math, sys
from datetime import datetime, timezone, date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from utils import btd_event_backtest as BT  # noqa: E402
from tests.btd_fixtures import DEFAULT_PARAMS  # noqa: E402

BASKETS = {"semi7": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"],
           "mag7": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]}
LIVE = {**DEFAULT_PARAMS, "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3, "pos_frac": 0.142857}
FOLDS = [("2026-02-11", "2026-03-13"), ("2026-03-13", "2026-04-12"), ("2026-04-12", "2026-05-12"),
         ("2026-05-12", "2026-06-11"), ("2026-06-11", "2026-07-11"), ("2026-07-11", "2026-08-10"),
         ("2026-08-10", "2026-09-09"), ("2026-09-09", "2026-10-09")]
END = date.today().isoformat()
PERIODS = {"long_2016": ("2016-01-04", END), "is_2016_2022": ("2016-01-04", "2022-12-31"),
           "oos_2023+": ("2023-01-01", END), "last_6m": ("2026-04-16", END)}
CAP = 10_000.0


def load():
    import yfinance as yf
    out = {}
    for s in sum(BASKETS.values(), []) + ["SPY", "SMH"]:
        df = yf.download(s, start="2015-10-01", auto_adjust=True, progress=False)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        out[s] = [{"t": d.date().isoformat(), "o": float(r.Open), "h": float(r.High), "l": float(r.Low),
                   "c": float(r.Close)} for d, r in df.dropna().iterrows()]
    return out


VARIANTS = {"base": ({}, {}), "cap60": ({"max_exposure": 6000.0}, {}), "regime": ({"regime_filter": "SPY,SMH"}, {}),
            "cap60+regime": ({"max_exposure": 6000.0, "regime_filter": "SPY,SMH"}, {}),
            "halt_d2_w4": ({}, {"halt_daily": 0.02, "halt_weekly": 0.04})}


def stats(eq):
    r = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq)) if eq[i-1] > 0]
    n = len(r); mu = sum(r)/n if n else 0; sd = math.sqrt(sum((x-mu)**2 for x in r)/(n-1)) if n > 1 else 0
    pk, mdd = eq[0], 0.0
    for x in eq: pk = max(pk, x); mdd = min(mdd, x/pk - 1)
    tot = eq[-1]/eq[0] - 1; yrs = max(n, 1)/252
    return {"total_pct": tot*100, "cagr_pct": ((1+tot)**(1/yrs)-1)*100 if tot > -1 else -100,
            "sharpe": mu/sd*math.sqrt(252) if sd else None, "max_dd_pct": mdd*100}


def main():
    data = load(); res = {}
    reg = {k: data[k] for k in ("SPY", "SMH")}
    spy = {b["t"]: b["c"] for b in data["SPY"]}
    for pn, (a, b) in {**PERIODS, **{f"fold_{i+1}": f for i, f in enumerate(FOLDS)}}.items():
        res[pn] = {"period": [a, b], "spy": stats([spy[k] for k in sorted(spy) if a <= k <= b]), "variants": {}}
        for vn, (pk, ok) in VARIANTS.items():
            row, curves = {}, []
            for bk, syms in BASKETS.items():
                r = BT.run({s: data[s] for s in syms}, {**LIVE, **pk, "symbols": syms}, a, b, CAP,
                           regime_bars=reg, **ok)
                eq = dict(r.equity); curves.append(eq)
                row[bk] = {**stats([CAP] + [eq[k] for k in sorted(eq)]), "trades": len(r.trades),
                           "blocked_days": len(r.blocked)}
            days = sorted(set(curves[0]) | set(curves[1])); last = [CAP, CAP]; tot = [2*CAP]
            for d in days:
                for i, c in enumerate(curves):
                    if d in c: last[i] = c[d]
                tot.append(sum(last))
            row["both"] = stats(tot)
            res[pn]["variants"][vn] = row
            print(pn, vn, round(row["both"]["total_pct"], 1), round(row["both"]["sharpe"] or 0, 2),
                  round(row["both"]["max_dd_pct"], 1), flush=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (ROOT / f"docs/btd_risk_overlay_wf_{ts}.json").write_text(json.dumps({"generated": ts, "engine": "btd_event_backtest",
                                                                           "rules": LIVE, "results": res}, indent=1))
    L = [f"# BTD risk overlays on the parity backtester ({ts} UTC)", "",
         "Engine utils/btd_event_backtest (same rules + schedule as live). Account = Mag-7 + Semi-7 $10k sleeves summed.", "",
         "| Period | Variant | Total | CAGR | Sharpe | Max DD | Mag7 Sharpe | Semi7 Sharpe | SPY total | SPY Sharpe | SPY DD |",
         "|" + "---|"*11]
    for pn, r in res.items():
        if pn.startswith("fold_"): continue
        for vn, row in r["variants"].items():
            x = row["both"]; s = r["spy"]
            L.append(f"| {pn} | {vn} | {x['total_pct']:+.1f}% | {x['cagr_pct']:+.1f}% | {(x['sharpe'] or 0):.2f} | "
                     f"{x['max_dd_pct']:.1f}% | {(row['mag7']['sharpe'] or 0):.2f} | {(row['semi7']['sharpe'] or 0):.2f} | "
                     f"{s['total_pct']:+.1f}% | {(s['sharpe'] or 0):.2f} | {s['max_dd_pct']:.1f}% |")
    L += ["", "30-day folds (account total %):", ""]
    for vn in VARIANTS:
        L.append(f"- {vn}: " + ", ".join(f"{res[f'fold_{i+1}']['variants'][vn]['both']['total_pct']:+.1f}" for i in range(len(FOLDS))))
    (ROOT / f"docs/btd_risk_overlay_wf_{ts}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

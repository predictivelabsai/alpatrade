#!/usr/bin/env python3
"""Risk-overlay comparison on the EXACT live buy_the_dip rules (same engine/costs as
scripts/btd_live_rules_wf.py: dip 3% vs 20d high, TP 8%, SL 1.5% with gap fills at the open,
3-day min=max hold, 1/7 per position, 10 bps/side, FINRA TAF + CAT).

Variants: base | cap60 (gross exposure <= 60% of sleeve equity) | regime (no entries when SPY or
SMH closes below its prior 5-day low) | cap60+regime | halt (no entries after a -2% day or a
-4% drawdown vs the last-5-day high).  Mag-7 and Semi-7 run as separate $10k sleeves; "both" is
the summed $20k account.  Periods: long 2016-01-04 -> end, in-sample 2016-2022, out-of-sample
2023-01-01 -> end, last 6 months, plus the 8 x 30-day folds.

    python scripts/btd_risk_overlay_wf.py   -> docs/btd_risk_overlay_wf_<ts>.{json,md}
"""
from __future__ import annotations
import json, math, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import utils.buy_the_dip as btd  # noqa: E402
from scripts.btd_live_rules_wf import BASKETS, LIVE, FOLDS, FEES, CAP, spy_close  # noqa: E402

END = datetime.now().date().isoformat()
PERIODS = {"long_2016": ("2016-01-04", END), "is_2016_2022": ("2016-01-04", "2022-12-31"),
           "oos_2023+": ("2023-01-01", END), "last_6m": ("2026-04-16", END)}


def regime_blocked():
    import yfinance as yf
    out = set()
    for t in ("SPY", "SMH"):
        df = yf.download(t, start="2015-11-01", auto_adjust=True, progress=False)
        c, l = df["Close"].squeeze(), df["Low"].squeeze()
        low5 = l.rolling(5).min().shift(1)
        out |= {d.date().isoformat() for d in c.index[(c < low5).values]}
    return out


def variants(blk):
    return {"base": {}, "cap60": {"max_exposure_frac": 0.60}, "regime": {"entry_blocked": blk},
            "cap60+regime": {"max_exposure_frac": 0.60, "entry_blocked": blk},
            "halt_d2_w4": {"daily_loss_halt": 0.02, "weekly_dd_halt": 0.04}}


def curve(syms, a, b, kw):
    r = btd.backtest_buy_the_dip(syms, datetime.fromisoformat(a), datetime.fromisoformat(b),
                                 initial_capital=CAP, data_source="yfinance", **LIVE, **FEES, **kw)
    if r is None:
        return {}, 0
    t, m, e = r
    return {str(ts)[:10]: float(v) for ts, v in zip(e["timestamp"], e["equity"])}, len(t)


def stats(eq):
    r = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq)) if eq[i-1] > 0]
    n = len(r); mu = sum(r)/n if n else 0; sd = math.sqrt(sum((x-mu)**2 for x in r)/(n-1)) if n > 1 else 0
    pk, mdd = eq[0], 0.0
    for x in eq: pk = max(pk, x); mdd = min(mdd, x/pk - 1)
    yrs = max(n, 1) / 252
    tot = eq[-1]/eq[0] - 1
    return {"total_pct": tot*100, "cagr_pct": ((1+tot)**(1/yrs)-1)*100 if tot > -1 else -100,
            "sharpe": mu/sd*math.sqrt(252) if sd else None, "max_dd_pct": mdd*100}


def combine(cs, start_cap):
    days = sorted(set().union(*[c.keys() for c in cs]))
    last = [start_cap]*len(cs); out = []
    for d in days:
        for i, c in enumerate(cs):
            if d in c: last[i] = c[d]
        out.append(sum(last))
    return [start_cap*len(cs)] + out


def spy_stats(a, b):
    s = spy_close(); return stats([s[k] for k in sorted(s) if a <= k <= b])


def main():
    blk = regime_blocked(); V = variants(blk); res = {}
    for pn, (a, b) in {**PERIODS, **{f"fold_{i+1}": f for i, f in enumerate(FOLDS)}}.items():
        res[pn] = {"period": [a, b], "spy": spy_stats(a, b), "variants": {}}
        for vn, kw in V.items():
            cs, row = [], {}
            for bk, syms in BASKETS.items():
                c, nt = curve(syms, a, b, kw); cs.append(c)
                row[bk] = {**stats([CAP] + [c[k] for k in sorted(c)] if c else [CAP, CAP]), "trades": nt}
            row["both"] = stats(combine(cs, CAP))
            res[pn]["variants"][vn] = row
            print(pn, vn, {k: round(v["sharpe"] or 0, 2) for k, v in row.items()},
                  round(row["both"]["total_pct"], 1), round(row["both"]["max_dd_pct"], 1), flush=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = {"generated": ts, "rules": LIVE, "regime_blocked_days": len(blk), "results": res}
    (ROOT / f"docs/btd_risk_overlay_wf_{ts}.json").write_text(json.dumps(out, indent=1))
    L = [f"# BTD risk overlays (live rules, {ts} UTC)", "",
         "Account = Mag-7 + Semi-7 $10k sleeves summed. Costs: 10 bps/side + TAF + CAT; stop gap-fills at open.", "",
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
    for vn in V:
        L.append(f"- {vn}: " + ", ".join(f"{res[f'fold_{i+1}']['variants'][vn]['both']['total_pct']:+.1f}" for i in range(len(FOLDS))))
    (ROOT / f"docs/btd_risk_overlay_wf_{ts}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

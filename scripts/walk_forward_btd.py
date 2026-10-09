#!/usr/bin/env python3
"""Walk-forward for buy_the_dip on the Mag-7 basket — PnL is the objective.

The honest anti-over-fit test: for each fold, optimise the grid on a TRAIN window
(pick the config with the highest **PnL**), then trade that exact config on the next,
unseen TEST window and record the **out-of-sample PnL**. Optimising and reporting on
PnL only (no Sharpe). Also runs a fixed naive-default config on each test window as a
baseline, to show whether per-fold optimisation actually adds PnL or just over-fits.

``--by-regime`` (Phase 4b): instead of fixed calendar folds, segment the test
windows by the market regime classifier (`engine.regime`). Each fold's test
window covers a single regime state, and the train window is the preceding
period of the *same* regime — so you see how a config chosen in one
low-vol/bear window transfers to the next low-vol/bear window. This is the
regime-conditional stability test that pure calendar folds miss.

Usage: python scripts/walk_forward_btd.py [--by-regime]
Writes docs/walk_forward_btd_<ts>.md (+ PDF rendered separately).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from agents.backtest_agent import BacktestAgent  # noqa: E402

MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]
# Semi 7: the 7 largest US-listed semiconductor stocks by market cap that are NOT in the
# Mag-7 (NVDA excluded). yfinance caps 2026-10-09 ($B): TSM 2346, AVGO 1726, MU 1159,
# AMD 992, ASML 684, INTC 552, AMAT 402 (next: LRCX 399, ARM 285, TXN 259).
SEMI7 = ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"]
BASKETS = {"mag7": ("Mag-7", MAG7), "semi7": ("Semi-7", SEMI7)}
BASKET_KEY, (BASKET_LABEL, BASKET) = "mag7", BASKETS["mag7"]
CAPITAL = 10000.0
GRID = {
    "dip_threshold": [0.03, 0.05, 0.07],
    "take_profit": [0.01, 0.015],
    "hold_days": [1, 2, 3],
    "stop_loss": [0.005],
    "position_size": [0.10],
}
NAIVE = {"dip_threshold": 0.05, "take_profit": 0.01, "hold_days": 2,
         "stop_loss": 0.005, "position_size": 0.10}

TRAIN_DAYS, TEST_DAYS, FOLDS = 60, 30, 8


def _pnl(total_return_pct) -> float:
    return CAPITAL * float(total_return_pct or 0) / 100.0


def _run(strategy_req: dict) -> dict:
    return BacktestAgent().run(strategy_req)


def _backtest(start, end, variations):
    """Return list of {params, return_pct, trades} for the grid over [start, end]."""
    res = _run({"strategy": "buy_the_dip", "symbols": BASKET,
                "start_date": start.isoformat(), "end_date": end.isoformat(),
                "variations": variations, "initial_capital": CAPITAL})
    return [{"params": r.get("params"), "return_pct": float(r.get("total_return", 0) or 0),
             "trades": int(r.get("total_trades", 0) or 0),
             "win_rate": float(r.get("win_rate", 0) or 0)}
            for r in (res.get("all_results_summary") or [])]


def _bh_return(start, end) -> float:
    """Equal-weight buy-and-hold return of the basket over [start, end] (adjusted closes)."""
    try:
        import yfinance as yf
        px = yf.download(BASKET, start=start.date().isoformat(), end=(end + timedelta(days=1)).date().isoformat(),
                         auto_adjust=True, progress=False)["Close"].dropna(how="all").ffill().dropna(axis=1)
        if len(px) < 2:
            return 0.0
        return float((px.iloc[-1] / px.iloc[0] - 1).mean())
    except Exception as e:  # noqa: BLE001
        print(f"  buy-and-hold {start.date()} failed: {e}")
        return 0.0


def risk_metrics(rows: list, test_days: int) -> dict:
    """CAGR / Sharpe / max DD / win rates of chained OOS fold returns vs buy-and-hold."""
    import statistics

    def stats(rets):
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in rets:
            eq *= 1 + r; peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        years = len(rets) * test_days / 365.0
        cagr = eq ** (1 / years) - 1 if years and eq > 0 else 0.0
        sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        sharpe = (statistics.mean(rets) / sd) * (365.0 / test_days) ** 0.5 if sd else 0.0
        return cagr, sharpe, mdd
    b = [r.get("oos_ret", 0.0) for r in rows]; h = [r.get("bh_ret", 0.0) for r in rows]
    bc, bs, bm = stats(b); hc, hs, hm = stats(h)
    trd = [r for r in rows if r.get("oos_trades")]
    return {"n": len(rows), "btd_cagr": bc, "btd_sharpe": bs, "btd_mdd": bm, "bh_cagr": hc, "bh_sharpe": hs,
            "bh_mdd": hm, "btd_pos": sum(x > 0 for x in b), "bh_pos": sum(x > 0 for x in h),
            "beat": sum(x > y for x, y in zip(b, h)),
            "trade_win_rate": (sum(r["oos_win_rate"] for r in trd) / len(trd)) if trd else 0.0}


def _pin(params: dict) -> dict:
    return {k: [params[k]] for k in GRID if k in params}


def _regime_folds(today: datetime, test_days: int, folds: int) -> list:
    """Generate folds segmented by market regime (Phase 4b).

    For each of the last `folds` calendar test windows, classify the regime
    of the test window's start date and label the fold. The train window is
    the preceding `TRAIN_DAYS` of the *same* regime state (scanned backwards
    from the test start until enough same-regime days are found, up to a
    2× lookback cap). Falls back to a plain calendar train window if the
    regime classifier is unavailable.
    """
    try:
        from engine.regime import classify_regime
    except Exception:  # noqa: BLE001
        classify_regime = None

    out = []
    for i in range(folds):
        test_end = today - timedelta(days=i * test_days)
        test_start = test_end - timedelta(days=test_days)
        train_end = test_start
        # Try to find a train window in the same regime
        regime_label = None
        if classify_regime:
            try:
                regime_label = classify_regime(test_start).state
            except Exception:  # noqa: BLE001
                pass
        # Scan backwards for same-regime days (up to 2x TRAIN_DAYS)
        if regime_label and classify_regime:
            collected = []
            scan = train_end
            for _ in range(TRAIN_DAYS * 2):
                try:
                    if classify_regime(scan).state == regime_label:
                        collected.append(scan)
                except Exception:  # noqa: BLE001
                    pass
                scan -= timedelta(days=1)
                if len(collected) >= TRAIN_DAYS:
                    break
            if len(collected) >= TRAIN_DAYS // 2:
                train_start = collected[-1] - timedelta(days=TRAIN_DAYS)
            else:
                train_start = train_end - timedelta(days=TRAIN_DAYS)
        else:
            train_start = train_end - timedelta(days=TRAIN_DAYS)
        out.append((train_start, train_end, test_start, test_end, regime_label or "unknown"))
    out.reverse()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-regime", action="store_true",
                    help="Segment folds by market regime (Phase 4b)")
    ap.add_argument("--basket", choices=sorted(BASKETS), default="mag7",
                    help="symbol basket (default mag7; semi7 = Semi 7)")
    args = ap.parse_args()
    global BASKET_KEY, BASKET_LABEL, BASKET
    BASKET_KEY = args.basket; BASKET_LABEL, BASKET = BASKETS[args.basket]

    today = datetime.now()
    if args.by_regime:
        folds = _regime_folds(today, TEST_DAYS, FOLDS)
    else:
        folds = [(today - timedelta(days=i * TEST_DAYS) - timedelta(days=TEST_DAYS + TRAIN_DAYS),
                  today - timedelta(days=i * TEST_DAYS) - timedelta(days=TEST_DAYS),
                  today - timedelta(days=i * TEST_DAYS) - timedelta(days=TEST_DAYS),
                  today - timedelta(days=i * TEST_DAYS), None)
                 for i in range(FOLDS)]
        folds.reverse()
        folds = [(tr_s, tr_e, te_s, te_e, None) for (tr_s, tr_e, te_s, te_e) in
                 [(f[0], f[1], f[2], f[3]) for f in folds]]

    rows = []
    for (tr_s, tr_e, te_s, te_e, regime) in folds:
        try:
            grid = _backtest(tr_s, tr_e, GRID)
            grid = [g for g in grid if g["params"]]
            if not grid:
                continue
            best = max(grid, key=lambda g: g["return_pct"])   # OPTIMISE ON PnL
            is_pnl = _pnl(best["return_pct"])
            oos = _backtest(te_s, te_e, _pin(best["params"]))
            oos_pnl = _pnl(oos[0]["return_pct"]) if oos else 0.0
            oos_trades = oos[0]["trades"] if oos else 0
            base = _backtest(te_s, te_e, {k: [v] for k, v in NAIVE.items()})
            base_pnl = _pnl(base[0]["return_pct"]) if base else 0.0
            rows.append({
                "test_period": f"{te_s.date()}→{te_e.date()}",
                "regime": regime or "",
                "params": {k: best["params"].get(k) for k in ("dip_threshold", "take_profit", "hold_days")},
                "is_pnl": round(is_pnl, 0), "oos_pnl": round(oos_pnl, 0),
                "oos_trades": oos_trades, "base_pnl": round(base_pnl, 0),
                "oos_ret": (oos[0]["return_pct"] / 100.0) if oos else 0.0,
                "oos_win_rate": oos[0]["win_rate"] if oos else 0.0,
                "bh_ret": _bh_return(te_s, te_e),
            })
            print(f"  {te_s.date()}→{te_e.date()} [{regime or '?'}]  IS=${is_pnl:,.0f}  "
                  f"OOS=${oos_pnl:,.0f}  (trades {oos_trades})  naive=${base_pnl:,.0f}")
        except Exception as e:  # noqa: BLE001
            print(f"  fold {te_s.date()} failed: {e}")

    if not rows:
        print("no folds produced results")
        return 1

    tot_oos = sum(r["oos_pnl"] for r in rows)
    tot_is = sum(r["is_pnl"] for r in rows)
    tot_base = sum(r["base_pnl"] for r in rows)
    oos_wins = sum(1 for r in rows if r["oos_pnl"] > 0)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    L = []
    a = L.append
    a(f"# AlpaTrade — buy_the_dip walk-forward ({BASKET_LABEL}, PnL objective)\n")
    a(f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · basket "
      f"{', '.join(BASKET)} · ${CAPITAL:,.0f}/fold · train {TRAIN_DAYS}d → test {TEST_DAYS}d, "
      f"rolling · {len(rows)} folds_\n")
    a("Each fold: optimise the grid on the **train** window by **PnL**, then trade that exact "
      "config on the next, unseen **test** window. **OOS PnL** is the honest number — money the "
      "just-optimised config made on data it never saw. Naive = a fixed default config, untouched.\n")
    a("## Fold-by-fold (out-of-sample)\n")
    if any(r.get("regime") for r in rows):
        a("| Test window | Regime | Chosen dip/TP/hold | In-sample PnL | **OOS PnL** | OOS trades | Naive PnL |")
        a("|---|---|---|---:|---:|---:|---:|")
        for r in rows:
            p = r["params"]
            a(f"| {r['test_period']} | {r.get('regime','?')} | {p['dip_threshold']}/{p['take_profit']}/{p['hold_days']} | "
              f"${r['is_pnl']:,.0f} | **${r['oos_pnl']:,.0f}** | {r['oos_trades']} | ${r['base_pnl']:,.0f} |")
        a(f"| **Total** | | | ${tot_is:,.0f} | **${tot_oos:,.0f}** | | ${tot_base:,.0f} |\n")
    else:
        a("| Test window | Chosen dip/TP/hold | In-sample PnL | **OOS PnL** | OOS trades | Naive PnL |")
        a("|---|---|---:|---:|---:|---:|")
        for r in rows:
            p = r["params"]
            a(f"| {r['test_period']} | {p['dip_threshold']}/{p['take_profit']}/{p['hold_days']} | "
              f"${r['is_pnl']:,.0f} | **${r['oos_pnl']:,.0f}** | {r['oos_trades']} | ${r['base_pnl']:,.0f} |")
        a(f"| **Total** | | ${tot_is:,.0f} | **${tot_oos:,.0f}** | | ${tot_base:,.0f} |\n")
    a("## Verdict (PnL)\n")
    a(f"- **Out-of-sample PnL: ${tot_oos:,.0f}** across {len(rows)} folds "
      f"(${CAPITAL:,.0f}/fold), profitable in **{oos_wins}/{len(rows)}** folds.")
    a(f"- In-sample PnL was ${tot_is:,.0f}. The **IS→OOS drop of "
      f"${tot_is - tot_oos:,.0f}** ({100*(tot_is-tot_oos)/tot_is:.0f}% of in-sample) is the over-fit "
      f"tax — how much the grid-optimised number overstates reality.")
    verdict = ("optimising per fold BEAT the fixed naive config out-of-sample — the tuning adds real PnL"
               if tot_oos > tot_base else
               "optimising per fold did NOT beat the fixed naive config out-of-sample — the per-fold "
               "tuning is likely over-fitting; prefer the simple fixed config")
    a(f"- vs a fixed naive config (${tot_base:,.0f} OOS): {verdict}.")
    a(f"- Bottom line: **${tot_oos:,.0f} of realistic (out-of-sample) PnL** is the number to trust, not "
      f"the ${tot_is:,.0f} in-sample figure.\n")

    # annualised return + periods
    import functools
    test_days = len(rows) * TEST_DAYS
    oos_rets = [r["oos_pnl"] / CAPITAL for r in rows]
    simple = sum(oos_rets)
    comp = functools.reduce(lambda x, y: x * (1 + y), oos_rets, 1.0) - 1
    ann_simple = simple * 365 / test_days
    ann_comp = (1 + comp) ** (365 / test_days) - 1
    periods = f"{rows[0]['test_period'].split('→')[0]} → {rows[-1]['test_period'].split('→')[1]}"
    a("## Annualised return & periods covered\n")
    a(f"- **Periods (out-of-sample):** {periods} ({len(rows)} × {TEST_DAYS}d = {test_days}d "
      f"≈ {test_days // 30} months); training data reaches ~{TRAIN_DAYS}d earlier.")
    a(f"- **Avg per-fold ({TEST_DAYS}d) OOS return:** +{100*simple/len(rows):.1f}%.")
    a(f"- **Annualised OOS return:** ~{ann_simple*100:.0f}% simple / ~{ann_comp*100:.0f}% compounded "
      f"(×{comp+1:.1f} over {test_days}d).")
    a("- A return this large is a **warning about idealised fills**, not a headline — realistic "
      "execution (slippage + fees) would cut it to a fraction.\n")

    m = risk_metrics(rows, TEST_DAYS)
    a("## Risk metrics vs buy-and-hold (out-of-sample windows)\n")
    a("Fold returns are chained (compounded) across the consecutive test windows. Buy-and-hold = "
      "equal-weight basket bought at the first close of each test window and held to its last close "
      "(yfinance adjusted closes). Sharpe = mean/stdev of fold returns × sqrt(folds per year), rf = 0.\n")
    a("| Metric | BTD (walk-forward OOS) | Buy & hold (same windows) |")
    a("|---|---:|---:|")
    a(f"| CAGR | {m['btd_cagr']*100:.1f}% | {m['bh_cagr']*100:.1f}% |")
    a(f"| Sharpe (fold-based) | {m['btd_sharpe']:.2f} | {m['bh_sharpe']:.2f} |")
    a(f"| Max drawdown (fold equity) | {m['btd_mdd']*100:.1f}% | {m['bh_mdd']*100:.1f}% |")
    a(f"| Profitable folds | {m['btd_pos']}/{m['n']} | {m['bh_pos']}/{m['n']} |")
    a(f"| Avg trade win rate (OOS) | {m['trade_win_rate']:.1f}% | — |")
    a(f"| Folds BTD beat B&H | {m['beat']}/{m['n']} | |\n")
    a("## Caveats\n")
    a("- Still uses the backtester's fill/fee model; OOS removes *window* over-fit but not idealised "
      "execution. Real fills/slippage would reduce this further.")
    a("- Each fold is a fresh $10k (not compounded). Hypothetical; not financial advice.\n")
    a("## Storage & reproduce\n")
    a("- All train + test runs persist to `alpatrade.runs`/`backtest_summaries`/`trades`.")
    a(f"- Reproduce: `python scripts/walk_forward_btd.py{'' if BASKET_KEY == 'mag7' else ' --basket ' + BASKET_KEY}`.\n")

    tag = "" if BASKET_KEY == "mag7" else f"{BASKET_KEY}_"
    out = ROOT / "docs" / f"walk_forward_btd_{tag}{ts}.md"
    out.write_text("\n".join(L))
    (ROOT / "docs" / "_last_wf_path.txt").write_text(str(out))
    print("WROTE", out)
    print(json.dumps({"rows": rows, "total_oos": tot_oos, "total_is": tot_is,
                      "total_naive": tot_base, "oos_wins": oos_wins, "metrics": m}, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

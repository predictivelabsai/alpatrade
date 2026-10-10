"""Semi 7 leaderboard backtest entry, built from the walk-forward report
(docs/walk_forward_btd_semi7_*.json, scripts/walk_forward_btd.py --basket semi7).

The out-of-sample fold returns are chained into an equity curve (one point per fold
boundary, $10k base), SPY closes on the same dates give the benchmark. Annualised = SIMPLE
total × 252 / trading days (engine/reporting/annualize.py); CAGR kept as a secondary field.
``live_slug`` makes the leaderboard switch to live figures once
the live Semi 7 sleeve has a session-close snapshot (engine.leaderboard.perf).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

SEED_KEY = "semi7-btd-backtest"
LIVE_SLUG = "buy_the_dip_semi7_minhold_live"
CAPITAL = 10_000.0


LIVE_PARAMS = {"dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3}


def audit_input(wf: dict | None = None) -> dict:
    """What the audit needs to know about how this walk-forward was produced
    (scripts/walk_forward_btd.py on utils/buy_the_dip.py as of 2026-10-09), incl. faults found
    by live ops on 2026-10-10 that the stored fold returns cannot show by themselves."""
    tested = {"dip_threshold": 0.03, "take_profit": 0.015, "stop_loss": 0.005, "hold_days": 1}
    if wf and wf.get("rows"):
        tested = dict(wf["rows"][0].get("params") or tested)
    out = {"engine": "buy_the_dip", "engine_stamp": {"engine": "buy_the_dip", "engine_version": "0.32.1"},
           "slippage_bps": 0.0, "fees_recorded": False, "label": "live", "params": tested,
           "live_params": LIVE_PARAMS, "same_bar_policy": "target_first", "fill_rule": "close",
           "universe": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"], "universe_as_of": "2026-10-09",
           "known_issues": ["utils/buy_the_dip.py overstated capital_after when several positions closed on "
                            "the same bar: the reported +550.8% total is about +28% once reconciled "
                            "(AlpaTrade live ops, 2026-10-10)"]}
    if wf:
        out["is_return_pct"] = wf.get("total_is", 0) / CAPITAL * 100 if wf.get("total_is") is not None else None
        out["oos_return_pct"] = wf.get("total_oos", 0) / CAPITAL * 100 if wf.get("total_oos") is not None else None
    return out


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def build_metrics(wf: dict, spy_close: dict, source: str = "") -> dict:
    """wf = walk-forward JSON; spy_close = {YYYY-MM-DD: close} (nearest prior close used)."""
    from engine.reporting.annualize import trading_days_between
    rows = wf["rows"]
    bounds = [r["test_period"].split("→") for r in rows]
    dates = [bounds[0][0]] + [b[1] for b in bounds]
    eq = [CAPITAL]
    for r in rows:
        eq.append(eq[-1] * (1 + float(r.get("oos_ret", r["oos_pnl"] / CAPITAL))))
    keys = sorted(spy_close)

    def spy_on(d):
        prior = [k for k in keys if k <= d]
        return float(spy_close[prior[-1]]) if prior else None
    spy = [spy_on(d) for d in dates]
    start, end = _d(dates[0]), _d(dates[-1])
    tot = eq[-1] / eq[0] - 1
    spy_tot = (spy[-1] / spy[0] - 1) if spy[0] and spy[-1] else None
    from engine.reporting.annualize import annualize
    days = trading_days_between(start, end)
    cagr = (annualize(tot * 100, days, 1)["compound_pct"] or 0.0) / 100
    spy_cagr = (annualize(spy_tot * 100, days, 1)["compound_pct"] or 0.0) / 100 if spy_tot is not None else None
    ann = tot * 252 / days if days else 0.0
    spy_ann = spy_tot * 252 / days if (days and spy_tot is not None) else None
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    m = wf.get("metrics") or {}
    trades = sum(int(r.get("oos_trades") or 0) for r in rows)
    return {
        "period_start": dates[0], "period_end": dates[-1],
        "trading_days": trading_days_between(start, end),
        "total_return_pct": tot * 100, "annualised_pct": ann * 100,
        "annualised_cagr_pct": cagr * 100,
        "spy_return_pct": None if spy_tot is None else spy_tot * 100,
        "spy_annualised_pct": None if spy_ann is None else spy_ann * 100,
        "spy_annualised_cagr_pct": None if spy_cagr is None else spy_cagr * 100,
        "alpha_pct": None if spy_tot is None else (tot - spy_tot) * 100,
        "alpha_annualised_pct": None if spy_ann is None else (ann - spy_ann) * 100,
        "sharpe": m.get("btd_sharpe"), "max_drawdown_pct": mdd * 100,
        "win_rate_pct": m.get("trade_win_rate"), "trades": trades,
        "universe": "Semi 7: TSM, AVGO, MU, AMD, ASML, INTC, AMAT",
        "template": "buy_the_dip walk-forward (8 × 30d out-of-sample folds)",
        "test": {}, "episodes": [], "source_report": source,
        "equity_curve": {"dates": dates, "equity": [round(v, 2) for v in eq], "spy": spy},
        "live_slug": LIVE_SLUG,
        "audit_input": audit_input(wf),
    }


def build_metrics_live_rules(report: dict, basket: str = "semi7", source: str = "") -> dict:
    """backtest_metrics from scripts/btd_live_rules_wf.py (exact live rules, fixed backtester):
    headline = the continuous 2016–2026 run; ``test`` = the 2026-02-11 → 2026-10-09 window."""
    r = report["baskets"][basket]
    L, S = r["long"], r["span"]
    return {
        "period_start": L["period"][0], "period_end": L["period"][1],
        "trading_days": L["trading_days"], "total_return_pct": L["total_return_pct"],
        "annualised_pct": L["simple_ann_pct"], "annualised_cagr_pct": L["cagr_pct"],
        "spy_return_pct": L["spy_return_pct"], "spy_annualised_pct": L["spy_simple_ann_pct"],
        "spy_annualised_cagr_pct": L["spy_cagr_pct"],
        "alpha_pct": L["total_return_pct"] - L["spy_return_pct"],
        "alpha_annualised_pct": L["alpha_simple_ann_pct"],
        "sharpe": L["sharpe"], "max_drawdown_pct": L["max_drawdown_pct"],
        "win_rate_pct": L["win_rate_pct"], "trades": L["trades"],
        "universe": "Semi 7: TSM, AVGO, MU, AMD, ASML, INTC, AMAT (today's largest; survivorship bias)",
        "template": ("buy_the_dip, exact live rules: dip 3% vs 20-day high, TP 8%, SL 1.5%, min = max "
                     "hold 3 days, 1/7 per position, cash only; stop-before-target, 10 bps/side"),
        "test": {"period_start": S["period"][0], "period_end": S["period"][1],
                 "annualised_pct": S["cagr_pct"], "spy_annualised_pct": S["spy_cagr_pct"],
                 "sharpe": S["sharpe"], "max_drawdown_pct": S["max_drawdown_pct"], "trades": S["trades"]},
        "episodes": [], "source_report": source,
        "equity_curve": L.get("curve") or {},
        "live_slug": LIVE_SLUG,
        "engine_stamp": report.get("engine_stamp") or _stamp(),
        "audit_input": {"engine": "buy_the_dip", "label": "live", "params": dict(LIVE_PARAMS),
                        "live_params": dict(LIVE_PARAMS), "slippage_bps": 10.0,
                        "fees_recorded": bool(report.get("fees_included")), "same_bar_policy": "stop_first",
                        "fill_rule": "close", "universe": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"],
                        "universe_as_of": "2026-10-09"},
    }


def _stamp() -> dict:
    from utils.engine_stamp import stamp
    return stamp("buy_the_dip")


def latest_report(root) -> Optional[str]:
    from pathlib import Path
    files = sorted(Path(root, "docs").glob("walk_forward_btd_semi7_*.json"))
    return str(files[-1]) if files else None

"""Backtest audit: run on every backtest result before its numbers are reported or published.

    from utils.backtest_audit import audit, AuditInput
    rep = audit(AuditInput(trades=..., initial_capital=10_000, final_equity=..., ...))
    rep.status            # 'pass' | 'warn' | 'fail'
    rep.checks            # [Check(name, status, reason)]

Inputs are plain dicts/lists so any engine can be audited (utils/buy_the_dip.py trades_df
records, alpatrade.trades rows, walk-forward JSON). A check that cannot be evaluated because a
field is missing is a *warn* ("not verifiable"), never a silent pass.

Checks (names are stable; tests and the leaderboard badge rely on them):
  reconciliation   sum(trade P&L) == final equity − initial capital; reported return matches
  same_bar_exits   several exits on one bar must each move capital_after by exactly their P&L
                   (catches double-counting the same capital on same-bar exits)
  cash             replayed cash never < 0 (no margin unless allow_margin)
  tp_sl_same_bar   a bar touching both target and stop must be resolved stop-first
  costs            slippage_bps > 0 and fees recorded (> 0)
  params           params tested == live strategy_configs params when labelled 'live'
                   (otherwise it must be labelled 'research')
  lookahead        signal_time <= entry_time <= exit_time; fills at t+1 open or at the close
  universe         universe membership fixed as of (or before) the backtest start
  plausibility     annualised > 200% / Sharpe > 4 / max DD 0 with > 20 trades -> warn;
                   annualised > 1000% or Sharpe > 8 -> fail unless overridden with a note
  min_trades       < 10 trades fail, < 30 warn
  oos_degradation  OOS vs IS return reported; OOS < 50% of IS -> warn
  engine_version   engine/version stamp present and >= the engine's minimum valid version
                   (buy_the_dip before b47e6de / v0.33.6 -> fail); missing stamp -> fail for
                   engines with a minimum, warn otherwise
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

PASS, WARN, FAIL = "pass", "warn", "fail"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}

# plausibility gates
WARN_ANNUALISED_PCT, FAIL_ANNUALISED_PCT = 200.0, 1000.0
WARN_SHARPE, FAIL_SHARPE = 4.0, 8.0
ZERO_DD_TRADES = 20
MIN_TRADES_FAIL, MIN_TRADES_WARN = 10, 30
OOS_DEGRADATION_WARN = 0.5
END_GRACE_DAYS, END_RESIDUAL_FRAC = 7, 0.02   # unlisted open positions at period end
# params compared against the live config (backtester name -> live strategy_configs name, scale)
PARAM_MAP = {"dip_threshold": ("dip", 100), "take_profit": ("tp", 100), "stop_loss": ("sl", 100),
             "hold_days": ("max_hold", 1), "min_hold_days": ("min_hold", 1),
             "dip": ("dip", 1), "tp": ("tp", 1), "sl": ("sl", 1), "max_hold": ("max_hold", 1),
             "min_hold": ("min_hold", 1), "pos_frac": ("pos_frac", 1)}


@dataclass
class Check:
    name: str
    status: str
    reason: str


@dataclass
class AuditInput:
    trades: List[Dict[str, Any]] = field(default_factory=list)
    initial_capital: Optional[float] = None
    final_equity: Optional[float] = None
    reported_return_pct: Optional[float] = None
    allow_margin: bool = False
    slippage_bps: Optional[float] = None
    fees_recorded: Optional[bool] = None       # None -> inferred from trades' total_fees
    same_bar_policy: Optional[str] = None      # 'stop_first' | 'target_first' | None
    label: Optional[str] = None                # 'live' | 'research'
    params: Optional[Dict[str, Any]] = None    # params actually tested
    live_params: Optional[Dict[str, Any]] = None
    fill_rule: Optional[str] = None            # 'next_open' | 'close'
    universe: Optional[List[str]] = None
    universe_as_of: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    open_at_end_possible: bool = False   # engine leaves positions open at period end, unlisted
    annualised_pct: Optional[float] = None
    sharpe: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    n_trades: Optional[int] = None
    is_return_pct: Optional[float] = None
    oos_return_pct: Optional[float] = None
    override_note: Optional[str] = None        # manual plausibility override (who/why)
    known_issues: List[str] = field(default_factory=list)  # externally established faults -> fail
    engine_stamp: Optional[Dict[str, Any]] = None  # utils.engine_stamp.stamp() of the producing code
    engine: Optional[str] = None                   # engine name when no stamp (e.g. 'buy_the_dip')


@dataclass
class AuditReport:
    status: str
    checks: List[Check]

    @property
    def reasons(self) -> List[str]:
        return [f"{c.name}: {c.reason}" for c in self.checks if c.status != PASS]

    def to_dict(self) -> dict:
        return {"status": self.status, "checks": [asdict(c) for c in self.checks],
                "audited_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _t(v) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _tol(cap: float) -> float:
    return max(1.0, abs(cap) * 1e-4)


# ------------------------------------------------------------------ checks
def check_reconciliation(a: AuditInput) -> Check:
    if a.initial_capital is None or (a.final_equity is None and a.reported_return_pct is None):
        return Check("reconciliation", WARN, "not verifiable: initial capital / final equity not recorded")
    pnl = sum(_f(t.get("pnl")) or 0.0 for t in a.trades)
    expected = a.initial_capital + pnl
    probs = []
    if a.final_equity is not None and abs(a.final_equity - expected) > _tol(a.initial_capital):
        probs.append(f"final equity ${a.final_equity:,.2f} ≠ initial ${a.initial_capital:,.2f} + "
                     f"Σ trade P&L ${pnl:,.2f} = ${expected:,.2f}")
    if a.reported_return_pct is not None:
        real = pnl / a.initial_capital * 100
        if abs(a.reported_return_pct - real) > max(0.1, abs(real) * 0.01):
            probs.append(f"reported return {a.reported_return_pct:+.2f}% ≠ Σ P&L return {real:+.2f}%")
    if probs:
        resid = (a.final_equity - expected) if a.final_equity is not None else 0.0
        if a.open_at_end_possible and abs(resid) <= END_RESIDUAL_FRAC * max(abs(expected), 1.0):
            return Check("reconciliation", WARN, f"residual ${resid:,.2f} vs Σ trade P&L: positions still open "
                         "at period end are marked to market but not listed as trades; " + "; ".join(probs))
        return Check("reconciliation", FAIL, "; ".join(probs))
    return Check("reconciliation", PASS, f"Σ trade P&L ${pnl:,.2f} reconciles with the equity change")


def check_same_bar_exits(a: AuditInput) -> Check:
    """Whenever the book is flat after an exit bar, the engine's capital_after must equal
    initial capital + cumulative realised P&L. Same-bar multi-exits are where engines
    double-count (each exit re-adds capital the previous exit already released)."""
    if a.initial_capital is None:
        return Check("same_bar_exits", WARN, "not verifiable: initial capital not recorded")
    rows = [t for t in a.trades if t.get("capital_after") is not None and _t(t.get("exit_time"))]
    if not rows:
        return Check("same_bar_exits", WARN, "not verifiable: no capital_after per trade")
    groups = defaultdict(list)
    for t in rows:
        groups[_t(t["exit_time"])].append(t)
    all_tr = [(_t(t.get("entry_time")), _t(t.get("exit_time"))) for t in a.trades]
    cum, bad, bad_meta, multi, checked = 0.0, [], [], 0, 0
    for ts in sorted(groups):
        g = groups[ts]
        cum += sum(_f(t.get("pnl")) or 0.0 for t in g)
        multi += len(g) > 1
        still_open = any(e is not None and e <= ts and (x is None or x > ts) for e, x in all_tr)
        if still_open:
            continue
        checked += 1
        # the last exit processed on the bar (row order within a bar is engine-specific) must
        # leave equity = cash = initial + realised P&L
        want = a.initial_capital + cum
        vals = [_f(t["capital_after"]) for t in g]
        got = min(vals, key=lambda v: abs(v - want))
        if abs(got - want) > _tol(a.initial_capital):
            bad_meta.append((ts, got - want, want))
            bad.append(f"{ts:%Y-%m-%d} ({len(g)} exit{'s' if len(g) > 1 else ''}): capital_after "
                       f"${got:,.2f} vs initial + realised P&L ${want:,.2f}")
    end = _t(a.period_end)
    if bad and a.open_at_end_possible and end is not None and all(
            (end - d).days <= END_GRACE_DAYS and abs(r) <= END_RESIDUAL_FRAC * max(abs(w), 1.0)
            for d, r, w in bad_meta):
        return Check("same_bar_exits", WARN, "only the final bars disagree (open positions at period end "
                     "are not listed as trades): " + "; ".join(bad[:2]))
    if bad:
        return Check("same_bar_exits", FAIL, f"capital_after overstated when flat ({len(bad)}x; capital "
                     "double-counted on same-bar exits): " + "; ".join(bad[:3]))
    if not checked:
        return Check("same_bar_exits", WARN, "not verifiable: book never flat after an exit")
    return Check("same_bar_exits", PASS, f"capital_after = initial + realised P&L at all {checked} flat points "
                 f"({multi} multi-exit bar{'s' if multi != 1 else ''})")


def check_cash(a: AuditInput) -> Check:
    if a.initial_capital is None:
        return Check("cash", WARN, "not verifiable: initial capital not recorded")
    ev = []
    for t in a.trades:
        sh, ep, xp = _f(t.get("shares")), _f(t.get("entry_price")), _f(t.get("exit_price"))
        et, xt = _t(t.get("entry_time")), _t(t.get("exit_time"))
        if None in (sh, ep, et):
            return Check("cash", WARN, "not verifiable: trades lack shares/entry price/time")
        fees = _f(t.get("total_fees")) or 0.0
        ev.append((et, 1, -(sh * ep)))
        if xt is not None and xp is not None:
            ev.append((xt, 0, sh * xp - fees))      # exits before entries on the same bar
    cash, low, when = a.initial_capital, a.initial_capital, None
    for ts, _, amt in sorted(ev, key=lambda e: (e[0], e[1])):
        cash += amt
        if cash < low:
            low, when = cash, ts
    if low < -_tol(a.initial_capital) and not a.allow_margin:
        return Check("cash", FAIL, f"cash goes negative (${low:,.2f} on {when:%Y-%m-%d}): uses margin")
    return Check("cash", PASS, f"cash never below ${low:,.2f}")


def check_tp_sl_same_bar(a: AuditInput) -> Check:
    amb = []
    for t in a.trades:
        hi, lo = _f(t.get("bar_high")), _f(t.get("bar_low"))
        tp, sl = _f(t.get("target_price")), _f(t.get("stop_price"))
        if None not in (hi, lo, tp, sl) and hi >= tp and lo <= sl:
            amb.append(t)
        elif t.get("same_bar_ambiguous"):
            amb.append(t)
    resolved_up = [t for t in amb if t.get("hit_target") or t.get("TP")]
    if resolved_up:
        return Check("tp_sl_same_bar", FAIL, f"{len(resolved_up)} bar(s) touched both target and stop and "
                     "were booked as take-profit; resolve stop-first")
    if a.same_bar_policy == "target_first":
        return Check("tp_sl_same_bar", FAIL, "engine resolves a bar touching both levels target-first")
    if a.same_bar_policy != "stop_first":
        return Check("tp_sl_same_bar", WARN, "same-bar TP/SL policy not declared (bars not recorded)")
    return Check("tp_sl_same_bar", PASS, f"stop-first; {len(amb)} ambiguous bar(s) booked as stops")


def check_costs(a: AuditInput) -> Check:
    fees = a.fees_recorded
    if fees is None:
        fees = any((_f(t.get("total_fees")) or 0) > 0 for t in a.trades)
    probs = []
    if not a.slippage_bps or a.slippage_bps <= 0:
        probs.append("slippage is 0 / not recorded")
    if not fees:
        probs.append("fees are 0 / not recorded")
    if probs:
        return Check("costs", FAIL, "; ".join(probs))
    return Check("costs", PASS, f"slippage {a.slippage_bps:g} bps and fees recorded")


def _norm(params: Dict[str, Any]) -> Dict[str, float]:
    out = {}
    for k, v in (params or {}).items():
        if k in PARAM_MAP and _f(v) is not None:
            name, scale = PARAM_MAP[k]
            out[name] = round(_f(v) * scale, 6)
    return out


def check_params(a: AuditInput) -> Check:
    if a.label == "research":
        return Check("params", PASS, "labelled research (not presented as the live strategy)")
    if a.label != "live":
        return Check("params", WARN, "not labelled 'live' or 'research'")
    if not a.params or not a.live_params:
        return Check("params", FAIL, "labelled live but tested / live params not recorded")
    tested, live = _norm(a.params), _norm(a.live_params)
    diff = [f"{k} {tested[k]:g} vs live {live[k]:g}" for k in sorted(live)
            if k in tested and abs(tested[k] - live[k]) > 1e-9]
    missing = [k for k in ("dip", "tp", "sl", "max_hold") if k in live and k not in tested]
    if diff or missing:
        return Check("params", FAIL, "tested params differ from live strategy_configs: "
                     + "; ".join(diff + [f"{k} not tested" for k in missing]))
    return Check("params", PASS, "tested params match the live strategy_configs")


def check_lookahead(a: AuditInput) -> Check:
    bad = []
    for t in a.trades:
        s, e, x = _t(t.get("signal_time")), _t(t.get("entry_time")), _t(t.get("exit_time"))
        if e and x and x < e:
            bad.append(f"{t.get('ticker') or t.get('symbol')} exits before entry")
        if s and e:
            if s > e:
                bad.append(f"{t.get('ticker') or t.get('symbol')} signal after fill")
            elif a.fill_rule == "next_open" and s.date() >= e.date():
                bad.append(f"{t.get('ticker') or t.get('symbol')} filled on the signal bar (rule: next open)")
    if bad:
        return Check("lookahead", FAIL, "; ".join(bad[:3]))
    if a.fill_rule not in ("next_open", "close"):
        return Check("lookahead", WARN, "fill rule not declared (next_open / close)")
    if not any(t.get("signal_time") for t in a.trades):
        return Check("lookahead", WARN, f"fill rule {a.fill_rule}; signal times not recorded")
    return Check("lookahead", PASS, f"signals ≤ fills, fills at {a.fill_rule.replace('_', ' ')}")


def check_universe(a: AuditInput) -> Check:
    if not a.universe:
        return Check("universe", WARN, "universe not recorded")
    if not a.universe_as_of or not a.period_start:
        return Check("universe", WARN, "universe selection date not recorded (survivorship risk)")
    if str(a.universe_as_of)[:10] > str(a.period_start)[:10]:
        return Check("universe", WARN, f"universe chosen on {a.universe_as_of[:10]}, after the backtest start "
                     f"{a.period_start[:10]} (hindsight / survivorship bias)")
    return Check("universe", PASS, f"universe fixed as of {a.universe_as_of[:10]}")


def check_plausibility(a: AuditInput) -> Check:
    n = a.n_trades if a.n_trades is not None else len(a.trades)
    warn, fail = [], []
    if a.annualised_pct is not None:
        if a.annualised_pct > FAIL_ANNUALISED_PCT:
            fail.append(f"annualised {a.annualised_pct:,.0f}% > {FAIL_ANNUALISED_PCT:g}%")
        elif a.annualised_pct > WARN_ANNUALISED_PCT:
            warn.append(f"annualised {a.annualised_pct:,.0f}% > {WARN_ANNUALISED_PCT:g}%")
    if a.sharpe is not None:
        if a.sharpe > FAIL_SHARPE:
            fail.append(f"Sharpe {a.sharpe:.2f} > {FAIL_SHARPE:g}")
        elif a.sharpe > WARN_SHARPE:
            warn.append(f"Sharpe {a.sharpe:.2f} > {WARN_SHARPE:g}")
    if a.max_drawdown_pct is not None and abs(a.max_drawdown_pct) < 1e-9 and n > ZERO_DD_TRADES:
        warn.append(f"max drawdown 0 with {n} trades")
    if fail and a.override_note:
        return Check("plausibility", WARN, "; ".join(fail + warn) + f" (overridden: {a.override_note})")
    if fail:
        return Check("plausibility", FAIL, "; ".join(fail + warn))
    if warn:
        return Check("plausibility", WARN, "; ".join(warn))
    return Check("plausibility", PASS, "within plausibility gates")


def check_min_trades(a: AuditInput) -> Check:
    n = a.n_trades if a.n_trades is not None else len(a.trades)
    if n < MIN_TRADES_FAIL:
        return Check("min_trades", FAIL, f"only {n} trades (< {MIN_TRADES_FAIL})")
    if n < MIN_TRADES_WARN:
        return Check("min_trades", WARN, f"only {n} trades (< {MIN_TRADES_WARN})")
    return Check("min_trades", PASS, f"{n} trades")


def check_oos(a: AuditInput) -> Check:
    if a.is_return_pct is None or a.oos_return_pct is None:
        return Check("oos_degradation", WARN, "no in-sample / out-of-sample split reported")
    ratio = a.oos_return_pct / a.is_return_pct if a.is_return_pct else None
    txt = f"IS {a.is_return_pct:+.2f}% vs OOS {a.oos_return_pct:+.2f}%"
    if ratio is not None and ratio < OOS_DEGRADATION_WARN:
        return Check("oos_degradation", WARN, f"{txt} (OOS keeps {ratio:.0%} of IS)")
    return Check("oos_degradation", PASS, txt + (f" (OOS keeps {ratio:.0%} of IS)" if ratio is not None else ""))


def check_engine_version(a: AuditInput) -> Check:
    from utils.engine_stamp import MIN_VALID, is_valid
    st = dict(a.engine_stamp or {})
    if not st.get("engine") and a.engine:
        st["engine"] = a.engine
    ok, why = is_valid(st)
    if ok:
        return Check("engine_version", PASS, why)
    return Check("engine_version", FAIL if st.get("engine") in MIN_VALID else WARN, why)


CHECKS = [check_engine_version, check_reconciliation, check_same_bar_exits, check_cash, check_tp_sl_same_bar, check_costs,
          check_params, check_lookahead, check_universe, check_plausibility, check_min_trades, check_oos]


def audit(a: AuditInput) -> AuditReport:
    checks = [c(a) for c in CHECKS]
    for issue in a.known_issues:
        checks.append(Check("known_issue", FAIL, issue))
    status = max((c.status for c in checks), key=_RANK.__getitem__)
    return AuditReport(status, checks)


# ------------------------------------------------------------------ adapters
def from_buy_the_dip(trades_df, metrics: dict, *, initial_capital: float, slippage_bps: float,
                     params: dict, label: str, live_params: Optional[dict] = None,
                     universe: Optional[list] = None, universe_as_of: Optional[str] = None,
                     period_start: Optional[str] = None, period_end: Optional[str] = None,
                     same_bar_policy: Optional[str] = None,
                     fill_rule: Optional[str] = "close",
                     engine_stamp: Optional[dict] = None) -> AuditInput:
    """utils/buy_the_dip.backtest_buy_the_dip output -> AuditInput. The reported final equity is
    the engine's own (last capital_after), so a capital double-count shows up as a mismatch."""
    from utils.engine_stamp import stamp
    trades = trades_df.to_dict("records") if hasattr(trades_df, "to_dict") else list(trades_df or [])
    final = _f(trades[-1].get("capital_after")) if trades else initial_capital
    return AuditInput(
        trades=trades, initial_capital=initial_capital, final_equity=final,
        reported_return_pct=_f(metrics.get("total_return")), slippage_bps=slippage_bps,
        same_bar_policy=same_bar_policy, label=label, params=params, live_params=live_params,
        fill_rule=fill_rule, universe=universe, universe_as_of=universe_as_of,
        period_start=period_start, period_end=period_end, open_at_end_possible=True,
        annualised_pct=_f(metrics.get("annualized_return")),
        sharpe=_f(metrics.get("sharpe_ratio")), max_drawdown_pct=_f(metrics.get("max_drawdown")),
        n_trades=len(trades), engine_stamp=engine_stamp or stamp("buy_the_dip"))


def from_leaderboard_metrics(bm: dict, live_params: Optional[dict] = None) -> AuditInput:
    """Leaderboard ``backtest_metrics`` JSON (no per-trade data) -> AuditInput. Trade-level checks
    come back as 'not verifiable'; ``bm['audit_input']`` (if stored) overrides fields."""
    extra = dict(bm.get("audit_input") or {})
    a = AuditInput(
        initial_capital=None, slippage_bps=_f(extra.pop("slippage_bps", None)),
        fees_recorded=extra.pop("fees_recorded", None), label=extra.pop("label", None),
        params=extra.pop("params", None), live_params=live_params or extra.pop("live_params", None),
        fill_rule=extra.pop("fill_rule", None), same_bar_policy=extra.pop("same_bar_policy", None),
        universe=extra.pop("universe", None) or ([bm["universe"]] if bm.get("universe") else None),
        universe_as_of=extra.pop("universe_as_of", None), period_start=bm.get("period_start"),
        annualised_pct=_f(bm.get("annualised_pct")), sharpe=_f(bm.get("sharpe")),
        max_drawdown_pct=_f(bm.get("max_drawdown_pct")), n_trades=bm.get("trades"),
        is_return_pct=_f(extra.pop("is_return_pct", None)), oos_return_pct=_f(extra.pop("oos_return_pct", None)),
        override_note=extra.pop("override_note", None), known_issues=list(extra.pop("known_issues", []) or []),
        engine_stamp=bm.get("engine_stamp") or extra.pop("engine_stamp", None),
        engine=extra.pop("engine", None) or ("buy_the_dip" if "buy_the_dip" in str(bm.get("template", "")) else None))
    return a


def assert_publishable(report: AuditReport) -> None:
    """Gate for leaderboard publishing / seed scripts: a failing audit is never published."""
    if report.status == FAIL:
        raise PermissionError("backtest audit FAILED, refusing to publish:\n  - " + "\n  - ".join(report.reasons))


def format_report(report: AuditReport) -> str:
    icon = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL"}
    lines = [f"Backtest audit: {report.status.upper()}"]
    lines += [f"  [{icon[c.status]}] {c.name}: {c.reason}" for c in report.checks]
    return "\n".join(lines)


def dumps(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2)

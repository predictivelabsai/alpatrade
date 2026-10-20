"""Single shared metrics definitions + guardrails (dashboard, /live, /live/account,
/leaderboard, backtests, daily report).

Definitions
-----------
* **Total return**: deposit-adjusted time-weighted return over the period
  (``engine.reporting.cash_flows.twr_pct``).
* **Annualised return = CAGR** = (1 + total)^(252 / trading_days) − 1, NYSE trading
  days. Always calculated, whatever the history length (2026-10-20, Julian); under
  ``MIN_TRACK_DAYS`` (60) trading days ``short_period`` is set and the UI adds a
  "short history, noisy" note.
* **Live strategy return**: :func:`live_strategy_return` is the only function the
  pages use for a live runner's return/SPY/alpha (TWR from the run's daily
  snapshots + the account's cash flows, as of the last completed session).

Guardrails
----------
:func:`sanity_issues` (annualised sign must match total, bounded magnitudes,
short history only flagged) and :func:`spy_benchmark_issue` (SPY CAGR over a long
window must look like SPY: ~5–25%/yr) return problems; :func:`guard` logs them as
``METRICS_GUARD`` and returns a cleaned value; :func:`check_consistency` logs
``METRICS_MISMATCH`` when two pages' figures for the same thing disagree.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Optional

log = logging.getLogger("engine.metrics")

TRADING_DAYS_PER_YEAR = 252
MIN_TRACK_DAYS = 60
MAX_ABS_ANNUALISED_PCT = 1000.0
MAX_ABS_SHARPE = 10.0
SPY_CAGR_BOUNDS = (5.0, 25.0)        # long-run SPY CAGR sanity window (%/yr)
SPY_CHECK_MIN_DAYS = 3 * TRADING_DAYS_PER_YEAR
MISMATCH_TOL_PCT = 0.05              # same quantity, same as-of → must agree to 0.05pp
_mismatches: list[dict] = []


def cagr_pct(total_pct: Optional[float], trading_days: Optional[int],
             min_days: int = 1) -> Optional[float]:
    """CAGR in % from a total return in %; None when unknown or under ``min_days``."""
    if total_pct is None or not trading_days or trading_days < max(1, min_days):
        return None
    r = float(total_pct) / 100.0
    if r <= -1:
        return -100.0
    try:
        return ((1 + r) ** (TRADING_DAYS_PER_YEAR / trading_days) - 1) * 100
    except OverflowError:
        return None


def total_from_cagr(cagr: Optional[float], trading_days: Optional[int]) -> Optional[float]:
    if cagr is None or not trading_days or cagr <= -100:
        return None
    return ((1 + cagr / 100.0) ** (trading_days / TRADING_DAYS_PER_YEAR) - 1) * 100


def annualised(total_pct: Optional[float], trading_days: Optional[int]) -> dict:
    """``{'total_pct','annualised_pct','days','short_period','basis':'cagr'}``."""
    days = int(trading_days or 0)
    return {"total_pct": total_pct, "annualised_pct": cagr_pct(total_pct, days),
            "days": days, "short_period": bool(total_pct is not None and days < MIN_TRACK_DAYS),
            "basis": "cagr"}


def fmt_annualised(a: dict) -> str:
    v = a.get("annualised_pct")
    if v is not None:
        return f"{v:+.2f}%" + ("*" if a.get("short_period") else "")
    return "—"


SHORT_HISTORY_NOTE = (f"* Short history (<{MIN_TRACK_DAYS} trading days): annualising a short "
                      "window extrapolates heavily, so the figure is noisy.")


# --------------------------------------------------------------------------- guardrails
def sanity_issues(total_pct: Optional[float], ann_pct: Optional[float],
                  trading_days: Optional[int], *, sharpe: Optional[float] = None) -> list[str]:
    out: list[str] = []
    if ann_pct is not None:
        if total_pct is not None and abs(total_pct) > 1e-9 and (ann_pct > 0) != (total_pct > 0):
            out.append(f"annualised sign ({ann_pct:+.2f}%) differs from total return ({total_pct:+.2f}%)")
        # Short histories (< MIN_TRACK_DAYS) are always shown, flagged noisy, so the
        # magnitude cap applies only to established track records.
        if abs(ann_pct) > MAX_ABS_ANNUALISED_PCT and (trading_days or 0) >= MIN_TRACK_DAYS:
            out.append(f"|annualised| {ann_pct:+.1f}% exceeds {MAX_ABS_ANNUALISED_PCT:.0f}%")
        if ann_pct < -100:
            out.append(f"annualised {ann_pct:+.1f}% below -100%")
    if total_pct is not None and total_pct < -100:
        out.append(f"total return {total_pct:+.1f}% below -100%")
    if sharpe is not None and abs(sharpe) > MAX_ABS_SHARPE:
        out.append(f"|Sharpe| {sharpe:.2f} exceeds {MAX_ABS_SHARPE:.0f}")
    return out


def spy_benchmark_issue(spy_total_pct: Optional[float], trading_days: Optional[int]) -> Optional[str]:
    """SPY over a long window must compound at a SPY-like rate (catches simple-vs-CAGR mixups)."""
    if spy_total_pct is None or not trading_days or trading_days < SPY_CHECK_MIN_DAYS:
        return None
    c = cagr_pct(spy_total_pct, trading_days)
    lo, hi = SPY_CAGR_BOUNDS
    if c is None or not (lo <= c <= hi):
        return f"SPY CAGR {c if c is None else round(c, 2)}% over {trading_days} days outside {lo}-{hi}%"
    return None


def guard(where: str, total_pct: Optional[float], ann_pct: Optional[float],
          trading_days: Optional[int], **kw) -> Optional[float]:
    """Log METRICS_GUARD issues; returns ``ann_pct`` or None when it is not trustworthy."""
    issues = sanity_issues(total_pct, ann_pct, trading_days, **kw)
    if issues:
        log.warning("METRICS_GUARD %s: %s", where, "; ".join(issues))
        if any("annualised" in i for i in issues):
            return None
    return ann_pct


def check_consistency(name: str, values: dict[str, Optional[float]],
                      tol: float = MISMATCH_TOL_PCT) -> bool:
    """Log METRICS_MISMATCH when the same metric differs between sources. True = consistent."""
    vals = {k: v for k, v in values.items() if v is not None}
    if len(vals) < 2:
        return True
    lo, hi = min(vals.values()), max(vals.values())
    if hi - lo > tol:
        rec = {"name": name, "values": vals}
        _mismatches.append(rec)
        del _mismatches[:-200]
        log.warning("METRICS_MISMATCH %s: %s", name, vals)
        return False
    return True


def recent_mismatches() -> list[dict]:
    return list(_mismatches)


# ------------------------------------------------------------------ single source of truth
def live_strategy_return(run: Optional[dict], flows: Optional[list] = None,
                         today: Optional[date] = None) -> dict:
    """THE live strategy figures (used by /live, /live/account since-inception, /leaderboard).

    Deposit-adjusted TWR from the run's start (``config.start_equity``) through the last
    completed session in ``results.daily``, SPY over the same dates, CAGR for any length.
    """
    from engine.leaderboard.perf import metrics_from_run
    m = metrics_from_run(run, today=today, flows=flows)
    if m.get("has_data"):
        m["annualised_pct"] = guard("live_strategy_return", m.get("return_pct"),
                                    m.get("annualised_pct"), m.get("trading_days"))
    return m


_lr_cache: dict = {}


def live_return_for_user(user_id: str, run: Optional[dict], today: Optional[date] = None,
                         ttl: float = 120.0) -> dict:
    """live_strategy_return with the owner's cash flows (same inputs as /leaderboard),
    cached ``ttl`` seconds per run so /live, /live/account and /leaderboard agree."""
    import time
    from engine.leaderboard.perf import _owner_flows
    if not run:
        return {}
    key = (str(run.get("run_id")), str(today))
    hit = _lr_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return dict(hit[1])
    m = live_strategy_return(run, _owner_flows(str(user_id), run), today)
    _lr_cache[key] = (time.time(), m)
    return dict(m)


def apply_canonical_since_inception(perf: dict, canon: dict, where: str) -> dict:
    """Overwrite a since-inception block with the canonical figures (keeping the
    intraday account value for the mismatch log)."""
    if not perf or not canon or not canon.get("has_data") or canon.get("return_pct") is None:
        return perf
    check_consistency(f"{where}:since_inception",
                      {"canonical": canon.get("return_pct"),
                       f"{where}_intraday": perf.get("account_return_pct")}, tol=1.0)
    perf = dict(perf)
    perf["account_return_pct_intraday"] = perf.get("account_return_pct")
    perf["account_return_pct"] = canon["return_pct"]
    if canon.get("spy_return_pct") is not None:
        perf["spy_return_pct"] = canon["spy_return_pct"]
    perf["excess_pct"] = (perf["account_return_pct"] - perf["spy_return_pct"]
                          if perf.get("spy_return_pct") is not None else None)
    perf["as_of"] = canon.get("as_of")
    return perf


def backtest_figures(best: Optional[dict]) -> dict:
    """Return / Sharpe for a finished backtest from its best variation (summary row or
    ``runs.results.best_config``); out-of-bounds Sharpe is flagged, not hidden."""
    best = best or {}

    def num(v):
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None
    tot, sh = num(best.get("total_return")), num(best.get("sharpe_ratio"))
    flags = sanity_issues(tot, None, None, sharpe=sh)
    return {"total_return": tot, "sharpe_ratio": sh, "flags": flags}


def iter_numbers(rows: Iterable[Any]):  # small helper for tests/CI
    for r in rows:
        if isinstance(r, (int, float)):
            yield float(r)

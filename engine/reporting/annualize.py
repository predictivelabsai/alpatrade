"""Annualised-return helpers. Headline everywhere = ``annualised_pct`` = CAGR, shown for
any history length; under 60 trading days it is flagged noisy (engine.metrics). ``simple_pct`` / ``compound_pct`` are kept for
back-compat (scripts, tooltips).

simple     = r * 252 / d
compounded = (1 + r) ** (252 / d) - 1
where r is the period return (fraction) and d the NYSE trading days elapsed.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

TRADING_DAYS_PER_YEAR = 252
# Don't annualise short records: compounding e.g. 15 days gives absurd figures. 63 NYSE
# sessions ~ 90 calendar days; below that the annualised values are None and
# ``short_period`` is True (rendered "n/a (<90d)").
MIN_ANNUALISE_TRADING_DAYS = 63  # short-period hint threshold only (tooltip)
# 2026-10-12 (Julian): one definition everywhere: CAGR, n/a under 60 trading days
# (replaces the earlier simple ×252/d headline).
DEFAULT_MIN_DAYS = 1


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def _nth_weekday(y: int, m: int, wd: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, m: int, wd: int) -> date:
    d = (date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - wd) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(y: int) -> set[date]:
    """Full-day NYSE closures (standard rules; ad-hoc closures not included)."""
    hs = {
        _nth_weekday(y, 1, 0, 3),   # MLK
        _nth_weekday(y, 2, 0, 3),   # Presidents
        _easter(y) - timedelta(days=2),  # Good Friday
        _last_weekday(y, 5, 0),     # Memorial
        _observed(date(y, 7, 4)),
        _nth_weekday(y, 9, 0, 1),   # Labor
        _nth_weekday(y, 11, 3, 4),  # Thanksgiving
        _observed(date(y, 12, 25)),
    }
    if y >= 2022:
        hs.add(_observed(date(y, 6, 19)))
    ny = date(y, 1, 1)
    if ny.weekday() != 5:  # Saturday New Year is not observed on Dec 31
        hs.add(_observed(ny))
    return hs


def trading_days_between(start: date, end: date) -> int:
    """NYSE trading days in [start, end] inclusive."""
    if end < start:
        return 0
    hol = nyse_holidays(start.year) | nyse_holidays(end.year)
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in hol:
            n += 1
        d += timedelta(days=1)
    return n


def annualize(return_pct: Optional[float], trading_days: int,
              min_days: int = DEFAULT_MIN_DAYS) -> dict:
    """Return {'simple_pct','compound_pct','days','short_period'}; values None when
    d < ``min_days`` (default 63 sessions ~ 90 calendar days)."""
    from engine.metrics import MIN_TRACK_DAYS, cagr_pct
    out = {"simple_pct": None, "compound_pct": None, "days": int(trading_days or 0),
           "short_period": False, "annualised_pct": None, "return_pct": return_pct,
           "basis": "cagr"}
    # Headline (everywhere): CAGR for any history length; short_period (<60d) = noisy note.
    out["annualised_pct"] = cagr_pct(return_pct, int(trading_days or 0))
    if return_pct is not None and trading_days:
        out["short_period"] = int(trading_days) < MIN_TRACK_DAYS
    if return_pct is None or not trading_days or trading_days < 1:
        return out
    if trading_days < max(1, int(min_days or 1)):
        out["short_period"] = True
        return out
    from engine.metrics import MIN_TRACK_DAYS as _M
    out["short_period"] = trading_days < _M
    r = float(return_pct) / 100.0
    out["simple_pct"] = r * TRADING_DAYS_PER_YEAR / trading_days * 100
    try:
        out["compound_pct"] = ((1 + r) ** (TRADING_DAYS_PER_YEAR / trading_days) - 1) * 100 \
            if r > -1 else -100.0
    except OverflowError:
        out["compound_pct"] = None
    return out


def fmt_ann(a: dict) -> str:
    """Headline annualised = CAGR for any length (``*`` under 60 trading days). Shared formatter."""
    from engine.metrics import fmt_annualised
    return fmt_annualised(a)


def tooltip(a: dict) -> str:
    from engine.metrics import MIN_TRACK_DAYS
    if a.get("annualised_pct") is None and a.get("short_period"):
        tot = a.get("return_pct")
        tot_s = "" if tot is None else f" Total return so far {tot:+.2f}%."
        return (f"Not annualised: only {a.get('days')} trading days (minimum {MIN_TRACK_DAYS})."
                + tot_s)
    if a.get("annualised_pct") is not None:
        since = f" since {a['start_date']}" if a.get("start_date") else ""
        tot = a.get("return_pct")
        tot_s = "" if tot is None else f"total {tot:+.2f}% over "
        noisy = (f" Short history (<{MIN_TRACK_DAYS} trading days): noisy, extrapolates heavily."
                 if a.get("short_period") else "")
        return (f"Annualised = CAGR (1+r)^(252/d)−1 = {a['annualised_pct']:+.2f}% "
                f"({tot_s}{a['days']} trading days{since}).{noisy}")
    if a.get("simple_pct") is None:
        if a.get("short_period"):
            return (f"Not annualised: only {a.get('days')} trading days (needs "
                    f"{MIN_ANNUALISE_TRADING_DAYS}, ~90 calendar days); compounding a short period "
                    "gives misleading figures")
        return "Not enough trading days in the period"
    c = a.get("compound_pct")
    cs = "—" if c is None else f"{c:+.2f}%"
    since = f" since {a['start_date']}" if a.get("start_date") else ""
    hint = (" Short period: fewer than 63 trading days, so the figure extrapolates heavily."
            if a.get("short_period") else "")
    return (f"Simple: return × 252 / days = {a['simple_pct']:+.2f}% "
            f"({a['days']} trading days{since}); compounded (1+r)^(252/d)−1 = {cs} "
            "(indicative only: we don't reinvest gains immediately)." + hint)

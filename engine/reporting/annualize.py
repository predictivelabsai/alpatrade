"""Annualised-return helpers (simple 252-day arithmetic + compounded).

simple     = r * 252 / d
compounded = (1 + r) ** (252 / d) - 1
where r is the period return (fraction) and d the NYSE trading days elapsed.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

TRADING_DAYS_PER_YEAR = 252


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


def annualize(return_pct: Optional[float], trading_days: int) -> dict:
    """Return {'simple_pct','compound_pct','days'}; values None when d < 1."""
    out = {"simple_pct": None, "compound_pct": None, "days": int(trading_days or 0)}
    if return_pct is None or not trading_days or trading_days < 1:
        return out
    r = float(return_pct) / 100.0
    out["simple_pct"] = r * TRADING_DAYS_PER_YEAR / trading_days * 100
    try:
        out["compound_pct"] = ((1 + r) ** (TRADING_DAYS_PER_YEAR / trading_days) - 1) * 100 \
            if r > -1 else -100.0
    except OverflowError:
        out["compound_pct"] = None
    return out


def fmt_ann(a: dict) -> str:
    v = a.get("simple_pct")
    return "—" if v is None else f"{v:+.2f}%"


def tooltip(a: dict) -> str:
    if a.get("simple_pct") is None:
        return "Not enough trading days in the period"
    c = a.get("compound_pct")
    cs = "—" if c is None else f"{c:+.2f}%"
    return (f"Simple: return × 252 / days = {a['simple_pct']:+.2f}% "
            f"({a['days']} trading days); compounded (1+r)^(252/d)−1 = {cs}")

"""13F-implied performance — pure calculation, no DB / network.

Method (see docs/hedge_funds_13f_plan.md):

* Each 13F-HR gives a fund's long US-equity positions at a quarter end. We build a
  replication portfolio weighted by reported market value (options, PRN/debt rows
  and unmapped / unpriced CUSIPs are dropped and the remaining weights renormalised).
* ``quarter_end`` method: the portfolio is bought at the report date's close and
  held (buy-and-hold, weights drift) until the next report date. This estimates
  what the fund's disclosed book did — it is NOT investable (filings lag ~45 days).
* ``follow_filing`` method: the same holdings are bought at the close of the first
  trading day after the filing date and held until the next filing is actionable.
  This is an investable "copycat" return.
* Daily portfolio returns are chained into calendar-year, year-to-date and
  trailing-12-month returns and compared with SPY over exactly the same window.
  Prices must be split/dividend adjusted (total-return proxy).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import math

import pandas as pd

# A report date more than this many days after the previous one means a filing is
# missing; the chain breaks instead of silently holding a stale book.
MAX_PERIOD_GAP_DAYS = 120


@dataclass
class Position:
    cusip: str
    value: float                 # reported market value (any unit — weights are relative)
    ticker: str | None = None
    put_call: str | None = None
    sh_prn_type: str | None = "SH"


@dataclass
class Filing:
    period_of_report: date
    filing_date: date
    positions: list[Position] = field(default_factory=list)


@dataclass
class PeriodResult:
    period_of_report: date
    start: date
    end: date
    fund_return: float | None
    spy_return: float | None
    coverage: float
    n_priced: int
    n_positions: int


def long_equity_positions(positions: list[Position]) -> list[Position]:
    """Long equity rows only: no PUT/CALL rows, no principal-amount (debt) rows."""
    out = []
    for p in positions:
        if (p.put_call or "").strip():
            continue
        if (p.sh_prn_type or "SH").strip().upper() != "SH":
            continue
        if p.value is None or not math.isfinite(float(p.value)) or float(p.value) <= 0:
            continue
        out.append(p)
    return out


def aggregate_by_ticker(positions: list[Position]) -> tuple[dict[str, float], float]:
    """Sum reported value per mapped ticker. Returns (ticker -> value, total long value)."""
    longs = long_equity_positions(positions)
    total = sum(float(p.value) for p in longs)
    by_ticker: dict[str, float] = {}
    for p in longs:
        if p.ticker:
            by_ticker[p.ticker] = by_ticker.get(p.ticker, 0.0) + float(p.value)
    return by_ticker, total


def _first_on_or_after(index: pd.DatetimeIndex, d: date) -> pd.Timestamp | None:
    pos = index.searchsorted(pd.Timestamp(d), side="left")
    return index[pos] if pos < len(index) else None


def _last_on_or_before(index: pd.DatetimeIndex, d: date) -> pd.Timestamp | None:
    pos = index.searchsorted(pd.Timestamp(d), side="right") - 1
    return index[pos] if pos >= 0 else None


def entry_date(filing: Filing, method: str, index: pd.DatetimeIndex) -> pd.Timestamp | None:
    """Trading day whose close the portfolio is bought at."""
    if method == "quarter_end":
        return _last_on_or_before(index, filing.period_of_report)
    if method == "follow_filing":
        # Filings are often accepted after the close — trade the next session.
        return _first_on_or_after(index, filing.filing_date + timedelta(days=1))
    raise ValueError(f"unknown method {method!r}")


def daily_returns(filings: list[Filing], prices: pd.DataFrame, method: str = "quarter_end",
                  benchmark: str = "SPY") -> tuple[pd.Series, list[PeriodResult]]:
    """Daily replication returns (NaN where no filing covers the day) + per-period detail.

    ``prices``: adjusted closes, DatetimeIndex (trading days) x ticker columns; must
    contain the benchmark column, which defines the trading calendar.
    """
    prices = prices.sort_index()
    index = prices[benchmark].dropna().index
    rets = pd.Series(float("nan"), index=index)
    periods: list[PeriodResult] = []
    filings = sorted(filings, key=lambda f: f.period_of_report)
    for i, filing in enumerate(filings):
        start = entry_date(filing, method, index)
        if start is None:
            continue
        nxt = filings[i + 1] if i + 1 < len(filings) else None
        if nxt is not None and (nxt.period_of_report - filing.period_of_report).days > MAX_PERIOD_GAP_DAYS:
            nxt = None
            hard_end = _last_on_or_before(
                index, filing.period_of_report + timedelta(days=MAX_PERIOD_GAP_DAYS))
        else:
            hard_end = index[-1]
        end = entry_date(nxt, method, index) if nxt is not None else hard_end
        if end is None:
            end = index[-1]
        if end <= start:
            continue
        by_ticker, total_long = aggregate_by_ticker(filing.positions)
        window = prices.loc[start:end]
        weights: dict[str, float] = {}
        drifted_value = 0.0
        for ticker, value in by_ticker.items():
            if ticker not in window.columns:
                continue
            p0 = window[ticker].iloc[0]
            if not (isinstance(p0, (int, float)) and math.isfinite(p0) and p0 > 0):
                continue
            drift = 1.0
            if method == "follow_filing":
                # Reported values are at quarter end; drift them to the entry close.
                q_end = _last_on_or_before(index, filing.period_of_report)
                pq = prices[ticker].get(q_end) if q_end is not None else None
                if pq is not None and math.isfinite(pq) and pq > 0:
                    drift = p0 / pq
            weights[ticker] = value * drift
            drifted_value += value * drift
        priced_value = sum(by_ticker[t] for t in weights)
        coverage = (priced_value / total_long) if total_long > 0 else 0.0
        n_long = len(long_equity_positions(filing.positions))
        if not weights or drifted_value <= 0:
            periods.append(PeriodResult(filing.period_of_report, start.date(), end.date(), None,
                                        None, coverage, 0, n_long))
            continue
        tickers = list(weights)
        w = pd.Series({t: weights[t] / drifted_value for t in tickers})
        # Delisted names: carry the last traded price (position frozen, not zeroed).
        rel = window[tickers].ffill().div(window[tickers].iloc[0])
        nav = (rel * w).sum(axis=1)
        period_daily = nav.pct_change().iloc[1:]
        rets.loc[period_daily.index] = period_daily.values
        bench = window[benchmark]
        periods.append(PeriodResult(
            filing.period_of_report, start.date(), end.date(),
            float(nav.iloc[-1] - 1.0), float(bench.iloc[-1] / bench.iloc[0] - 1.0),
            coverage, len(tickers), n_long))
    return rets, periods


def window_return(daily: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    """Compound daily returns over (start, end]; None if any day is uncovered."""
    seg = daily.loc[(daily.index > start) & (daily.index <= end)]
    if seg.empty or seg.isna().any():
        return None
    return float((1.0 + seg).prod() - 1.0)


def summarize(daily: pd.Series, bench_prices: pd.Series, today: date | None = None,
              first_year: int | None = None) -> list[dict]:
    """Calendar-year, YTD and TTM rows for a daily return series vs a benchmark."""
    bench_prices = bench_prices.dropna().sort_index()
    index = bench_prices.index
    if len(index) < 2:
        return []
    last = index[-1]
    if today is not None:
        last = _last_on_or_before(index, today) or last
    bench_daily = bench_prices.pct_change()
    covered = daily.dropna()
    rows: list[dict] = []
    if covered.empty:
        return rows
    y0 = first_year or covered.index[0].year
    for year in range(y0, last.year + 1):
        start = _last_on_or_before(index, date(year - 1, 12, 31))
        if start is None:
            continue
        if year < last.year:
            end = _last_on_or_before(index, date(year, 12, 31))
            label, kind = str(year), "year"
        else:
            end = last
            label, kind = f"YTD {year}", "ytd"
        if end is None or end <= start:
            continue
        rows.append({"label": label, "kind": kind, "start": start.date(), "end": end.date(),
                     "fund": window_return(daily, start, end),
                     "spy": window_return(bench_daily, start, end)})
    ttm_start = _last_on_or_before(index, (last - pd.Timedelta(days=365)).date())
    if ttm_start is not None:
        rows.append({"label": "TTM", "kind": "ttm", "start": ttm_start.date(), "end": last.date(),
                     "fund": window_return(daily, ttm_start, last),
                     "spy": window_return(bench_daily, ttm_start, last)})
    return rows


def avg_coverage(periods: list[PeriodResult], start: date, end: date) -> tuple[float | None, int]:
    """Mean coverage of the holding periods overlapping [start, end]."""
    used = [p for p in periods if p.end > start and p.start < end and p.fund_return is not None]
    if not used:
        return None, 0
    return sum(p.coverage for p in used) / len(used), len(used)

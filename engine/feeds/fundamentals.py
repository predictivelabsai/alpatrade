"""Publication-lagged fundamentals for historical valuation, independent of prices.

EODHD adapter: Earnings.History.{quarter}: date, reportDate, epsActual.
Dates without a time are conservatively usable from the next calendar day.
Verified legacy endpoint and fields (2026-10-16):
https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds
https://eodhd.com/financial-academy/building-stocks-apps-examples/fundamental-data-for-the-financial-trading-dashboard-with-python-django
This reconstructs publication timing, not historical revision vintages: EODHD
may revise/restate EPS or its split basis. No snapshot ratios or estimates enter.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import tempfile
from pathlib import Path
from typing import Protocol

import pandas as pd


class FundamentalsProvider(Protocol):
    def get_fundamentals(self, symbol: str) -> dict:
        """Return quarterly earnings with fiscal and publication dates."""


class CachedFundamentals:
    """Cache successful provider payloads for 24 hours, without credentials."""

    def __init__(self, provider: FundamentalsProvider | None = None,
                 cache_dir: Path | None = None, ttl_seconds: float = 86400):
        if provider is None:
            if not os.getenv("EODHD_API_KEY"):
                raise ValueError("Valuation backtests require EODHD_API_KEY and fundamentals access; "
                                 "snapshot P/E is not a historical substitute.")
            from engine.feeds.eodhd import EODHD_API
            provider = EODHD_API()
        self.provider = provider
        self.cache_dir = cache_dir or Path(__file__).resolve().parents[2] / "data" / "fundamentals" / "eodhd"
        self.ttl_seconds = ttl_seconds

    def get_fundamentals(self, symbol: str) -> dict:
        symbol = symbol.upper()
        if not re.fullmatch(r"[A-Z0-9^_-]+(?:\.[A-Z0-9_-]+)?", symbol):
            raise ValueError("Invalid fundamentals symbol")
        path = self.cache_dir / f"{symbol}.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if 0 <= time.time() - cached["fetched_at"] < self.ttl_seconds:
                return cached["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        payload = self.provider.get_fundamentals(symbol)
        # Validate before caching an error or a malformed response.
        quarterly_earnings(payload)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"fetched_at": time.time(), "payload": payload}, handle)
        temporary.replace(path)
        return payload


def quarterly_earnings(payload: dict) -> list[tuple[pd.Timestamp, pd.Timestamp, float]]:
    """Normalise valid actuals. Never substitute fiscal dates for report dates."""
    earnings = payload.get("Earnings") if isinstance(payload, dict) else None
    history = earnings.get("History", {}) if isinstance(earnings, dict) else {}
    rows = []
    for item in history.values() if isinstance(history, dict) else []:
        try:
            period = pd.Timestamp(item["date"]).normalize()
            report = pd.Timestamp(item["reportDate"]).normalize()
            eps = float(item["epsActual"])
            if pd.isna(period) or pd.isna(report) or report <= period or not math.isfinite(eps):
                continue
            rows.append((period, report + pd.Timedelta(days=1), eps))
        except (ValueError, KeyError, TypeError):
            continue
    if not rows:
        raise ValueError("EODHD has no usable quarterly EPS with reportDate; "
                         "cannot backtest valuation without publication dates.")
    return sorted(rows, key=lambda row: (row[1], row[0]))


def daily_valuation(payload: dict, close: pd.Series) -> pd.DataFrame:
    """Daily TTM EPS, P/E and trailing YoY EPS growth in percentage points.

    Four consecutive reported quarters are required for EPS; eight for growth.
    Missing quarters and stale reports are excluded. PEG = P/E / growth_pct,
    defined only for positive TTM EPS and positive trailing growth.
    """
    reports = quarterly_earnings(payload)
    dates = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    output = []
    known = {}
    cursor = 0
    for date, price in zip(dates, close):
        while cursor < len(reports) and reports[cursor][1] <= date:
            period, available, eps = reports[cursor]
            known[period] = (available, eps)
            cursor += 1
        periods = sorted(known)
        ttm = growth = float("nan")
        if len(periods) >= 4:
            latest = periods[-4:]
            consecutive = all(60 <= (b - a).days <= 120 for a, b in zip(latest, latest[1:]))
            if consecutive and (date - known[latest[-1]][0]).days <= 200:
                ttm = sum(known[q][1] for q in latest)
                if len(periods) >= 8:
                    eight = periods[-8:]
                    if all(60 <= (b - a).days <= 120 for a, b in zip(eight, eight[1:])):
                        prior = sum(known[q][1] for q in eight[:4])
                        if prior > 0 and ttm > 0:
                            growth = (ttm / prior - 1) * 100
        pe = float(price) / ttm if ttm > 0 and float(price) > 0 else float("nan")
        peg = pe / growth if growth > 0 else float("nan")
        output.append((ttm, pe, growth, peg))
    return pd.DataFrame(output, index=close.index, columns=["ttm_eps", "pe", "growth_pct", "peg"])

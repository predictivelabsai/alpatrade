"""Bounded REST adapters for Massive and Finnhub; no SDK global clients."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

import httpx

from engine.premarket_data import (
    DELAY_MINUTES, ET, OBSERVATION_AT, cached, finite, now_et,
)


class ProviderUnavailable(RuntimeError):
    """An operator-safe provider failure (never includes request credentials)."""


def _get(provider: str, path: str, params: dict | None = None) -> dict:
    variable = "MASSIVE_API_KEY" if provider == "massive" else "FINNHUB_API_KEY"
    key = os.getenv(variable)
    if not key:
        raise ProviderUnavailable(f"{variable} is not configured.")
    base = "https://api.massive.com" if provider == "massive" else "https://finnhub.io/api/v1"
    headers = {"Authorization": f"Bearer {key}"} if provider == "massive" else {"X-Finnhub-Token": key}
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.get(base + path, params=params, headers=headers)
        if response.status_code != 200:
            raise ProviderUnavailable(f"{provider.title()} returned HTTP {response.status_code}.")
        result = response.json()
        if not isinstance(result, dict) or result.get("error") or result.get("status") in {"ERROR", "NOT_AUTHORIZED"}:
            raise ProviderUnavailable(f"{provider.title()} data is unavailable for this subscription.")
        return result
    except (httpx.HTTPError, ValueError):
        raise ProviderUnavailable(f"{provider.title()} request failed.") from None


def timestamp(value) -> datetime | None:
    number = finite(value)
    if not number or number < 0:
        return None
    if number > 1e17:  # nanoseconds in market snapshots
        number /= 1e9
    elif number > 1e14:
        number /= 1e6
    elif number > 1e11:  # milliseconds in aggregate bars
        number /= 1000
    try:
        return datetime.fromtimestamp(number, timezone.utc).astimezone(ET)
    except (OverflowError, ValueError, OSError):
        return None


def market_snapshot() -> list[dict]:
    return cached(("massive-snapshot",), 60, lambda: _get(
        "massive", "/v2/snapshot/locale/us/markets/stocks/tickers",
        {"include_otc": "false"}).get("tickers", []))


def live_observations(companies: list[dict], current: datetime) -> dict[int, dict]:
    day = current.date()
    cutoff = min(current, datetime.combine(day, OBSERVATION_AT, tzinfo=ET))
    by_ticker = {row["ticker"]: row for row in companies}
    result = {}
    for item in market_snapshot():
        meta = by_ticker.get(item.get("ticker"))
        minute, previous = item.get("min") or {}, item.get("prevDay") or {}
        observed = timestamp(minute.get("t"))
        # A snapshot's minute timestamp labels the beginning of its OHLC bar.
        observed = observed + timedelta(minutes=1) if observed else None
        if not meta or not observed or observed.date() != day or not time(4) < observed.time() <= cutoff.time():
            continue
        result[meta["company_id"]] = {
            "company_id": meta["company_id"], "prev_close": finite(previous.get("c")),
            "premarket_close": finite(minute.get("c")),
            "accumulated_volume": finite(minute.get("av")), "quote_timestamp": observed,
            "as_of": observed, "data_source": "massive", "snapshot_id": f"live:{observed.isoformat()}",
        }
    return result


def previous_closes(previous_day: date, companies: list[dict]) -> list[dict]:
    """Explicit session date keeps restart/catch-up independent of today's feed."""
    result = cached(("massive-closes", previous_day), 3600, lambda: _get(
        "massive", f"/v2/aggs/grouped/locale/us/market/stocks/{previous_day}",
        {"adjusted": "false", "include_otc": "false"}).get("results", []))
    prices = {row.get("T"): finite(row.get("c")) for row in result}
    return [{"company_id": meta["company_id"], "prev_close": prices[meta["ticker"]]}
            for meta in companies if prices.get(meta["ticker"]) and prices[meta["ticker"]] > 0]


def minute_bars(ticker: str, start: datetime, end: datetime) -> list[dict]:
    path = (f"/v2/aggs/ticker/{quote(ticker, safe='')}/range/1/minute/"
            f"{int(start.timestamp() * 1000)}/{int(end.timestamp() * 1000)}")
    response = _get("massive", path, {"adjusted": "false", "sort": "asc", "limit": 50000})
    if response.get("next_url"):
        raise ProviderUnavailable("Minute-bar response was incomplete.")
    return response.get("results", [])


def final_observation(meta: dict, day: date, prior: float | None) -> dict | None:
    cutoff = datetime.combine(day, OBSERVATION_AT, tzinfo=ET)
    start = datetime.combine(day, time(4), tzinfo=ET)
    bars = minute_bars(meta["ticker"], start, cutoff)
    valid = []
    for bar in bars:
        stamp = timestamp(bar.get("t"))
        closed = stamp + timedelta(minutes=1) if stamp else None
        price = finite(bar.get("c"))
        if closed and start < closed <= cutoff and price is not None and price > 0:
            valid.append((closed, price, finite(bar.get("v")) or 0))
    if not valid:
        return None
    valid.sort(key=lambda item: item[0])
    return {"company_id": meta["company_id"], "prev_close": prior,
            "premarket_close": valid[-1][1], "quote_timestamp": valid[-1][0],
            "as_of": cutoff, "accumulated_volume": sum(item[2] for item in valid)}


def chart(ticker: str, day: date, prior_hours: dict, now: datetime | None = None) -> list[dict]:
    current = now_et(now)
    cutoff = datetime.combine(day, OBSERVATION_AT, tzinfo=ET)
    if day == current.date():
        cutoff = min(cutoff, current - timedelta(minutes=DELAY_MINUTES))
    before = prior_hours["close"]
    bars = cached(("chart", ticker, day, cutoff.replace(second=0, microsecond=0)),
                  60 if day == current.date() else 3600,
                  lambda: minute_bars(ticker, before, cutoff))
    result = []
    for bar in bars:
        stamp = timestamp(bar.get("t"))
        stamp = stamp + timedelta(minutes=1) if stamp else None
        price = finite(bar.get("c"))
        if not stamp or price is None or price <= 0 or stamp > cutoff:
            continue
        after = before < stamp <= prior_hours["after_hour_close"]
        pre = stamp.date() == day and time(4) < stamp.time() <= OBSERVATION_AT
        if after or pre:
            result.append({"timestamp": stamp.isoformat(), "price": price,
                           "session": "after_hours" if after else "premarket"})
    return sorted(result, key=lambda row: row["timestamp"])


def earnings(day: date, previous_day: date, companies: list[dict]) -> list[dict]:
    response = cached(("earnings", day), 300, lambda: _get(
        "finnhub", "/calendar/earnings", {"from": previous_day.isoformat(), "to": day.isoformat(),
                                          "symbol": "", "international": "false"}))
    names = {row["ticker"]: row["company_name"] for row in companies}
    result = {}
    for row in response.get("earningsCalendar", []):
        ticker = str(row.get("symbol", "")).upper()
        morning = row.get("date") == day.isoformat() and row.get("hour") == "bmo"
        overnight = row.get("date") == previous_day.isoformat() and row.get("hour") == "amc"
        if ticker in names and (morning or overnight):
            result[(ticker, row["date"])] = {"ticker": ticker, "company_name": names[ticker],
                "date": row["date"], "session": "Premarket" if morning else "After hours"}
    return sorted(result.values(), key=lambda row: (row["ticker"], row["date"]))

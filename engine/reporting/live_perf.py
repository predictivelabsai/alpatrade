"""Live-account performance vs SPY — shared by the daily LIVE email, /live/account, and /dashboard.

Builds:
* a since-start summary (account return, SPY return, excess, strategy P&L)
* daily equity curves (account $ and SPY, plus index-100 series for Plotly / SVG / email PNG)

Callers supply a GET-only live client (portfolio history) and the runner ``run``
row; this module never reads credentials itself.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("reporting.live_perf")
ET = ZoneInfo("America/New_York")


def _fn(v) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _f(v, default: float = 0.0) -> float:
    x = _fn(v)
    return default if x is None else x


def spy_close(day: date, run: dict | None = None) -> Optional[float]:
    """SPY close on/before ``day`` from market data, else the runner's recorded SPY."""
    try:
        import pandas as pd
        from engine.feeds.market_data import get_historical_data
        df = get_historical_data(
            "SPY",
            datetime.combine(day - timedelta(days=7), dtime.min),
            datetime.combine(day + timedelta(days=1), dtime.min),
            timeframe="day",
        )
        if df is not None and not df.empty and "Close" in df:
            closes = df["Close"].dropna()
            closes = closes[pd.to_datetime(closes.index).date <= day]
            if len(closes):
                return float(closes.iloc[-1])
    except Exception:  # noqa: BLE001
        log.debug("spy_close market data failed", exc_info=True)
    run = run or {}
    res = run.get("results") or {}
    snap = (res.get("daily") or {}).get(day.isoformat()) or {}
    return _fn(snap.get("spy")) or _fn((res.get("latest") or {}).get("spy"))


def performance_since_start(
    equity: float | None,
    run: dict,
    day: date | None = None,
    spy: float | None = None,
    runner_open: list[dict] | None = None,
) -> dict:
    """Account / SPY / strategy summary since the live runner started."""
    cfg = (run or {}).get("config") or {}
    if not (run or {}).get("run_id"):
        return {}
    day = day or datetime.now(ET).date()
    start_eq, start_spy = _fn(cfg.get("start_equity")), _fn(cfg.get("start_spy"))
    if spy is None:
        spy = spy_close(day, run)
    equity = _fn(equity)
    acct_ret = (equity / start_eq - 1) * 100 if equity is not None and start_eq else None
    spy_ret = (spy / start_spy - 1) * 100 if spy and start_spy else None
    latest = ((run or {}).get("results") or {}).get("latest") or {}
    upl = sum(_f(r.get("upl")) for r in (runner_open or []))
    realized = _fn(latest.get("realized_pnl"))
    out = {
        "started": cfg.get("started") or (run or {}).get("started_at"),
        "start_equity": start_eq,
        "equity": equity,
        "account_return_pct": acct_ret,
        "account_pnl": (equity - start_eq) if equity is not None and start_eq else None,
        "spy_start": start_spy,
        "spy": spy,
        "spy_return_pct": spy_ret,
        "excess_pct": (acct_ret - spy_ret)
        if acct_ret is not None and spy_ret is not None else None,
        "strategy_realized": realized,
        "strategy_unrealized": upl if runner_open is not None else _fn(latest.get("unrealized_pnl")),
        "closed_trades": latest.get("closed_trades"),
    }
    sr = _fn(out["strategy_realized"])
    su = _fn(out["strategy_unrealized"])
    if sr is not None or su is not None:
        out["strategy_pnl"] = _f(sr) + _f(su)
    return out


def _parse_started(cfg: dict, run: dict) -> Optional[date]:
    raw = cfg.get("started") or (run or {}).get("started_at")
    if raw is None:
        return None
    if hasattr(raw, "date"):
        try:
            return raw.astimezone(ET).date() if getattr(raw, "tzinfo", None) else raw.date()
        except Exception:  # noqa: BLE001
            return raw.date() if hasattr(raw, "date") else None
    s = str(raw)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def equity_curves(
    client,
    run: dict,
    *,
    end: date | None = None,
    spy_series: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Daily account equity + SPY from live-start through ``end``.

    Returns ``{dates, account, spy, account_idx, spy_idx, start_equity, start_spy}``
    with index-100 series when baselines exist. Empty dict on failure / no run.
    """
    cfg = (run or {}).get("config") or {}
    if not (run or {}).get("run_id"):
        return {}
    start_d = _parse_started(cfg, run)
    if not start_d:
        return {}
    end = end or datetime.now(ET).date()
    if end < start_d:
        end = start_d
    start_eq = _fn(cfg.get("start_equity"))
    start_spy = _fn(cfg.get("start_spy"))

    dates: list[str] = []
    account: list[float] = []
    try:
        hist = client.get_portfolio_history(
            (start_d - timedelta(days=2)).isoformat(),
            end.isoformat(),
            "1D",
        )
        ts, eq = hist.get("timestamp") or [], hist.get("equity") or []
        for t, e in zip(ts, eq):
            if e is None:
                continue
            d = datetime.fromtimestamp(int(t), ET).date()
            if d < start_d or d > end:
                continue
            dates.append(d.isoformat())
            account.append(float(e))
    except Exception:  # noqa: BLE001
        log.warning("portfolio history for equity curve failed", exc_info=True)
        return {}

    if not dates:
        return {}

    # SPY closes aligned to account dates
    spy_map = dict(spy_series or {})
    if not spy_map:
        try:
            import pandas as pd
            from engine.feeds.market_data import get_historical_data
            df = get_historical_data(
                "SPY",
                datetime.combine(start_d - timedelta(days=5), dtime.min),
                datetime.combine(end + timedelta(days=1), dtime.min),
                timeframe="day",
            )
            if df is not None and not df.empty and "Close" in df:
                for idx, row in df.iterrows():
                    d = pd.to_datetime(idx).date()
                    spy_map[d.isoformat()] = float(row["Close"])
        except Exception:  # noqa: BLE001
            log.debug("SPY series for equity curve failed", exc_info=True)

    # Forward-fill SPY onto account dates
    spy: list[Optional[float]] = []
    last = start_spy
    for d in dates:
        if d in spy_map:
            last = spy_map[d]
        spy.append(last)

    # Prefer runner baselines when present; else first point
    base_eq = start_eq or (account[0] if account else None)
    base_spy = start_spy or next((s for s in spy if s), None)
    account_idx = [
        (v / base_eq * 100.0) if base_eq else None for v in account
    ]
    spy_idx = [
        (v / base_spy * 100.0) if (base_spy and v) else None for v in spy
    ]
    return {
        "dates": dates,
        "account": account,
        "spy": spy,
        "account_idx": account_idx,
        "spy_idx": spy_idx,
        "start_equity": base_eq,
        "start_spy": base_spy,
        "start_date": start_d.isoformat(),
        "end_date": end.isoformat(),
    }


def svg_equity_chart(curves: dict, width: int = 560, height: int = 180) -> str:
    """Minimal inline SVG (email-safe) for account vs SPY index-100 curves."""
    if not curves or not curves.get("dates"):
        return ""
    dates = curves["dates"]
    a = curves.get("account_idx") or []
    s = curves.get("spy_idx") or []
    pts = [(i, a[i], s[i] if i < len(s) else None) for i in range(len(dates))
           if a[i] is not None]
    if len(pts) < 2:
        return ""
    ys = [p[1] for p in pts] + [p[2] for p in pts if p[2] is not None]
    ymin, ymax = min(ys), max(ys)
    if ymax <= ymin:
        ymax = ymin + 1.0
    pad = (ymax - ymin) * 0.08
    ymin, ymax = ymin - pad, ymax + pad
    left, right, top, bottom = 36, width - 12, 14, height - 24
    n = len(pts) - 1

    def xy(i, y):
        x = left + (right - left) * (i / n)
        yy = top + (bottom - top) * (1 - (y - ymin) / (ymax - ymin))
        return x, yy

    def path(vals_idx):
        parts = []
        for i, (_, av, sv) in enumerate(pts):
            y = av if vals_idx == 0 else sv
            if y is None:
                continue
            x, yy = xy(i, y)
            parts.append(("M" if not parts else "L") + f"{x:.1f},{yy:.1f}")
        return " ".join(parts)

    a_path, s_path = path(0), path(1)
    y0 = xy(0, 100.0)[1] if ymin <= 100 <= ymax else None
    grid = ""
    if y0 is not None:
        grid = (f'<line x1="{left}" y1="{y0:.1f}" x2="{right}" y2="{y0:.1f}" '
                f'stroke="#D5D2C8" stroke-dasharray="3,3"/>')
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}" role="img"
     aria-label="Live account vs SPY since start (index 100)">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#FFFFFF"/>
  {grid}
  <path d="{s_path}" fill="none" stroke="#7A867E" stroke-width="2"/>
  <path d="{a_path}" fill="none" stroke="#1F5D43" stroke-width="2.4"/>
  <text x="{left}" y="{height - 6}" font-size="10" fill="#7A867E"
        font-family="Inter,Arial,sans-serif">{dates[0][5:]} → {dates[-1][5:]} · index 100 at start</text>
  <text x="{right}" y="12" text-anchor="end" font-size="10" fill="#1F5D43"
        font-family="Inter,Arial,sans-serif">Account</text>
  <text x="{right - 58}" y="12" text-anchor="end" font-size="10" fill="#7A867E"
        font-family="Inter,Arial,sans-serif">SPY</text>
</svg>""".strip()



def png_equity_chart(curves: dict, width: int = 560, height: int = 180) -> bytes:
    """PNG equity curve (account vs SPY, index 100) for email CID attachments.

    Gmail strips inline ``<svg>``; a CID-attached PNG is the reliable email path.
    Returns empty bytes when there is nothing to draw.
    """
    if not curves or not curves.get("dates"):
        return b""
    dates = curves["dates"]
    a = curves.get("account_idx") or []
    s = curves.get("spy_idx") or []
    pts = [(i, a[i], s[i] if i < len(s) else None) for i in range(len(dates))
           if i < len(a) and a[i] is not None]
    if len(pts) < 2:
        return b""
    ys = [p[1] for p in pts] + [p[2] for p in pts if p[2] is not None]
    ymin, ymax = min(ys), max(ys)
    if ymax <= ymin:
        ymax = ymin + 1.0
    pad = (ymax - ymin) * 0.08
    ymin, ymax = ymin - pad, ymax + pad
    left, right, top, bottom = 36, width - 12, 14, height - 24
    n = len(pts) - 1

    def xy(i, y):
        x = left + (right - left) * (i / n)
        yy = top + (bottom - top) * (1 - (y - ymin) / (ymax - ymin))
        return int(round(x)), int(round(yy))

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover
        log.warning("Pillow missing; cannot render email equity PNG")
        return b""

    im = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(im)
    if ymin <= 100 <= ymax:
        y0 = xy(0, 100.0)[1]
        # dashed baseline at index 100
        x = left
        while x < right:
            draw.line([(x, y0), (min(x + 3, right), y0)], fill="#D5D2C8", width=1)
            x += 6
    spy_pts = [xy(i, sv) for i, (_, _, sv) in enumerate(pts) if sv is not None]
    acct_pts = [xy(i, av) for i, (_, av, _) in enumerate(pts)]
    if len(spy_pts) >= 2:
        draw.line(spy_pts, fill="#7A867E", width=2)
    if len(acct_pts) >= 2:
        draw.line(acct_pts, fill="#1F5D43", width=3)
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    label = f"{dates[0][5:]} → {dates[-1][5:]} · index 100 at start"
    draw.text((left, height - 14), label, fill="#7A867E", font=font)
    # right-aligned legend approx
    draw.text((right - 48, 2), "Account", fill="#1F5D43", font=font)
    draw.text((right - 100, 2), "SPY", fill="#7A867E", font=font)
    import io
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()



__all__ = [
    "equity_curves",
    "performance_since_start",
    "spy_close",
    "svg_equity_chart",
    "png_equity_chart",
]

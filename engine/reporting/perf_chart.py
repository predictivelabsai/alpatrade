"""ONE performance chart for every surface: /dashboard (live + paper), /live/account and the
strategy pages (/strategies/<id>#details, Leaderboard "View more").

The chart never plots raw equity. Account performance is a deposit-adjusted, time-weighted
index (base 100): daily session-close equity chained, each day net of that day's external cash
flows (CSD / CSW / JNLC, engine/reporting/cash_flows.py), so a deposit or withdrawal is never
drawn as a jump. SPY is indexed to 100 on the same baseline; the x-axis is dates.

* ``performance_series()``  pure: dates/equity/SPY (+flows) -> TWR index, SPY index, drawdown, daily %
* ``period_returns()``      pure: MTD / YTD / since-inception account %, SPY %, excess from a series
* ``spy_closes()``          SPY daily closes {iso date: close} (market data; {} when unavailable)
* ``chart_html()``          the shared Plotly block (div + JSON payload + renderer)
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Iterable, Optional

log = logging.getLogger("reporting.perf_chart")


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _d(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def performance_series(dates: Iterable, equity: Iterable, spy: Iterable,
                       flows: Optional[list] = None, start_equity: Optional[float] = None,
                       start_spy: Optional[float] = None,
                       start_date: Optional[Any] = None) -> dict:
    """Base-100 TWR index (flows removed day by day), SPY index, drawdown %, daily returns %.

    With ``start_equity`` (and ``start_date``) the baseline is that equity at the inception
    date, so the first point is already a return; otherwise the first point is the baseline.
    A flow dated on day k is booked at the end of day k: r_k = (E_k - F(prev, k]) / E_prev - 1.
    """
    from engine.reporting.cash_flows import net_flows
    pts = [(_d(a), _num(e), _num(s)) for a, e, s in zip(dates, equity, spy) if _num(e)]
    if start_date is not None:
        pts = [p for p in pts if p[0] >= _d(start_date)]
    if not pts:
        return {}
    base_eq = _num(start_equity) or pts[0][1]
    base_spy = _num(start_spy) or next((s for _, _, s in pts if s), None)
    prev_day = _d(start_date) if (start_date is not None and _num(start_equity)) else None
    idx, rets, dd, sidx = [], [], [], []
    level, prev_eq, peak = 100.0, base_eq, 100.0
    for i, (day, e, s) in enumerate(pts):
        if i == 0 and _num(start_equity) is None:
            r = 0.0
        else:
            f = net_flows(flows or [], prev_day, day) if prev_day and day > prev_day else 0.0
            r = (e - f) / prev_eq - 1 if prev_eq else 0.0
        level *= 1 + r
        peak = max(peak, level)
        idx.append(round(level, 4))
        rets.append(round(r * 100, 4))
        dd.append(round((level / peak - 1) * 100, 4))
        sidx.append(round(s / base_spy * 100, 4) if s and base_spy else None)
        prev_eq, prev_day = e, day
    return {"dates": [p[0].isoformat() for p in pts], "index": idx, "spy_index": sidx,
            "equity": [p[1] for p in pts], "spy": [p[2] for p in pts],
            "drawdown_pct": dd, "daily_return_pct": rets,
            "max_drawdown_pct": min(dd) if dd else None,
            "start_date": (_d(start_date).isoformat() if start_date is not None else pts[0][0].isoformat()),
            "flows_ok": flows is not None}


def _ret(level_end: Optional[float], level_base: Optional[float]) -> Optional[float]:
    if level_end is None or not level_base:
        return None
    return (level_end / level_base - 1) * 100


def period_returns(series: dict, today: Optional[date] = None) -> dict:
    """{'mtd'|'ytd'|'inception': {account_pct, spy_pct, excess_pct, base_date, clipped}}.

    Same TWR chain as the chart: the period return is index[end] / index[base] - 1, where base is
    the last session close before the period starts (index 100 at inception when the period
    starts before inception; ``clipped`` is then True). SPY is measured over the same dates."""
    dates = [date.fromisoformat(x) for x in (series or {}).get("dates") or []]
    if not dates:
        return {}
    idx, sidx = series["index"], series.get("spy_index") or [None] * len(dates)
    today = today or dates[-1]
    inception = date.fromisoformat(series.get("start_date") or dates[0].isoformat())
    end_a, end_s = idx[-1], next((v for v in reversed(sidx) if v is not None), None)
    out = {}
    for key, start in (("mtd", today.replace(day=1)), ("ytd", date(today.year, 1, 1)),
                       ("inception", None)):
        base_i = None
        if start is not None:
            prior = [i for i, d in enumerate(dates) if d < start]
            base_i = prior[-1] if prior else None
        ba = 100.0 if base_i is None else idx[base_i]
        bs = 100.0 if base_i is None else sidx[base_i]
        a, s = _ret(end_a, ba), _ret(end_s, bs)
        out[key] = {"account_pct": a, "spy_pct": s,
                    "excess_pct": (a - s) if a is not None and s is not None else None,
                    "base_date": (inception if base_i is None else dates[base_i]).isoformat(),
                    "clipped": start is not None and base_i is None}
    return out


def spy_closes(start: date, end: date) -> dict[str, float]:
    """SPY daily closes {iso date: close} from market data; {} when unavailable."""
    try:
        import pandas as pd
        from engine.feeds.market_data import get_historical_data
        df = get_historical_data("SPY", datetime.combine(start - timedelta(days=7), dtime.min),
                                 datetime.combine(end + timedelta(days=1), dtime.min), timeframe="day")
        if df is None or df.empty or "Close" not in df:
            return {}
        return {pd.to_datetime(i).date().isoformat(): float(v) for i, v in df["Close"].dropna().items()}
    except Exception:  # noqa: BLE001
        log.debug("SPY closes unavailable", exc_info=True)
        return {}


def ffill_spy(dates: list[str], spy_map: dict[str, float], first: Optional[float] = None) -> list:
    """SPY close aligned to ``dates`` (forward-filled; seeded with the last close before)."""
    if first is None and dates:
        prior = sorted(k for k in spy_map if k < dates[0])
        first = spy_map[prior[-1]] if prior else None
    out, last = [], first
    for d in dates:
        last = spy_map.get(d, last)
        out.append(last)
    return out


# Extracted verbatim from the strategy page (/strategies/<id>#details, ph_leaderboard
# _DETAIL_JS): same layout, colours and trade markers. Only additions: wait for Plotly and an
# optional shaded period (dashboard MTD/YTD).
_JS = """<script>(function(){function go(){var n=document.getElementById('pc-data-__ID__');if(!n)return;
if(!window.Plotly)return setTimeout(go,150);
var d=JSON.parse(n.textContent),s=d.s,L={margin:{l:40,r:10,t:10,b:30},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
legend:{orientation:'h'},xaxis:{type:'date'}},C={displayModeBar:false,responsive:true};
var tr=[{x:s.dates,y:s.index,name:d.label,line:{color:'#1F5D43',width:2}}];
if(s.spy_index&&s.spy_index.some(function(v){return v!=null}))tr.push({x:s.dates,y:s.spy_index,name:'SPY',line:{color:'#7A867E'}});
var pos={};s.dates.forEach(function(x,i){pos[x]=s.index[i]});var bx=[],by=[],bt=[],sx=[],sy=[],st=[];
(d.trades||[]).forEach(function(t){if(t.entry&&pos[t.entry]!=null){bx.push(t.entry);by.push(pos[t.entry]);bt.push('Buy '+t.symbol)}
 if(t.exit&&pos[t.exit]!=null){sx.push(t.exit);sy.push(pos[t.exit]);st.push('Sell '+t.symbol+(t.pnl!=null?' '+t.pnl.toFixed(2):''))}});
if(bx.length)tr.push({x:bx,y:by,text:bt,mode:'markers',name:'Buys',marker:{symbol:'triangle-up',color:'#147a4b',size:9},hoverinfo:'text+x'});
if(sx.length)tr.push({x:sx,y:sy,text:st,mode:'markers',name:'Sells',marker:{symbol:'triangle-down',color:'#b43b35',size:9},hoverinfo:'text+x'});
if(d.hl&&d.hl[0])L.shapes=[{type:'rect',xref:'x',yref:'paper',x0:d.hl[0],x1:d.hl[1],y0:0,y1:1,
 fillcolor:'rgba(31,93,67,.07)',line:{width:0},layer:'below'}];
Plotly.newPlot('__ID__',tr,L,C);
var hasS=s.spy_drawdown_pct&&s.spy_drawdown_pct.some(function(v){return v!=null});
var dd=document.getElementById('__ID__-dd');if(dd){var t=[{x:s.dates,y:s.drawdown_pct,fill:'tozeroy',name:'Drawdown %',line:{color:'#b43b35'}}];
 if(hasS)t.push({x:s.dates,y:s.spy_drawdown_pct,name:'SPY drawdown %',line:{color:'#7A867E'}});Plotly.newPlot(dd,t,L,C);}
var dr=document.getElementById('__ID__-dr');if(dr){var t2=[{x:s.dates,y:s.daily_return_pct,type:'bar',name:'Daily return %',
 marker:{color:s.daily_return_pct.map(function(v){return v>=0?'#147a4b':'#b43b35'})}}];
 if(hasS)t2.push({x:s.dates,y:s.spy_daily_return_pct,name:'SPY daily %',mode:'lines+markers',line:{color:'#7A867E',width:1},marker:{size:4}});
 Plotly.newPlot(dr,t2,L,C);}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();})();</script>"""


def risk_series(series: dict) -> dict:
    """Drawdown % and daily return % for the account (from the TWR index) and SPY (from its
    index), all on the same dates: the inputs of the drawdown and daily-returns charts."""
    def dd_daily(idx):
        dd, dr, peak, prev = [], [], None, 100.0
        for v in idx or []:
            if v is None:
                dd.append(None); dr.append(None)
                continue
            peak = v if peak is None else max(peak, v)
            dd.append(round((v / peak - 1) * 100, 4))
            dr.append(round((v / prev - 1) * 100, 4) if prev else None)
            prev = v
        return dd, dr
    _, a_dr = dd_daily(series.get("index"))
    s_dd, s_dr = dd_daily(series.get("spy_index"))
    peak, a_dd = 100.0, []  # account drawdown counts the inception baseline (100) as a peak
    for v in series.get("index") or []:
        if v is None:
            a_dd.append(None)
            continue
        peak = max(peak, v)
        a_dd.append(round((v / peak - 1) * 100, 4))
    return {"drawdown_pct": a_dd, "daily_return_pct": a_dr,
            "spy_drawdown_pct": s_dd, "spy_daily_return_pct": s_dr}


def chart_html(el_id: str, series: dict, *, label: str = "Account (TWR)",
               trades: Optional[list] = None, highlight: Optional[tuple] = None,
               css_class: str = "chart", note: str = "", daily: bool = True,
               ytitle: str = "Index (100 = start)") -> str:
    """Shared chart block (the strategy-page charts): 1) account TWR index vs SPY (base 100)
    with trade markers, 2) drawdown % vs SPY drawdown, 3) daily returns % (bars) vs SPY daily
    — all from the same deposit-adjusted daily series, dates on x, optional shaded period
    (``highlight`` = (iso start, iso end)). ``daily=False`` omits chart 3 (backtests). Requires
    Plotly on the page (it waits for it). Returns '' when the series is empty."""
    if not series or not series.get("dates"):
        return ""
    s = {k: series.get(k) for k in ("dates", "index", "spy_index")}
    s.update(risk_series(s))
    if highlight:  # never widen the x-axis beyond the data (e.g. YTD before inception)
        lo, hi = max(str(highlight[0]), s["dates"][0]), min(str(highlight[1]), s["dates"][-1])
        highlight = (lo, hi) if lo <= hi else None
    payload = json.dumps({"s": s, "label": label, "trades": trades or [], "ytitle": ytitle,
                          "hl": list(highlight) if highlight else None},
                         default=str).replace("</", "<\\/")
    safe = "".join(ch for ch in el_id if ch.isalnum() or ch in "-_")
    foot = (f"<p class='note pc-note' style='font-size:.72rem;color:var(--ink-dim);margin:.35rem 0 0'>"
            f"{note}</p>") if note else ""
    h3 = "style='font-size:.85rem;margin:.9rem 0 .3rem'"
    small = f"class='{css_class} small perf-chart-sub' style='height:200px;width:100%'"
    return (f"<div class='perf-charts'><div id='{safe}' class='{css_class} perf-chart' data-perf-chart='1'></div>"
            f"<h3 class='pc-h' {h3}>Drawdown</h3><div id='{safe}-dd' {small}></div>"
            + (f"<h3 class='pc-h' {h3}>Daily returns</h3><div id='{safe}-dr' {small}></div>" if daily else "")
            + f"<script type='application/json' id='pc-data-{safe}'>{payload}</script>"
            + _JS.replace("__ID__", safe) + foot + "</div>")


def series_from_curves(curves: dict) -> dict:
    """The performance series of live_perf.equity_curves() output (TWR index)."""
    c = curves or {}
    if c.get("series"):
        return c["series"]
    if not c.get("dates"):
        return {}
    return {"dates": c["dates"], "index": c.get("account_idx") or [],
            "spy_index": c.get("spy_idx") or [], "start_date": c.get("start_date") or c["dates"][0]}


__all__ = ["risk_series", "series_from_curves", "performance_series", "period_returns", "spy_closes", "ffill_spy", "chart_html"]

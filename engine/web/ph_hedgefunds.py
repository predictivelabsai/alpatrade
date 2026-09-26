"""Hedge Funds page — 13F-implied performance, a 13F filer screener, the AUM
treemap and activist filings.

Backend: engine.publicmarkets.hedge_funds (shared hedgefolio 13F schema + the
alpatrade.hf13f_* tables filled by scripts/hedge_fund_13f.py).
Feature-module contract: register(app, rt).
"""
from __future__ import annotations

from fasthtml.common import (A, Button, Details, Div, Form, Hidden, Input, Label, NotStr, Option, P, Script,
                             Select, Span, Style, Summary, Table, Tbody, Td, Th, Thead, Tr)
from starlette.responses import JSONResponse

from engine.web.ph_layout import page

_CSS = """

.hfpage{max-width:1180px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.hfpage h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.hfpage h3{color:var(--accent);margin:1.4rem 0 .4rem;font-size:1rem}
.hfpage .hf-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.hf-plot{width:100%;min-height:460px;background:#fff;border:1px solid var(--line);
  border-radius:.6rem;padding:.3rem}
.hf-status{font-size:.8rem;color:var(--ink-muted);margin:.5rem 0}
.hfpage table{border-collapse:collapse;width:100%;font-size:.82rem}
.hfpage th,.hfpage td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.hfpage thead{background:var(--bg-raise)}
.hfpage a{color:var(--accent)}
.hf-filters{display:flex;gap:.5rem;flex-wrap:wrap;margin:.65rem 0}
.hf-filters input,.hf-filters select{font-family:var(--font-body);font-size:.86rem;color:var(--ink);background:var(--bg);
  border:1px solid var(--line-br);border-radius:.45rem;padding:.5rem .6rem}
.hf-filters button{font-size:.85rem;color:var(--bg);background:var(--accent);border:0;border-radius:.45rem;padding:.55rem 1.1rem;cursor:pointer}
.hf-note{font-size:.78rem;color:var(--ink-muted);margin:.35rem 0 .6rem;line-height:1.45}
.hf-note b{color:var(--ink)}
.hfpage td.num,.hfpage th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.hf-pos{color:#1F7A4D}.hf-neg{color:#B23B3B}.hf-na{color:var(--ink-muted)}
.hf-small{font-size:.72rem;color:var(--ink-muted)}.hf-nowrap{white-space:nowrap}
.hf-spy td{background:var(--bg-raise);font-weight:600}
.hf-badge{display:inline-block;font-size:.68rem;padding:.05rem .35rem;border-radius:.3rem;
  background:var(--bg-raise);border:1px solid var(--line);color:var(--ink-muted);margin-left:.3rem}
.hf-method{font-size:.8rem;color:var(--ink);background:var(--bg-raise);border:1px solid var(--line);
  border-radius:.5rem;padding:.4rem .75rem;margin:.5rem 0 1rem}
.hf-method summary{cursor:pointer;color:var(--accent);font-weight:600}
.hf-method li{margin:.2rem 0}
.hf-filters label{font-size:.8rem;color:var(--ink-muted);display:flex;align-items:center;gap:.3rem}
@media(max-width:600px){
  .hfpage{padding-left:.75rem;padding-right:.75rem}
  .hf-plot{min-height:360px}.hf-filters button{min-height:44px}
  .hf-table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.hfpage table{min-width:42rem}
  .hf-filters input,.hf-filters select{flex:1 1 45%}
}
"""

_JS = """
(function(){
  async function draw(){
    var el=document.getElementById('hf-plot'), s=document.getElementById('hf-status');
    if(!el||!window.Plotly) return;
    try{
      var d=await (await fetch('/hedge-funds/data')).json();
      if(!d.funds||!d.funds.length){ s.textContent='No 13F data.'; return; }
      var labels=d.funds.map(f=>f.name), values=d.funds.map(f=>f.value),
          parents=d.funds.map(()=>''),
          text=d.funds.map(f=>'$'+(f.value/1e12>=1?(f.value/1e12).toFixed(2)+'T':(f.value/1e9).toFixed(0)+'B'));
      Plotly.newPlot(el,[{type:'treemap',labels:labels,parents:parents,values:values,
        text:text,texttemplate:'%{label}<br>%{text}',hovertemplate:'%{label}<br>%{text}<extra></extra>',
        marker:{colors:values,colorscale:[[0,'#CFE5DA'],[1,'#1F5D43']]},tiling:{pad:2}}],
        {margin:{l:0,r:0,t:0,b:0},height:460,paper_bgcolor:'#fff',
         font:{family:'Inter,sans-serif',size:11,color:'#14231B'}},{displayModeBar:false,responsive:true});
      s.textContent=d.funds.length+' managers · sized by 13F portfolio value';
    }catch(e){ s.textContent='Could not load: '+e; }
  }
  if(document.readyState!=='loading') draw(); else document.addEventListener('DOMContentLoaded',draw);
})();
"""


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


def _b(v):
    return f"${v/1e12:.2f}T" if v >= 1e12 else (f"${v/1e9:.1f}B" if v >= 1e9 else f"${v/1e6:.0f}M")


def _pct(v, cls=True):
    if v is None:
        return Span("n/a", cls="hf-na")
    return Span(f"{v * 100:+.1f}%", cls=("hf-pos" if v >= 0 else "hf-neg") if cls else "")


def _money(v):
    return "—" if v is None else _b(v)


METHODOLOGY_TIP = ("Estimated from 13F holdings: long US-equity positions from each 13F-HR, weighted by "
                   "reported value, bought at the quarter-end close and held until the next quarter end; "
                   "adjusted (total-return) Yahoo prices; options, debt, cash, shorts and non-US assets "
                   "excluded. Not the fund's reported return.")
PLAN_URL = "https://github.com/predictivelabsai/alpatrade/blob/main/docs/hedge_funds_13f_plan.md"


def _methodology():
    return Details(
        Summary("Methodology — how the 13F-implied returns are estimated"),
        NotStr("""<ul>
<li><b>Holdings:</b> each 13F-HR information table from SEC EDGAR (quarter-end long positions in
13(f) securities). Restatement amendments replace a quarter; &ldquo;new holdings&rdquo; amendments
(confidential positions disclosed later) are added.</li>
<li><b>Portfolio:</b> long equity rows only (PUT/CALL option rows and principal-amount/debt rows are
excluded), weighted by reported market value. CUSIPs are mapped to tickers via OpenFIGI; unmapped or
unpriced positions are dropped and the rest re-weighted. <i>Coverage</i> is the share of long-equity value
that was priced.</li>
<li><b>13F-implied (default):</b> bought at the report-date close, buy-and-hold until the next report
date, then rebalanced to the new filing. This estimates what the <i>disclosed book</i> did; it is not
investable because 13Fs are filed up to 45 days after quarter end.</li>
<li><b>Follow-the-filing:</b> the same holdings bought at the close of the first trading day after the
filing date and held until the next filing — an investable copycat return.</li>
<li><b>Returns:</b> daily split/dividend-adjusted Yahoo closes, chained into calendar years, year-to-date
and trailing 12 months, vs SPY over the identical window. A missing filing breaks the chain (n/a).</li>
<li><b>Caveats:</b> no shorts, cash, bonds, derivatives, non-US or other non-13F assets, no intra-quarter
trading, fees or leverage; delisted names are held at their last price. Treat figures as a rough
&ldquo;13F-implied&rdquo; estimate, never as the fund&rsquo;s reported performance.</li>
</ul>"""),
        A("Full plan & method notes", href=PLAN_URL, target="_blank"),
        cls="hf-method", id="hf-methodology")


def _performance_section(method: str):
    from engine.publicmarkets.hedge_funds import METHOD_LABELS_UI, performance_rows
    data = performance_rows(method)
    labels = data["labels"]
    head = [Th("Fund"), Th("Latest 13F"), Th("13F value", cls="num"), Th("Positions", cls="num")]
    head += [Th(lbl, cls="num", title=METHODOLOGY_TIP) for lbl in labels]
    head += [Th("TTM vs SPY", cls="num"), Th("Coverage", cls="num", title="Share of 13F long-equity value priced (TTM window)")]
    body = []
    if labels:
        spy_cells = [Td(_pct(data["spy"].get(lbl)), cls="num") for lbl in labels]
        body.append(Tr(Td("SPY (S&P 500 ETF, total return)"), Td(""), Td(""), Td(""), *spy_cells, Td(""), Td(""),
                       cls="hf-spy"))
    for f in data["funds"]:
        rets = f["returns"]
        cells = [Td(_pct((rets.get(lbl) or {}).get("fund")), cls="num") for lbl in labels]
        ttm = rets.get("TTM") or {}
        excess = (ttm["fund"] - ttm["spy"]) if ttm.get("fund") is not None and ttm.get("spy") is not None else None
        cov = ttm.get("coverage")
        latest = (Td(f["latest_period"], Div(f"filed {f['latest_filed']}", cls="hf-small"), cls="hf-nowrap")
                  if f["latest_period"] else Td(Span("n/a", cls="hf-na")))
        body.append(Tr(Td(f["name"]), latest, Td(_money(f["value"]), cls="num"),
                       Td(f"{f['positions']:,}" if f["positions"] is not None else "—", cls="num"),
                       *cells, Td(_pct(excess), cls="num"),
                       Td(f"{cov * 100:.0f}%" if cov is not None else "n/a", cls="num")))
    toggle = Form(
        Select(*[Option(lbl, value=m, selected=m == method) for m, lbl in METHOD_LABELS_UI.items()],
               name="method", onchange="this.form.submit()"),
        Button("Show", type="submit"), method="get", action="/hedge-funds", cls="hf-filters")
    note = P(NotStr(
        "<b>Estimated from 13F holdings</b> — a replication of each fund&rsquo;s disclosed long US-equity "
        "positions, <b>not</b> the fund&rsquo;s reported performance. "
        f"{'Computed ' + data['computed_at'] + ' UTC. ' if data['computed_at'] else ''}"
        "n/a = not enough consecutive 13F filings for that window. "
        '<a href="#hf-methodology">Methodology</a>'), cls="hf-note", title=METHODOLOGY_TIP)
    if not data["funds"]:
        table = P("13F-implied returns are not computed yet (run scripts/hedge_fund_13f.py).", cls="hf-note")
    else:
        table = Div(Table(Thead(Tr(*head)), Tbody(*body)), cls="hf-table-scroll", id="hf-perf")
    return Div(NotStr("<h3>📈 13F-implied performance <span class='hf-badge'>estimated from 13F holdings</span></h3>"),
               note, toggle, table, _methodology())


def _screener_section(params: dict):
    from engine.publicmarkets.hedge_funds import default_period, filing_periods, screen_13f
    try:
        periods = filing_periods()
    except Exception:  # noqa: BLE001
        periods = []
    period = params.get("period") or default_period(periods)
    try:
        res = screen_13f(period=period, q=params["q"], min_aum=params["min_aum"], pos=params["pos"],
                         rtype=params["rtype"], holds=params["holds"], perf_only=params["perf"],
                         sort=params["hsort"], limit=50)
        err = None
    except Exception as exc:  # noqa: BLE001 - never 500 the page on a data hiccup
        res, err = {"rows": [], "holds_unmapped": False}, str(exc)[:200]

    def opt(value, label, current):
        return Option(label, value=value, selected=current == value)

    form = Form(
        Input(name="q", placeholder="Manager name", value=params["q"]),
        Select(*[Option(f"{p['period']} ({p['filers']:,} filers)", value=p["period"], selected=p["period"] == period)
                 for p in periods[:24]], name="period", title="13F report quarter"),
        Select(opt("holdings", "13F-HR holdings reports", params["rtype"]),
               opt("holdings_only", "Holdings report only", params["rtype"]),
               opt("combination", "Combination reports", params["rtype"]),
               opt("notice", "13F-NT notices (no holdings)", params["rtype"]),
               opt("any", "All 13F types", params["rtype"]), name="rtype", title="13F report type"),
        Select(opt("", "Any 13F value", params["min_aum"]), opt("lt100m", "< $100M", params["min_aum"]),
               opt("100m", "≥ $100M", params["min_aum"]), opt("1b", "≥ $1B", params["min_aum"]),
               opt("10b", "≥ $10B", params["min_aum"]), opt("100b", "≥ $100B", params["min_aum"]), name="min_aum"),
        Select(opt("", "Any # positions", params["pos"]), opt("concentrated", "1–20 (concentrated)", params["pos"]),
               opt("focused", "21–100", params["pos"]), opt("diversified", "101–500", params["pos"]),
               opt("broad", "500+", params["pos"]), name="pos"),
        Input(name="holds", placeholder="Holds ticker (e.g. AAPL)", value=params["holds"]),
        Select(opt("aum", "Sort: 13F value", params["hsort"]), opt("positions", "Sort: # positions", params["hsort"]),
               opt("filed", "Sort: latest filed", params["hsort"]), opt("name", "Sort: name", params["hsort"]),
               opt("ttm", "Sort: 13F-implied TTM", params["hsort"]), name="hsort"),
        Label(Input(type="checkbox", name="perf", value="1", checked=params["perf"]), "With 13F-implied returns"),
        Hidden(name="method", value=params["method"]),
        Button("Filter", type="submit"), method="get", action="/hedge-funds", cls="hf-filters", id="hf-13f-filters")
    rows = []
    for r in res["rows"]:
        ttm = r.get("ttm") or {}
        ly = r.get("last_year") or {}
        value = _money(r["value"]) + (" *" if r.get("value_scaled") else "")
        rows.append(Tr(Td(r["name"]), Td(r["period"]), Td(r["filed"]), Td(r["form"] or ""),
                       Td(value, cls="num"),
                       Td(f"{r['positions']:,}" if r["positions"] is not None else "—", cls="num"),
                       Td(_pct(ttm.get("fund")), cls="num", title=METHODOLOGY_TIP),
                       Td(_pct(ly.get("fund")), (Span(f" {ly['label']}", cls="hf-na") if ly else ""), cls="num",
                          title=METHODOLOGY_TIP)))
    msgs = []
    if res.get("holds_unmapped"):
        msgs.append(P(f"Ticker {params['holds'].upper()} isn't in the CUSIP map yet — no 13F match.", cls="hf-note"))
    if err:
        msgs.append(P("Could not load 13F filers right now.", cls="hf-note"))
    if not rows and not msgs:
        msgs.append(P("No 13F filers match these filters.", cls="hf-note"))
    return Div(
        NotStr("<h3>🔎 13F filers</h3>"),
        P("Screen every 13F filer for a report quarter by report type, 13F portfolio value, number of positions, "
          "or a ticker they hold (long, non-option rows). * = filer reported values in $ thousands; scaled.",
          cls="hf-note"),
        form, *msgs,
        Div(Table(Thead(Tr(Th("Manager"), Th("Period"), Th("Filed"), Th("Form"), Th("13F value", cls="num"),
                           Th("Positions", cls="num"), Th("13F-implied TTM", cls="num", title=METHODOLOGY_TIP),
                           Th("Last full year", cls="num", title=METHODOLOGY_TIP))),
                  Tbody(*rows)), cls="hf-table-scroll", id="hf-13f-table"))


def _clean_params(q="", period="", min_aum="", pos="", rtype="holdings", holds="", perf="", hsort="aum",
                  method="quarter_end"):
    from engine.publicmarkets.hedge_funds import AUM_BUCKETS, POSITION_BUCKETS, REPORT_TYPES, SCREEN_SORTS
    return {"q": (q or "")[:80], "period": (period or "")[:10] if len(period or "") == 10 else "",
            "min_aum": min_aum if min_aum in AUM_BUCKETS else "",
            "pos": pos if pos in POSITION_BUCKETS else "",
            "rtype": rtype if rtype in REPORT_TYPES else "holdings",
            "holds": (holds or "").strip()[:12], "perf": str(perf) in ("1", "on", "true"),
            "hsort": hsort if hsort in SCREEN_SORTS else "aum",
            "method": method if method in ("quarter_end", "follow_filing") else "quarter_end"}


def _page(user, ticker="", form="", sort="latest", params: dict | None = None):
    from engine.publicmarkets.hedge_funds import activist_filings
    params = params or _clean_params()
    acts = activist_filings(ticker=ticker, form=form, sort=sort, limit=20)
    act_rows = [Tr(Td(a["filed_at"]), Td((a["filer"] or "")[:34]),
                   Td((a["subject"] or "")[:26]), Td(a["ticker"] or ""),
                   Td(A(a["form"] or "view", href=a.get("url") or "#", target="_blank")))
                for a in acts]
    filters = Form(
        Input(name="ticker", placeholder="Target ticker", value=ticker),
        Select(Option("All forms", value="", selected=not form),
               Option("Schedule 13D", value="SCHEDULE 13D", selected=form == "SCHEDULE 13D"),
               Option("Schedule 13D/A", value="SCHEDULE 13D/A", selected=form == "SCHEDULE 13D/A"), name="form"),
        Select(Option("Latest first", value="latest", selected=sort == "latest"),
               Option("Oldest first", value="oldest", selected=sort == "oldest"),
               Option("Target A–Z", value="target", selected=sort == "target"),
               Option("Filer A–Z", value="filer", selected=sort == "filer"), name="sort"),
        Button("Apply", type="submit"), method="get", action="/hedge-funds", cls="hf-filters")
    body = Div(
        NotStr("<h1>🏦 Hedge Funds</h1>"),
        P("13F-implied performance for well-known funds, a screener over every 13F filer, the largest managers "
          "by 13F portfolio value, and recent activist filings.", cls="hf-sub"),
        _performance_section(params["method"]),
        _screener_section(params),
        NotStr("<h3>Largest managers by 13F value</h3>"),
        Div(id="hf-plot", cls="hf-plot"), Div("", id="hf-status", cls="hf-status"),
        NotStr("<h3>Recent activist filings</h3>"),
        filters,
        Div(Table(Thead(Tr(Th("Filed (ET)"), Th("Filer"), Th("Target"), Th("Ticker"), Th("Form"))),
                  Tbody(*act_rows)), cls="hf-table-scroll"),
        cls="hfpage",
    )
    return page("hedgefunds", Style(_CSS), body, Script(_JS),
                user=user, title="Hedge Funds · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("🏦 Hedge Funds", "/hedge-funds", "hedgefunds")
    if entry not in ph_layout.EXPLORE_PAGES:
        ph_layout.EXPLORE_PAGES.append(entry)

    @rt("/hedge-funds", methods=["GET"])
    def hf_get(session, ticker: str = "", form: str = "", sort: str = "latest", q: str = "",
               period: str = "", min_aum: str = "", pos: str = "", rtype: str = "holdings",
               holds: str = "", perf: str = "", hsort: str = "aum", method: str = "quarter_end"):
        params = _clean_params(q, period, min_aum, pos, rtype, holds, perf, hsort, method)
        return _page(_user(session), ticker=ticker, form=form, sort=sort, params=params)

    @rt("/hedge-funds/data", methods=["GET"])
    def hf_data(limit: int = 40):
        from engine.publicmarkets.hedge_funds import top_funds
        return JSONResponse({"funds": top_funds(limit)})

    @rt("/hedge-funds/13f.json", methods=["GET"])
    def hf_13f_json(q: str = "", period: str = "", min_aum: str = "", pos: str = "",
                    rtype: str = "holdings", holds: str = "", perf: str = "", hsort: str = "aum",
                    limit: int = 50):
        from engine.publicmarkets.hedge_funds import default_period, filing_periods, screen_13f
        p = _clean_params(q, period, min_aum, pos, rtype, holds, perf, hsort)
        period_ = p["period"] or default_period(filing_periods())
        res = screen_13f(period=period_, q=p["q"], min_aum=p["min_aum"], pos=p["pos"], rtype=p["rtype"],
                         holds=p["holds"], perf_only=p["perf"], sort=p["hsort"], limit=limit)
        return JSONResponse(res)

    @rt("/hedge-funds/performance.json", methods=["GET"])
    def hf_perf_json(method: str = "quarter_end"):
        from engine.publicmarkets.hedge_funds import performance_rows
        m = method if method in ("quarter_end", "follow_filing") else "quarter_end"
        return JSONResponse(dict(performance_rows(m), method=m,
                                 note="Estimated from 13F holdings; not reported fund performance."))

    return ["/hedge-funds", "/hedge-funds/data", "/hedge-funds/13f.json", "/hedge-funds/performance.json"]

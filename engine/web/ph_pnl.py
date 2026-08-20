"""Authenticated, account-scoped portfolio P&L dashboard."""
from __future__ import annotations

import html
import json

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.reporting.pnl_dashboard import dashboard_data
from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}.dash{width:100%;max-width:1180px;margin:auto;padding:0 1rem 3rem}
.dash-head,.dash-controls,.metric-grid,.panel-grid,.panel-head{display:flex;align-items:center}
.dash-head{justify-content:space-between;gap:1rem;flex-wrap:wrap;margin:.4rem 0 1rem}
.dash h1{font-size:1.35rem;margin:0}.muted{color:var(--ink-muted);font-size:.8rem}
.dash-controls{gap:.5rem;flex-wrap:wrap}.dash select,.periods a{border:1px solid var(--line);
 background:#fff;color:var(--ink);border-radius:.45rem;padding:.48rem .7rem;font-size:.8rem}
.dash-signout,.dash-news{border:1px solid var(--line);border-radius:.45rem;padding:.48rem .7rem;
 color:var(--ink-muted);font-size:.8rem;text-decoration:none;background:#fff}
.dash-news{cursor:pointer}.dash-signout:hover,.dash-news:hover{color:var(--accent);border-color:var(--accent)}
.periods{display:flex}.periods a{border-radius:0;text-decoration:none}.periods a:first-child{border-radius:.45rem 0 0 .45rem}
.periods a:last-child{border-radius:0 .45rem .45rem 0}.periods a.active{background:var(--accent);color:#fff}
.metric-grid{align-items:stretch;display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem}
.metric,.panel{background:#fff;border:1px solid var(--line);border-radius:.65rem;padding:1rem}
.metric .label{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ink-muted)}
.metric .value{font-size:1.28rem;font-weight:650;margin-top:.2rem}.positive{color:#147a4b}.negative{color:#b43b35}
.panel-grid{display:grid;grid-template-columns:2fr 1fr;align-items:stretch;gap:.8rem;margin-top:.8rem}
.panel{min-width:0}.panel h2{font-size:.95rem;margin:0 0 .7rem}.chart{height:340px}
.ai-copy{line-height:1.55;font-size:.88rem}.contributors{font-size:.79rem;width:100%;border-collapse:collapse}
.advisor-card{border-left:4px solid #6f7b74;padding-left:.8rem;margin:.45rem 0 1rem}.advisor-card.review,
.advisor-card.urgent{border-left-color:#b43b35}.advisor-card.monitor{border-left-color:#c4902f}
.advisor-meta,.advisor-note{color:var(--ink-muted);font-size:.75rem}.advisor-card h3{font-size:.9rem;margin:.25rem 0}
.advisor-card ul{padding-left:1.1rem;margin:.4rem 0}.advisor-card li{font-size:.8rem;margin:.3rem 0}
.advisor-history{display:flex;gap:.35rem;flex-wrap:wrap;margin-top:.65rem}.advisor-history span{font-size:.7rem;
 border:1px solid var(--line);padding:.2rem .4rem;border-radius:1rem;color:var(--ink-muted)}
.contributors td,.contributors th{padding:.45rem;border-bottom:1px solid var(--line);text-align:right}
.contributors td:first-child,.contributors th:first-child{text-align:left}.rank-tabs button{border:0;background:none;
 color:var(--ink-muted);cursor:pointer;padding:.3rem .5rem}.rank-tabs button.active{color:var(--accent);font-weight:650}
.empty{text-align:center;padding:4rem 1rem}.empty a{display:inline-block;background:var(--accent);color:#fff;
 padding:.6rem 1rem;border-radius:.5rem;text-decoration:none}.error{color:#9b302b;background:#fff0ee;padding:.7rem;border-radius:.4rem}
@media(max-width:820px){.metric-grid{grid-template-columns:repeat(2,1fr)}.panel-grid{grid-template-columns:1fr}}
@media(max-width:480px){.metric-grid{grid-template-columns:1fr 1fr}.metric{padding:.75rem}.chart{height:285px}}
"""

_JS = """
(function(){
 const d=window.__PNL_DASH__; if(!d||!window.Plotly)return;
 const base={paper_bgcolor:'#fff',plot_bgcolor:'#f7f6f1',font:{family:'Inter,system-ui',color:'#2d352f'},
 margin:{t:12,r:15,b:42,l:62},showlegend:false};
 Plotly.newPlot(document.getElementById('equity-chart'),[{x:d.history.timestamps,y:d.history.equity,type:'scatter',
 mode:'lines',line:{color:'#1f5d43',width:3},fill:'tozeroy',fillcolor:'rgba(31,93,67,.08)',
 hovertemplate:'%{x}<br>$%{y:,.2f}<extra></extra>'}],{...base,yaxis:{tickprefix:'$'}},
 {responsive:true,displayModeBar:false});
 const c=d.contributors||[];
 Plotly.newPlot(document.getElementById('contrib-chart'),[{x:c.slice(0,10).map(x=>x.symbol),y:c.slice(0,10).map(x=>x.pnl),
 type:'bar',marker:{color:c.slice(0,10).map(x=>x.pnl>=0?'#27865e':'#c64a43')},
 hovertemplate:'%{x}<br>$%{y:,.2f}<extra></extra>'}],{...base,yaxis:{tickprefix:'$'}},
 {responsive:true,displayModeBar:false});
 window.showRanks=function(kind){
  document.querySelectorAll('.rank-table').forEach(x=>x.hidden=x.dataset.kind!==kind);
  document.querySelectorAll('.rank-tabs button').forEach(x=>x.classList.toggle('active',x.dataset.kind===kind));
 };
})();
"""


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _metric(label: str, value: str, tone: str = "") -> str:
    return f"<div class='metric'><div class='label'>{label}</div><div class='value {tone}'>{value}</div></div>"


def _rank_table(rows: list[dict], kind: str) -> str:
    body = []
    for i, row in enumerate(rows, 1):
        metric = row.get("avg_pnl", 0) if kind == "paper" else row.get("avg_ann_return", 0)
        suffix = "$" if kind == "paper" else "%"
        shown = f"{suffix}{metric:,.2f}" if kind == "paper" else f"{metric:,.2f}{suffix}"
        body.append(
            f"<tr><td>{i}. {html.escape(str(row.get('strategy_slug') or 'Unknown'))}</td>"
            f"<td>{shown}</td><td>{row.get('avg_win_rate', 0):.1f}%</td></tr>")
    if not body:
        body.append("<tr><td colspan='3' class='muted'>No strategy results in this account yet.</td></tr>")
    return (
        f"<table class='contributors rank-table' data-kind='{kind}'"
        f"{' hidden' if kind != 'paper' else ''}><thead><tr><th>Strategy</th>"
        f"<th>{'PnL' if kind == 'paper' else 'Annual return'}</th><th>Win rate</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>")


def _advisor_cards(data: dict) -> str:
    reports = data.get("advisor_reports") or []
    if not reports:
        return (
            "<p class='ai-copy'>No post-close daily advisor report has been generated "
            "for this paper account yet.</p><p class='advisor-note'>Reports appear after "
            "the NYSE session close plus 15 minutes.</p>"
        )
    cards = []
    for report in reports:
        advisory = report.get("advisory") or {}
        evidence = report.get("evidence") or {}
        account = evidence.get("account") or {}
        paper = evidence.get("paper") or {}
        severity = str(report.get("severity") or "insufficient_data")
        drivers = "".join(
            f"<li><b>{html.escape(str(item.get('title') or 'Evidence'))}:</b> "
            f"{html.escape(str(item.get('detail') or ''))}</li>"
            for item in (advisory.get("drivers") or [])
        )
        recommendations = "".join(
            f"<li><b>{html.escape(str(item.get('title') or 'Review'))}:</b> "
            f"{html.escape(str(item.get('explanation') or item.get('rationale') or ''))} "
            "<em>(explicit approval required)</em></li>"
            for item in (advisory.get("recommendations") or [])
        )
        if not recommendations:
            no_change = advisory.get("why_no_change") or "No parameter change recommended."
            recommendations = f"<li>{html.escape(str(no_change))}</li>"
        warnings = "".join(
            f"<li>{html.escape(str(item))}</li>"
            for item in (advisory.get("data_warnings") or [])
        )
        parameter_guard = ""
        if advisory.get("recommendations") and advisory.get("why_no_change"):
            parameter_guard = (
                "<p><b>Parameter-change guard:</b> "
                f"{html.escape(str(advisory.get('why_no_change')))}</p>"
            )
        cards.append(f"""
        <article class="advisor-card {html.escape(severity)}">
          <div class="advisor-meta">{html.escape(str(account.get('account_name') or 'Paper account'))}
          · session {html.escape(str(report.get('session_date') or ''))}
          · status {html.escape(str(report.get('status') or 'unknown'))}
          · evidence {html.escape(str(paper.get('window_start') or 'n/a'))} to
          {html.escape(str(paper.get('window_end') or report.get('session_date') or ''))}</div>
          <h3>{html.escape(str(advisory.get('headline') or severity.replace('_', ' ').title()))}</h3>
          <p class="ai-copy">{html.escape(str(advisory.get('summary') or report.get('narrative') or ''))}</p>
          <p class="advisor-note">{html.escape(str(advisory.get('generation_note') or ''))}</p>
          <b>Performance drivers and evidence</b><ul>{drivers or '<li>No detailed drivers were available.</li>'}</ul>
          <b>Recommended next step</b><ul>{recommendations}</ul>
          {parameter_guard}
          {f'<b>Data-quality notes</b><ul>{warnings}</ul>' if warnings else ''}
          <p class="advisor-note">{html.escape(str(advisory.get('disclaimer') or 'Paper trading is simulated; every action requires approval.'))}</p>
        </article>""")
    history = "".join(
        f"<span>{html.escape(str(item.get('session_date') or ''))} · "
        f"{html.escape(str(item.get('severity') or '').replace('_', ' '))}</span>"
        for item in (data.get("advisor_history") or [])[:10]
    )
    return "".join(cards) + (
        f"<div class='advisor-history' aria-label='Advisor report history'>{history}</div>"
        if history else ""
    )


def _render(data: dict, selected_id: str | None) -> str:
    if data.get("needs_account"):
        return (
            "<div class='empty'><h1>Connect an Alpaca account</h1>"
            "<p class='muted'>Add an account to see equity, P&L and strategy performance.</p>"
            "<a href='/settings'>Connect account</a></div>")
    if "equity" not in data:
        errors = "".join(f"<p>{html.escape(e['message'])}</p>" for e in data.get("errors", []))
        return f"<div class='empty'><h1>Portfolio unavailable</h1><div class='error'>{errors}</div></div>"
    chosen = selected_id or data["account_id"]
    options = ["<option value='all'>All accounts</option>"] + [
        f"<option value='{a['account_id']}' {'selected' if chosen == a['account_id'] else ''}>"
        f"{html.escape(a['account_name'])}</option>" for a in data["accounts"]
    ]
    if chosen == "all":
        options[0] = "<option value='all' selected>All accounts</option>"
    period = data["period"]
    period_links = "".join(
        f"<a class='{'active' if p == period else ''}' href='/dashboard?account_id={chosen}&period={p}'>{p.title()}</a>"
        for p in ("daily", "weekly", "monthly"))
    pnl_tone = "positive" if data["period_pnl"] >= 0 else "negative"
    rows = "".join(
        f"<tr><td>{html.escape(str(r['symbol']))}</td><td class='{'positive' if r['pnl'] >= 0 else 'negative'}'>"
        f"{_money(r['pnl'])}</td><td>{_money(r['market_value'])}</td></tr>"
        for r in data["contributors"][:8]
    ) or "<tr><td colspan='3' class='muted'>No open contributors.</td></tr>"
    advisor_html = _advisor_cards(data)
    return f"""
      <div class="dash-head"><div><h1>Portfolio P&amp;L</h1>
      <div class="muted">{html.escape(data['account_name'])} · calendar {period} · updated {data['as_of'][:16].replace('T',' ') } UTC</div></div>
      <form class="dash-controls" method="get" action="/dashboard">
       <select name="account_id" aria-label="Portfolio account" onchange="this.form.submit()">{''.join(options)}</select>
       <input type="hidden" name="period" value="{period}"><div class="periods">{period_links}</div>
       <button class="dash-news" type="button" onclick="toggleNewsPane()">News</button>
       <a class="dash-signout" href="/logout">Sign out</a>
      </form></div>
      <div class="metric-grid">
       {_metric('Equity', _money(data['equity']))}
       {_metric(f'{period.title()} P&L', _money(data['period_pnl']), pnl_tone)}
       {_metric('Period return', f"{data['period_pct']:+.2f}%", pnl_tone)}
       {_metric('Unrealized P&L', _money(data['unrealized_pnl']), 'positive' if data['unrealized_pnl'] >= 0 else 'negative')}
       {_metric('Cash', _money(data['cash']))}{_metric('Buying power', _money(data['buying_power']))}
       {_metric('Accounts', str(len(data['accounts'])))}{_metric('Connection', data['environment'].title())}
      </div>
      <div class="panel-grid"><section class="panel"><h2>Equity curve</h2><div id="equity-chart" class="chart"></div></section>
       <section class="panel"><h2>Daily trading advisor</h2>{advisor_html}</section></div>
      <div class="panel-grid"><section class="panel"><h2>P&amp;L contributors</h2><div id="contrib-chart" class="chart"></div></section>
       <section class="panel"><div class="panel-head"><h2>Strategy rankings</h2>
       <span class="rank-tabs"><button class="active" data-kind="paper" onclick="showRanks('paper')">Paper</button>
       <button data-kind="backtest" onclick="showRanks('backtest')">Backtest</button></span></div>
       {_rank_table(data['paper_rankings'], 'paper')}{_rank_table(data['backtest_rankings'], 'backtest')}</section></div>
      <section class="panel" style="margin-top:.8rem"><h2>Top open-position contributors</h2>
       <table class="contributors"><thead><tr><th>Symbol</th><th>P&amp;L</th><th>Market value</th></tr></thead><tbody>{rows}</tbody></table></section>
    """


def register(app, rt):
    @rt("/dashboard")
    def dashboard(session, account_id: str = "", period: str = "daily"):
        user_id = session.get("user_id")
        if not user_id:
            return RedirectResponse("/signin", status_code=303)
        requested = account_id or session.get("dashboard_account_id")
        data = dashboard_data(str(user_id), requested, period)
        data["user_id"] = str(user_id)
        # Persist only an owned concrete account; "all" is intentionally opt-in.
        if data.get("account_id") and data["account_id"] != "all":
            session["dashboard_account_id"] = data["account_id"]
        selected = requested
        serializable = {k: data.get(k) for k in ("history", "contributors")}
        try:
            from engine.auth import get_user_by_id
            user = get_user_by_id(str(user_id))
        except Exception:  # noqa: BLE001
            user = None
        body = Div(
            NotStr(_render(data, selected)),
            NotStr(f"<script>window.__PNL_DASH__={json.dumps(serializable, default=str)};{_JS}</script>"),
            cls="dash",
        )
        return page("dashboard", Style(_CSS), body, user=user,
                    title="Portfolio P&L · AlpaTrade", right_news=True,
                    right_news_open=True)

    @rt("/pnl")
    def pnl_redirect():
        return RedirectResponse("/dashboard", status_code=303)

    return ["/dashboard", "/pnl"]

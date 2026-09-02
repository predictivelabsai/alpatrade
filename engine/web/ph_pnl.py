"""Authenticated, account-scoped portfolio P&L dashboard."""
from __future__ import annotations

import html
import json
from urllib.parse import quote as _urlquote

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.reporting.pnl_dashboard import dashboard_data
from engine.web import onboarding
from engine.web.ph_layout import page

_CSS = """
.dash{width:100%;max-width:1180px;margin:auto;padding:0 1rem 3rem}
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
.advisor-card h3 a{color:inherit;text-decoration:none}.advisor-card h3 a:hover{color:var(--accent)}
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
/* ---- Start Here checklist (progressive onboarding; retires when complete) ---- */
.start-here{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;
 padding:1.05rem 1.15rem .6rem;margin:0 0 .85rem;position:relative;overflow:hidden}
.start-here-head{display:flex;align-items:baseline;gap:.7rem;flex-wrap:wrap}
.start-here-head h2{font-size:1rem;margin:0}
.start-here-head .sh-sub{color:var(--ink-muted);font-size:.76rem}
.sh-progress{flex:1 1 7rem;height:3px;background:var(--bg-raise);border-radius:2px;min-width:5rem}
.sh-progress i{display:block;height:100%;background:var(--accent);border-radius:2px}
.sh-count{font-family:var(--font-mono);font-size:.7rem;color:var(--ink-dim);white-space:nowrap}
.sh-steps{display:flex;flex-direction:column;margin-top:.55rem}
.sh-step{display:flex;gap:.8rem;padding:.62rem .6rem;border-radius:.5rem;align-items:flex-start}
.sh-step.now{background:var(--accent-dim)}
.sh-num{flex:0 0 1.4rem;height:1.4rem;border-radius:50%;display:grid;place-items:center;
 font-family:var(--font-mono);font-size:.68rem;font-weight:600;margin-top:.05rem;
 border:1.5px solid var(--line-br);color:var(--ink-muted);background:var(--bg-elev)}
.sh-step.now .sh-num{border-color:var(--accent);color:var(--accent)}
.sh-step.done .sh-num{border:none;background:var(--accent);color:var(--bg-elev)}
.sh-step.done .sh-title{color:var(--ink-dim);text-decoration:line-through;
 text-decoration-color:var(--line-br);text-decoration-thickness:1px}
.sh-title{font-size:.88rem;font-weight:650;margin:0}
.sh-desc{font-size:.76rem;color:var(--ink-muted);margin:.12rem 0 0}
.sh-step.now .sh-title{color:var(--accent)}
.sh-actions{margin-top:.55rem;display:flex;gap:.55rem;flex-wrap:wrap;align-items:center}
.sh-btn{display:inline-block;background:var(--accent);color:var(--bg-elev);border-radius:.45rem;
 padding:.58rem 1rem;font-size:.82rem;font-weight:650;text-decoration:none;min-height:2.75rem;
 display:inline-flex;align-items:center}
.sh-btn:hover{background:var(--accent-deep);text-decoration:none}
.sh-btn.ghost{background:transparent;color:var(--accent);border:1px solid var(--accent);
 display:inline-flex;align-items:center;min-height:2.75rem;padding:.52rem .9rem}
.sh-btn.ghost:hover{background:var(--accent-dim);text-decoration:none}
.sh-hint{font-size:.72rem;color:var(--ink-dim)}
.sh-inline{color:var(--accent);font-weight:600;text-decoration:none;white-space:nowrap}
.sh-inline:hover{text-decoration:underline}
"""

_JS = """
(function(){
 const d=window.__PNL_DASH__; if(!d||!window.Plotly)return;
 const base={paper_bgcolor:'#fff',plot_bgcolor:'#f7f6f1',font:{family:'Inter,system-ui',color:'#2d352f'},
 margin:{t:12,r:15,b:42,l:62},showlegend:false};
 // Empty accounts render no chart elements (and history may be null); skip
 // plotting rather than crash, but keep the plots for accounts with points.
 if(d.history && document.getElementById('equity-chart'))
 Plotly.newPlot(document.getElementById('equity-chart'),[{x:d.history.timestamps,y:d.history.equity,type:'scatter',
 mode:'lines',line:{color:'#1f5d43',width:3},fill:'tozeroy',fillcolor:'rgba(31,93,67,.08)',
 hovertemplate:'%{x}<br>$%{y:,.2f}<extra></extra>'}],{...base,yaxis:{tickprefix:'$'}},
 {responsive:true,displayModeBar:false});
 const c=d.contributors||[];
 if(document.getElementById('contrib-chart'))
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
        if kind == "backtest":
            action = (f" <a class='sh-inline' href='{onboarding.autorun_url('agent:backtest lookback:3m')}'>"
                      f"Run your first backtest →</a>")
            body.append(
                "<tr><td colspan='3' class='muted'>No strategy results in this account yet."
                f"{action}</td></tr>")
        else:
            body.append(
                "<tr><td colspan='3' class='muted'>No paper sessions yet — backtest a "
                "strategy first, then trade it here.</td></tr>")
    return (
        f"<table class='contributors rank-table' data-kind='{kind}'"
        f"{' hidden' if kind != 'paper' else ''}><thead><tr><th>Strategy</th>"
        f"<th>{'PnL' if kind == 'paper' else 'Annual return'}</th><th>Win rate</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>")


def _start_here(state: dict) -> str:
    """Start Here checklist — state-derived, self-retiring.

    Every step's done-ness comes from a production-table query (see
    engine/web/onboarding.py); nothing is a dismissible banner. The card
    disappears entirely once all three steps have cleared, leaving the
    P&L view to stand on its own.
    """
    steps = []  # each entry: (title, desc, state, num, actions)

    # Step 1 — brokerage connected (own keys vs shared paper fallback).
    if state["keys"]:
        steps.append(("Connect your brokerage",
                      "Alpaca keys connected and trading under your login.",
                      "done", "1", ""))
    else:
        actions = (
            "<div class='sh-actions'>"
            "<a class='sh-btn ghost' href='/settings'>Add your own keys</a>"
            "<span class='sh-hint'>Paper keys active — you're trading test money "
            "until you connect live keys.</span>"
            "</div>"
        )
        steps.append(("Connect your brokerage",
                      "Link your Alpaca account so every trade is yours.",
                      "now", "1", actions))

    # Step 2 — first backtest.
    if state["backtests"]:
        steps.append(("Run your first backtest",
                      "Grid-searched a strategy against real market data.",
                      "done", "2", ""))
    else:
        run_url = onboarding.autorun_url("agent:backtest lookback:3m")
        draft_url = onboarding.autorun_url("agent:backtest symbols:", draft=True)
        actions = (
            "<div class='sh-actions'>"
            f"<a class='sh-btn' href='{run_url}'>Run backtest for me</a>"
            f"<a class='sh-btn ghost' href='{draft_url}'>I'll choose symbols</a>"
            "<a class='sh-btn ghost' href='/backtests'>Strategy presets →</a>"
            "<span class='sh-hint'>Defaults: AAPL, MSFT, NVDA, TSLA · 3 months"
            " — or start from a curated preset on the backtests page.</span>"
            "</div>"
        )
        steps.append(("Run your first backtest",
                      "One click with sensible defaults — tune everything after.",
                      "now", "2", actions))

    # Step 3 — paper deployment.
    if state["paper"]:
        steps.append(("Deploy a strategy to paper",
                      "A backtested config is live on the Alpaca paper API.",
                      "done", "3", ""))
    elif state["latest"]:
        cmd = onboarding.paper_deploy_command(state["latest"])
        metrics = ""
        lr = state["latest"]
        if lr.get("total_return") is not None:
            metrics = (f"Best run: {html.escape(str(lr.get('strategy_slug') or 'result'))}"
                       f" · {float(lr['total_return']):+.1f}% return"
                       + (f", {float(lr['max_drawdown']):.1f}% max drawdown"
                          if lr.get("max_drawdown") is not None else ""))
        if cmd:
            actions = (
                f"<div class='sh-actions'><a class='sh-btn' "
                f"href='{onboarding.autorun_url(cmd)}'>Deploy to paper →</a>"
                f"<span class='sh-hint'>{metrics}</span></div>"
            )
            steps.append(("Trade your best result on paper",
                          "The strongest config from your latest backtest, ready to go live.",
                          "now", "3", actions))
        else:
            draft_url = onboarding.autorun_url("agent:paper duration:7d", draft=True)
            steps.append(("Trade a strategy on paper",
                          "Open a paper session and pick the strategy in chat.",
                          "now", "3",
                          ("<div class='sh-actions'>"
                           f"<a class='sh-btn ghost' href='{draft_url}'>"
                           "Start paper trading →</a></div>")))
    else:
        steps.append(("Deploy to paper",
                      "Backtest first — this becomes your deploy step right after.",
                      "later", "3", ""))

    done_steps = sum(1 for _, _, s, _, _ in steps if s == "done")
    pct = int(round(100 * done_steps / 3))
    rows = []
    for title, desc, s, num, actions in steps:
        cls = "sh-step" + (f" {s}" if s else "")
        aria = ' aria-current="step"' if s == "now" else ""
        marker = "✓" if s == "done" else num
        rows.append(
            f"<div class='sh-step {s}'{aria}>"
            f"<div class='sh-num' aria-hidden='true'>{marker}</div>"
            f"<div><p class='sh-title'>{title}</p><p class='sh-desc'>{desc}</p>{actions}</div>"
            f"</div>"
        )
    return (
        "<section class='start-here' aria-label='Getting started'>"
        "<div class='start-here-head'><h2>Start here</h2>"
        "<span class='sh-progress' aria-hidden='true'>"
        f"<i style='width:{pct}%'></i></span>"
        f"<span class='sh-count'>{done_steps} of 3 done</span>"
        "<span class='sh-sub'>Test a strategy on real data, then trade it on paper.</span>"
        "</div>"
        f"<div class='sh-steps'>{''.join(rows)}</div>"
        "</section>"
    )


def _advisor_cards(data: dict) -> str:
    reports = data.get("advisor_reports") or []
    if not reports:
        return (
            "<p class='ai-copy'>No post-close daily advisor report has been generated "
            "for this paper account yet.</p><p class='advisor-note'>Reports appear after "
            "the NYSE session close plus 15 minutes — the full history lives on the "
            "<a href='/advisor'>daily advisor page</a>.</p>"
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
          <h3><a href="/advisor?report={_urlquote(str(report.get('report_id') or ''))}">{html.escape(str(advisory.get('headline') or severity.replace('_', ' ').title()))}</a></h3>
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
            "<p class='muted'>Add an account to see equity, P&amp;L and strategy "
            "performance — and to trade the strategies you've backtested.</p>"
            "<p class='muted'>No keys yet? Link your Alpaca paper account from "
            "Settings first; you can decide about live keys whenever you're ready.</p>"
            "<a href='/settings'>Connect account</a></div>")
    if "equity" not in data:
        errors = "".join(f"<p>{html.escape(e['message'])}</p>" for e in data.get("errors", []))
        cta = ""
        if any("unauthorized" in str(e.get("message", "")).lower() for e in data.get("errors", [])):
            cta = ("<p style='margin:.9rem 0 0'><a href='/settings'>"
                   "Update your Alpaca keys →</a></p>")
        return f"<div class='empty'><h1>Portfolio unavailable</h1><div class='error'>{errors}</div>{cta}</div>"
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
    checklist = ""
    state = data.get("start_here") or {}
    if not all((state.get("keys"), state.get("backtests"), state.get("paper"))):
        try:
            checklist = _start_here(state)
        except Exception:  # noqa: BLE001
            checklist = ""  # never let onboarding break the P&L page
    return f"""
      {checklist}
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
        uid = str(user_id)
        # Start Here checklist — read-only state queries; any failure just
        # hides the card rather than breaking the dashboard.
        try:
            data["start_here"] = {
                "keys": onboarding.has_linked_account(uid),
                "backtests": onboarding.has_backtests(uid),
                "paper": onboarding.has_paper_activity(uid),
                "latest": onboarding.latest_backtest_config(uid),
            }
        except Exception:  # noqa: BLE001
            data["start_here"] = {}
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

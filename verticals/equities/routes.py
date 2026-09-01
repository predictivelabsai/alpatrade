"""Equities vertical routes — mounted under /equities/* by app.py.

Reuses the extracted engine layers: engine.brokers.alpaca (account/positions),
engine.backtest (the Alpaca-skill methodology backtester), and the report agent
(recent runs). Rendered in the shared house-style shell.
"""
from __future__ import annotations

from datetime import datetime

from fasthtml.common import (
    A, Button, Div, Form, H2, H3, Input, Label, Option, P, Select, Span, Style,
    Table, Tbody, Td, Th, Thead, Tr, NotStr,
)
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page

_EQUITIES_CSS = """
.equities{max-width:960px;margin:0 auto;width:100%;padding:0 1rem 3rem}
.equities h2{font-size:1.2rem;margin:.4rem 0 .9rem;color:var(--ink)}
.equities .card{background:var(--bg-elev);border:1px solid var(--line);
  border-radius:.7rem;padding:1rem 1.2rem;margin-bottom:1.2rem}
.equities .kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.8rem}
.equities .kpi .v{font-size:1.25rem;font-weight:700;color:var(--ink)}
.equities .kpi .l{font-size:.72rem;color:var(--ink-dim);margin-top:.15rem}
.equities .muted{font-size:.82rem;color:var(--ink-muted)}
.equities .notice{border-radius:.5rem;padding:.6rem .8rem;font-size:.82rem;margin-bottom:1rem}
.equities .notice.err{background:rgba(176,101,63,.12);color:#b0653f}
.equities table{width:100%;border-collapse:collapse;font-size:.82rem;color:var(--ink)}
.equities th{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;
  color:var(--ink-dim);text-align:left;padding:.4rem .5rem;border-bottom:1px solid var(--line)}
.equities td{padding:.45rem .5rem;border-bottom:1px solid var(--line)}
.equities td.right,.equities th.right{text-align:right}
.equities td.pos{color:var(--green,#2e7d32)}
.equities td.neg{color:var(--red,#b0653f)}
.equities .formrow{display:flex;flex-direction:column;gap:.25rem;margin-bottom:.7rem}
.equities .formrow label{font-size:.74rem;color:var(--ink-muted);font-weight:600}
.equities .formrow input,.equities .formrow select{font-size:.86rem;color:var(--ink);
  background:var(--bg);border:1px solid var(--line-br);border-radius:.45rem;padding:.5rem .6rem}
.equities .btn{font-size:.85rem;color:var(--bg);background:var(--accent);border:0;
  border-radius:.45rem;padding:.55rem 1.1rem;cursor:pointer;margin-top:.3rem}
.equities .btn:hover{opacity:.92}
"""


# --- data helpers -----------------------------------------------------------

def _account_kpis(user):
    """Account KPI boxes from the viewer's own linked Alpaca paper account.

    Returns ``(boxes, positions, error)``; ``boxes is None`` means no keys are
    linked (render the connect-your-keys card instead of falling back to the
    shared server keys).
    """
    try:
        from engine.auth import get_alpaca_keys
        keys = get_alpaca_keys(user["user_id"])
        if not keys:
            return None, [], None
        from engine.brokers.alpaca import AlpacaAPI
        api = AlpacaAPI(api_key=keys[0], secret_key=keys[1], paper=True)
        a = api.get_account()
        positions = api.get_positions() or []
        boxes = [
            ("Equity", f"${float(a.get('equity', 0)):,.0f}"),
            ("Cash", f"${float(a.get('cash', 0)):,.0f}"),
            ("Buying power", f"${float(a.get('buying_power', 0)):,.0f}"),
            ("Open positions", str(len(positions))),
        ]
        return boxes, positions, None
    except Exception as e:  # noqa: BLE001
        return [], [], str(e)


def _recent_runs(limit=12):
    try:
        from agents.report_agent import ReportAgent
        return ReportAgent().summary(limit=limit), None
    except Exception as e:  # noqa: BLE001
        return [], str(e)


def _kpi_row(boxes):
    return Div(*[Div(Div(v, cls="v"), Div(l, cls="l")) for l, v in boxes], cls="kpi")


def _positions_table(positions):
    if not positions:
        return P("No open positions.", cls="muted")
    rows = []
    for p in positions:
        upl = float(p.get("unrealized_pl", 0) or 0)
        cls = "pos" if upl >= 0 else "neg"
        rows.append(Tr(
            Td(p.get("symbol", "")),
            Td(str(p.get("qty", "")), cls="right"),
            Td(f"${float(p.get('avg_entry_price', 0) or 0):,.2f}", cls="right"),
            Td(f"${float(p.get('current_price', 0) or 0):,.2f}", cls="right"),
            Td(f"${upl:,.2f}", cls=f"right {cls}"),
        ))
    return Table(
        Thead(Tr(Th("Symbol"), Th("Qty", cls="right"), Th("Avg", cls="right"),
                 Th("Price", cls="right"), Th("Unreal. P&L", cls="right"))),
        Tbody(*rows),
    )


def _runs_table(runs):
    if not runs:
        return P("No runs yet. Run a backtest to populate this.", cls="muted")
    rows = []
    for r in runs:
        ret = r.get("total_return")
        ret_txt = f"{float(ret):.2f}%" if ret is not None else "—"
        cls = "pos" if (ret or 0) >= 0 else "neg"
        rows.append(Tr(
            Td(NotStr(f"<code>{str(r.get('run_id',''))[:8]}</code>")),
            Td(r.get("mode", "")),
            Td(r.get("strategy_slug") or r.get("strategy") or ""),
            Td(r.get("status", "")),
            Td(ret_txt, cls=f"right {cls}"),
            Td(str(r.get("total_trades") or r.get("paper_trades") or ""), cls="right"),
        ))
    return Table(
        Thead(Tr(Th("Run"), Th("Mode"), Th("Strategy"), Th("Status"),
                 Th("Return", cls="right"), Th("Trades", cls="right"))),
        Tbody(*rows),
    )


# --- views ------------------------------------------------------------------

def _connect_keys_card():
    return Div(
        H3("Connect your Alpaca keys"),
        P("Add your own Alpaca paper API keys to see account equity, positions "
          "and run this vertical's backtester. Paper trading only.", cls="muted"),
        P(A("Connect keys →", href="/settings", cls="btn"), style="margin-top:.6rem"),
        cls="card",
    )


def _dashboard(user):
    boxes, positions, acct_err = _account_kpis(user)
    runs, runs_err = _recent_runs()
    center = [H2("Equities — Dashboard")]
    if acct_err:
        center.append(Div(f"Alpaca account unavailable: {acct_err}", cls="notice err"))
    elif boxes is None:
        center.append(_connect_keys_card())
    else:
        center.append(Div(_kpi_row(boxes), cls="card"))
        center.append(Div(H3("Open positions"), _positions_table(positions), cls="card"))
    if runs_err:
        center.append(Div(f"Runs unavailable: {runs_err}", cls="notice err"))
    else:
        center.append(Div(H3("Recent runs"), _runs_table(runs), cls="card"))
    return page("equities", Style(_EQUITIES_CSS), *center, user=user,
                title="AlpaTrade · Equities", right_news=False)


def _backtest_form(user, result_block=None):
    form = Form(
        Div(Label("Symbols"), Input(name="symbols", value="AAPL,MSFT"), cls="formrow"),
        Div(
            Div(Label("Start"), Input(name="start", value="2024-01-01", type="date"), cls="formrow"),
            Div(Label("End"), Input(name="end", value="2024-06-30", type="date"), cls="formrow"),
            style="display:flex;gap:1rem",
        ),
        Div(
            Div(Label("Dip %"), Input(name="dip_threshold", value="0.03", type="number", step="0.01"), cls="formrow"),
            Div(Label("Take-profit %"), Input(name="take_profit", value="0.04", type="number", step="0.01"), cls="formrow"),
            Div(Label("Stop-loss %"), Input(name="stop_loss", value="0.03", type="number", step="0.01"), cls="formrow"),
            Div(Label("Hold days"), Input(name="hold_days", value="5", type="number"), cls="formrow"),
            style="display:flex;gap:1rem;flex-wrap:wrap",
        ),
        Div(Label("Fill model"),
            Select(Option("next_open", value="next_open"), Option("same_bar", value="same_bar"),
                   name="fill_model"), cls="formrow"),
        Button("Run backtest", cls="btn", type="submit"),
        method="post", action="/equities/backtest",
    )
    center = [H2("Equities — Backtest"),
              P("Deterministic Alpaca-data backtest using the Alpaca-skill methodology "
                "(Teaching Five + reproducible artifact folder).", cls="muted"),
              Div(form, cls="card")]
    if result_block is not None:
        center.append(result_block)
    return page("equities", Style(_EQUITIES_CSS), *center, user=user,
                title="AlpaTrade · Backtest", right_news=False)


def _teaching_five_block(res):
    t5 = res.teaching_five

    def pct(x):
        return f"{x*100:.2f}%"
    boxes = [
        ("Total return", pct(t5["total_return"])),
        ("Benchmark", pct(t5["benchmark_total_return"])),
        ("Max drawdown", pct(t5["max_drawdown"])),
        ("Trades", str(t5["trades"])),
        ("Win rate", pct(t5["win_rate"])),
        ("Sharpe", f"{t5['sharpe']:.2f}"),
    ]
    return Div(
        H3("Result — Teaching Five"),
        _kpi_row(boxes),
        P(NotStr(f"Artifacts written to <code>{res.folder}</code> "
                 f"(report.md, trades.csv, equity.csv, data_fingerprint.json, run.py)."),
          cls="muted", style="margin-top:.8rem"),
        cls="card",
    )


def register(app, rt, current_user):
    """Attach equities routes to the FastHTML app. `current_user(session)->dict|None`."""

    def guard(session):
        return current_user(session)

    @rt("/equities")
    def equities_home(session):
        user = guard(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        return _dashboard(user)

    @rt("/equities/backtest", methods=["GET"])
    def equities_backtest_get(session):
        user = guard(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        return _backtest_form(user)

    @app.post("/equities/backtest")
    async def equities_backtest_post(session, request):
        user = guard(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        try:
            from engine.backtest.runner import run_backtest
            res = run_backtest(
                symbols=[s.strip().upper() for s in form.get("symbols", "AAPL").split(",") if s.strip()],
                start=datetime.fromisoformat(form.get("start", "2024-01-01")),
                end=datetime.fromisoformat(form.get("end", "2024-06-30")),
                strategy_params={
                    "dip_threshold": float(form.get("dip_threshold", 0.03)),
                    "take_profit": float(form.get("take_profit", 0.04)),
                    "stop_loss": float(form.get("stop_loss", 0.03)),
                    "hold_days": int(form.get("hold_days", 5)),
                },
                fill_model=form.get("fill_model", "next_open"),
                request="equities web backtest",
            )
            return _backtest_form(user, _teaching_five_block(res))
        except Exception as e:  # noqa: BLE001
            return _backtest_form(user, Div(f"Backtest failed: {e}", cls="notice err"))

    @rt("/equities/runs")
    def equities_runs(session):
        user = guard(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        runs, err = _recent_runs(limit=30)
        center = [H2("Equities — Runs")]
        center.append(Div(f"Runs unavailable: {err}", cls="notice err") if err
                      else Div(_runs_table(runs), cls="card"))
        return page("equities", Style(_EQUITIES_CSS), *center, user=user,
                    title="AlpaTrade · Runs", right_news=False)

    @app.post("/equities/assistant")
    async def equities_assistant(session, request):
        user = guard(session)
        if not user:
            return "Please log in."
        form = await request.form()
        q = (form.get("q") or "").strip().lower()
        return _assistant_answer(q)


def _assistant_answer(q: str) -> str:
    """Lightweight keyless assistant for the rail (full LangGraph chat lands later)."""
    if q in ("help", "", "?"):
        return ("<b>Try:</b> <code>runs</code>, <code>trades</code>, <code>report</code>. "
                "Use the Backtest page to run the Alpaca-skill methodology backtester.")
    try:
        from agents.report_agent import ReportAgent
        ra = ReportAgent()
        if q.startswith("run"):
            rows = ra.summary(limit=8)
            if not rows:
                return "No runs yet."
            out = "<b>Recent runs</b><br>" + "<br>".join(
                f"<code>{str(r.get('run_id',''))[:8]}</code> {r.get('mode','')} "
                f"{r.get('strategy_slug') or r.get('strategy') or ''} — {r.get('status','')}"
                for r in rows)
            return out
        if q.startswith("trade") or q.startswith("report"):
            rows = ra.summary(trade_type=("paper" if q.startswith("trade") else None), limit=8)
            if not rows:
                return "No data yet."
            return "<b>Summary</b><br>" + "<br>".join(
                f"<code>{str(r.get('run_id',''))[:8]}</code> {r.get('mode','')} "
                f"return={r.get('total_return','—')} trades={r.get('total_trades') or r.get('paper_trades') or 0}"
                for r in rows)
    except Exception as e:  # noqa: BLE001
        return f"assistant error: {e}"
    return (f"I can answer <code>runs</code>, <code>trades</code>, <code>report</code>, or "
            f"<code>help</code>. (You asked: {q!r})")

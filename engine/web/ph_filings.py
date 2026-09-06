"""SEC Filings page — EDGAR full-text search + company filing history.

Backend: engine.publicmarkets.edgar (no DB). Parchment/forest shell.
Feature-module contract: register(app, rt).
"""
from __future__ import annotations

from fasthtml.common import A, Button, Div, Form, Input, NotStr, Option, P, Select, Span, Style, Table, Tbody, Td, Th, Thead, Tr

from engine.web.ph_layout import page

_CSS = """

.filings{max-width:960px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.filings h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.filings .f-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.filings form{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.2rem}
.filings input,.filings select{font-family:var(--font-body);font-size:.86rem;color:var(--ink);
  background:var(--bg);border:1px solid var(--line-br);border-radius:.45rem;padding:.5rem .6rem}
.filings input[name=q]{flex:1;min-width:14rem}
.filings .f-btn{font-size:.85rem;color:var(--bg);background:var(--accent);border:0;
  border-radius:.45rem;padding:.55rem 1.1rem;cursor:pointer}
.filings table{border-collapse:collapse;width:100%;font-size:.82rem}
.filings th,.filings td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.filings thead{background:var(--bg-raise)}
.filings a{color:var(--accent)}
@media(max-width:600px){
  .filings{padding-left:.75rem;padding-right:.75rem}
  .filings input[name=q]{min-width:0;width:100%;flex-basis:100%}
  .filings .f-btn{min-height:44px}
  .filings-table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .filings table{min-width:38rem}
}
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


def _table(rows):
    trs = [Tr(Td(r.get("form_type", "")), Td(r.get("entity_name", "")), Td(r.get("filing_date", "")),
              Td(A("view", href=r.get("file_url", r.get("url", "#")), target="_blank")))
           for r in rows]
    return Div(Table(Thead(Tr(Th("Form"), Th("Entity"), Th("Date"), Th("Doc"))), Tbody(*trs)),
               cls="filings-table-scroll")


def _results(q, ticker, forms, start_date, end_date, sort):
    from engine.publicmarkets import edgar
    if ticker and not q:
        data = edgar.get_company_filings(ticker, form_type=forms, limit=30)
        rows = data.get("filings", [])
        if data.get("error"):
            return P(data["error"], cls="f-sub")
        head = data.get("company_name", ticker)
        rows = [{**filing, "entity_name": head, "file_url": filing.get("url", "")}
                for filing in rows]
        rows = edgar._sort_filings(rows, sort)
        return Div(P(f"Recent filings — {head}", cls="f-sub"),
                   _table(rows))
    if not q:
        data = edgar.latest_filings(forms=forms, limit=30)
        label = "Latest SEC filings"
    else:
        data = edgar.search_filings(q, forms=forms, ticker=ticker, start_date=start_date,
                                    end_date=end_date, limit=30, sort=sort)
        label = f"{data.get('total', 0)} results for “{q}”"
    if data.get("error"):
        return P(data["error"], cls="f-sub")
    return Div(P(label, cls="f-sub"), _table(data.get("results", [])))


def _page(user, q="", ticker="", forms="", start_date="", end_date="", sort="latest"):
    form = Form(
        Input(name="q", placeholder="Full-text search (e.g. 'going concern')", value=q),
        Input(name="ticker", placeholder="Ticker (optional)", value=ticker, style="width:10rem"),
        Select(Option("Any form", value="", selected=not forms),
               *[Option(f, value=f, selected=(f == forms)) for f in ("10-K", "10-Q", "8-K", "S-1", "DEF 14A", "13F-HR")],
               name="forms"),
        Input(name="start_date", type="date", value=start_date, aria_label="Filed after"),
        Input(name="end_date", type="date", value=end_date, aria_label="Filed before"),
        Select(Option("Latest first", value="latest", selected=sort == "latest"),
               Option("Oldest first", value="oldest", selected=sort == "oldest"),
               Option("Entity A–Z", value="entity", selected=sort == "entity"),
               Option("Form A–Z", value="form", selected=sort == "form"), name="sort"),
        Button("Search", type="submit", cls="f-btn"),
        method="get", action="/filings",
    )
    body = Div(NotStr("<h1>📄 SEC Filings</h1>"),
               P("EDGAR full-text search and company filing history.", cls="f-sub"),
               form, _results(q, ticker, forms, start_date, end_date, sort), cls="filings")
    return page("filings", Style(_CSS), body, user=user, title="SEC Filings · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    if ("📄 SEC Filings", "/filings", "filings") not in ph_layout.TOOLS_PAGES:
        ph_layout.TOOLS_PAGES.append(("📄 SEC Filings", "/filings", "filings"))

    @rt("/filings", methods=["GET"])
    def filings_get(session, q: str = "", ticker: str = "", forms: str = "",
                    start_date: str = "", end_date: str = "", sort: str = "latest"):
        return _page(_user(session), q=q, ticker=ticker, forms=forms,
                     start_date=start_date, end_date=end_date, sort=sort)

    return ["/filings"]

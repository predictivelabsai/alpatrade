"""Press Releases page — search the shared public.news feed. register(app, rt)."""
from __future__ import annotations

from fasthtml.common import A, Button, Div, Form, Input, NotStr, Option, P, Select, Span, Style, Table, Tbody, Td, Th, Thead, Tr

from engine.web.ph_layout import page

_CSS = """

.press{max-width:1000px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.press h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.press .p-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.press form{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.2rem}
.press input{font-family:var(--font-body);font-size:.86rem;color:var(--ink);background:var(--bg);
  border:1px solid var(--line-br);border-radius:.45rem;padding:.5rem .6rem}
.press input[name=q]{flex:1;min-width:14rem}
.press .p-btn{font-size:.85rem;color:var(--bg);background:var(--accent);border:0;border-radius:.45rem;
  padding:.55rem 1.1rem;cursor:pointer}
.press table{border-collapse:collapse;width:100%;font-size:.82rem}
.press th,.press td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.press thead{background:var(--bg-raise)}
.press a{color:var(--accent)}
.side-up{color:var(--accent)} .side-down{color:#b0653f}
@media(max-width:600px){
  .press{padding-left:.75rem;padding-right:.75rem}
  .press input[name=q]{min-width:0;width:100%;flex-basis:100%}
  .press .p-btn{min-height:44px}
  .press-table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .press table{min-width:38rem}
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


def _results(q, ticker, company="", event="", side="", date_from="", date_to=""):
    from engine.publicmarkets.news import search_news
    rows = search_news(q, ticker, limit=40, company=company, event=event,
                       predicted_side=side, date_from=date_from, date_to=date_to)
    if not rows:
        return P("No press releases found — try a ticker or a headline keyword.", cls="p-sub")
    trs = []
    for r in rows:
        side = (r["predicted_side"] or "").lower()
        title = A(r["title"] or "", href=r["link"] or "#", target="_blank") if r["link"] else (r["title"] or "")
        move = "" if r["predicted_move"] is None else f"{r['predicted_move']:+.2f}%"
        trs.append(Tr(Td(r["published"][:10]), Td(r["company"] or ""), Td(r["ticker"] or ""),
                      Td(r["publisher"] or ""), Td(r["event"] or ""), Td(title),
                      Td(Span(r["predicted_side"] or "",
                              cls="side-up" if side == "up" else ("side-down" if side == "down" else ""))),
                      Td(move), Td(r.get("reason") or "")))
    return Div(Table(Thead(Tr(Th("Date"), Th("Company"), Th("Ticker"), Th("Publisher"),
                              Th("Event"), Th("English headline"), Th("Side"), Th("Move"), Th("XAI reason"))),
                     Tbody(*trs)), cls="press-table-scroll")


def _page(user, q="", ticker="", company="", event="", side="", date_from="", date_to=""):
    form = Form(
        Input(name="q", placeholder="Headline keyword (e.g. 'earnings', 'guidance')", value=q),
        Input(name="ticker", placeholder="Ticker (optional)", value=ticker, style="width:10rem"),
        Input(name="company", placeholder="Company", value=company),
        Input(name="event", placeholder="Event", value=event),
        Select(Option("Any side", value=""), *[Option(v, value=v, selected=side.upper() == v) for v in ("UP", "DOWN", "NEUTRAL")], name="side"),
        Input(name="date_from", type="date", value=date_from, title="From date"),
        Input(name="date_to", type="date", value=date_to, title="To date"),
        Button("Search", type="submit", cls="p-btn"),
        method="get", action="/press",
    )
    body = Div(NotStr("<h1>📰 Press Releases</h1>"),
               P("Company news & press releases with a modeled directional read.", cls="p-sub"),
               form, _results(q, ticker, company, event, side, date_from, date_to), cls="press")
    return page("press", Style(_CSS), body, user=user, title="Press Releases · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("📰 Press Releases", "/press", "press")
    if entry not in ph_layout.TOOLS_PAGES:
        ph_layout.TOOLS_PAGES.append(entry)

    @rt("/press", methods=["GET"])
    def press_get(session, q: str = "", ticker: str = "", company: str = "", event: str = "",
                  side: str = "", date_from: str = "", date_to: str = ""):
        return _page(_user(session), q, ticker, company, event, side, date_from, date_to)

    return ["/press"]

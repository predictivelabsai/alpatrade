"""Press Releases page — search the shared public.news feed. register(app, rt)."""
from __future__ import annotations

from fasthtml.common import A, Button, Div, Form, Input, NotStr, P, Span, Style, Table, Tbody, Td, Th, Thead, Tr

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}
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


def _results(q, ticker):
    from engine.publicmarkets.news import search_news
    rows = search_news(q, ticker, limit=40)
    if not rows:
        return P("No press releases found — try a ticker or a headline keyword.", cls="p-sub")
    trs = []
    for r in rows:
        side = (r["predicted_side"] or "").lower()
        title = A(r["title"] or "", href=r["link"] or "#", target="_blank") if r["link"] else (r["title"] or "")
        trs.append(Tr(Td(r["published"][:10]), Td(r["ticker"] or ""), Td(title),
                      Td(Span(r["predicted_side"] or "",
                              cls="side-up" if side == "up" else ("side-down" if side == "down" else "")))))
    return Table(Thead(Tr(Th("Date"), Th("Ticker"), Th("Headline"), Th("Side"))), Tbody(*trs))


def _page(user, q="", ticker=""):
    form = Form(
        Input(name="q", placeholder="Headline keyword (e.g. 'earnings', 'guidance')", value=q),
        Input(name="ticker", placeholder="Ticker (optional)", value=ticker, style="width:10rem"),
        Button("Search", type="submit", cls="p-btn"),
        method="get", action="/press",
    )
    body = Div(NotStr("<h1>📰 Press Releases</h1>"),
               P("Company news & press releases with a modeled directional read.", cls="p-sub"),
               form, _results(q, ticker), cls="press")
    return page("press", Style(_CSS), body, user=user, title="Press Releases · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("📰 Press Releases", "/press", "press")
    if entry not in ph_layout.TOOLS_PAGES:
        ph_layout.TOOLS_PAGES.append(entry)

    @rt("/press", methods=["GET"])
    def press_get(session, q: str = "", ticker: str = ""):
        return _page(_user(session), q=q, ticker=ticker)

    return ["/press"]

"""SPACs page — screener over the shared liquidround.spac_data. register(app, rt)."""
from __future__ import annotations

from fasthtml.common import Div, Form, Input, NotStr, Option, P, Select, Style, Table, Tbody, Td, Th, Thead, Tr

from engine.web.ph_layout import page

_CSS = """

.spacs{max-width:1080px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.spacs h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.spacs .s-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.spacs table{border-collapse:collapse;width:100%;font-size:.82rem}
.spacs th,.spacs td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.spacs thead{background:var(--bg-raise)}
.spac-controls{display:grid;grid-template-columns:minmax(180px,2fr) repeat(2,minmax(150px,1fr)) auto;gap:.6rem;margin:0 0 1rem}
.spac-controls input,.spac-controls select,.spac-controls button{min-height:2.5rem;padding:.45rem .6rem;border:1px solid var(--line);border-radius:.45rem;background:var(--bg-elev);color:var(--ink);font:inherit;font-size:.8rem}
.spac-controls button{background:var(--accent);color:var(--bg);cursor:pointer;font-weight:600}
.spac-table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:.6rem}
.spac-meta{font-size:.72rem;color:var(--ink-dim);margin:-.5rem 0 .7rem}
.prem-pos{color:var(--accent)} .prem-neg{color:#b0653f}
@media(max-width:700px){.spac-controls{grid-template-columns:1fr 1fr}.spac-controls input{grid-column:1/-1}}
@media(max-width:460px){.spac-controls{grid-template-columns:1fr}}
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


def _page(user, q: str = "", status: str = "", sort: str = "trust"):
    from engine.publicmarkets.spacs import spac_list
    rows = spac_list(limit=100)
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in " ".join(str(r.get(key) or "")
                for key in ("ticker", "company", "sponsor", "target", "exchange")).lower()]
    if status:
        rows = [r for r in rows if status.lower() in str(r["status"] or "").lower()]
    if sort == "price":
        rows.sort(key=lambda r: r["price"] is None, reverse=False)
        rows.sort(key=lambda r: r["price"] or 0, reverse=True)
    elif sort == "premium":
        rows.sort(key=lambda r: r["nav_premium_pct"] is None, reverse=False)
        rows.sort(key=lambda r: r["nav_premium_pct"] or 0, reverse=True)
    elif sort == "company":
        rows.sort(key=lambda r: (r["company"] or "").lower())
    else:
        rows.sort(key=lambda r: r["trust_size"] or 0, reverse=True)

    def _b(v):
        return f"${v/1e6:.0f}M" if v else "—"
    trs = []
    for r in rows:
        p = r["nav_premium_pct"]
        prem = "—" if p is None else NotStr(
            f'<span class="{"prem-pos" if p >= 0 else "prem-neg"}">{p:+.1f}%</span>')
        trs.append(Tr(Td(r["ticker"] or ""), Td((r["company"] or "")[:26]),
                      Td((r["sponsor"] or "")[:22]), Td(r["status"] or ""),
                      Td(_b(r["trust_size"])),
                      Td(f"${r['price']:,.2f}" if r["price"] else "—"),
                      Td(prem), Td((r["target"] or "—")[:24])))
    body = Div(
        NotStr("<h1>🔀 SPACs</h1>"),
        P("Special-purpose acquisition companies — trust size, NAV premium, status, targets.", cls="s-sub"),
        Form(
            Input(name="q", value=q, type="search", placeholder="Search ticker, company, sponsor, target…",
                  aria_label="Search SPACs"),
            Select(Option("All statuses", value=""), Option("Searching", value="searching"),
                   Option("Target announced", value="target"), Option("Completed", value="completed"),
                   name="status", value=status, aria_label="Filter SPAC status"),
            Select(Option("Largest trust", value="trust"), Option("Highest price", value="price"),
                   Option("Highest NAV premium", value="premium"), Option("Company A–Z", value="company"),
                   name="sort", value=sort, aria_label="Sort SPACs"),
            NotStr('<button type="submit">Apply</button>'),
            method="get", action="/spacs", cls="spac-controls",
        ),
        P(f"{len(rows)} matching SPACs · prices and NAV premium are refreshed from market data.", cls="spac-meta"),
        Div(Table(Thead(Tr(Th("Ticker"), Th("Company"), Th("Sponsor"), Th("Status"),
                       Th("Trust"), Th("Price"), Th("NAV prem."), Th("Target"))),
              Tbody(*trs)), cls="spac-table-wrap"),
        cls="spacs",
    )
    return page("spacs", Style(_CSS), body, user=user, title="SPACs · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("🔀 SPACs", "/spacs", "spacs")
    if entry not in ph_layout.TOOLS_PAGES:
        ph_layout.TOOLS_PAGES.append(entry)

    @rt("/spacs", methods=["GET"])
    def spacs_get(session, q: str = "", status: str = "", sort: str = "trust"):
        return _page(_user(session), q=q, status=status, sort=sort)

    return ["/spacs"]

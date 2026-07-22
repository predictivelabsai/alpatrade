"""SPACs page — screener over the shared liquidround.spac_data. register(app, rt)."""
from __future__ import annotations

from fasthtml.common import Div, NotStr, P, Style, Table, Tbody, Td, Th, Thead, Tr

from engine.web.ph_layout import page

_CSS = """
.app{padding-right:0}
.spacs{max-width:1080px;margin:0 auto;width:100%;padding:0 1rem 2.5rem}
.spacs h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.spacs .s-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1rem}
.spacs table{border-collapse:collapse;width:100%;font-size:.82rem}
.spacs th,.spacs td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.spacs thead{background:var(--bg-raise)}
.prem-pos{color:var(--accent)} .prem-neg{color:#b0653f}
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


def _page(user):
    from engine.publicmarkets.spacs import spac_list
    rows = spac_list(limit=100)

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
        Table(Thead(Tr(Th("Ticker"), Th("Company"), Th("Sponsor"), Th("Status"),
                       Th("Trust"), Th("Price"), Th("NAV prem."), Th("Target"))),
              Tbody(*trs)),
        cls="spacs",
    )
    return page("spacs", Style(_CSS), body, user=user, title="SPACs · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("🔀 SPACs", "/spacs", "spacs")
    if entry not in ph_layout.TOOLS_PAGES:
        ph_layout.TOOLS_PAGES.append(entry)

    @rt("/spacs", methods=["GET"])
    def spacs_get(session):
        return _page(_user(session))

    return ["/spacs"]

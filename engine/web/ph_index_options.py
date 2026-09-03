"""Index-options paper-trading hub."""
from __future__ import annotations

from fasthtml.common import Button, Div, H1, H2, H3, P, Span, Style

from engine.web.ph_layout import page

_CSS = """

.ix{width:100%;max-width:1120px;margin:0 auto;padding:1rem 1.2rem 3rem;overflow:auto}
.ix-hero{background:linear-gradient(135deg,var(--ink),var(--accent));color:white;
 border-radius:.85rem;padding:1.25rem;margin-bottom:1rem}
.ix-hero h1{margin:0 0 .35rem;font-size:1.45rem}.ix-hero p{margin:.2rem 0;color:#e5f3ec;font-size:.82rem}
.ix-badge{display:inline-block;margin-top:.6rem;padding:.25rem .55rem;border:1px solid #8bc2a7;
 border-radius:999px;font-size:.66rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.ix-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin:.8rem 0}
.ix-card{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;padding:.85rem}
.ix-card h3{margin:0 0 .35rem;font-size:.86rem;color:var(--ink)}
.ix-card p{font-size:.72rem;color:var(--ink-muted);line-height:1.45;margin:.3rem 0}
.ix-symbols{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0}
.ix-symbol{font:600 .74rem var(--font-mono);padding:.3rem .55rem;background:var(--accent-dim);
 color:var(--accent);border-radius:.35rem}
.ix-action{border:0;border-radius:.45rem;background:var(--accent);color:white;padding:.5rem .7rem;
 cursor:pointer;font:600 .72rem var(--font-body);margin-top:.45rem}
.ix-action:hover{background:var(--ink)}
.ix-warning{border-left:4px solid #c08b2c;background:#fff8e8;padding:.7rem .85rem;
 font-size:.74rem;color:var(--ink-muted);margin:.8rem 0}
.ix-steps{counter-reset:step;display:grid;grid-template-columns:repeat(3,1fr);gap:.65rem}
.ix-step{background:var(--bg-elev);border:1px solid var(--line);padding:.75rem;border-radius:.6rem;
 font-size:.72rem;color:var(--ink-muted)}
.ix-step:before{counter-increment:step;content:counter(step);display:inline-grid;place-items:center;
 width:1.4rem;height:1.4rem;border-radius:50%;background:var(--accent);color:white;
 font-weight:700;margin-right:.35rem}
@media(max-width:800px){.ix-grid,.ix-steps{grid-template-columns:1fr}}
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


def _action(label: str, prompt: str):
    return Button(label, type="button", cls="ix-action", onclick=f"fillChat({prompt!r})")


def _page(user):
    strategies = (
        ("Defined-risk directional spread",
         "Buy a call or put and sell a farther out-of-the-money contract with the same expiry.",
         "Design a one-contract XSP debit spread. List real contracts first and do not place orders."),
        ("XSP protective put",
         "Test smaller-notional S&P 500 portfolio protection with a fixed premium budget.",
         "Find active XSP puts 20 to 45 days out and propose a defined-risk portfolio hedge."),
        ("SPXW iron condor",
         "Evaluate defined-risk short premium with both wings, fees, slippage, and loss exits.",
         "Compare active SPXW iron-condor candidates. Show maximum loss and do not place orders."),
        ("VIX call spread",
         "Test convex volatility protection without assuming VIX options track spot VIX one-for-one.",
         "Find active VIX calls and propose a call spread with a fixed maximum premium."),
        ("0DTE SPXW debit spread",
         "Paper-test same-day PM settlement, entry cutoffs, exits, and fill assumptions.",
         "Plan a one-lot SPXW 0DTE debit-spread paper experiment. Do not place orders."),
        ("Expiry workflow test",
         "Validate European-style cash settlement without share delivery or early assignment.",
         "Help me test index-option expiration and cash settlement in my Alpaca paper account."),
    )
    body = Div(
        Div(
            H1("Index Options Paper Trading"),
            P("Discover and paper trade Cboe index options through Alpaca's Trading API."),
            Span("Paper only · cash settled · European style", cls="ix-badge"),
            cls="ix-hero",
        ),
        H2("Supported at launch"),
        Div(*[Span(s, cls="ix-symbol") for s in ("SPX", "SPXW", "VIX", "VIXW", "DJX", "XSP")],
            cls="ix-symbols"),
        Div(
            _action("Find XSP contracts",
                    "Show active XSP calls and puts expiring 20 to 45 days from now."),
            _action("Find SPXW 0DTE contracts",
                    "List active SPXW contracts expiring today and explain PM settlement risk."),
            _action("Review my option positions",
                    "Show my current Alpaca paper positions and identify any index options."),
            cls="ix-symbols",
        ),
        Div(
            "Alpaca does not currently supply underlying index market data. Contract discovery and "
            "paper execution are available, but signals, index levels, quotes, and Greeks require an "
            "appropriate external data source. Paper fills may differ materially from live execution.",
            cls="ix-warning",
        ),
        H2("Strategy lab"),
        Div(*[
            Div(H3(title), P(description), _action("Open in chat", prompt), cls="ix-card")
            for title, description, prompt in strategies
        ], cls="ix-grid"),
        H2("Safe workflow"),
        Div(
            Div("Choose the index, thesis, expiry horizon, and maximum acceptable loss.", cls="ix-step"),
            Div("Let the agent query Alpaca for active contracts—never invent an option symbol.", cls="ix-step"),
            Div("Review settlement timing and order details, then explicitly request a paper order.", cls="ix-step"),
            cls="ix-steps",
        ),
        cls="ix",
    )
    return page("indexoptions", Style(_CSS), body, user=user,
                title="Index Options · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("🎯 Index Options", "/index-options", "indexoptions")
    if entry not in ph_layout.PUBLIC_PAGES:
        ph_layout.PUBLIC_PAGES.append(entry)

    @rt("/index-options", methods=["GET"])
    def index_options_get(session):
        return _page(_user(session))

    return ["/index-options"]

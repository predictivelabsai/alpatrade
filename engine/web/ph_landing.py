"""AlpaTrade marketing landing — PEHero-skinned (parchment + forest).

Mirrors ``pehero/landing/components.py`` in structure (hero, feature pillars,
how-it-works, CTA, footer) but rebranded to AlpaTrade and skinned with the shared
house palette. It reuses the ``<head>`` from :mod:`engine.web.ph_layout` (which
loads ``static/app.css`` — the parchment/forest design tokens) and layers a small
landing-only ``<style>`` block on top, built entirely from the same CSS custom
properties (``--bg``, ``--accent``, ``--ink`` …) so the marketing site matches the
app skin exactly.

Contract: exposes :func:`register(app, rt)`, which wires the anonymous marketing
routes. Logged-in visitors (``session['user_id']``) are bounced from ``/`` to the
app at ``/app``. All CTAs point at the real auth surface: Sign in (``/signin``),
Start (``/register``) and Continue with Google (``/login``).
"""
from __future__ import annotations

from fasthtml.common import (
    A, Div, Footer, H1, H2, H3, Main, Nav, NotStr, P, Section, Span, Style,
)
from starlette.responses import RedirectResponse

from engine.web.ph_layout import head

SITE_NAME = "AlpaTrade"
SITE_TAGLINE = "Backtest, paper-trade and prove the P&L — one AI trading desk on Alpaca."

_GOOGLE_SVG = (
    '<svg width="17" height="17" viewBox="0 0 18 18" style="display:inline-block;'
    'vertical-align:middle"><path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844'
    'c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" '
    'fill="#4285F4"/><path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86'
    '-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>'
    '<path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 '
    '0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/><path d="M9 3.58c1.321 0 2.508.454 '
    '3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 '
    '5.163 6.656 3.58 9 3.58z" fill="#EA4335"/></svg>'
)

# --------------------------------------------------------------------------- css
# Landing-only styles, all expressed in the app.css design tokens so the parchment
# / forest skin is identical. app.css locks html/body to overflow:hidden for the
# chat shell — the marketing pages must scroll, hence the overrides below.
LANDING_CSS = """
html, body { overflow-x: hidden !important; overflow-y: auto !important; height: auto !important; }
body { background: var(--bg); color: var(--ink); font-family: var(--font-body); -webkit-font-smoothing: antialiased; }
.lp a { text-decoration: none; }

/* nav */
.lp-nav { position: sticky; top: 0; z-index: 50; backdrop-filter: blur(10px);
  background: color-mix(in srgb, var(--bg) 82%, transparent); border-bottom: 1px solid var(--line); }
.lp-nav-inner { max-width: 1160px; margin: 0 auto; padding: 0 1.5rem; height: 4rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.lp-brand { display: flex; align-items: center; gap: .5rem; color: var(--ink); font-weight: 600; font-size: 1.02rem; letter-spacing: -.01em; }
.lp-brand .mark { color: var(--accent); }
.lp-brand .badge { font-size: .58rem; font-weight: 600; color: var(--accent); background: var(--accent-dim);
  padding: .12rem .4rem; border-radius: 4px; letter-spacing: .08em; text-transform: uppercase; }
.lp-nav-links { display: flex; align-items: center; gap: 1.75rem; }
.lp-nav-link { font-size: .85rem; color: var(--ink-muted); }
.lp-nav-link:hover, .lp-nav-link.active { color: var(--ink); }
.lp-nav-cta { display: flex; align-items: center; gap: .55rem; }

/* buttons */
.lp-btn { display: inline-flex; align-items: center; gap: .5rem; padding: .6rem 1.15rem;
  border-radius: 2rem; font-size: .85rem; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; transition: all .18s ease; font-family: var(--font-body); }
.lp-btn.sm { padding: .42rem .85rem; font-size: .78rem; }
.lp-btn.primary { background: var(--accent); color: var(--bg); box-shadow: 0 0 0 1px var(--accent); }
.lp-btn.primary:hover { background: var(--ink); box-shadow: 0 0 0 1px var(--ink); }
.lp-btn.ghost { background: transparent; color: var(--ink); border-color: var(--line-br); }
.lp-btn.ghost:hover { border-color: var(--accent); color: var(--accent); }
.lp-btn.google { background: var(--bg-elev); color: var(--ink); border-color: var(--line-br); }
.lp-btn.google:hover { border-color: var(--accent); }

/* sections + type */
.lp-section { max-width: 1160px; margin: 0 auto; padding: 4rem 1.5rem; }
.lp-section.tight { padding-top: 3rem; padding-bottom: 3rem; }
.lp-bordered { border-top: 1px solid var(--line); }
.lp-eyebrow { font-family: var(--font-mono); font-size: .7rem; letter-spacing: .18em;
  text-transform: uppercase; color: var(--accent); }
.lp-h1 { font-size: clamp(2.4rem, 5.5vw, 4.4rem); font-weight: 500; letter-spacing: -.035em;
  line-height: 1.04; color: var(--ink); margin-top: 1.2rem; max-width: 20ch; }
.lp-h2 { font-size: clamp(1.6rem, 3.2vw, 2.6rem); font-weight: 500; letter-spacing: -.025em;
  line-height: 1.1; color: var(--ink); }
.lp-lede { font-size: clamp(1rem, 1.4vw, 1.2rem); line-height: 1.6; color: var(--ink-muted); max-width: 44rem; margin-top: 1.5rem; }
.lp-accent { color: var(--accent); }
.lp-muted { color: var(--ink-muted); }

/* hero */
.lp-hero { position: relative; overflow: hidden;
  background: radial-gradient(ellipse 70% 55% at 50% -10%, var(--accent-dim), transparent 65%); }
.lp-hero-inner { max-width: 1160px; margin: 0 auto; padding: 5rem 1.5rem 3.5rem; }
.lp-cta-row { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem; margin-top: 2.25rem; }
.lp-terminal { margin-top: 3rem; max-width: 46rem; background: var(--bg-elev); border: 1px solid var(--line);
  border-radius: .8rem; padding: 1.1rem 1.25rem; box-shadow: 0 8px 40px rgba(0,0,0,.05); }
.lp-terminal .row { font-family: var(--font-mono); font-size: .82rem; line-height: 1.7; }
.lp-terminal .cmd { color: var(--accent); }
.lp-terminal .out { color: var(--ink-muted); }
.lp-terminal .dim { color: var(--ink-dim); font-size: .74rem; }

/* stats bar */
.lp-stats { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: var(--bg-elev); }
.lp-stats-inner { max-width: 1160px; margin: 0 auto; padding: 1.75rem 1.5rem;
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.5rem; }
.lp-stat-value { font-size: 1.7rem; font-weight: 600; color: var(--ink); letter-spacing: -.02em; }
.lp-stat-cap { font-size: .78rem; color: var(--ink-muted); margin-top: .25rem; }

/* card grids */
.lp-grid { display: grid; gap: 1rem; margin-top: 2.5rem; }
.lp-grid.c5 { grid-template-columns: repeat(5, 1fr); }
.lp-grid.c3 { grid-template-columns: repeat(3, 1fr); }
.lp-card { background: var(--bg-elev); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.6rem; transition: border-color .18s ease; display: flex; flex-direction: column; height: 100%; }
.lp-card:hover { border-color: var(--accent); }
.lp-card .icon { font-size: 1.6rem; color: var(--accent); }
.lp-card .num { font-family: var(--font-mono); font-size: .7rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ink-dim); }
.lp-card .title { font-size: 1.05rem; font-weight: 600; color: var(--ink); margin-top: .75rem; letter-spacing: -.01em; }
.lp-card .body { font-size: .86rem; line-height: 1.55; color: var(--ink-muted); margin-top: .55rem; }
.lp-card .prefix { font-family: var(--font-mono); font-size: .68rem; color: var(--accent);
  background: var(--accent-dim); padding: .1rem .4rem; border-radius: 4px; align-self: flex-start; margin-top: .75rem; }

/* pricing */
.lp-price { background: var(--bg-elev); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.9rem; display: flex; flex-direction: column; height: 100%; }
.lp-price.hot { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.lp-price .name { font-family: var(--font-mono); font-size: .7rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ink-dim); }
.lp-price .amt { font-size: 2.6rem; font-weight: 600; letter-spacing: -.03em; color: var(--ink); margin-top: .5rem; }
.lp-price .per { font-size: .85rem; color: var(--ink-muted); margin-left: .3rem; font-weight: 400; }
.lp-price .feat { font-size: .84rem; color: var(--ink-muted); padding: .3rem 0; }
.lp-price .feat b { color: var(--accent); font-weight: 700; margin-right: .4rem; }
.lp-price-cta { margin-top: auto; padding-top: 1.4rem; }

/* cta band */
.lp-band { position: relative; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
  background: var(--bg-elev);
  background-image: radial-gradient(ellipse 60% 90% at 15% 20%, var(--accent-dim), transparent 60%); }
.lp-band-inner { max-width: 1160px; margin: 0 auto; padding: 5rem 1.5rem; }

/* footer */
.lp-footer { border-top: 1px solid var(--line); background: var(--bg-elev); }
.lp-footer-inner { max-width: 1160px; margin: 0 auto; padding: 3rem 1.5rem; }
.lp-footer-top { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.lp-footer-links { display: flex; flex-wrap: wrap; gap: 1.25rem; }
.lp-footer-links a { font-size: .82rem; color: var(--ink-muted); }
.lp-footer-links a:hover { color: var(--accent); }
.lp-fine { font-size: .72rem; line-height: 1.55; color: var(--ink-dim); max-width: 60rem;
  margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid var(--line); }

@media (max-width: 960px) {
  .lp-nav-links { display: none; }
  .lp-grid.c5 { grid-template-columns: repeat(2, 1fr); }
  .lp-grid.c3 { grid-template-columns: 1fr; }
  .lp-stats-inner { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
  .lp-grid.c5 { grid-template-columns: 1fr; }
  .lp-nav-cta .lp-btn.ghost { display: none; }
}
"""

# --------------------------------------------------------------------------- data
# (icon, name, prefix, blurb) — the five workflow stages of the trading desk.
PILLARS = [
    ("◧", "Research & Signals", "research:",
     "Screen the market, pull news, analyst ratings and fundamentals before you commit capital."),
    ("◆", "Backtest & Optimize", "backtest:",
     "Sweep parameter grids or run a deterministic, reproducible study on real Alpaca data."),
    ("◉", "Paper Trade", "trade:",
     "Send the winning strategy live on Alpaca paper — background polling, PDT-aware."),
    ("◐", "Validate & Reconcile", "validate:",
     "Cross-check every fill against market data and tie the DB out against the broker."),
    ("◼", "P&L & Reporting", "report:",
     "See what worked — P&L, top strategies, drawdown and per-run detail on demand."),
]

STEPS = [
    ("01", "Pick a strategy & universe",
     "Choose Buy-the-Dip, VIX, Momentum or Box-Wedge, set your tickers and parameters. "
     "The strategy library encodes it as a compact, reproducible slug."),
    ("02", "Backtest across the grid",
     "Sweep the parameter space on real Alpaca data. Every run is stored to the database, "
     "and the methodology lab writes a deterministic, dated artifact folder you can reproduce."),
    ("03", "Paper-trade & prove the P&L",
     "Send the winner to Alpaca paper trading. The validator checks every fill, the reconciler "
     "ties out positions, and the reporter shows P&L, drawdown and top strategies."),
]

STATS = [
    ("5-agent", "trading squad"),
    ("4", "strategies built-in"),
    ("Alpaca", "live paper trading"),
    ("Reproducible", "dated backtest artifacts"),
]


# --------------------------------------------------------------------------- chrome
def _btn(label, href, variant="primary", *, arrow=False, sm=False, google=False):
    kids = []
    if google:
        kids.append(NotStr(_GOOGLE_SVG))
    kids.append(Span(label))
    if arrow:
        kids.append(Span("→"))
    cls = "lp-btn " + variant + (" sm" if sm else "")
    return A(*kids, href=href, cls=cls)


def _brand():
    return A(Span("◆", cls="mark"), Span(SITE_NAME), Span("beta", cls="badge"),
             href="/", cls="lp-brand")


def _nav(active="home"):
    def link(label, href, key):
        return A(label, href=href, cls="lp-nav-link" + (" active" if key == active else ""))
    return Nav(
        Div(
            _brand(),
            Div(link("Platform", "/platform", "platform"),
                link("Pricing", "/pricing", "pricing"),
                cls="lp-nav-links"),
            Div(_btn("Sign in", "/signin", "ghost", sm=True),
                _btn("Start", "/register", "primary", sm=True, arrow=True),
                cls="lp-nav-cta"),
            cls="lp-nav-inner",
        ),
        cls="lp-nav",
    )


def _footer():
    return Footer(
        Div(
            Div(
                Div(_brand(),
                    P(SITE_TAGLINE, cls="lp-muted",
                      style="font-size:.85rem;margin-top:.75rem;max-width:22rem")),
                Div(
                    A("Platform", href="/platform"),
                    A("Pricing", href="/pricing"),
                    A("Sign in", href="/signin"),
                    A("Start free", href="/register"),
                    cls="lp-footer-links",
                ),
                cls="lp-footer-top",
            ),
            P("Paper trading is a simulated environment and does not involve real money. Backtested "
              "results are hypothetical, do not represent actual trading, and do not guarantee future "
              "results. AlpaTrade is for research and educational purposes only — not investment advice. "
              f"© 2026 Predictive Labs Ltd.",
              cls="lp-fine"),
            cls="lp-footer-inner",
        ),
        cls="lp-footer",
    )


# --------------------------------------------------------------------------- sections
def _hero():
    return Section(
        Div(
            Div(Span("◈ ", cls="lp-accent"),
                Span("AI trading desk · backtest → paper → P&L", cls="lp-eyebrow")),
            H1(Span("Backtest, "), Span("paper-trade", cls="lp-accent"),
               Span(" and prove the "), Span("P&L", cls="lp-accent"), Span("."),
               cls="lp-h1"),
            P("A squad of specialist AI analysts on Alpaca — they screen and research the market, "
              "backtest strategies across a parameter grid, paper-trade the winners live, then validate "
              "every fill and report the P&L. Chat-first, from ticker to track record.",
              cls="lp-lede"),
            Div(_btn("Start free", "/register", "primary", arrow=True),
                _btn("Sign in", "/signin", "ghost"),
                _btn("Continue with Google", "/login", "google", google=True),
                cls="lp-cta-row"),
            Div(
                Div(Span("$ ", cls="dim"),
                    Span("alpatrade backtest paper btd-7dp-05sl-1tp-1d-3m", cls="cmd"),
                    cls="row"),
                Div(Span("→ 42 trades · win-rate 61% · Sharpe 1.34 · max DD -6.2%", cls="out"),
                    cls="row"),
                Div(Span("→ artifacts → backtest-results/2026-…_AAPL_buy_the_dip_1d/", cls="dim"),
                    cls="row"),
                cls="lp-terminal",
            ),
            cls="lp-hero-inner",
        ),
        cls="lp-hero",
    )


def _stats():
    return Div(
        Div(*[Div(Div(v, cls="lp-stat-value"), Div(c, cls="lp-stat-cap"))
              for v, c in STATS], cls="lp-stats-inner"),
        cls="lp-stats",
    )


def _pillar_card(icon, name, prefix, blurb):
    return Div(
        Span(icon, cls="icon"),
        Div(name, cls="title"),
        Div(blurb, cls="body"),
        Span(prefix, cls="prefix"),
        cls="lp-card",
    )


def _pillars():
    return Section(
        Span("The desk", cls="lp-eyebrow"),
        H2("One system. Ticker to track record.", cls="lp-h2", style="margin-top:.75rem;max-width:24ch"),
        P("Your AI trading squad spans five workflow stages — talk to any one directly, or let the "
          "orchestrator run the whole loop.", cls="lp-lede", style="margin-top:1rem"),
        Div(*[_pillar_card(*p) for p in PILLARS], cls="lp-grid c5"),
        cls="lp-section lp-bordered",
    )


def _how():
    return Section(
        Span("How it works", cls="lp-eyebrow"),
        H2("From ticker to track record in an afternoon.", cls="lp-h2",
           style="margin-top:.75rem;max-width:22ch"),
        Div(*[Div(Div(num, cls="num"), Div(title, cls="title"), Div(body, cls="body"), cls="lp-card")
              for num, title, body in STEPS], cls="lp-grid c3"),
        cls="lp-section lp-bordered",
    )


def _cta_band():
    return Section(
        Div(
            Span("Get started", cls="lp-eyebrow"),
            H2("Backtest it. Paper-trade it. Prove it.", cls="lp-h2", style="margin-top:.75rem"),
            P("Create an account and put the squad to work — bring your own Alpaca keys.",
              cls="lp-lede"),
            Div(_btn("Start free", "/register", "primary", arrow=True),
                _btn("Continue with Google", "/login", "google", google=True),
                cls="lp-cta-row"),
            cls="lp-band-inner",
        ),
        cls="lp-band",
    )


# --------------------------------------------------------------------------- pages
def _shell(title, *sections, active="home"):
    return (
        *head(title),
        Style(LANDING_CSS),
        Div(_nav(active), Main(*sections), _footer(), cls="lp"),
    )


def home_page():
    return _shell(
        "AlpaTrade — AI trading, backtest & P&L analyst squad",
        _hero(), _stats(), _pillars(), _how(), _cta_band(),
        active="home",
    )


def platform_page():
    hero = Section(
        Span("The platform", cls="lp-eyebrow"),
        H1("One engine. Every asset class.", cls="lp-h1"),
        P("A shared engine — brokers, market-data feeds, a backtester and a paper-trading loop — with the "
          "equities / Alpaca vertical live today and crypto, FX and prediction markets on the roadmap. "
          "Every vertical inherits the same backtest → validate → paper-trade → report workflow.",
          cls="lp-lede"),
        Div(_btn("Start free", "/register", "primary", arrow=True),
            _btn("See pricing", "/pricing", "ghost"),
            cls="lp-cta-row"),
        cls="lp-hero-inner",
    )
    return _shell(
        "Platform — AlpaTrade",
        Section(hero, cls="lp-hero"),
        _stats(), _pillars(), _how(), _cta_band(),
        active="platform",
    )


def pricing_page():
    tiers = [
        ("Research", "$0", "/mo", False,
         [("✓", "Backtesting on delayed data"), ("✓", "Full strategy library"),
          ("✓", "50 AI queries / month"), ("✓", "Community support")],
         "Start free"),
        ("Trader", "$29", "/mo", True,
         [("✓", "Everything in Research"), ("✓", "Live Alpaca paper trading"),
          ("✓", "Reproducible backtest artifacts"), ("✓", "Validation & reconciliation"),
          ("✓", "Unlimited AI queries")],
         "Start free"),
        ("Desk", "Contact", "us", False,
         [("✓", "Everything in Trader"), ("✓", "Multi-account & team"),
          ("✓", "Priority support"), ("✓", "Custom strategies")],
         "Talk to us"),
    ]

    def card(name, amt, per, hot, feats, cta):
        return Div(
            Div(name, cls="name"),
            Div(Span(amt), Span(per, cls="per"), cls="amt"),
            Div(*[Div(Span(mark, style="color:var(--accent);font-weight:700;margin-right:.4rem"),
                      Span(txt), cls="feat") for mark, txt in feats],
                style="margin-top:1.25rem"),
            Div(_btn(cta, "/register", "primary" if hot else "ghost", arrow=True),
                cls="lp-price-cta"),
            cls="lp-price" + (" hot" if hot else ""),
        )

    hero = Section(
        Span("Pricing", cls="lp-eyebrow"),
        H1("Start free on paper.", cls="lp-h1"),
        P("Bring your own Alpaca keys. Upgrade when you go live.", cls="lp-lede"),
        cls="lp-hero-inner",
    )
    return _shell(
        "Pricing — AlpaTrade",
        Section(hero, cls="lp-hero"),
        Section(Div(*[card(*t) for t in tiers], cls="lp-grid c3", style="margin-top:0"),
                cls="lp-section lp-bordered"),
        _cta_band(),
        active="pricing",
    )


# --------------------------------------------------------------------------- register
def register(app, rt):
    """Wire the anonymous marketing routes. Returns the list of paths registered."""

    @rt("/")
    def landing_home(session):
        if session.get("user_id"):
            return RedirectResponse("/app", status_code=303)
        return home_page()

    @rt("/platform")
    def landing_platform(session):
        return platform_page()

    @rt("/pricing")
    def landing_pricing(session):
        return pricing_page()

    return ["/", "/platform", "/pricing"]

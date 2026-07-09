"""AlpaTrade marketing landing page — FastHTML components.

Design ported from the sibling LiquidRound landing (dark-navy hero, specialist-agent
directory, how-it-works, dual CTAs) and reworked for the AlpaTrade story: a squad of
AI trading, P&L and research analysts that backtest, paper-trade, validate and report.

Wired by app.py at `/`, `/platform`, `/agents`, `/pricing`.
"""
from __future__ import annotations

from fasthtml.common import (
    A, Button, Div, H1, H2, H3, Img, Link, Main, Meta, P, Script, Span, Style, Title,
    NotStr,
)

# ───── Palette (matches LiquidRound's dark navy; green/red carry P&L semantics) ─────
BG        = "#0B1220"   # deep navy
BG_ELEV   = "#111A2E"   # elevated panels
INK       = "#E5E7EB"   # near-white text
INK_MUTED = "#94A3B8"   # slate-400
LONG      = "#3B82F6"   # blue-500  — primary / long
GAIN      = "#10B981"   # emerald-500 — P&L up
LOSS      = "#EF4444"   # red-500 — P&L down
CTA       = "#F59E0B"   # amber-500 accents
LINE      = "#1E293B"   # slate-800

_OG_DESC = ("A squad of specialist AI analysts that backtest strategies, paper-trade live "
            "on Alpaca, validate every fill, and report P&L — one chat-first workspace.")


# ───── Shared chrome ────────────────────────────────────────────────────
def landing_head(title: str = "AlpaTrade", description: str | None = None):
    desc = description or _OG_DESC
    return (
        Title(title),
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(name="theme-color", content=BG),
        Meta(name="description", content=desc),
        Meta(property="og:type", content="website"),
        Meta(property="og:site_name", content="AlpaTrade"),
        Meta(property="og:title", content=title),
        Meta(property="og:description", content=desc),
        Meta(name="twitter:card", content="summary_large_image"),
        Script(src="https://cdn.tailwindcss.com"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
        Link(href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap", rel="stylesheet"),
        Style(f"""
            html {{ overflow-x: hidden; overflow-y: auto; scrollbar-width: none; }}
            html::-webkit-scrollbar {{ display: none; }}
            html, body {{ background: {BG}; color: {INK}; font-family: 'Inter', system-ui, sans-serif; letter-spacing: -0.01em; margin: 0; }}
            .mono {{ font-family: 'JetBrains Mono', ui-monospace, monospace; }}
            .tighter {{ letter-spacing: -0.025em; }}
            .tightest {{ letter-spacing: -0.04em; }}
            .hero-gradient {{ background: radial-gradient(ellipse 80% 50% at 50% 0%, rgba(59,130,246,0.12), transparent 70%); }}
            .cta-glow-long {{ box-shadow: 0 0 40px rgba(59,130,246,0.35); }}
            .cta-glow-gain {{ box-shadow: 0 0 40px rgba(16,185,129,0.30); }}
            a {{ transition: color .15s ease, opacity .15s ease; }}
            .nav-link:hover {{ color: {CTA}; }}
            .card {{ background: {BG_ELEV}; border: 1px solid {LINE}; }}
            .card:hover {{ border-color: {CTA}; }}
        """),
    )


def _brand(size_cls: str = "text-base"):
    return A(
        Div(
            Span("◈", cls="text-xl mr-2", style=f"color:{CTA}"),
            Span("Alpa", cls=f"{size_cls} font-semibold tighter", style=f"color:{INK};"),
            Span("Trade", cls=f"{size_cls} font-semibold tighter", style=f"color:{LONG};"),
            cls="flex items-center",
        ),
        href="/", cls="no-underline",
    )


def landing_nav(active: str = "home"):
    def link(href: str, label: str, key: str):
        cls = "text-sm nav-link " + ("text-white font-medium" if key == active else "text-slate-400")
        return A(label, href=href, cls=cls)

    return Div(
        Div(
            _brand(),
            Div(
                link("/platform", "Platform", "platform"),
                link("/agents", "Agent Squad", "agents"),
                link("/pricing", "Pricing", "pricing"),
                cls="hidden lg:flex items-center gap-6",
            ),
            Div(
                A("Sign in", href="/signin",
                  cls="hidden sm:inline-flex text-sm px-3 py-1.5 rounded-md font-medium no-underline",
                  style=f"background:{BG_ELEV}; color:{INK}; border:1px solid {LINE};"),
                A("Start free →", href="/register",
                  cls="text-sm px-3 py-1.5 rounded-md font-medium no-underline text-white",
                  style=f"background:{CTA};"),
                cls="flex items-center gap-2",
            ),
            cls="max-w-6xl mx-auto flex items-center justify-between px-4 sm:px-6 py-4",
        ),
        cls="border-b sticky top-0 z-40 backdrop-blur",
        style=f"border-color:{LINE}; background: rgba(11,18,32,0.85);",
    )


def landing_footer():
    return Div(
        Div(
            Div(
                Span("AlpaTrade", cls="text-sm font-semibold tighter"),
                Span("© 2026 Predictive Labs Ltd.", cls="ml-3 text-xs text-slate-500"),
                cls="flex items-center",
            ),
            Div(
                A("Platform", href="/platform", cls="text-xs text-slate-400 nav-link"),
                Span("·", cls="text-xs text-slate-600 mx-2"),
                A("Agent Squad", href="/agents", cls="text-xs text-slate-400 nav-link"),
                Span("·", cls="text-xs text-slate-600 mx-2"),
                A("Pricing", href="/pricing", cls="text-xs text-slate-400 nav-link"),
                Span("·", cls="text-xs text-slate-600 mx-2"),
                A("Sign in", href="/signin", cls="text-xs text-slate-400 nav-link"),
                cls="flex items-center flex-wrap gap-y-1 justify-center sm:justify-end",
            ),
            cls="max-w-6xl mx-auto px-4 sm:px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-3",
        ),
        Div(
            P("Paper trading is a simulated environment and does not involve real money. Backtested "
              "results are hypothetical, do not represent actual trading, and do not guarantee future "
              "results. For research and educational purposes only — not investment advice.",
              cls="max-w-6xl mx-auto px-4 sm:px-6 pb-6 text-[11px] leading-relaxed",
              style=f"color:#475569;"),
        ),
        cls="border-t mt-20",
        style=f"border-color:{LINE};",
    )


# ───── Agent-squad content ──────────────────────────────────────────────
# (icon, name, prefix, one-liner, tint)
CATEGORIES = [
    {"key": "research", "icon": "◧", "name": "Research & Signals", "tint": LONG,
     "blurb": "Screen the market, pull news, ratings and fundamentals before you commit capital.",
     "agents": [
         ("Market Research", "research:", "News, analyst ratings and screening across your universe."),
         ("Strategy Library", "strategy:", "Buy-the-Dip, VIX, Momentum and Box-Wedge — parameterised and ready."),
     ]},
    {"key": "backtest", "icon": "◆", "name": "Backtest & Optimize", "tint": CTA,
     "blurb": "Sweep parameter grids or run a deterministic, reproducible study on real Alpaca data.",
     "agents": [
         ("Backtester", "backtest:", "Grid-search across params, encode as slugs, store every run to the DB."),
         ("Methodology Lab", "study:", "Deterministic dated artifacts — data fingerprints, fills, the Teaching Five."),
     ]},
    {"key": "execution", "icon": "◉", "name": "Paper Trade", "tint": GAIN,
     "blurb": "Take the winning strategy live on Alpaca paper — background polling, PDT-aware.",
     "agents": [
         ("Paper Trader", "trade:", "Live paper execution on Alpaca with FINRA PDT rule enforcement."),
     ]},
    {"key": "assurance", "icon": "◐", "name": "Validate & Reconcile", "tint": LONG,
     "blurb": "Trust every number: cross-check fills against market data and DB against the broker.",
     "agents": [
         ("Validator", "validate:", "Cross-checks trades vs market data with a self-correcting loop."),
         ("Reconciler", "reconcile:", "Compares DB positions against live Alpaca holdings."),
     ]},
    {"key": "reporting", "icon": "◼", "name": "P&L & Reporting", "tint": GAIN,
     "blurb": "See what worked — P&L, top strategies, drawdown and run detail on demand.",
     "agents": [
         ("Reporter", "report:", "Summaries, top strategies and per-run P&L straight from the database."),
     ]},
]


# ───── Home-page sections ───────────────────────────────────────────────
def _google_svg():
    return NotStr('<svg width="18" height="18" viewBox="0 0 18 18" style="display:inline-block;vertical-align:middle;margin-right:8px"><path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/><path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/><path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/><path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/></svg>')


def hero():
    return Div(
        Div(
            Div(
                Span("◈", cls="mono mr-2", style=f"color:{CTA}"),
                Span("AI trading desk · backtest → paper → P&L",
                     cls="text-xs mono uppercase tracking-widest", style=f"color:{INK_MUTED}"),
                cls="flex items-center justify-center mb-6 md:mb-8",
            ),
            H1(
                Span("Your AI "),
                Span("trading & research ", style=f"color:{CTA};"),
                Span("analyst squad. "),
                Span("Backtest, ", style=f"color:{LONG}"),
                Span("paper-trade, ", style=f"color:{GAIN}"),
                Span("and prove the P&L.", style=f"color:{INK}"),
                cls="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-bold tightest text-center mb-4 md:mb-6",
                style=f"color:{INK};",
            ),
            P(
                Span("A squad of specialist AI analysts on ", style=f"color:{INK_MUTED};"),
                Span("Alpaca", style=f"color:{INK};"),
                Span(" — they ", style=f"color:{INK_MUTED};"),
                Span("screen and research ", style=f"color:{LONG};"),
                Span("the market, ", style=f"color:{INK_MUTED};"),
                Span("backtest ", style=f"color:{CTA};"),
                Span("strategies across a parameter grid, ", style=f"color:{INK_MUTED};"),
                Span("paper-trade ", style=f"color:{GAIN};"),
                Span("the winners live, then ", style=f"color:{INK_MUTED};"),
                Span("validate every fill ", style=f"color:{INK};"),
                Span("and report the P&L. Chat-first, from ticker to track record.",
                     style=f"color:{INK_MUTED};"),
                cls="text-base md:text-lg lg:text-xl text-center max-w-3xl mx-auto mb-8 md:mb-10 leading-relaxed px-2",
            ),
            Div(
                A(Span("Start backtesting", cls="text-base font-semibold"), Span(" →", cls="ml-2"),
                  href="/register",
                  cls="cta-glow-long rounded-lg px-6 py-3 inline-flex items-center text-white no-underline cursor-pointer",
                  style=f"background:{LONG};"),
                A(Span("Paper trade", cls="text-base font-semibold"), Span(" →", cls="ml-2"),
                  href="/register",
                  cls="cta-glow-gain rounded-lg px-6 py-3 inline-flex items-center text-white no-underline cursor-pointer",
                  style=f"background:{GAIN};"),
                cls="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4 mb-4",
            ),
            A(_google_svg(), "Continue with Google",
              href="/login",
              cls="inline-flex items-center justify-center text-sm px-4 py-2.5 rounded-lg font-medium no-underline mb-16",
              style=f"background:{BG_ELEV}; color:{INK}; border:1px solid {LINE};"),
            Div(
                Div(
                    Div(
                        P("$ assethero backtest paper btd-7dp-05sl-1tp-1d-3m",
                          cls="mono text-sm", style=f"color:{GAIN};"),
                        P("→ 42 trades · win-rate 61% · Sharpe 1.34 · max DD -6.2%",
                          cls="mono text-sm mt-2", style=f"color:{INK_MUTED};"),
                        P("→ artifacts written to backtest-results/2026-…_AAPL_buy_the_dip_1d/",
                          cls="mono text-xs mt-1", style=f"color:#475569;"),
                        cls="text-left p-6",
                    ),
                    cls="max-w-3xl mx-auto rounded-lg", style=f"border:1px solid {LINE}; background:{BG_ELEV};",
                ),
                cls="px-6",
            ),
            cls="max-w-4xl mx-auto px-4 sm:px-6 pt-12 md:pt-20 pb-10 md:pb-12 text-center",
        ),
        cls="hero-gradient",
    )


def stats_bar():
    items = [
        ("5-agent", "trading squad"),
        ("4", "strategies built-in"),
        ("Alpaca", "live paper trading"),
        ("Reproducible", "dated backtest artifacts"),
    ]
    return Div(
        Div(
            *[Div(
                Div(val, cls="text-2xl font-bold tightest", style=f"color:{INK};"),
                Div(label, cls="text-xs mono uppercase tracking-widest mt-1", style=f"color:{INK_MUTED};"),
                cls="text-center",
            ) for val, label in items],
            cls="grid grid-cols-2 md:grid-cols-4 gap-6 md:gap-8 max-w-4xl mx-auto px-4 sm:px-6 py-10 md:py-12",
        ),
        cls="border-y", style=f"border-color:{LINE};",
    )


def _pillar(cat):
    return Div(
        Span(cat["icon"], cls="text-3xl mono", style=f"color:{cat['tint']};"),
        H3(cat["name"], cls="text-base font-semibold mt-3 tighter", style=f"color:{INK};"),
        P(cat["blurb"], cls="text-sm mt-2 leading-relaxed", style=f"color:{INK_MUTED};"),
        cls="card rounded-lg p-5 transition",
    )


def pillars_section():
    return Div(Div(
        H2("One system. Ticker to track record.",
           cls="text-3xl md:text-4xl font-bold tightest text-center mb-4", style=f"color:{INK};"),
        P("Your AI trading squad spans five workflow stages.",
          cls="text-center mb-12", style=f"color:{INK_MUTED};"),
        Div(*[_pillar(c) for c in CATEGORIES],
            cls="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4"),
        cls="max-w-6xl mx-auto px-4 sm:px-6 py-14 md:py-20",
    ))


def _agent_card(name, prefix, one_liner, tint):
    return Div(
        Div(
            Span("◆", cls="text-xl mono", style=f"color:{tint};"),
            Span(prefix, cls="text-xs mono ml-auto px-1.5 py-0.5 rounded",
                 style=f"color:{INK_MUTED}; background:rgba(255,255,255,0.03); border:1px solid {LINE};"),
            cls="flex items-center mb-3",
        ),
        H3(name, cls="text-sm font-semibold tighter", style=f"color:{INK};"),
        P(one_liner, cls="text-xs mt-1.5 leading-relaxed", style=f"color:{INK_MUTED};"),
        cls="card rounded-lg p-4 h-full",
    )


def agent_grid_section():
    sections = []
    for cat in CATEGORIES:
        sections.append(Div(
            Div(
                Span(cat["icon"], cls="text-2xl mono mr-3", style=f"color:{cat['tint']};"),
                Div(
                    H3(cat["name"], cls="text-lg font-semibold tighter", style=f"color:{INK};"),
                    P(cat["blurb"], cls="text-xs", style=f"color:{INK_MUTED};"),
                ),
                cls="flex items-center mb-4",
            ),
            Div(*[_agent_card(n, p, o, cat["tint"]) for n, p, o in cat["agents"]],
                cls="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"),
            cls="mb-12",
        ))
    return Div(Div(
        H2("Every analyst already on the desk.",
           cls="text-3xl md:text-4xl font-bold tightest text-center mb-4", style=f"color:{INK};"),
        P("A squad of AI trading analysts — each with a role and a one-word prefix. Talk to them "
          "directly or let the orchestrator route the workflow.",
          cls="text-center mb-12 max-w-2xl mx-auto", style=f"color:{INK_MUTED};"),
        *sections,
        cls="max-w-6xl mx-auto px-4 sm:px-6 py-14 md:py-20",
    ))


def how_it_works_section():
    steps = [
        ("1. Pick a strategy & universe", "Choose Buy-the-Dip, VIX, Momentum or Box-Wedge, set your tickers and parameters. The strategy library encodes it as a compact, reproducible slug.", LONG),
        ("2. Backtest across the grid", "Sweep the parameter space on real Alpaca data. Every run is stored to the database, and the methodology lab writes a deterministic dated artifact folder you can reproduce.", CTA),
        ("3. Paper-trade & prove P&L", "Send the winner to Alpaca paper trading. The validator checks every fill, the reconciler ties out positions, and the reporter shows P&L, drawdown and top strategies.", GAIN),
    ]
    return Div(Div(
        H2("From ticker to track record in an afternoon.",
           cls="text-3xl md:text-4xl font-bold tightest text-center mb-12", style=f"color:{INK};"),
        Div(*[Div(
            Div(label.split(".")[0] + ".", cls="text-4xl font-bold tightest mb-3", style=f"color:{color};"),
            H3(label.split(". ", 1)[1], cls="text-lg font-semibold tighter mb-2", style=f"color:{INK};"),
            P(body, cls="text-sm leading-relaxed", style=f"color:{INK_MUTED};"),
            cls="card rounded-lg p-6",
        ) for label, body, color in steps],
            cls="grid grid-cols-1 md:grid-cols-3 gap-4"),
        cls="max-w-6xl mx-auto px-4 sm:px-6 py-14 md:py-20",
    ))


def cta_section():
    return Div(Div(
        H2("Backtest it. Paper-trade it. Prove it.",
           cls="text-3xl md:text-4xl font-bold tightest text-center mb-4", style=f"color:{INK};"),
        P("Create an account and put the squad to work.", cls="text-center mb-10", style=f"color:{INK_MUTED};"),
        Div(
            A("Start free →", href="/register",
              cls="cta-glow-long rounded-lg px-6 py-3 text-base font-semibold text-white no-underline",
              style=f"background:{LONG};"),
            A(_google_svg(), "Continue with Google", href="/login",
              cls="rounded-lg px-6 py-3 text-base font-semibold no-underline inline-flex items-center",
              style=f"background:{BG_ELEV}; color:{INK}; border:1px solid {LINE};"),
            cls="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4",
        ),
        cls="max-w-4xl mx-auto px-4 sm:px-6 py-14 md:py-20 text-center",
    ))


# ───── Page shells ──────────────────────────────────────────────────────
def landing_page(*sections, active: str = "home", title: str = "AlpaTrade",
                 description: str | None = None):
    return (
        *landing_head(title, description=description),
        landing_nav(active=active),
        Main(*sections),
        landing_footer(),
    )


def home_page():
    return landing_page(
        hero(), stats_bar(), pillars_section(), agent_grid_section(),
        how_it_works_section(), cta_section(),
        active="home",
        title="AlpaTrade — AI trading, backtest & P&L analyst squad",
    )


def platform_page():
    return landing_page(
        Div(Div(
            H1("The platform", cls="text-4xl md:text-5xl font-bold tightest text-center mb-4", style=f"color:{INK};"),
            P("One shared engine — brokers, market-data feeds, a backtester and a paper-trading loop — "
              "with the equities / Alpaca vertical live today and crypto, FX and prediction markets on the roadmap.",
              cls="text-center max-w-3xl mx-auto", style=f"color:{INK_MUTED};"),
            cls="max-w-4xl mx-auto px-4 sm:px-6 pt-16 pb-6 text-center",
        ), cls="hero-gradient"),
        pillars_section(), how_it_works_section(), cta_section(),
        active="platform", title="Platform — AlpaTrade",
    )


def agents_page():
    return landing_page(
        Div(Div(
            H1("The agent squad", cls="text-4xl md:text-5xl font-bold tightest text-center mb-4", style=f"color:{INK};"),
            P("Five coordinated AI analysts, orchestrated Backtest → Validate → Paper-Trade → Validate → Report.",
              cls="text-center max-w-3xl mx-auto", style=f"color:{INK_MUTED};"),
            cls="max-w-4xl mx-auto px-4 sm:px-6 pt-16 pb-2 text-center",
        ), cls="hero-gradient"),
        agent_grid_section(), cta_section(),
        active="agents", title="Agent Squad — AlpaTrade",
    )


def _price_card(name, price, note, features, highlight=False):
    return Div(
        H3(name, cls="text-lg font-semibold tighter", style=f"color:{INK};"),
        Div(Span(price, cls="text-3xl font-bold tightest", style=f"color:{INK};"),
            Span(note, cls="text-sm ml-1", style=f"color:{INK_MUTED};"), cls="my-3"),
        Div(*[P(NotStr(f"✓ {f}"), cls="text-sm py-1", style=f"color:{INK_MUTED};") for f in features]),
        A("Get started", href="/register",
          cls="block text-center mt-5 px-4 py-2.5 rounded-lg font-semibold no-underline text-white",
          style=f"background:{CTA if highlight else LONG};"),
        cls="card rounded-xl p-6" + (" ring-1" if highlight else ""),
        style=(f"border-color:{CTA};" if highlight else ""),
    )


def pricing_page():
    return landing_page(
        Div(Div(
            H1("Pricing", cls="text-4xl md:text-5xl font-bold tightest text-center mb-4", style=f"color:{INK};"),
            P("Start free on paper. Bring your own Alpaca keys.",
              cls="text-center", style=f"color:{INK_MUTED};"),
            cls="max-w-4xl mx-auto px-4 sm:px-6 pt-16 pb-8 text-center",
        ), cls="hero-gradient"),
        Div(Div(
            _price_card("Research", "$0", "/mo", [
                "Backtesting on delayed data", "Full strategy library", "50 AI queries / month", "Community support"]),
            _price_card("Trader", "$29", "/mo", [
                "Everything in Research", "Live Alpaca paper trading", "Reproducible backtest artifacts",
                "Validation & reconciliation", "Unlimited AI queries"], highlight=True),
            _price_card("Desk", "Contact", "us", [
                "Everything in Trader", "Multi-account & team", "Priority support", "Custom strategies"]),
            cls="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-5xl mx-auto px-4 sm:px-6 pb-10",
        )),
        cta_section(),
        active="pricing", title="Pricing — AlpaTrade",
    )

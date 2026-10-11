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

Pricing: AlpaTrade is free for everyone for now, so there is no public Pricing page;
``/pricing`` permanently redirects to the home page's Hedge Funds section.
"""
from __future__ import annotations

from fasthtml.common import (
    Code, Em, Details, Summary, Ol, Li,
    A, Button, Div, Footer, H1, H2, H3, Img, Main, Nav, NotStr, P, Picture, Section, Source, Span, Strong, Style, Script,
)
from starlette.responses import RedirectResponse

from engine.agents.catalog import AGENT_CATALOG_ENTRIES
from engine.web.ph_layout import head, TILE_MARK

SITE_NAME = "AlpaTrade"
SITE_TAGLINE = "Backtest, paper-trade and prove the P&L — one AI trading desk on Alpaca."

# Public teaser for the signed-in /hedge-funds page: a real screenshot of that page
# (static assets, regenerated with scripts/hedge_funds_snapshot.py). The CTA links to
# /hedge-funds itself, which requires sign-in and bounces signed-out visitors to
# /signin?next=/hedge-funds — so after auth they land on the page.
HEDGE_FUNDS_HREF = "/hedge-funds"
HEDGE_FUNDS_ANCHOR = "/#hedge-funds"
HF_IMG_DESKTOP = "/static/landing/hedge-funds-desktop.png"
HF_IMG_MOBILE = "/static/landing/hedge-funds-mobile.png"
HF_IMG_ALT = ("Screenshot of the AlpaTrade Hedge Funds page: 13F-implied estimated annual returns "
              "for well-known hedge funds compared with SPY, and a screener over 13F filers' "
              "holdings with filters for quarter, AUM and positions.")

# The mobile pipeline publishes this asset on each release and marks it latest.
# GitHub resolves the stable URL, so the landing needs no version-specific edits.
_APK_DOWNLOAD_URL = (
    "https://github.com/predictivelabsai/alpatrade-mobile/"
    "releases/latest/download/alpatrade-latest.apk"
)


def latest_apk_url() -> str:
    """Canonical signed Android download, maintained by the mobile release pipeline."""
    return _APK_DOWNLOAD_URL


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
.lp-brand .mark { display: inline-flex; align-items: center; }
.lp-brand .mark .tile-mark { width: 1.5rem; height: 1.5rem; }
.lp-brand .badge { font-size: .58rem; font-weight: 600; color: var(--accent); background: var(--accent-dim);
  padding: .12rem .4rem; border-radius: 4px; letter-spacing: .08em; text-transform: uppercase; }
.lp-nav-links { display: flex; align-items: center; gap: 1.75rem; }
.lp-nav-link { font-size: .85rem; color: var(--ink-muted); }
.lp-nav-link:hover, .lp-nav-link.active { color: var(--ink); }
.lp-nav-cta { display: flex; align-items: center; gap: .55rem; }
.lp-nav-lb { display: none; font-size: .82rem; font-weight: 500; color: var(--ink-muted);
  padding: .5rem .35rem; min-height: 44px; align-items: center; }
.lp-nav-lb:hover, .lp-nav-lb.active { color: var(--accent); }
.lp-lb-link { display: inline-flex; align-items: center; gap: .2rem; margin-top: 1.1rem; font-size: .9rem;
  font-weight: 500; color: var(--accent); }
.lp-lb-link:hover { text-decoration: underline; text-underline-offset: 3px; }

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

/* how it works: systematic trading primer */
.lp-primer { margin-top: 2.5rem; max-width: 760px; }
.lp-primer-h { font-size: 1.15rem; font-weight: 600; letter-spacing: -.01em; color: var(--ink); }
.lp-primer-p { font-size: .92rem; line-height: 1.6; color: var(--ink-muted); margin-top: .7rem; }
.lp-pieces { display: grid; grid-template-columns: repeat(4, 1fr); gap: .6rem; margin-top: 1rem; }
.lp-piece { border: 1px solid var(--line); border-radius: .75rem; padding: .7rem .8rem; background: var(--bg-elev); }
.lp-piece .k { font-family: var(--font-mono); font-size: .72rem; letter-spacing: .12em; text-transform: uppercase; color: var(--accent); }
.lp-piece .v { font-size: .84rem; color: var(--ink); margin-top: .25rem; }
.lp-origins { margin-top: 1.2rem; }
.lp-origins summary { cursor: pointer; font-weight: 600; color: var(--ink); font-size: .92rem; }
.lp-timeline { list-style: none; padding: 0; margin: .7rem 0 0; border-left: 2px solid var(--line); }
.lp-timeline li { position: relative; padding: .3rem 0 .3rem 1rem; font-size: .86rem; line-height: 1.5; color: var(--ink-muted); }
.lp-timeline li::before { content: ""; position: absolute; left: -5px; top: .75rem; width: 8px; height: 8px; border-radius: 99px; background: var(--accent); }
.lp-timeline .y { font-family: var(--font-mono); color: var(--ink); font-weight: 600; margin-right: .55rem; }
.lp-through { color: var(--ink); font-weight: 500; }
.lp-alpa { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: var(--bg-elev); }
.lp-alpa-inner { max-width: 1160px; margin: 0 auto; padding: 3.5rem 1.5rem; text-align: center; }
.lp-alpa-word { font-size: clamp(3rem, 9vw, 6.5rem); font-weight: 700; line-height: 1.05; letter-spacing: -.02em; margin-top: .9rem; color: var(--ink); }
.lp-alpa-word .dev { color: var(--accent); font-family: "Noto Sans Devanagari", "Mangal", "Kohinoor Devanagari", var(--font-sans, sans-serif); }
.lp-alpa-word .dot { color: var(--ink-muted); font-weight: 400; }
.lp-alpa-gloss { font-family: var(--font-mono); font-size: .9rem; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-muted); margin-top: .6rem; }
.lp-alpa-line { font-size: clamp(1.35rem, 3vw, 2.1rem); line-height: 1.3; font-weight: 500; letter-spacing: -.01em; color: var(--ink); max-width: 28ch; margin: 1.2rem auto 0; }
@media (max-width: 640px) { .lp-pieces { grid-template-columns: repeat(2, 1fr); } }
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
.lp-brokers { display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
  gap: 1rem 2rem; padding-top: 1.4rem; padding-bottom: 1.4rem; }
.lp-brokers-label { font-family: var(--font-mono); font-size: .68rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ink-dim); }
.lp-brokers-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
  gap: 1rem 2.25rem; max-width: 100%; }
.lp-broker { display: inline-flex; align-items: center; height: 28px; }
.lp-broker img { height: 100%; width: auto; max-width: 150px; object-fit: contain;
  filter: grayscale(1) contrast(.9); opacity: .6; transition: filter .18s ease, opacity .18s ease; }
.lp-broker:hover img, .lp-broker:focus-visible img { filter: none; opacity: 1; }
#cli .dev-agent { min-width: 0; }
#cli .dev-agent-body, #cli .dev-agent-body code { overflow-wrap: anywhere; }
#cli .lp-terminal { max-width: 100%; overflow-wrap: anywhere; }
.dev-cli-note { margin-top: .6rem; font-size: .74rem; color: var(--ink-dim); font-style: italic; }

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
.lp-card-link { color: inherit; }
.lp-card-link .lp-card { min-height: 12rem; }
.lp-card-link:hover .title { color: var(--accent); }
.lp-code { margin-top: 1.5rem; padding: 1rem 1.15rem; background: var(--ink); color: var(--bg);
  border-radius: .75rem; font-family: var(--font-mono); font-size: .82rem; overflow-x: auto; }

/* developer portal */
.dev-actions { display: flex; flex-wrap: wrap; gap: .7rem; margin-top: 1.5rem; }
.dev-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-top: 2rem; }
.dev-stat { padding: 1rem 1.1rem; border: 1px solid var(--line); border-radius: .75rem;
  background: var(--bg-elev); }
.dev-stat strong { display: block; color: var(--ink); font-size: 1.35rem; }
.dev-stat span { color: var(--ink-muted); font-size: .76rem; }
.dev-group + .dev-group { margin-top: 3rem; }
.dev-group-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem;
  margin-bottom: 1rem; }
.dev-group-title { color: var(--ink); font-size: 1.15rem; font-weight: 600; }
.dev-group-count { color: var(--ink-dim); font: .68rem var(--font-mono); text-transform: uppercase;
  letter-spacing: .1em; }
.dev-agent-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.dev-agent { padding: 1.35rem; border: 1px solid var(--line); border-radius: .9rem;
  background: var(--bg-elev); }
.dev-agent-top { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
.dev-agent-name { color: var(--ink); font-size: 1rem; font-weight: 600; }
.dev-method { flex-shrink: 0; padding: .16rem .45rem; border-radius: .3rem;
  background: var(--accent-dim); color: var(--accent); font: 600 .66rem var(--font-mono); }
.dev-agent-body { color: var(--ink-muted); font-size: .82rem; line-height: 1.5; margin-top: .5rem; }
.dev-endpoint { margin-top: .8rem; color: var(--ink); font: .7rem var(--font-mono);
  overflow-wrap: anywhere; }
.dev-skills { display: flex; flex-wrap: wrap; gap: .38rem; margin-top: .85rem; }
.dev-skill { padding: .2rem .45rem; border: 1px solid var(--line); border-radius: 999px;
  color: var(--ink-muted); background: var(--bg); font-size: .67rem; }
.dev-meta { display: flex; flex-wrap: wrap; align-items: center; gap: .55rem; margin-top: .9rem;
  color: var(--ink-dim); font: .64rem var(--font-mono); }
.dev-meta a { margin-left: auto; color: var(--accent); }
.dev-contracts { margin-top: 1.5rem; color: var(--ink-muted); font-size: .8rem; line-height: 1.7; }
.dev-contracts a { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }

/* hedge funds teaser */
.lp-hf { scroll-margin-top: 4.5rem; }
.lp-hf-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 1.25rem; }
.lp-hf-head .lp-lede { margin-top: 1rem; }
.lp-hf-shot { display: block; margin-top: 2rem; border: 1px solid var(--line); border-radius: 1rem;
  overflow: hidden; background: var(--bg-elev); box-shadow: 0 10px 44px rgba(0,0,0,.07);
  transition: border-color .18s ease; }
.lp-hf-shot:hover { border-color: var(--accent); }
.lp-hf-shot img { display: block; width: 100%; height: auto; max-width: 100%; }
.lp-hf-cta { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem 1rem; margin-top: 1.4rem; }
.lp-hf-note { font-size: .8rem; color: var(--ink-dim); }

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
.lp-footer-apps { display: flex; align-items: center; gap: 1rem; margin: 1.75rem 0 .5rem; flex-wrap: wrap; }
.apk-badge-label { font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; color: var(--ink-dim); font-family: var(--font-mono); }
.apk-badge { display: inline-flex; align-items: center; gap: .6rem; padding: .5rem 1rem; border: 1px solid var(--line-br); border-radius: .7rem; background: var(--bg); color: var(--ink); text-decoration: none; transition: all .15s; }
.apk-badge:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
.apk-badge-ic { display: inline-flex; color: var(--accent); }
.apk-badge-txt { display: flex; flex-direction: column; line-height: 1.12; text-align: left; }
.apk-badge-top { font-size: .58rem; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-dim); }
.apk-badge-big { font-size: .95rem; font-weight: 600; }
.lp-fine { font-size: .72rem; line-height: 1.55; color: var(--ink-dim); max-width: 60rem;
  margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid var(--line); }

.lp-burger { display: none; width: 40px; height: 40px; align-items: center; justify-content: center;
  border: 1px solid var(--line); border-radius: 10px; background: transparent; color: var(--ink);
  cursor: pointer; padding: 0; }
.lp-burger.open { background: var(--line); }
.lp-menu { display: none; }
@media (max-width: 960px) {
  .lp-burger { display: inline-flex; }
  .lp-menu:not([hidden]) { display: flex; flex-direction: column; padding: .4rem 1rem 1rem;
    border-top: 1px solid var(--line); background: var(--bg, #fff); max-height: calc(100vh - 4rem);
    overflow-y: auto; box-shadow: 0 12px 24px rgba(0,0,0,.08); }
  .lp-menu-link { padding: .8rem .25rem; font-size: 1rem; color: var(--ink);
    border-bottom: 1px solid var(--line); }
  .lp-menu-link:last-child { border-bottom: 0; }
  .lp-menu-link.active { color: var(--accent); font-weight: 600; }
  .lp-nav-links { display: none; }
  .lp-nav-lb { display: inline-flex; }
  .lp-grid.c5 { grid-template-columns: repeat(2, 1fr); }
  .lp-grid.c3 { grid-template-columns: 1fr; }
  .dev-summary { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
  .lp-grid.c5 { grid-template-columns: 1fr; }
  .lp-nav-cta .lp-btn.ghost { display: none; }
  .lp-nav-lb { display: none; }
  .lp-nav-inner { padding: 0 1rem; }
  .lp-nav-cta { gap: .35rem; }
  .dev-agent-grid, .dev-summary { grid-template-columns: 1fr; }
  .lp-brokers-row { gap: .9rem 1.5rem; }
  .lp-broker { height: 22px; }
  .lp-broker img { max-width: 110px; }
  .dev-group-head { align-items: flex-start; flex-direction: column; gap: .25rem; }
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
    ("01", "Describe a strategy",
     "Start from Buy-the-Dip, VIX, Momentum, Box-Wedge or any leaderboard skill, and pick your "
     "universe. Every rule is written down: entry, exit, size and risk."),
    ("02", "Fine-tune the parameters with AI",
     "Chat with the desk: the AI proposes dip thresholds, stops, targets and hold times, sweeps "
     "the grid on real Alpaca data and explains what moved the result and why."),
    ("03", "Walk-forward, then go live",
     "Re-test the chosen settings on unseen data, paper-trade them, then run them live in a "
     "cash-only sleeve of your own account, with every fill validated and the P&L reported."),
]

PRIMER_PIECES = [
    ("Signal", "When to enter and exit."),
    ("Sizing", "How much to trade each time."),
    ("Risk", "Stops, exposure caps, limits."),
    ("Execution", "How orders reach the market."),
]

PRIMER_TIMELINE = [
    ("1730", "Dojima rice exchange, Osaka: the roots of candlestick charting."),
    ("1900", "Bachelier models prices as a random walk."),
    ("1952", "Markowitz turns diversification into mathematics."),
    ("1969", "Thorp's Princeton Newport runs quantitative arbitrage."),
    ("1970s", "After 1971, trend-following CTAs (Campbell, Millburn, later AHL, Winton, Aspect); Bridgewater founded 1975."),
    ("1980s", "Renaissance (1982); the Turtles learn rules, not instinct (1983–84); Tartaglia's stat-arb desk at Morgan Stanley; D.E. Shaw."),
    ("Today", "Smart beta and high-frequency trading bring rules to every corner of the market."),
]

# "Works with" broker row (replaces the old stats stripe, 2026-10-10). Official logo files
# are vendored under static/brokers/ (never hotlinked): (name, site, logo path).
BROKERS = [
    ("LHV", "https://www.lhv.ee", "/static/brokers/lhv.svg"),
    ("Alpaca", "https://alpaca.markets", "/static/brokers/alpaca.svg"),
    ("Interactive Brokers", "https://www.interactivebrokers.com", "/static/brokers/ibkr.svg"),
    ("Saxo Bank", "https://www.home.saxo", "/static/brokers/saxo.svg"),
    ("moomoo", "https://www.moomoo.com", "/static/brokers/moomoo.png"),
]

# Example CLI session shown on /developers. Figures are illustrative, not a live result.
CLI_EXAMPLE = {
    "cmd": "alpatrade backtest paper btd-7dp-05sl-1tp-1d-3m",
    "out": "42 trades · win-rate 61% · Sharpe 1.34 · max DD -6.2%",
    "artifacts": "backtest-results/2026-…_AAPL_buy_the_dip_1d/",
}


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
    return A(Span(NotStr(TILE_MARK), cls="mark"), Span(SITE_NAME), Span("beta", cls="badge"),
             href="/", cls="lp-brand")


def _nav(active="home"):
    def link(label, href, key):
        return A(label, href=href, cls="lp-nav-link" + (" active" if key == active else ""))
    return Nav(
        Div(
            _brand(),
            Div(link("Platform", "/platform", "platform"),
                link("Leaderboard", "/leaderboard", "leaderboard"),
                link("Hedge Funds", HEDGE_FUNDS_ANCHOR, "hedgefunds"),
                link("Developers", "/developers", "developers"),
                cls="lp-nav-links"),
            Div(A("Leaderboard", href="/leaderboard",
                  cls="lp-nav-lb" + (" active" if active == "leaderboard" else "")),
                _btn("Sign in", "/signin", "ghost", sm=True),
                _btn("Start", "/register", "primary", sm=True, arrow=True),
                Button(NotStr(_BURGER_SVG), type="button", cls="lp-burger", id="lp-burger",
                       aria_label="Open menu", aria_expanded="false", aria_controls="lp-menu"),
                cls="lp-nav-cta"),
            cls="lp-nav-inner",
        ),
        Div(*[A(label, href=href, cls="lp-menu-link" + (" active" if key == active else ""))
              for label, href, key in MOBILE_MENU],
            id="lp-menu", cls="lp-menu", hidden=True),
        Script(_BURGER_JS),
        cls="lp-nav",
    )


# Mobile hamburger (≤960px; desktop nav unchanged). Same pattern as carhero's
# .mobile-menu-btn: 3-line SVG, 40×40 tap target, hidden on desktop.
MOBILE_MENU = [
    ("Platform", "/platform", "platform"),
    ("Leaderboard", "/leaderboard", "leaderboard"),
    ("Hedge Funds", HEDGE_FUNDS_ANCHOR, "hedgefunds"),
    ("Developers", "/developers", "developers"),
    ("Open app / Chat", "/app", "app"),
    ("Profile", "/profile", "profile"),
    ("Sign in", "/signin", "signin"),
    ("Start — create account", "/register", "register"),
]
_BURGER_SVG = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="2" aria-hidden="true"><line x1="3" y1="6" x2="21" y2="6"/>'
               '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>')
_BURGER_JS = """(function(){var b=document.getElementById('lp-burger'),m=document.getElementById('lp-menu');
if(!b||!m)return;function set(o){m.hidden=!o;b.setAttribute('aria-expanded',o?'true':'false');
b.setAttribute('aria-label',o?'Close menu':'Open menu');b.classList.toggle('open',o);}
b.addEventListener('click',function(e){e.stopPropagation();set(m.hidden);});
m.addEventListener('click',function(e){if(e.target.closest('a'))set(false);});
document.addEventListener('click',function(e){if(!m.hidden&&!m.contains(e.target))set(false);});
document.addEventListener('keydown',function(e){if(e.key==='Escape')set(false);});
window.addEventListener('resize',function(){if(window.innerWidth>960)set(false);});})();"""


_ANDROID_SVG = (
    '<svg viewBox="0 0 24 24" width="26" height="26" fill="currentColor" aria-hidden="true">'
    '<path d="M17.6 9.48l1.84-3.18a.4.4 0 0 0-.69-.4l-1.86 3.23a11.4 11.4 0 0 0-9.78 0L5.25 5.9a.4.4 0 1 0-.69.4L6.4 9.48'
    'A10.8 10.8 0 0 0 1 18.13h22a10.8 10.8 0 0 0-5.4-8.65zM7 15.25a1.1 1.1 0 1 1 1.1-1.1 1.1 1.1 0 0 1-1.1 1.1zm10 0a1.1 '
    '1.1 0 1 1 1.1-1.1 1.1 1.1 0 0 1-1.1 1.1z"/></svg>'
)


def apk_badge():
    """Unigox-style 'GET & INSTALL / APK for Android' download badge."""
    return A(
        Span(NotStr(_ANDROID_SVG), cls="apk-badge-ic"),
        Span(Span("GET & INSTALL", cls="apk-badge-top"),
             Span("APK for Android", cls="apk-badge-big"), cls="apk-badge-txt"),
        href="/download/android", cls="apk-badge",
        title="Download the AlpaTrade Android app (APK)",
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
                    A("Leaderboard", href="/leaderboard"),
                    A("Hedge Funds", href=HEDGE_FUNDS_ANCHOR),
                    A("Developers", href="/developers"),
                    A("Sign in", href="/signin"),
                    A("Start free", href="/register"),
                    cls="lp-footer-links",
                ),
                cls="lp-footer-top",
            ),
            Div(Span("Get the mobile app", cls="apk-badge-label"), apk_badge(),
                cls="lp-footer-apps"),
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
            H1(Span("Systematic trading", cls="lp-accent"), Span(", reimagined."), cls="lp-h1"),
            P("A squad of specialist AI analysts on Alpaca — they screen and research the market, "
              "backtest strategies across a parameter grid, paper-trade the winners live, then validate "
              "every fill and report the P&L. Chat-first, from ticker to track record.",
              cls="lp-lede"),
            Div(_btn("Start free", "/register", "primary", arrow=True),
                _btn("Sign in", "/signin", "ghost"),
                _btn("Continue with Google", "/login", "google", google=True),
                cls="lp-cta-row"),
            A(Span("◆ "), Span("See live strategies on the Leaderboard"), Span(" →"),
              href="/leaderboard", cls="lp-lb-link"),
            cls="lp-hero-inner",
        ),
        cls="lp-hero",
    )


def _alpa():
    """Name origin, right under the hero (Julian, 2026-10-10)."""
    return Section(
        Div(Span("Why AlpaTrade?", cls="lp-eyebrow"),
            Div(Span("अल्प", cls="dev", lang="sa"), Span(" · ", cls="dot"), Span("alpa", cls="lat"),
                cls="lp-alpa-word"),
            Div("Sanskrit for “little”", cls="lp-alpa-gloss"),
            P("It ties into the idea of small, disciplined edges compounding over time.",
              cls="lp-alpa-line"),
            cls="lp-alpa-inner"),
        id="why-alpatrade", cls="lp-alpa",
    )


def _stats():
    """'Works with' broker logo row (same spot as the old stats stripe)."""
    return Div(
        Div(Span("Works with", cls="lp-brokers-label"),
            Div(*[A(Img(src=logo, alt=f"{name} logo", loading="lazy"),
                    href=site, target="_blank", rel="noopener noreferrer",
                    title=name, cls="lp-broker")
                  for name, site, logo in BROKERS], cls="lp-brokers-row"),
            cls="lp-stats-inner lp-brokers"),
        cls="lp-stats",
    )


def _cli_section():
    ex = CLI_EXAMPLE
    return Section(
        Span("Command line", cls="lp-eyebrow"),
        H2("Backtest from your terminal.", cls="lp-h2", style="margin-top:.75rem"),
        P("The alpatrade CLI runs the same backtester as the web desk and writes every run to a "
          "dated folder you can diff, re-run and share.", cls="lp-lede", style="margin-top:1rem"),
        Div(
            Div(Span("$ ", cls="dim"), Span(ex["cmd"], cls="cmd"), cls="row"),
            Div(Span("→ " + ex["out"], cls="out"), cls="row"),
            Div(Span("→ artifacts → " + ex["artifacts"], cls="dim"), cls="row"),
            cls="lp-terminal",
        ),
        P("Example output — illustrative figures, not a live result.", cls="dev-cli-note"),
        Div(
            Div(H3("Command name format", cls="dev-group-title"),
                P(Code("btd-7dp-05sl-1tp-1d-3m"), " reads as: ", Strong("btd"),
                  " buy-the-dip strategy · ", Strong("7dp"), " 7% dip threshold · ",
                  Strong("05sl"), " 0.5% stop-loss · ", Strong("1tp"), " 1% take-profit · ",
                  Strong("1d"), " 1-day hold · ", Strong("3m"), " 3-month lookback. "
                  "Pattern: {strategy}-{param}-…-{lookback}; 0.5% is written 05.",
                  cls="dev-agent-body"),
                cls="dev-agent"),
            Div(H3("The artifacts folder", cls="dev-group-title"),
                P("Each run lands in ", Code("backtest-results/<date>_<symbol>_<strategy>_<interval>/"),
                  ": config.json and strategy_spec.json (parameters), "
                  "trades.csv and round_trips.csv, equity.csv with a benchmark curve, summary.json "
                  "(trades, win-rate, Sharpe, max drawdown), data_fingerprint.json and fee_source.json, "
                  "report.md / notes.md, and a run.py that reproduces the run.", cls="dev-agent-body"),
                cls="dev-agent"),
            cls="dev-agent-grid", style="margin-top:1.5rem",
        ),
        id="cli", cls="lp-section lp-bordered",
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
        Span("How it works?", cls="lp-eyebrow"),
        H2("You set the rules. AI helps you tune them.", cls="lp-h2",
           style="margin-top:.75rem;max-width:24ch"),
        Div(*[Div(Div(num, cls="num"), Div(title, cls="title"), Div(body, cls="body"), cls="lp-card")
              for num, title, body in STEPS], cls="lp-grid c3"),
        _primer(),
        id="how-it-works",
        cls="lp-section lp-bordered",
    )


def _primer():
    """Condensed 'what is systematic trading' summary (brief from Julian, 2026-10-10)."""
    return Div(
        H3("Systematic trading, in short", cls="lp-primer-h"),
        P("Trading by fixed rules instead of in-the-moment judgment. Entries, exits, position size and "
          "risk limits are set in advance and applied the same way every time, so the same signal gives "
          "the same decision whether you are confident, scared or away from the screen. "
          "It is rule-based; ", Em("algorithmic"), " is just the delivery, the rules coded so a computer "
          "places the orders (many early systems were run by hand).", cls="lp-primer-p"),
        Div(*[Div(Div(k, cls="k"), Div(v, cls="v"), cls="lp-piece") for k, v in PRIMER_PIECES],
            cls="lp-pieces"),
        P("Unlike discretionary trading, a system is backtested on history first and only then traded "
          "live. Common styles: trend following, mean reversion, carry, statistical arbitrage and "
          "volatility strategies.", cls="lp-primer-p"),
        Details(Summary("Origins: from rice charts to Medallion"),
                Ol(*[Li(Span(y, cls="y"), Span(t)) for y, t in PRIMER_TIMELINE], cls="lp-timeline"),
                open=True, cls="lp-origins"),
        P("The through-line: explicit, testable rules beat in-the-moment judgment.",
          cls="lp-primer-p lp-through"),
        cls="lp-primer",
    )


def _hedge_funds():
    """Hedge Funds teaser: real snapshot of the signed-in page + a sign-in-gated CTA."""
    return Section(
        Div(
            Div(
                Span("Hedge Funds", cls="lp-eyebrow"),
                H2("See what the big funds hold — and how it performed.", cls="lp-h2",
                   style="margin-top:.75rem;max-width:26ch"),
                P("13F holdings for every filer: screen by quarter, AUM and position, follow "
                  "well-known funds, and compare their estimated annual returns with SPY. "
                  "Free for everyone — just sign in.", cls="lp-lede"),
            ),
            cls="lp-hf-head",
        ),
        A(
            Picture(
                Source(media="(max-width: 560px)", srcset=HF_IMG_MOBILE, width="800", height="1159"),
                Img(src=HF_IMG_DESKTOP, alt=HF_IMG_ALT, width="1600", height="982",
                    loading="lazy", decoding="async"),
            ),
            href=HEDGE_FUNDS_HREF, cls="lp-hf-shot", aria_label="Open the Hedge Funds page",
        ),
        Div(_btn("See more", HEDGE_FUNDS_HREF, "primary", arrow=True),
            Span("Sign in or create a free account to open the full Hedge Funds page.",
                 cls="lp-hf-note"),
            cls="lp-hf-cta"),
        id="hedge-funds",
        cls="lp-section lp-bordered lp-hf",
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
        _hero(), _alpa(), _stats(), _how(), _hedge_funds(), _pillars(), _cta_band(),
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
            _btn("See Hedge Funds", HEDGE_FUNDS_ANCHOR, "ghost"),
            cls="lp-cta-row"),
        cls="lp-hero-inner",
    )
    return _shell(
        "Platform — AlpaTrade",
        Section(hero, cls="lp-hero"),
        _stats(), _pillars(), _how(), _cta_band(),
        active="platform",
    )


def developers_page():
    docs = [
        ("Agent reference", "Browse agent skills, request schemas, responses, and safety boundaries.",
         "https://api.alpatrade.chat/redoc#tag/agent-invocation", "Agent API docs →"),
        ("Swagger UI", "Authorize, compose requests, and call every typed endpoint interactively.",
         "https://api.alpatrade.chat/docs#/agent-invocation", "Open API explorer →"),
        ("Complete ReDoc", "Search the complete, grouped API contract in a clean reference layout.",
         "https://api.alpatrade.chat/redoc", "Browse all endpoints →"),
    ]

    def doc_card(title, body, href, label):
        return A(
            Div(
                Div("API", cls="num"),
                Div(title, cls="title"),
                Div(body, cls="body"),
                Div(label, cls="prefix"),
                cls="lp-card",
            ),
            href=href,
            target="_blank",
            rel="noopener noreferrer",
            cls="lp-card-link",
        )

    def agent_card(agent):
        reference = "https://api.alpatrade.chat/redoc#tag/agent-invocation"
        return Div(
            Div(
                H3(agent["name"], cls="dev-agent-name"),
                Span(agent["method"], cls="dev-method"),
                cls="dev-agent-top",
            ),
            P(agent["description"], cls="dev-agent-body"),
            Div(f'{agent["method"]} {agent["path"]}', cls="dev-endpoint"),
            Div(*[Span(skill, cls="dev-skill") for skill in agent["skills"]],
                cls="dev-skills"),
            Div(
                Span(agent["access"]),
                Span("·"),
                Span(agent["execution"]),
                Span("·"),
                Span(agent["safety"].replace("_", " ")),
                A("Schema & examples →", href=reference, target="_blank",
                  rel="noopener noreferrer"),
                cls="dev-meta",
            ),
            cls="dev-agent",
        )

    category_labels = {
        "assistant": "DeepAgent interfaces",
        "research": "Research agents",
        "analysis": "Analysis and validation",
        "trading": "Paper trading operations",
        "orchestration": "Agent orchestration",
    }
    grouped_agents = []
    for category, label in category_labels.items():
        agents = [agent for agent in AGENT_CATALOG_ENTRIES
                  if agent["category"] == category]
        grouped_agents.append(
            Div(
                Div(H3(label, cls="dev-group-title"),
                    Span(f"{len(agents)} agent{'s' if len(agents) != 1 else ''}",
                         cls="dev-group-count"),
                    cls="dev-group-head"),
                Div(*[agent_card(agent) for agent in agents], cls="dev-agent-grid"),
                cls="dev-group",
            )
        )

    hero = Section(
        Span("Developers", cls="lp-eyebrow"),
        H1("Build on the AlpaTrade agent desk.", cls="lp-h1"),
        P("Call the primary LangChain DeepAgent, research analysts, backtester, validator, "
          "paper trader, reconciler, reporter, and durable autonomy pipeline through typed APIs.",
          cls="lp-lede"),
        Div("https://api.alpatrade.chat", cls="lp-code"),
        Div(
            _btn("Agent API reference", "https://api.alpatrade.chat/redoc#tag/agent-invocation"),
            _btn("Try in Swagger", "https://api.alpatrade.chat/docs#/agent-invocation", "ghost"),
            cls="dev-actions",
        ),
        Div(
            Div(Strong(str(len(AGENT_CATALOG_ENTRIES))), Span("callable agent interfaces"),
                cls="dev-stat"),
            Div(Strong(str(len(category_labels))), Span("capability groups"), cls="dev-stat"),
            Div(Strong("2"), Span("JWT and service-key auth modes"), cls="dev-stat"),
            Div(Strong("Paper"), Span("trading safety boundary"), cls="dev-stat"),
            cls="dev-summary",
        ),
        cls="lp-hero-inner",
    )
    catalogue = Section(
        Span("Agent catalogue", cls="lp-eyebrow"),
        H2("Choose the right specialist for the job.", cls="lp-h2",
           style="margin-top:.75rem"),
        P("Every agent below is callable through a typed HTTP contract. Skills describe stable "
          "capabilities; follow the reference link for request bodies, response schemas, examples, "
          "authentication, and error responses.", cls="lp-lede", style="margin-top:1rem"),
        Div(*grouped_agents, style="margin-top:2.5rem"),
        cls="lp-section lp-bordered",
    )
    contracts = Section(
        Span("Documentation", cls="lp-eyebrow"),
        H2("Human guides and machine contracts.", cls="lp-h2", style="margin-top:.75rem"),
        P("Use ReDoc for reading and Swagger UI for interactive calls. OpenAPI and catalogue "
          "JSON remain machine-readable for SDK generators, agents, and service discovery.",
          cls="lp-lede", style="margin-top:1rem"),
        Div(*[doc_card(*item) for item in docs], cls="lp-grid c3"),
        P(
            "Machine-readable: ",
            A("OpenAPI JSON", href="https://api.alpatrade.chat/openapi.json",
              target="_blank", rel="noopener noreferrer"),
            " · ",
            A("Agent catalogue JSON", href="https://api.alpatrade.chat/v2/agents",
              target="_blank", rel="noopener noreferrer"),
            cls="dev-contracts",
        ),
        cls="lp-section lp-bordered",
    )
    access = Section(
        Span("Authentication", cls="lp-eyebrow"),
        H2("User JWTs and service API keys.", cls="lp-h2", style="margin-top:.75rem"),
        P("User clients send an Authorization bearer token obtained from /auth/login. Trusted "
          "services send X-API-Key and include X-User-Id when acting for a user. All trading and "
          "autonomy routes are paper-only.", cls="lp-lede"),
        cls="lp-section lp-bordered",
    )
    return _shell(
        "Developers — AlpaTrade API",
        Section(hero, cls="lp-hero"),
        _cli_section(),
        catalogue,
        contracts,
        access,
        active="developers",
    )


# --------------------------------------------------------------------------- register
def register(app, rt):
    """Wire the anonymous marketing routes. Returns the list of paths registered."""

    @rt("/")
    def landing_home():
        return home_page()

    @rt("/platform")
    def landing_platform(session):
        return platform_page()

    @rt("/pricing")
    def landing_pricing():
        # No public pricing — AlpaTrade is free for everyone for now.
        return RedirectResponse(HEDGE_FUNDS_ANCHOR, status_code=301)

    @rt("/developers")
    def landing_developers(session):
        return developers_page()

    @rt("/download/android")
    def download_android():
        # Always resolves to the newest release's APK — no need to update the link per version.
        return RedirectResponse(latest_apk_url(), status_code=302)

    return ["/", "/platform", "/pricing", "/developers", "/download/android"]

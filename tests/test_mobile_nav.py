"""Mobile hamburger menu in the public top nav (≤960px); desktop links unchanged."""
from fasthtml.common import to_xml

from engine.web import ph_landing as lp


def _html(active="home"):
    return to_xml(lp._nav(active))


def test_desktop_nav_unchanged():
    h = _html()
    links = h[h.index("lp-nav-links"):h.index("lp-nav-cta")]
    for label in ("Platform", "Leaderboard", "Hedge Funds", "Developers"):
        assert label in links
    assert "Sign in" in h and "/register" in h


def test_burger_button_and_menu_items():
    h = _html("leaderboard")
    assert "id=\"lp-burger\"" in h and 'aria-controls="lp-menu"' in h and 'aria-expanded="false"' in h
    assert '<div hidden id="lp-menu"' in h                         # closed by default
    menu = h[h.index('id="lp-menu"'):]
    for label, href in (("Leaderboard", "/leaderboard"), ("Hedge Funds", lp.HEDGE_FUNDS_ANCHOR),
                        ("Open app / Chat", "/app"), ("Profile", "/profile"),
                        ("Sign in", "/signin"), ("Developers", "/developers"), ("Platform", "/platform")):
        assert label in menu and f'href="{href}"' in menu
    assert 'href="/leaderboard" class="lp-menu-link active"' in menu
    assert "getElementById('lp-burger')" in h


def test_css_hides_burger_on_desktop():
    css = lp.LANDING_CSS
    assert ".lp-burger { display: none;" in css
    mob = css[css.index("@media (max-width: 960px)"):]
    assert ".lp-burger { display: inline-flex; }" in mob.split("}\n@media")[0] or ".lp-burger { display: inline-flex; }" in mob

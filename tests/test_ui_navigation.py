from fastcore.xml import to_xml

from engine.web.ph_layout import PH_JS, _left_pane


def test_sidebar_sections_are_collapsed_by_default():
    html = to_xml(_left_pane("guide", None))

    for section in ("Explore", "Chats", "Agents", "Tools", "Public Markets", "Research", "Admin"):
        assert f'<span class="nav-section-name">{section}</span>' in html
    assert '<details class="nav-section" open' not in html
    assert 'class="nav-section-expand">&gt;' in html
    assert 'class="nav-section-collapse">&lt;' in html


def test_fill_chat_redirects_non_chat_pages_with_pending_prompt():
    assert "sessionStorage.setItem('alpatrade.pendingPrompt',t)" in PH_JS
    assert "window.location.href='/app'" in PH_JS
    assert "sessionStorage.removeItem('alpatrade.pendingPrompt')" in PH_JS


def test_public_market_pages_are_registered_in_their_own_section():
    import app  # registers feature modules
    from engine.web import ph_layout

    paths = {href for _label, href, _key in ph_layout.PUBLIC_PAGES}
    assert {"/ipo-map", "/ipo-pipeline", "/index-options"} <= paths
    assert "/ipo-map" not in {href for _label, href, _key in ph_layout.EXPLORE_PAGES}


def test_research_pages_have_separate_submenu_entries():
    import app
    from engine.web import ph_layout

    paths = {href for _label, href, _key in ph_layout.RESEARCH_PAGES}
    assert paths == {
        "/research/premarket", "/research/models", "/research/news",
        "/research/timing", "/research/history",
    }

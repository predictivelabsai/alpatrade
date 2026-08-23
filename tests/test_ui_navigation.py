import inspect
from pathlib import Path

from fasthtml.common import Div
from fastcore.xml import to_xml

from engine.web.ph_layout import PH_JS, _left_pane, chat_center, page


def test_sidebar_sections_are_collapsed_by_default():
    html = to_xml(_left_pane("guide", None))

    for section in ("Explore", "Chats", "Agents", "Monitoring",
                    "Tools", "Public Markets", "Research", "Admin"):
        assert f'<span class="nav-section-name">{section}</span>' in html
    assert '<details class="nav-section" open' not in html
    assert 'class="nav-section-expand">&gt;' in html
    assert 'class="nav-section-collapse">&lt;' in html
    assert 'href="/dashboard"' in html


def test_sidebar_alpha_research_shortcuts_fill_editable_commands():
    html = to_xml(_left_pane("guide", None))

    # Alpha Research shortcuts now live inside the merged "Research" section.
    assert 'nav-section-name">Research<' in html
    assert "Growth Agent" in html
    assert "Value Agent" in html
    assert "Combined View" in html
    assert "Saved Reports" in html
    assert "alpha:growth ticker:AAPL" in html
    assert "alpha:value ticker:BBY" in html
    assert "alpha:compare ticker:AAPL" in html
    assert "alpha:runs limit:10" in html
    assert "alpha:show run-id:&lt;uuid&gt;" in html
    assert "onclick=\"fillChat('alpha:growth ticker:AAPL')\"" in html
    assert "onclick=\"fillChat('alpha:value ticker:BBY')\"" in html
    assert "onclick=\"fillChat('alpha:compare ticker:AAPL')\"" in html
    assert "onclick=\"fillChat('alpha:runs limit:10')\"" in html
    assert "onclick=\"fillChat('alpha:show run-id:&lt;uuid&gt;')\"" in html


def test_sidebar_lists_one_message_runtime_overrides():
    html = to_xml(_left_pane("guide", None))

    assert "AI Runtime" in html
    assert "/hermes " in html
    assert "/deepagents " in html
    assert "/langgraph " in html


def test_authenticated_sidebar_has_visible_sign_out():
    html = to_xml(_left_pane("dashboard", {"email": "user@example.com"}))
    assert 'href="/logout"' in html
    assert ">Sign out<" in html


def test_root_stays_landing_and_login_redirects_to_dashboard():
    from engine.web import ph_auth, ph_landing

    landing_source = inspect.getsource(ph_landing.register)
    auth_source = inspect.getsource(ph_auth.register)
    assert 'RedirectResponse("/dashboard"' not in landing_source
    assert 'return RedirectResponse("/dashboard", status_code=303)' in auth_source


def test_landing_links_to_developer_docs_and_openapi():
    from engine.web.ph_landing import developers_page, home_page

    home_html = to_xml(home_page())
    developer_html = to_xml(developers_page())

    assert 'href="/developers"' in home_html
    assert "https://api.alpatrade.chat/docs" in developer_html
    assert "https://api.alpatrade.chat/redoc" in developer_html
    assert "https://api.alpatrade.chat/openapi.json" in developer_html
    assert "https://api.alpatrade.chat/v2/agents" in developer_html
    assert "Choose the right specialist for the job" in developer_html
    assert "DeepAgent Assistant" in developer_html
    assert "Portfolio and position analysis" in developer_html
    assert "Machine-readable" in developer_html


def test_signin_fields_have_accessible_names_and_autocomplete_hints():
    from engine.web.ph_auth import _signin_page

    html = to_xml(_signin_page())
    assert 'for="signin-email"' in html
    assert 'id="signin-email"' in html
    assert 'autocomplete="email"' in html
    assert 'for="signin-password"' in html
    assert 'id="signin-password"' in html
    assert 'autocomplete="current-password"' in html


def test_news_pane_can_be_open_by_default():
    html = to_xml(page("app", user={"email": "user@example.com"},
                       right_news=True, right_news_open=True))
    assert 'id="app" class="app"' in html
    assert 'id="app" class="app pane-closed"' not in html
    assert 'id="right-pane" class="right-pane open"' in html
    assert 'title="Minimize News"' in html
    assert '&gt;</button>' in html


def test_new_chat_opens_news_and_toggle_uses_directional_controls():
    html = to_xml(page("app", chat_center(), right_news_open=True))

    assert "function newChat(){setNewsPane(true)" in PH_JS
    assert "function setNewsPane(open)" in PH_JS
    assert 'title="Maximize News"' in html
    assert 'aria-controls="right-pane"' in html


def test_pages_share_a_constrained_scroll_viewport():
    html = to_xml(page("guide", Div("Long page", cls="content"), right_news=False))
    css = (Path(__file__).parents[1] / "static" / "app.css").read_text()

    assert 'class="page-pane"' in html
    assert 'class="content">Long page</div>' in html
    assert html.index('class="page-pane"') < html.index('class="content">Long page')
    assert ".page-pane {" in css
    assert "overflow-x: auto" in css
    assert "overflow-y: auto" in css
    assert ".page-pane > .center-pane" in css


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


def test_monitoring_has_pipeline_page_and_paper_only_controls():
    import app
    from engine.web import ph_layout, ph_monitoring

    assert ("⚡ Agent Pipeline", "/monitoring/pipeline", "agent-pipeline") \
        in ph_layout.MONITORING_PAGES
    source = inspect.getsource(ph_monitoring.register)
    assert 'action="/monitoring/pipeline/run"' in inspect.getsource(ph_monitoring._render)
    assert 'scout.enqueue_run(user_id=' in source
    assert "queue.retry" in source
    assert "Paper-only" in inspect.getsource(ph_monitoring._render)


def test_pipeline_snapshot_orders_accounts_by_created_at_not_is_default():
    """Regression guard: user_accounts has no ``is_default`` column (see
    ``sql/11_add_user_accounts.sql``). Referencing it raised UndefinedColumn and
    turned /monitoring/pipeline into a 500."""
    from engine.web import ph_monitoring

    source = inspect.getsource(ph_monitoring.pipeline_snapshot)
    assert "is_default" not in source
    assert "ORDER BY created_at" in source


def test_monitoring_render_handles_empty_state():
    """The pipeline page must render a graceful empty state, not crash, when a
    user has no autonomy runs and no linked accounts."""
    from engine.web import ph_monitoring

    data = {
        "counts": {"queued": 0, "running": 0, "done": 0, "failed": 0},
        "accounts": [],
        "configured": False,
        "fresh_heartbeat": False,
        "runs": [],
    }
    html = ph_monitoring._render(data)
    assert "Autonomous agent pipeline" in html
    assert "No pipeline runs for this user yet." in html
    assert "Worker config" in html


def test_no_duplicate_nav_routes():
    """The sidebar must not register the same route or label twice.

    Guards against regressions like "Premarket" appearing under both Explore
    and Research, or a mislabeled "Options" group duplicating "Index Options".
    """
    import app  # noqa: F401  (registers feature modules)
    from engine.web import ph_layout
    from engine.web.ph_commands import (
        AGENT_SHORTCUTS, ALPHA_RESEARCH_SHORTCUTS, MAIN_NAV,
    )

    # Page links: no duplicate hrefs or labels across all registered sections.
    all_pages = (ph_layout.EXPLORE_PAGES + ph_layout.TOOLS_PAGES +
                 ph_layout.PUBLIC_PAGES + ph_layout.RESEARCH_PAGES +
                 ph_layout.MONITORING_PAGES)
    hrefs = [href for _label, href, _key in all_pages]
    labels = [label for label, _href, _key in all_pages]
    assert len(hrefs) == len(set(hrefs)), f"duplicate hrefs: {hrefs}"
    assert len(labels) == len(set(labels)), f"duplicate labels: {labels}"

    # Command groups: no duplicate group labels.
    group_labels = [lbl for lbl, _ in AGENT_SHORTCUTS + ALPHA_RESEARCH_SHORTCUTS + MAIN_NAV]
    assert len(group_labels) == len(set(group_labels)), \
        f"duplicate group labels: {group_labels}"

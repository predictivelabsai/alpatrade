"""Regression coverage for phone-first public-market research results."""

from pathlib import Path

from fastcore.xml import to_xml
from fasthtml.common import Table

from engine.web.ph_press import _results
from engine.web.ph_tables import research_card, responsive_table


def test_research_card_uses_native_disclosure_and_safe_external_link():
    html = to_xml(research_card(
        title="Catalyst update", meta="2026-09-06 · ALPA", details="A concise event summary.",
        href="https://example.test/release",
    ))

    assert "<details" in html
    assert "<summary" in html
    assert "research-card" in html
    assert "Open source" in html
    assert 'rel="noopener"' in html


def test_mobile_card_table_is_explicitly_marked_for_desktop_only_display():
    html = to_xml(responsive_table(Table(), label="Research results", mobile_cards=True))

    assert "data-table-scroll mobile-card-table" in html
    assert 'aria-label="Research results"' in html


def test_press_results_render_a_mobile_card_for_each_event(monkeypatch):
    monkeypatch.setattr("engine.publicmarkets.news.search_news", lambda *_args, **_kwargs: [{
        "published": "2026-09-06T12:30:00Z",
        "ticker": "ALPA",
        "title": "Alpa reports a material catalyst",
        "summary": "The company issued a concise update.",
        "publisher": "Alpa IR",
        "link": "https://example.test/release",
        "predicted_side": "up",
    }])

    html = to_xml(_results("catalyst", "ALPA"))

    assert "mobile-research-cards" in html
    assert "Alpa reports a material catalyst" in html
    assert "2026-09-06 · ALPA · up" in html


def test_mobile_card_css_preserves_touch_targets_and_hides_wide_table_on_phone():
    css = Path("static/app.css").read_text(encoding="utf-8")

    assert ".mobile-card-table { display: none; }" in css
    assert ".research-card summary" in css
    assert "min-height: 44px" in css

"""DB-free tests for the redesigned news panel (layout + feed rendering)."""
from fastcore.xml import to_xml

from engine.web.ph_chat import _news_card, _news_feed, _news_slug
from engine.web.ph_layout import PH_JS


def test_news_slug_is_attribute_safe():
    assert _news_slug("Other catalysts") == "other-catalysts"
    assert _news_slug("M&A & partnerships") == "m-a-partnerships"
    assert _news_slug("Products & expansion") == "products-expansion"
    assert _news_slug("") == "other"
    assert _news_slug("   ") == "other"


def test_news_card_renders_source_date_headline_summary():
    item = {
        "cat": "Other catalysts",
        "source": "AAPL",
        "meta": "2026-08-05",
        "meta_cls": "",
        "title": "Apple reports record quarter",
        "summary": "Revenue beat estimates.",
        "link": "https://example.com/a",
        "side": "",
    }
    html = to_xml(_news_card(item))
    assert 'class="news-source">AAPL<' in html
    assert 'class="news-time">2026-08-05<' in html
    assert "Apple reports record quarter" in html
    assert "Revenue beat estimates." in html
    assert 'data-cat="other-catalysts"' in html
    assert 'href="https://example.com/a"' in html


def test_news_card_renders_predicted_side_badge():
    item = {
        "cat": "Earnings & guidance",
        "source": "MSFT",
        "meta": "2026-08-05",
        "meta_cls": "",
        "title": "Guidance raised",
        "summary": "",
        "link": "#",
        "side": "up",
    }
    html = to_xml(_news_card(item))
    assert 'class="news-side side-up"' in html
    assert ">up<" in html


def test_news_card_omits_summary_when_empty():
    item = {
        "cat": "Management", "source": "GOOG", "meta": "2026-08-05",
        "meta_cls": "", "title": "CEO change", "summary": "", "link": "#", "side": "",
    }
    html = to_xml(_news_card(item))
    assert "news-item-summary" not in html


def test_filter_news_js_is_registered():
    assert "function filterNews(el)" in PH_JS
    assert "window.filterNews=filterNews" in PH_JS


def test_dashboard_css_does_not_override_app_padding():
    from engine.web.ph_pnl import _CSS
    assert ".app{padding-right:0}" not in _CSS


def _item(cat, title, sort):
    return {"cat": cat, "source": "T", "meta": "2026-08-05", "meta_cls": "",
            "title": title, "summary": "", "link": "#", "side": "", "sort": sort}


def test_news_feed_renders_all_items_without_cap():
    """A low-count category whose articles sort beyond a 40-item cap must still
    be rendered (the old items[:40] cap hid them, breaking the filter)."""
    items = [_item("Other catalysts", f"Item {i}", f"2026-08-{i:02d}") for i in range(50)]
    items.append(_item("Management", "CEO change", "2026-08-01"))
    html = to_xml(_news_feed(items))
    assert "CEO change" in html
    assert "Management · 1" in html


def test_news_feed_pill_counts_match_rendered_cards():
    items = [
        _item("Management", "A1", "2026-08-05"),
        _item("Management", "A2", "2026-08-04"),
        _item("Products & expansion", "B1", "2026-08-03"),
    ]
    html = to_xml(_news_feed(items))
    assert "Management · 2" in html
    assert "Products &amp; expansion · 1" in html
    assert html.count('class="news-item"') == 3


def test_news_feed_pill_data_cat_matches_card_data_cat():
    """The pill's filter value must equal the card's data-cat attribute."""
    html = to_xml(_news_feed([_item("Products & expansion", "B1", "2026-08-03")]))
    # pill
    assert 'data-cat="products-expansion"' in html
    # card
    assert 'data-cat="products-expansion"' in html


def test_news_feed_includes_empty_state():
    html = to_xml(_news_feed([_item("Management", "A1", "2026-08-05")]))
    assert "No articles available under this topic" in html
    assert 'id="news-empty-filter"' in html


def test_filter_news_js_shows_empty_state():
    assert "news-empty-filter" in PH_JS
    assert "visible?'none':'block'" in PH_JS


def test_news_css_has_pill_and_card_rules():
    """Contract test: the news panel CSS rules must exist in app.css so the
    pills/cards are actually styled (not default browser buttons)."""
    from pathlib import Path
    css = (Path(__file__).parents[1] / "static" / "app.css").read_text()
    # pills: borderless, 13px, fully rounded, horizontal-scroll container
    assert ".news-pill {" in css
    assert "border: none" in css
    assert "font-size: 13px" in css
    assert "border-radius: 999px" in css
    assert "overflow-x: auto" in css
    assert "white-space: nowrap" in css
    # cards: padding + bottom-border separator + summary line-height
    assert ".news-item {" in css
    assert "padding: 12px 16px" in css
    assert "border-bottom: 1px solid" in css
    assert "line-height: 1.5" in css
    # subtitle: body font (not monospace)
    assert ".right-subtitle" in css

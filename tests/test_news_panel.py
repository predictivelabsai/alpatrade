"""DB-free tests for the redesigned news panel (layout + feed rendering)."""
from unittest.mock import MagicMock, patch

from fastcore.xml import to_xml

from engine.web.ph_chat import _news_card, _news_feed, _news_slug
from engine.web.ph_layout import PH_JS

# Non-Latin sample strings (Japanese / Russian / Arabic) used to assert the
# English-only filter — the platform surface is English-only.
_JA = "市場は節分後も材料難──日経平均は小動か"
_RU = "Крупнейший банк объявил о сделке"
_AR = "البنك المركزي يرفع أسعار الفائدة"


def test_is_english_text_rejects_non_english_scripts():
    from engine.publicmarkets.news import is_english_text

    assert is_english_text("Apple beats quarterly estimates")
    assert is_english_text("")
    assert is_english_text(None)
    assert is_english_text("Naïve café résumé — Latin-1 accents are fine")
    assert not is_english_text(_JA)
    assert not is_english_text(_RU)
    assert not is_english_text(_AR)


def test_search_news_excludes_non_english_rows():
    """Language metadata gates the SQL (so LIMIT applies after filtering);
    rows without language metadata still pass the script guard."""
    import engine.publicmarkets.news as news_mod

    captured = {}

    def fake_execute(sql, params=None):
        captured.update(sql=str(sql), params=params or {})

        raw = [
            ("English headline", "u1", "AAPL", "Apple", None, "e", "p",
             "s", "up", 1.0, "en"),
            ("Communiqué semestriel 2024", "u2", "BNP", "BNP", None, "e",
             "p", "s", None, None, "fr"),
            (_JA, "u3", "TYO", "T", None, "e", "p", "s", None, None, None),
        ]
        # Simulate the SQL gate: language IS NULL OR language = ANY(:langs).
        gated = [r for r in raw if r[10] is None
                 or r[10].lower() in captured["params"]["langs"]]

        class Result:
            @staticmethod
            def fetchall():
                return gated

        return Result()

    session = MagicMock()
    session.execute.side_effect = fake_execute
    with patch.object(news_mod, "DatabasePool") as pool_cls:
        ctx = pool_cls.return_value.get_session.return_value
        ctx.__enter__.return_value = session
        ctx.__exit__.return_value = False
        rows = news_mod.search_news(limit=60)

    assert "language IS NULL OR lower(btrim(language)) = ANY(:langs)" in captured["sql"]
    assert captured["params"]["langs"] == list(news_mod.ENGLISH_LANGUAGES)
    # 'fr' is excluded by the SQL gate; the NULL-language non-Latin title
    # falls through the SQL but is dropped by the script guard.
    assert [row["title"] for row in rows] == ["English headline"]


def test_rss_ingester_drops_non_english_headlines(monkeypatch):
    import utils.news_feed as nf

    entries = [
        {"link": "https://example.com/1", "title": "Markets rally on rate hopes",
         "summary": "Stocks rose."},
        {"link": "https://example.com/2", "title": _JA, "summary": "Tokyo."},
    ]
    resp = MagicMock()
    resp.content = b"<rss/>"
    parsed = MagicMock()
    parsed.entries = entries
    monkeypatch.setattr(nf.requests, "get", lambda *a, **k: resp)
    monkeypatch.setattr(nf.feedparser, "parse", lambda content: parsed)
    items = nf._fetch_one({"name": "Test", "url": "https://example.com/rss", "icon": "T"})
    assert [item["title"] for item in items] == ["Markets rally on rate hopes"]


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

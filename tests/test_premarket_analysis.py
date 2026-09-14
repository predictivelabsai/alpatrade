"""Grounded Grok generation and historical read/sanitization contracts."""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import openai

from engine import premarket_analysis as analysis, premarket_data as data

DAY = date(2026, 8, 7)
CUTOFF = datetime(2026, 8, 7, 9, tzinfo=data.ET)
URL = "https://example.org/earnings"


def catalyst(**changes):
    return {"title": "Earnings", "publisher": "Example", "url": URL,
            "published_at": "2026-08-07T08:00:00-04:00", "impact": "Guidance may explain repricing.",
            "confidence": "Medium", "justification": "Timing is consistent.", **changes}


@pytest.mark.parametrize("stamp", [CUTOFF + timedelta(seconds=1), CUTOFF - timedelta(hours=48, seconds=1),
                                    datetime(2026, 8, 7, 8), None])
def test_undated_and_out_of_window_evidence_cannot_be_factual_catalysts(stamp):
    narrative, sources = analysis.grounded_narrative({"catalysts": [catalyst()]}, {URL}, DAY, {URL: stamp})
    assert narrative == "No specific news catalyst found."
    assert sources == []


def test_model_invented_timestamp_cannot_override_verified_timestamp():
    result, sources = analysis.grounded_narrative({"catalysts": [catalyst()]}, {URL}, DAY,
                                                 {URL: CUTOFF + timedelta(hours=1)})
    assert not sources
    assert "No specific news" in result


def test_native_citation_and_verified_publication_are_both_required():
    for citations, verified in [(set(), {URL: CUTOFF}), ({URL}, {})]:
        assert not analysis.grounded_narrative({"catalysts": [catalyst()]}, citations, DAY, verified)[1]


def test_catalyst_includes_mechanism_confidence_and_verified_sources():
    text, sources = analysis.grounded_narrative({"catalysts": [catalyst()]}, {URL}, DAY, {URL: CUTOFF})
    assert "Impact explanation" in text and "Confidence:** Medium" in text
    assert sources[0]["published_at"] == CUTOFF.isoformat()
    assert sources[0]["url"] == URL


def test_possible_non_news_explanations_are_explicitly_uncertain():
    text, sources = analysis.grounded_narrative({"catalysts": [], "non_news_explanations": [
        "Thin liquidity is possible. [unverified](https://bad.example/story)"]}, set(), DAY)
    assert text.startswith("No specific news catalyst found.")
    assert "unconfirmed" in text and "Thin liquidity" in text
    assert "https:" not in text and not sources


def test_native_responses_citations_are_extracted():
    assert analysis.cited_urls({"output": [{"content": [{"annotations": [
        {"type": "url_citation", "url": URL}, {"type": "url_citation", "url": "javascript:alert(1)"}]}]}]}) == {URL}


def test_publication_timestamp_requires_unambiguous_zoned_metadata():
    assert analysis.publication_time('<meta property="article:published_time" content="2026-08-07T08:00:00-04:00">')
    assert analysis.publication_time('<script type="application/ld+json">{"datePublished":"2026-08-07T08:00:00-04:00"}</script>')
    assert analysis.publication_time('<meta name="date" content="2026-08-07">') is None
    assert analysis.publication_time('<meta name="date" content="2026-08-07T08:00:00-04:00"><meta name="date" content="2026-08-07T10:00:00-04:00">') is None


def test_verifier_does_not_fetch_private_or_invalid_urls(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))])
    for url in ["https://localhost/", "https://example.org:bad/", "http://example.org/", "javascript:alert(1)"]:
        assert analysis.verify_publication(url) is None


def test_source_updated_after_cutoff_is_excluded():
    html = '<meta property="article:published_time" content="2026-08-07T08:00:00-04:00">'
    html += '<meta property="article:modified_time" content="2026-08-07T10:00:00-04:00">'
    assert analysis.publication_time(html, CUTOFF) is None


@pytest.mark.parametrize("day", [date(2026, 3, 9), date(2026, 11, 2)])
def test_research_window_is_48_elapsed_hours_across_dst(day):
    earliest, cutoff = analysis.research_window(day)
    assert cutoff.hour == 9
    assert cutoff.astimezone(timezone.utc) - earliest.astimezone(timezone.utc) == timedelta(hours=48)


def test_legacy_markdown_is_sanitized_and_links_are_safe():
    html = analysis.markdown_html('<script>alert(1)</script> **Saved** [unsafe](javascript:alert) [safe](https://example.org)')
    assert "<script>" not in html and '<a href="javascript:' not in html
    assert "<strong>Saved</strong>" in html and 'href="https://example.org"' in html
    assert not analysis.safe_url("https://user:password@example.org/")


def test_gemini_history_is_preserved_and_new_grok_takes_precedence(monkeypatch):
    def query(sql, params):
        if "premarket_screener" in sql:
            return [{"company_id": 1, "provider": "gemini", "text": "Historical Gemini", "analysis_id": "1"},
                    {"company_id": 1, "provider": "grok", "text": "Legacy Grok", "analysis_id": "2"}]
        return [{"company_id": 1, "provider": "grok", "text": "New Grok", "analysis_id": "new",
                 "sources": [], "model_name": "grok-test", "generated_at": CUTOFF, "retrospective": True}]
    monkeypatch.setattr(analysis, "query", query)
    monkeypatch.setattr(analysis, "table_exists", lambda _: True)
    saved = analysis.saved_for_date(DAY, 1)[1]
    assert [(row["provider"], row["text"]) for row in saved] == [("gemini", "Historical Gemini"), ("grok", "New Grok")]
    assert saved[0]["legacy"] and saved[1]["retrospective"]


def test_grok_responses_uses_native_search_and_records_actual_usage(monkeypatch):
    result = Mock(output_text=json.dumps({"catalysts": [catalyst()], "non_news_explanations": []}))
    result.model_dump.return_value = {"citations": [URL], "usage": {"input_tokens": 123, "output_tokens": 45, "cost_in_usd_ticks": 10000000}}
    client = Mock()
    client.responses.create.return_value = result
    monkeypatch.setattr(openai, "OpenAI", Mock(return_value=client))
    monkeypatch.setattr(analysis, "verify_publication", lambda url, cutoff: CUTOFF)
    monkeypatch.setattr(analysis, "now_et", lambda: CUTOFF + timedelta(days=1))
    generated = analysis.generate({"ticker": "AAA", "company_name": "Example"}, DAY, "test-placeholder", ["grok-test"])
    call = client.responses.create.call_args.kwargs
    assert call["tools"] == [{"type": "web_search"}]
    assert call["store"] is False
    assert "2026-08-05T09:00:00-04:00" in call["input"] and CUTOFF.isoformat() in call["input"]
    assert generated["usage"].input_tokens == 123
    assert str(generated["usage"].cost_usd) == "0.001"
    assert generated["retrospective"] and generated["sources"][0]["url"] == URL
    client.close.assert_called_once()


def test_byok_resolution_uses_user_xai_key_even_when_another_provider_selected(monkeypatch):
    from engine import config, auth
    monkeypatch.setattr(config, "get_settings", lambda uid: SimpleNamespace(
        model_provider="openai", model_name="other", api_key="not-xai"))
    monkeypatch.setattr(auth, "get_provider_api_key", lambda uid, provider: "test-xai" if provider == "xai" else None)
    key, models, byok = analysis.credentials("user")
    assert key == "test-xai" and byok
    assert all(model.startswith("grok-") for model in models)

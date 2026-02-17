"""
Tests for XAI (Grok) and Tavily news API connectivity.

Verifies API keys are valid and endpoints return expected data.
Run: python -m pytest tests/test_news_apis.py -v
"""
import os
import sys
import pytest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# XAI / Grok API tests
# ---------------------------------------------------------------------------

class TestXAIApi:
    """Test XAI (Grok) API connectivity and responses."""

    @pytest.fixture(autouse=True)
    def _check_key(self):
        key = os.getenv("XAI_API_KEY")
        if not key:
            pytest.skip("XAI_API_KEY not set")

    def test_xai_simple_query(self):
        """XAI API responds to a simple question."""
        from openai import OpenAI

        client = OpenAI(
            api_key=os.getenv("XAI_API_KEY"),
            base_url="https://api.x.ai/v1",
        )
        resp = client.chat.completions.create(
            model="grok-3-mini-fast",
            messages=[{"role": "user", "content": "What is the weather like in Paris today? Reply in one sentence."}],
            temperature=0.1,
        )
        content = resp.choices[0].message.content
        assert content, "XAI returned empty response"
        assert len(content) > 10, f"XAI response too short: {content}"

    def test_xai_news_tsla(self):
        """XAI returns news articles for TSLA via MarketResearch."""
        from utils.market_research_util import MarketResearch

        research = MarketResearch()
        articles = research._news_xai("TSLA", 5)
        assert articles is not None, "XAI returned None for TSLA news"
        assert len(articles) > 0, "XAI returned empty list for TSLA news"
        # Check article structure
        for a in articles:
            assert "title" in a, f"Missing 'title' in article: {a}"
            assert "source" in a, f"Missing 'source' in article: {a}"
            assert len(a["title"]) > 0, f"Empty title in article: {a}"

    def test_xai_news_general(self):
        """XAI returns general market news (no ticker)."""
        from utils.market_research_util import MarketResearch

        research = MarketResearch()
        articles = research._news_xai(None, 5)
        assert articles is not None, "XAI returned None for general news"
        assert len(articles) > 0, "XAI returned empty list for general news"


# ---------------------------------------------------------------------------
# Tavily API tests
# ---------------------------------------------------------------------------

class TestTavilyApi:
    """Test Tavily search API connectivity and responses."""

    @pytest.fixture(autouse=True)
    def _check_key(self):
        key = os.getenv("TAVILY_API_KEY")
        if not key:
            pytest.skip("TAVILY_API_KEY not set")

    def test_tavily_simple_search(self):
        """Tavily API responds to a simple search query."""
        import requests

        r = requests.post("https://api.tavily.com/search", json={
            "api_key": os.getenv("TAVILY_API_KEY"),
            "query": "What is the weather in Paris today?",
            "search_depth": "basic",
            "max_results": 3,
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        assert "results" in data, f"Tavily response missing 'results': {list(data.keys())}"
        assert len(data["results"]) > 0, "Tavily returned no results"

    def test_tavily_news_tsla(self):
        """Tavily returns news for TSLA via MarketResearch."""
        from utils.market_research_util import MarketResearch

        research = MarketResearch()
        articles = research._news_tavily("TSLA", 5)
        assert articles is not None, "Tavily returned None for TSLA news"
        assert len(articles) > 0, "Tavily returned empty list for TSLA news"
        for a in articles:
            assert "title" in a, f"Missing 'title' in article: {a}"
            assert len(a["title"]) > 0, f"Empty title in article: {a}"


# ---------------------------------------------------------------------------
# Integration: full news command flow
# ---------------------------------------------------------------------------

class TestNewsCommand:
    """Test the full news command with provider selection."""

    def test_news_xai_provider(self):
        """news:TSLA provider:xai returns formatted markdown."""
        if not os.getenv("XAI_API_KEY"):
            pytest.skip("XAI_API_KEY not set")

        from utils.market_research_util import MarketResearch

        research = MarketResearch()
        result = research.news("TSLA", limit=5, provider="xai")
        assert "# News: TSLA" in result, f"Unexpected output: {result[:100]}"
        assert "No results" not in result, f"Got no results: {result}"
        assert "XAI Grok" in result, f"Provider not shown: {result[:200]}"

    def test_news_tavily_provider(self):
        """news:TSLA provider:tavily returns formatted markdown."""
        if not os.getenv("TAVILY_API_KEY"):
            pytest.skip("TAVILY_API_KEY not set")

        from utils.market_research_util import MarketResearch

        research = MarketResearch()
        result = research.news("TSLA", limit=5, provider="tavily")
        assert "# News: TSLA" in result, f"Unexpected output: {result[:100]}"
        assert "No results" not in result, f"Got no results: {result}"
        assert "Tavily" in result, f"Provider not shown: {result[:200]}"

    def test_news_auto_provider(self):
        """news:TSLA (auto) returns results from any available provider."""
        from utils.market_research_util import MarketResearch

        research = MarketResearch()
        result = research.news("TSLA", limit=5)
        assert "# News: TSLA" in result, f"Unexpected output: {result[:100]}"
        # Should succeed from at least one provider
        assert "No news found" not in result, f"All providers failed: {result}"

"""Tavily API connectivity test.

Verifies TAVILY_API_KEY in .env is valid by running a live search.

Run (pytest):   python -m pytest tests/tavily_test.py -v
Run (script):   python tests/tavily_test.py
"""
import os
import sys
from pathlib import Path

import requests

try:
    import pytest
except ImportError:  # allow running as a plain script without pytest installed
    pytest = None

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

TAVILY_URL = "https://api.tavily.com/search"


def _search(api_key: str, query: str = "apple stock", max_results: int = 1):
    """Call Tavily /search. Tries body-key auth, then Bearer header."""
    r = requests.post(TAVILY_URL, json={"api_key": api_key, "query": query,
                                        "max_results": max_results}, timeout=25)
    if r.status_code == 401:
        r = requests.post(TAVILY_URL, headers={"Authorization": f"Bearer {api_key}"},
                          json={"query": query, "max_results": max_results}, timeout=25)
    return r


if pytest is not None:
    class TestTavily:
        @pytest.fixture(autouse=True)
        def _check_key(self):
            if not os.getenv("TAVILY_API_KEY"):
                pytest.skip("TAVILY_API_KEY not set")

        def test_key_authenticates(self):
            """The key is accepted (not 401/403)."""
            r = _search(os.getenv("TAVILY_API_KEY"))
            assert r.status_code == 200, f"Tavily auth failed: HTTP {r.status_code} {r.text[:120]}"

        def test_search_returns_results(self):
            """A search returns a non-empty results list."""
            r = _search(os.getenv("TAVILY_API_KEY"))
            assert r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}"
            data = r.json()
            assert isinstance(data.get("results"), list) and data["results"], "no results returned"


def _main() -> int:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        print("SKIP  Tavily — TAVILY_API_KEY not set")
        return 0
    try:
        r = _search(key)
        if r.status_code == 200 and r.json().get("results"):
            print(f"PASS  Tavily — {len(r.json()['results'])} result(s)")
            return 0
        print(f"FAIL  Tavily — HTTP {r.status_code}: {r.text[:120]}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  Tavily — {e!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())

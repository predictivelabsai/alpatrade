"""Authenticated local Playwright regression suite for AlpaTrade.

Usage:
    uv sync --extra e2e
    uv run --extra e2e python evals/run_playwright_tests.py --url http://localhost:5001

The runner signs a local session for an existing user without changing the
database. It is intended for local/staging regression runs, not production.
"""
from __future__ import annotations

import argparse
import json
import os
from base64 import b64encode
from pathlib import Path

from dotenv import load_dotenv
from itsdangerous import TimestampSigner
from playwright.sync_api import sync_playwright
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _session_cookie() -> str:
    from engine.db.pool import DatabasePool

    with DatabasePool().get_session() as session:
        user_id = session.execute(
            text("SELECT id FROM alpatrade.users ORDER BY id LIMIT 1")
        ).scalar()
    if user_id is None:
        raise RuntimeError("No existing alpatrade user is available for the local smoke test")
    secret = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
    data = b64encode(json.dumps({"user_id": str(user_id)}).encode("utf-8"))
    return TimestampSigner(secret).sign(data).decode("utf-8")


def run(base_url: str, screenshot: Path | None = None) -> dict[str, bool]:
    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        context.add_cookies([{
            "name": "session_", "value": _session_cookie(),
            "url": base_url, "httpOnly": True, "sameSite": "Lax",
        }])
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"{base_url}/app", wait_until="networkidle")
        page.fill("#chat-input", "Show me a market map")
        page.click("#send-btn")
        chart = ".msg-assistant .msg-bubble .js-plotly-plot"
        nodes = ".msg-assistant .msg-bubble .treemaplayer path"
        page.wait_for_selector(chart, timeout=60_000)
        page.wait_for_selector(nodes, timeout=15_000)
        results = {
            "chat_loaded": page.locator("#chat-input").is_visible(),
            "market_map_summary": page.get_by_text("Market map", exact=False).count() > 0,
            "plotly_chart": page.locator(chart).count() > 0,
            "treemap_nodes": page.locator(nodes).count() > 0,
            "no_page_errors": not errors,
        }
        if screenshot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True)
        context.close()
        browser.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:5001")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    results = run(args.url.rstrip("/"), args.screenshot)
    for name, passed in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

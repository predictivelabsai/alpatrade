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
            text("""
                SELECT u.user_id
                FROM alpatrade.users u
                LEFT JOIN alpatrade.user_accounts a
                  ON a.user_id = u.user_id AND a.is_active = TRUE
                ORDER BY (a.account_id IS NOT NULL) DESC, u.created_at
                LIMIT 1
            """)
        ).scalar()
    if user_id is None:
        raise RuntimeError("No existing alpatrade user is available for the local smoke test")
    secret = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
    data = b64encode(json.dumps({"user_id": str(user_id)}).encode("utf-8"))
    return TimestampSigner(secret).sign(data).decode("utf-8")


def run(base_url: str, screenshot: Path | None = None) -> dict[str, bool]:
    errors: list[str] = []
    viewports = {
        "desktop": {"width": 1400, "height": 900},
        "tablet": {"width": 820, "height": 1180},
        "mobile": {"width": 390, "height": 844},
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport=viewports["desktop"])
        context.add_cookies([{
            "name": "session_", "value": _session_cookie(),
            "url": base_url, "httpOnly": True, "sameSite": "Lax",
        }])
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"{base_url}/", wait_until="networkidle")
        root_is_landing = page.url.rstrip("/") == base_url.rstrip("/")
        page.goto(f"{base_url}/app", wait_until="networkidle")
        page.fill("#chat-input", "Show me a market map")
        page.click("#send-btn")
        chart = ".msg-assistant .msg-bubble .js-plotly-plot"
        nodes = ".msg-assistant .msg-bubble .treemaplayer path"
        page.wait_for_selector(chart, timeout=60_000)
        page.wait_for_selector(nodes, timeout=15_000)
        results = {
            "authenticated_root_stays_landing": root_is_landing,
            "chat_loaded": page.locator("#chat-input").is_visible(),
            "chat_news_open_by_default": (
                page.locator("#right-pane").is_visible()
                and "pane-closed" not in (page.locator("#app").get_attribute("class") or "")
            ),
            "market_map_summary": page.get_by_text("Market map", exact=False).count() > 0,
            "plotly_chart": page.locator(chart).count() > 0,
            "treemap_nodes": page.locator(nodes).count() > 0,
            "no_page_errors": not errors,
        }
        for screen, viewport in viewports.items():
            page.set_viewport_size(viewport)
            page.goto(f"{base_url}/dashboard", wait_until="networkidle", timeout=120_000)
            results[f"dashboard_loaded_{screen}"] = page.get_by_text(
                "Portfolio P&L", exact=True).is_visible()
            results[f"dashboard_equity_plot_{screen}"] = (
                page.locator("#equity-chart.js-plotly-plot").count() == 1)
            results[f"dashboard_contributor_plot_{screen}"] = (
                page.locator("#contrib-chart.js-plotly-plot").count() == 1)
            results[f"dashboard_signout_{screen}"] = page.locator(
                "a.dash-signout[href='/logout']").is_visible()
        results["dashboard_no_page_errors"] = not errors
        if screenshot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True)
        auth_context = browser.new_context(viewport={"width": 390, "height": 500})
        auth_page = auth_context.new_page()
        auth_page.goto(f"{base_url}/signin", wait_until="networkidle")
        auth_page.evaluate(
            "document.querySelector('.auth-page').scrollTop = "
            "document.querySelector('.auth-page').scrollHeight"
        )
        results["signin_short_screen_scrolls"] = auth_page.evaluate(
            "document.querySelector('.auth-page').scrollTop > 0 || "
            "document.querySelector('.auth-page').scrollHeight <= "
            "document.querySelector('.auth-page').clientHeight"
        )
        auth_context.close()
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

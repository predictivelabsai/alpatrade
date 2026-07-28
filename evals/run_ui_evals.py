"""Playwright UI evals for every chart surface and responsive screen size.

Run:
    uv run --with playwright python evals/run_ui_evals.py

Chrome must be installed (the repository's Playwright workflow uses the system
Chrome channel). Results use the same PASS/FAIL CSV convention as run_evals.py.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "eval-results"
ARTIFACTS = ROOT / "output" / "playwright"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 820, "height": 1180},
    "mobile": {"width": 390, "height": 844},
}
MAP_DATA = {
    "period": "1mo",
    "sectors": [{"name": "Technology", "return": 2.5, "count": 1}],
    "stocks": [{
        "ticker": "AAPL", "sector": "Technology", "return": 2.5,
        "price": 200, "size": 100,
    }],
}


def _shell(body: str, script: str) -> str:
    marker = f"__CHART_DATA__{json.dumps(MAP_DATA | {'type': 'treemap'})}__END_CHART__"
    sse = (
        'event: agent_route\ndata: {"agent":"AlpaTrade AI"}\n\n'
        'event: tool_start\ndata: {"name":"show_market_map"}\n\n'
        f"event: token\ndata: {json.dumps({'text': 'Market map rendered below.\\n\\n' + marker})}\n\n"
        "event: done\ndata: {}\n\n"
    )
    ohlc = {
        "ticker": "AAPL", "period": "6mo", "dates": ["2026-01-01", "2026-01-02"],
        "open": [100, 101], "high": [102, 103], "low": [99, 100],
        "close": [101, 102], "volume": [1000, 1200],
    }
    return f"""<!doctype html><html><body>{body}<script>
window.marked={{parse:function(s){{return s;}}}};
window.Plotly={{
  newPlot:function(el,traces,layout){{el.dataset.plotly='rendered';el.textContent=traces[0].type;}},
  downloadImage:function(){{}}
}};
window.fetch=function(url){{
  if(String(url).includes('/app/chat')) return Promise.resolve(new Response({json.dumps(sse)},
    {{status:200,headers:{{'Content-Type':'text/event-stream'}}}}));
  if(String(url).includes('/charts/data')) return Promise.resolve(
    new Response(JSON.stringify({json.dumps(ohlc)}),
    {{status:200,headers:{{'Content-Type':'application/json'}}}}));
  return Promise.resolve(new Response(JSON.stringify({json.dumps(MAP_DATA)}),
    {{status:200,headers:{{'Content-Type':'application/json'}}}}));
}};
</script><script>{script}</script></body></html>"""


def _cases():
    from engine.web.ph_chat import CHAT_JS
    from engine.web.ph_charts import _CHARTS_JS, _MAP_JS
    from engine.web.ph_pnl import _JS as _DASHBOARD_JS
    chat = _shell(
        '<div id="messages"></div><div id="welcome-hero"></div>'
        '<textarea id="chat-input">Show me a market map</textarea>'
        '<button id="send-btn"></button><span id="current-agent-label"></span>',
        CHAT_JS,
    )
    market_map = _shell(
        '<select id="map-period"><option value="1mo">1mo</option></select>'
        '<div id="map-plot"></div><div id="map-status"></div>',
        _MAP_JS,
    )
    charts = _shell(
        '<button id="seg-candle"></button><button id="seg-compare"></button>'
        '<input id="cp-ticker" value="AAPL"><select id="cp-period">'
        '<option value="6mo">6mo</option></select><div id="cp-hint"></div>'
        '<div id="cp-plot"></div><div id="cp-status"></div>',
        _CHARTS_JS,
    )
    dashboard_data = {
        "history": {
            "timestamps": ["2026-07-28T08:00:00+00:00", "2026-07-28T16:00:00+00:00"],
            "equity": [100_000, 101_250],
        },
        "contributors": [
            {"symbol": "AAPL", "pnl": 900},
            {"symbol": "TSLA", "pnl": -250},
        ],
    }
    dashboard = _shell(
        '<div id="equity-chart"></div><div id="contrib-chart"></div>',
        f"window.__PNL_DASH__={json.dumps(dashboard_data)};{_DASHBOARD_JS}",
    )
    return [
        ("chat_market_map", chat, "window.sendMessage()", "#messages [data-plotly=rendered]"),
        ("market_map_page", market_map, "window.loadMap()", "#map-plot[data-plotly=rendered]"),
        ("charts_page", charts, "window.loadChart()", "#cp-plot[data-plotly=rendered]"),
        ("dashboard_equity", dashboard, "void 0", "#equity-chart[data-plotly=rendered]"),
        ("dashboard_contributors", dashboard, "void 0", "#contrib-chart[data-plotly=rendered]"),
    ]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install the UI eval dependency with: uv run --with playwright "
              "python evals/run_ui_evals.py", file=sys.stderr)
        return 2

    OUT.mkdir(exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        for screen, viewport in VIEWPORTS.items():
            page = browser.new_page(viewport=viewport)
            for name, html, action, selector in _cases():
                error = ""
                try:
                    page.set_content(html, wait_until="load")
                    page.evaluate(action)
                    page.locator(selector).wait_for(state="attached", timeout=5_000)
                    page.screenshot(path=ARTIFACTS / f"{name}-{screen}.png")
                    passed = True
                except Exception as exc:  # noqa: BLE001
                    passed, error = False, str(exc)[:300]
                results.append({
                    "case_id": f"ui.{name}.{screen}",
                    "category": "ui_rendering",
                    "agent_type": "playwright",
                    "screen": screen,
                    "result": "PASS" if passed else "FAIL",
                    "score": 1.0 if passed else 0.0,
                    "reason": error or f"{selector} rendered",
                })
            page.close()
        browser.close()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = OUT / f"ui-evals-{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=results[0])
        writer.writeheader()
        writer.writerows(results)
    passed = sum(row["result"] == "PASS" for row in results)
    print(f"UI EVALS  {passed}/{len(results)} PASS")
    print(path)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

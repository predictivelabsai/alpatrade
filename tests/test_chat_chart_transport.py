import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from engine.web.ph_chat import CHAT_JS, _stream, _tool_chart_marker


def _marker():
    payload = {
        "type": "treemap",
        "period": "1mo",
        "sectors": [{"name": "Technology", "return": 2.5, "count": 1}],
        "stocks": [{
            "ticker": "AAPL", "sector": "Technology", "return": 2.5,
            "price": 200.0, "size": 100,
        }],
    }
    return f"__CHART_DATA__{json.dumps(payload)}__END_CHART__"


def test_tool_chart_marker_extracts_langchain_tool_output():
    marker = _marker()

    assert _tool_chart_marker({"data": {"output": f"Summary\n\n{marker}"}}) == marker


def test_tool_chart_marker_accepts_structured_content():
    marker = _marker()
    output = type("ToolOutput", (), {"content": [{"type": "text", "text": marker}]})()

    assert _tool_chart_marker({"data": {"output": output}}) == marker


def test_show_market_map_keeps_ui_transport_marker():
    market_data = {
        "period": "1mo",
        "sectors": [
            {"name": "Technology", "return": 2.5, "count": 1},
            {"name": "Energy", "return": -1.0, "count": 1},
        ],
        "stocks": [
            {"ticker": "AAPL", "sector": "Technology", "return": 2.5,
             "price": 200.0, "size": 100},
            {"ticker": "XOM", "sector": "Energy", "return": -1.0,
             "price": 100.0, "size": 80},
        ],
    }
    with patch("engine.market_map.market_map_data", return_value=market_data):
        from agui_app import show_market_map
        result = show_market_map()

    assert "Market map" in result
    assert "__CHART_DATA__" in result
    assert '"type": "treemap"' in result
    assert "__END_CHART__" in result


def test_chat_client_extracts_multiline_markers_and_renders_treemap():
    assert r"/__CHART_DATA__([\s\S]+?)__END_CHART__/" in CHAT_JS
    assert "if(data.type==='treemap')" in CHAT_JS
    assert "Plotly.newPlot(div,[tm]" in CHAT_JS
    assert "acc.indexOf('__END_CHART__')!==-1" in CHAT_JS
    assert "enhanceTables(bubble); renderChart(bubble);" in CHAT_JS
    assert "if(!bubble._chartRendered)" in CHAT_JS
    assert "bubble._chartRendered=true" in CHAT_JS


def test_chat_client_renders_research_correlation_charts():
    assert "data.type==='research_correlation_heatmap'" in CHAT_JS
    assert "data.type==='research_correlation_scatter'" in CHAT_JS


def test_chat_client_renders_premarket_breadth_and_mover_panels_once():
    assert "data.type==='premarket_overview'" in CHAT_JS
    assert "Sector breadth (count)" in CHAT_JS
    assert "Top movers (%)" in CHAT_JS
    assert "premarket-overview" in CHAT_JS
    assert "Plotly.downloadImage" in CHAT_JS
    assert "responsive:true" in CHAT_JS
    assert "bubble._chartRendered) return" in CHAT_JS


def test_premarket_tool_keeps_chart_transport_marker():
    payload = {
        "type": "premarket_overview",
        "mode": "auto",
        "breadth": [{"sector": "Technology", "gainers": 2, "fallers": 1}],
        "gainers": [{"ticker": "AAPL", "movement_pct": 2.0}],
        "fallers": [{"ticker": "PFE", "movement_pct": -1.0}],
    }
    marker = f"__CHART_DATA__{json.dumps(payload)}__END_CHART__"
    with patch("agents.premarket_agent.PremarketAgent.report",
               return_value=f"# Premarket screening\n\n{marker}"):
        from agui_app import get_premarket_movers
        result = get_premarket_movers()

    assert '"type": "premarket_overview"' in result
    assert _tool_chart_marker({"data": {"output": result}}) == marker


def test_sse_forwards_premarket_tool_chart_when_model_omits_it():
    payload = {
        "type": "premarket_overview", "mode": "auto", "breadth": [],
        "gainers": [], "fallers": [],
    }
    marker = f"__CHART_DATA__{json.dumps(payload)}__END_CHART__"

    class _Agent:
        async def astream_events(self, _input, version):
            assert version == "v2"
            yield {"event": "on_tool_end", "name": "get_premarket_movers",
                   "data": {"output": f"tool commentary\n\n{marker}"}}
            yield {"event": "on_chat_model_stream",
                   "data": {"chunk": SimpleNamespace(content="Observed facts and risks.")}}

    async def collect():
        with patch("engine.web.ph_chat._command_interceptor", new=AsyncMock(return_value=None)), \
             patch("engine.web.ph_chat._agui.agent_for_user", return_value=_Agent()):
            response = await _stream(
                "Show me the latest premarket overview",
                {"user_id": "user-1", "thread_id": "premarket-sse-test"},
            )
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

    stream = asyncio.run(collect())

    assert "Observed facts and risks." in stream
    assert stream.count("__CHART_DATA__") == 1
    assert stream.count("__END_CHART__") == 1
    assert "event: done" in stream


def test_research_tool_keeps_chart_transport_marker():
    summary = {
        "count": 2, "correlation": 1.0, "mae": 0.5,
        "points": [{"event": "earnings", "industry": "Tech", "predicted": 1, "actual": 2}],
        "matrix": [{"event": "earnings", "industry": "Tech", "count": 2, "correlation": 1.0}],
    }
    with patch("engine.research.data.correlation_summary", return_value=summary):
        from agui_app import analyze_prediction_correlation
        result = analyze_prediction_correlation()
    assert "Pearson correlation **1.000**" in result
    assert '"type": "research_correlation_heatmap"' in result
    assert "__CHART_DATA__" in result and "__END_CHART__" in result

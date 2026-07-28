import json
from unittest.mock import patch

from engine.web.ph_chat import CHAT_JS, _tool_chart_marker


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


def test_chat_client_renders_research_correlation_charts():
    assert "data.type==='research_correlation_heatmap'" in CHAT_JS
    assert "data.type==='research_correlation_scatter'" in CHAT_JS


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

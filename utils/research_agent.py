from typing import Literal, Optional, TypedDict, Annotated
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import os

load_dotenv()


class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: Optional[str]


# ---------------------------------------------------------------------------
# Research tools (wrap MarketResearch)
# ---------------------------------------------------------------------------

def _get_research():
    from utils.market_research_util import MarketResearch
    return MarketResearch()


@tool
def get_stock_news(ticker: Optional[str] = None, limit: int = 5) -> str:
    """Get recent news for a stock ticker, or general market news if no ticker given."""
    try:
        return _get_research().news(ticker, limit)
    except Exception as e:
        return f"Error getting news: {e}"


@tool
def get_company_profile(ticker: str) -> str:
    """Get company profile including sector, description, market cap, and key stats."""
    try:
        return _get_research().profile(ticker)
    except Exception as e:
        return f"Error getting profile: {e}"


@tool
def get_financials(ticker: str, period: str = "annual") -> str:
    """Get financial statements (income, balance sheet, cash flow). Period: 'annual' or 'quarterly'."""
    try:
        return _get_research().financials(ticker, period)
    except Exception as e:
        return f"Error getting financials: {e}"


@tool
def get_stock_price(ticker: str) -> str:
    """Get current stock price, quote data, and technical indicators."""
    try:
        return _get_research().price(ticker)
    except Exception as e:
        return f"Error getting price: {e}"


@tool
def get_market_movers(direction: str = "both") -> str:
    """Get top market movers. Direction: 'gainers', 'losers', or 'both'."""
    try:
        return _get_research().movers(direction)
    except Exception as e:
        return f"Error getting movers: {e}"


@tool
def get_analyst_ratings(ticker: str) -> str:
    """Get analyst ratings, price targets, and consensus for a stock."""
    try:
        return _get_research().analysts(ticker)
    except Exception as e:
        return f"Error getting analyst ratings: {e}"


@tool
def get_valuation(tickers: str) -> str:
    """Get valuation comparison for one or more tickers (comma-separated, e.g. 'AAPL,MSFT,GOOGL')."""
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",")]
        return _get_research().valuation(ticker_list)
    except Exception as e:
        return f"Error getting valuation: {e}"


# ---------------------------------------------------------------------------
# Agent setup
# ---------------------------------------------------------------------------
tools = [
    get_stock_news, get_company_profile, get_financials, get_stock_price,
    get_market_movers, get_analyst_ratings, get_valuation,
]

system_prompt = """\
You are AlpaTrade Research Assistant — an AI market research analyst.

You have access to the following tools:
1. get_stock_news — recent news for a ticker or the broad market
2. get_company_profile — company overview, sector, market cap
3. get_financials — income statement, balance sheet, cash flow (annual/quarterly)
4. get_stock_price — current quote and technical indicators
5. get_market_movers — top gainers and losers
6. get_analyst_ratings — analyst consensus, price targets
7. get_valuation — comparative valuation metrics across tickers

Guidelines:
- Always call the appropriate tool. Never fabricate financial data.
- When asked about cash flow, revenue, income, or balance sheet, call get_financials with the right period and synthesize a focused answer.
- Use markdown tables and bullet points for readability. Keep responses concise.
- Be precise with numbers. Explain financial terms when helpful.
"""

_model = None
_streaming_model = None
_graph = None
_streaming_graph = None


def _get_model():
    global _model
    if _model is None:
        _model = ChatOpenAI(
            model=os.getenv("GROK_MODEL", "grok-4"),
            temperature=0.7,
            streaming=False,
            api_key=os.getenv("XAI_API_KEY"),
            base_url="https://api.x.ai/v1",
        ).bind_tools(tools)
    return _model


def _get_streaming_model():
    global _streaming_model
    if _streaming_model is None:
        _streaming_model = ChatOpenAI(
            model=os.getenv("GROK_MODEL", "grok-4"),
            temperature=0.7,
            streaming=True,
            api_key=os.getenv("XAI_API_KEY"),
            base_url="https://api.x.ai/v1",
        ).bind_tools(tools)
    return _streaming_model


def get_graph():
    global _graph
    if _graph is None:
        _graph = _create_graph()
    return _graph


tool_node = ToolNode(tools)


def should_continue(state: MessagesState) -> Literal["tools", END]:
    messages = state['messages']
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END


def call_model(state: ResearchState):
    messages = state['messages']
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + list(messages)
    response = _get_model().invoke(messages)
    return {"messages": [response]}


def _create_graph():
    workflow = StateGraph(ResearchState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


def _call_streaming_model(state: ResearchState):
    messages = state['messages']
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + list(messages)
    response = _get_streaming_model().invoke(messages)
    return {"messages": [response]}


def _get_streaming_graph():
    global _streaming_graph
    if _streaming_graph is None:
        workflow = StateGraph(ResearchState)
        workflow.add_node("agent", _call_streaming_model)
        workflow.add_node("tools", tool_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")
        checkpointer = MemorySaver()
        _streaming_graph = workflow.compile(checkpointer=checkpointer)
    return _streaming_graph


async def async_stream_response(question: str, thread_id: str = "research_demo"):
    """Async generator yielding streaming events from the research agent."""
    graph = _get_streaming_graph()
    input_msg = {"messages": [{"role": "user", "content": question}]}
    config = {"configurable": {"thread_id": thread_id}}

    final_content = ""
    async for event in graph.astream_events(input_msg, config=config, version="v2"):
        evt = event.get("event", "")

        if evt == "on_tool_start":
            tool_name = event.get("name", "")
            tool_input = event.get("data", {}).get("input", {})
            yield {"type": "tool_call", "tool": tool_name, "args": tool_input}

        elif evt == "on_tool_end":
            output = str(event.get("data", {}).get("output", ""))[:500]
            yield {"type": "tool_result", "tool": event.get("name", ""), "result": output}

        elif evt == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                final_content += chunk.content
                yield {"type": "token", "content": chunk.content}

    yield {"type": "done", "content": final_content}


def get_response(question: str, thread_id: str = "research_demo") -> dict:
    """Get a response from the research agent."""
    initial_message = {
        "messages": [{"role": "user", "content": question}],
        "thread_id": thread_id,
    }
    return get_graph().invoke(
        initial_message,
        config={"configurable": {"thread_id": thread_id}},
    )


if __name__ == "__main__":
    question = "What are TSLA's latest financials?"
    final_state = get_response(question)
    for message in final_state["messages"]:
        print(f"\n{message.type.upper()}: {message.content}")

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

# https://github.com/langchain-ai/langgraph/blob/main/docs/docs/concepts/low_level.md
load_dotenv()

# Define the state type
class AlpacaState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: Optional[str]

# ---------------------------------------------------------------------------
# Lazy Alpaca client
# ---------------------------------------------------------------------------
_trading_client = None

def _get_trading_client():
    global _trading_client
    if _trading_client is None:
        from alpaca.trading.client import TradingClient
        _trading_client = TradingClient(
            os.getenv("ALPACA_PAPER_API_KEY"),
            os.getenv("ALPACA_PAPER_SECRET_KEY"),
            paper=True,
        )
    return _trading_client

# ---------------------------------------------------------------------------
# Trading tools
# ---------------------------------------------------------------------------

@tool
def get_account_info() -> str:
    """Get the current account information including buying power and equity."""
    try:
        account = _get_trading_client().get_account()
        return (
            f"Account Information:\n"
            f"- Buying Power: ${float(account.buying_power):,.2f}\n"
            f"- Cash: ${float(account.cash):,.2f}\n"
            f"- Portfolio Value: ${float(account.portfolio_value):,.2f}\n"
            f"- Pattern Day Trader: {account.pattern_day_trader}\n"
            f"- Trading Status: {account.status}"
        )
    except Exception as e:
        return f"Error getting account info: {str(e)}"

@tool
def get_assets(asset_class: Optional[str] = None) -> str:
    """
    Get available assets for trading. Optionally filter by asset class (CRYPTO or US_EQUITY).
    """
    try:
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass
        params = GetAssetsRequest()
        if asset_class:
            params.asset_class = AssetClass(asset_class.upper())

        assets = _get_trading_client().get_all_assets(params)

        response = "Available Assets:\n"
        for asset in assets[:10]:
            response += (
                f"\n{asset.symbol}:\n"
                f"- Name: {asset.name}\n"
                f"- Class: {asset.class_}\n"
                f"- Tradable: {asset.tradable}\n"
            )
        return response
    except Exception as e:
        return f"Error getting assets: {str(e)}"

@tool
def place_market_order(symbol: str, qty: float, side: str) -> str:
    """
    Place a market order for a given symbol.
    Parameters:
        symbol: The stock symbol (e.g., 'MSFT')
        qty: Number of shares
        side: 'buy' or 'sell'
    """
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY
        )

        order = _get_trading_client().submit_order(order_data)
        return (
            f"Order placed successfully:\n"
            f"- Symbol: {order.symbol}\n"
            f"- Quantity: {order.qty}\n"
            f"- Side: {order.side}\n"
            f"- Status: {order.status}\n"
            f"- Order ID: {order.id}"
        )
    except Exception as e:
        return f"Error placing order: {str(e)}"

@tool
def get_positions() -> str:
    """Get all current positions in the portfolio."""
    try:
        positions = _get_trading_client().get_all_positions()
        if not positions:
            return "No open positions."

        response = "Current Positions:\n"
        for pos in positions:
            response += (
                f"\n{pos.symbol}:\n"
                f"- Quantity: {pos.qty}\n"
                f"- Market Value: ${float(pos.market_value):,.2f}\n"
                f"- Unrealized P/L: ${float(pos.unrealized_pl):,.2f}\n"
                f"- Current Price: ${float(pos.current_price):,.2f}\n"
            )
        return response
    except Exception as e:
        return f"Error getting positions: {str(e)}"

@tool
def get_orders(status: Optional[str] = None) -> str:
    """
    Get orders. Optionally filter by status (open, closed, all).
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        params = GetOrdersRequest()
        if status:
            if status.lower() == 'open':
                params.status = QueryOrderStatus.OPEN
            elif status.lower() == 'closed':
                params.status = QueryOrderStatus.CLOSED
            else:
                params.status = QueryOrderStatus.ALL

        orders = _get_trading_client().get_orders(params)

        if not orders:
            return f"No {status or 'recent'} orders found."

        response = f"{status.capitalize() if status else 'Recent'} Orders:\n"
        for order in orders[:10]:
            response += (
                f"\n{order.symbol}:\n"
                f"- Side: {order.side}\n"
                f"- Quantity: {order.qty}\n"
                f"- Status: {order.status}\n"
                f"- Order Type: {order.order_type}\n"
                f"- Submitted: {order.submitted_at}\n"
            )
        return response
    except Exception as e:
        return f"Error getting orders: {str(e)}"

# ---------------------------------------------------------------------------
# Agent setup
# ---------------------------------------------------------------------------
tools = [get_account_info, get_assets, place_market_order, get_positions, get_orders]

system_prompt = """You are a professional trading assistant for Alpaca Markets. Your task is to help users manage their \
Alpaca trading account by providing information about assets, placing orders, and checking positions.

You have access to the following tools:
1. get_account_info: Check account balance and status
2. get_assets: View available assets for trading
3. place_market_order: Place market orders
4. get_positions: View current positions
5. get_orders: View recent or filtered orders

When placing orders:
1. Always confirm the details before executing
2. Use market orders with caution
3. Provide clear feedback about the order status
4. Remind users this is paper trading

Remember to:
1. Be precise with numbers and symbols
2. Warn about potential risks
3. Maintain a professional tone
4. Explain any errors clearly
5. Use natural, conversational language
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

def call_model(state: AlpacaState):
    messages = state['messages']
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + list(messages)
    response = _get_model().invoke(messages)
    return {"messages": [response]}

def _create_graph():
    workflow = StateGraph(AlpacaState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


def _call_streaming_model(state: AlpacaState):
    messages = state['messages']
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + list(messages)
    response = _get_streaming_model().invoke(messages)
    return {"messages": [response]}


def _get_streaming_graph():
    global _streaming_graph
    if _streaming_graph is None:
        workflow = StateGraph(AlpacaState)
        workflow.add_node("agent", _call_streaming_model)
        workflow.add_node("tools", tool_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")
        checkpointer = MemorySaver()
        _streaming_graph = workflow.compile(checkpointer=checkpointer)
    return _streaming_graph


async def async_stream_response(question: str, thread_id: str = "trading_demo"):
    """Async generator yielding streaming events from the broker agent."""
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


output_nodes = ["agent"]

def get_response(question: str, thread_id: str = "trading_demo") -> dict:
    """Get a response from the trading agent."""
    initial_message = {
        "messages": [{"role": "user", "content": question}],
        "thread_id": thread_id,
    }
    return get_graph().invoke(
        initial_message,
        config={"configurable": {"thread_id": thread_id}},
    )

if __name__ == "__main__":
    question = "What's my current account status?"
    final_state = get_response(question)
    for message in final_state["messages"]:
        print(f"\n{message.type.upper()}: {message.content}")

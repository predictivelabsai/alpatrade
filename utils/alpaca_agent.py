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
# Load environment variables
load_dotenv()

# Define the state type
class AlpacaState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: Optional[str]

# ---------------------------------------------------------------------------
# Lazy Alpaca client — avoids requiring API keys at import time
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
# Trading tools (Alpaca)
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
        for asset in assets[:10]:  # Limit to first 10 for readability
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
        for order in orders[:10]:  # Limit to 10 most recent
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
# Market research tools (wrap MarketResearch)
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
# All tools
# ---------------------------------------------------------------------------
tools = [
    # Trading
    get_account_info, get_assets, place_market_order, get_positions, get_orders,
    # Research
    get_stock_news, get_company_profile, get_financials, get_stock_price,
    get_market_movers, get_analyst_ratings, get_valuation,
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
system_prompt = """\
You are AlpaTrade Assistant — an AI trading and market research assistant for an Alpaca paper trading account.

## Tool Routing — FOLLOW STRICTLY

Match the user's intent to the CORRECT tool. Do NOT guess or fabricate data — always call a tool.

| User intent | Tool to call |
|---|---|
| "positions", "holdings", "what do I own" | get_positions |
| "balance", "buying power", "account", "equity" | get_account_info |
| "orders", "order history", "pending orders" | get_orders |
| "buy X shares of Y" / "sell X shares of Y" | place_market_order |
| "price of X", "how much is X" | get_stock_price |
| "news about X" | get_stock_news |
| "profile of X", "what does X do" | get_company_profile |
| "financials", "cash flow", "revenue", "income" | get_financials |
| "movers", "gainers", "losers" | get_market_movers |
| "analysts", "ratings", "price target" | get_analyst_ratings |
| "valuation", "P/E", "compare X vs Y" | get_valuation |

## Rules

1. **Read-only queries first**: Questions about positions, balance, orders, prices, or research → call the matching read-only tool immediately. NEVER call place_market_order for information queries.
2. **Orders**: When the user explicitly says "buy" or "sell" with a symbol and quantity, execute place_market_order directly. This is a paper account — no confirmation needed.
3. **Data precision**: Use exact numbers from tool results. Never fabricate financial data.
4. **Formatting**: Use markdown tables and bullet points for readability. Keep responses concise.
5. **Financials**: When asked about cash flow, revenue, income, or balance sheet, call get_financials with the right period (annual/quarterly) and synthesize a focused answer from the results.
"""

# ---------------------------------------------------------------------------
# Lazy model + graph
# ---------------------------------------------------------------------------
_model = None
_graph = None

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

def get_graph():
    global _graph
    if _graph is None:
        _graph = _create_graph()
    return _graph

# Create tool node
tool_node = ToolNode(tools)

def should_continue(state: MessagesState) -> Literal["tools", END]:
    """Determine if we should continue using tools or end the conversation."""
    messages = state['messages']
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END

def call_model(state: AlpacaState):
    """Call the model with the current state, injecting the system prompt."""
    messages = state['messages']
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + list(messages)
    response = _get_model().invoke(messages)
    return {"messages": [response]}

def _create_graph():
    """Create and configure the LangGraph for the Alpaca agent."""
    workflow = StateGraph(AlpacaState)

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )
    workflow.add_edge("tools", "agent")

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)

# Define the output nodes
output_nodes = ["agent"]

def get_response(
    question: str,
    thread_id: str = "trading_demo"
) -> dict:
    """
    Get a response from the trading agent for a given question.

    Args:
        question (str): The user's trading-related question
        thread_id (str): Thread identifier for the conversation

    Returns:
        dict: The final state containing the conversation
    """
    initial_message = {
        "messages": [{
            "role": "user",
            "content": question
        }],
        "thread_id": thread_id
    }

    return get_graph().invoke(
        initial_message,
        config={"configurable": {"thread_id": thread_id}}
    )

if __name__ == "__main__":
    # Test the agent directly
    question = "What's my current account status?"
    final_state = get_response(question)

    # Print the conversation
    for message in final_state["messages"]:
        print(f"\n{message.type.upper()}: {message.content}")

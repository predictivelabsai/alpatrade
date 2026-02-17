from typing import Literal, Optional, TypedDict, Annotated
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    GetAssetsRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass, QueryOrderStatus

# https://github.com/langchain-ai/langgraph/blob/main/docs/docs/concepts/low_level.md
# Load environment variables
load_dotenv()

# Define the state type
class AlpacaState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: Optional[str]

# Initialize Alpaca client
trading_client = TradingClient(
    os.getenv("ALPACA_PAPER_API_KEY"),
    os.getenv("ALPACA_PAPER_SECRET_KEY"),
    paper=True  # Use paper trading for safety
)

@tool
def get_account_info() -> str:
    """Get the current account information including buying power and equity."""
    try:
        account = trading_client.get_account()
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
        params = GetAssetsRequest()
        if asset_class:
            params.asset_class = AssetClass(asset_class.upper())
        
        assets = trading_client.get_all_assets(params)
        
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
        # Map the side string to the correct OrderSide enum
        order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
        
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY
        )
        
        order = trading_client.submit_order(order_data)
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
        positions = trading_client.get_all_positions()
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
        params = GetOrdersRequest()
        if status:
            if status.lower() == 'open':
                params.status = QueryOrderStatus.OPEN
            elif status.lower() == 'closed':
                params.status = QueryOrderStatus.CLOSED
            else:
                params.status = QueryOrderStatus.ALL
        
        orders = trading_client.get_orders(params)
        
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

# Initialize tools
tools = [get_account_info, get_assets, place_market_order, get_positions, get_orders]

# Initialize the model with a specific prompt
system_prompt = """You are a professional trading assistant for Alpaca Markets. Your task is to help users manage their 
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

# Initialize the model with XAI API
model = ChatOpenAI(
    model=os.getenv("GROK_MODEL", "grok-4"),
    temperature=0.7,
    streaming=True,
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1"
).bind_tools(tools)

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
    """Call the model with the current state."""
    messages = state['messages']
    response = model.invoke(messages)
    return {"messages": [response]}

# Create and configure the graph
def create_graph():
    """Create and configure the LangGraph for the Alpaca agent."""
    # Create the graph
    workflow = StateGraph(AlpacaState)
    
    # Add nodes
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    # Add edges
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
    
    # Initialize memory
    checkpointer = MemorySaver()
    
    # Compile the graph
    return workflow.compile(checkpointer=checkpointer)

# Create the graph
graph = create_graph()

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
    
    return graph.invoke(
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

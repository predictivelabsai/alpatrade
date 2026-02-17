#!/usr/bin/env python3
"""
Alpaca Utility Tests
Tests for Alpaca API utility functions including positions, account info, and order management
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

from utils.alpaca_util import AlpacaAPI

# Test results storage
test_results = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "tests": []
}


def print_test_result(test_name, passed, details=None, error=None):
    """Print test result to console and store in results"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"\n{status}: {test_name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    test_results["tests"].append({
        "test_name": test_name,
        "passed": passed,
        "details": details,
        "error": str(error) if error else None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def json_serializer(obj):
    """Custom JSON serializer for objects not serializable by default json code"""
    from uuid import UUID
    if isinstance(obj, UUID):
        return str(obj)
    if hasattr(obj, '__dict__'):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def save_results():
    """Save test results to JSON file"""
    results_dir = Path("test-results")
    results_dir.mkdir(exist_ok=True)
    
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results_file = results_dir / f"alpaca_util_tests_{timestamp_str}.json"
    
    # Convert non-serializable objects to strings
    def convert_to_serializable(obj):
        from uuid import UUID
        if isinstance(obj, UUID):
            return str(obj)
        elif hasattr(obj, 'value'):  # Handle enums
            return str(obj.value) if hasattr(obj, 'value') else str(obj)
        elif isinstance(obj, dict):
            return {k: convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_serializable(item) for item in obj]
        elif isinstance(obj, (datetime, type)):
            return str(obj)
        else:
            return obj
    
    serializable_results = convert_to_serializable(test_results)
    
    with open(results_file, 'w') as f:
        json.dump(serializable_results, f, indent=2, default=str)
    
    print(f"\n📄 Test results saved to: {results_file}")
    return results_file


def test_account_info(client):
    """Test getting account information"""
    print("\n" + "="*60)
    print("TEST: Get Account Information")
    print("="*60)
    
    try:
        account = client.get_account()
        
        if 'error' in account:
            print_test_result("Get Account Info", False, error=account['error'])
            return None
        
        # Extract key account fields
        account_summary = {
            "portfolio_value": float(account.get('portfolio_value', 0)),
            "cash": float(account.get('cash', 0)),
            "buying_power": float(account.get('buying_power', 0)),
            "equity": float(account.get('equity', 0)),
            "status": str(account.get('status', '')),
            "pattern_day_trader": bool(account.get('pattern_day_trader', False)),
            "trading_blocked": bool(account.get('trading_blocked', False))
        }
        
        print(f"Portfolio Value: ${account_summary['portfolio_value']:,.2f}")
        print(f"Cash: ${account_summary['cash']:,.2f}")
        print(f"Buying Power: ${account_summary['buying_power']:,.2f}")
        print(f"Equity: ${account_summary['equity']:,.2f}")
        print(f"Status: {account_summary['status']}")
        print(f"Pattern Day Trader: {account_summary['pattern_day_trader']}")
        print(f"Trading Blocked: {account_summary['trading_blocked']}")
        
        print_test_result("Get Account Info", True, account_summary)
        return account_summary
        
    except Exception as e:
        print_test_result("Get Account Info", False, error=e)
        return None


def test_get_all_positions(client):
    """Test getting all positions"""
    print("\n" + "="*60)
    print("TEST: Get All Positions")
    print("="*60)
    
    try:
        positions = client.get_positions()
        
        if isinstance(positions, dict) and 'error' in positions:
            print_test_result("Get All Positions", False, error=positions['error'])
            return []
        
        print(f"Found {len(positions)} positions:")
        
        positions_summary = []
        for pos in positions:
            pos_info = {
                "symbol": pos.get('symbol'),
                "qty": float(pos.get('qty', 0)),
                "market_value": float(pos.get('market_value', 0)),
                "unrealized_pl": float(pos.get('unrealized_pl', 0)),
                "current_price": float(pos.get('current_price', 0))
            }
            positions_summary.append(pos_info)
            
            print(f"  {pos_info['symbol']}: {pos_info['qty']} shares @ ${pos_info['current_price']:.2f}")
            print(f"    Market Value: ${pos_info['market_value']:,.2f}")
            print(f"    Unrealized P/L: ${pos_info['unrealized_pl']:,.2f}")
        
        if len(positions) == 0:
            print("  No open positions")
        
        print_test_result("Get All Positions", True, {"count": len(positions), "positions": positions_summary})
        return positions
        
    except Exception as e:
        print_test_result("Get All Positions", False, error=e)
        return []


def test_get_specific_position(client, symbol="AAPL"):
    """Test getting a specific position"""
    print("\n" + "="*60)
    print(f"TEST: Get Position for {symbol}")
    print("="*60)
    
    try:
        position = client.get_position(symbol)
        
        if position is None:
            print(f"No position found for {symbol}")
            print_test_result(f"Get Position ({symbol})", True, {"position": None})
            return None
        
        if isinstance(position, dict) and 'error' in position:
            print_test_result(f"Get Position ({symbol})", False, error=position['error'])
            return None
        
        pos_info = {
            "symbol": position.get('symbol'),
            "qty": float(position.get('qty', 0)),
            "market_value": float(position.get('market_value', 0)),
            "unrealized_pl": float(position.get('unrealized_pl', 0)),
            "current_price": float(position.get('current_price', 0))
        }
        
        print(f"Symbol: {pos_info['symbol']}")
        print(f"Quantity: {pos_info['qty']}")
        print(f"Current Price: ${pos_info['current_price']:.2f}")
        print(f"Market Value: ${pos_info['market_value']:,.2f}")
        print(f"Unrealized P/L: ${pos_info['unrealized_pl']:,.2f}")
        
        print_test_result(f"Get Position ({symbol})", True, pos_info)
        return position
        
    except Exception as e:
        print_test_result(f"Get Position ({symbol})", False, error=e)
        return None


def test_create_market_order(client, symbol="SPY", qty=1):
    """Test creating a market order"""
    print("\n" + "="*60)
    print(f"TEST: Create Market Order - BUY {qty} {symbol}")
    print("="*60)
    
    try:
        # Check if we already have a position
        existing_pos = client.get_position(symbol)
        if existing_pos and isinstance(existing_pos, dict) and 'error' not in existing_pos:
            print(f"⚠️  Warning: Already have position in {symbol}")
            print(f"   Quantity: {existing_pos.get('qty')}")
            print("   Skipping order creation to avoid duplicate position")
            print_test_result("Create Market Order", True, {"skipped": True, "reason": "Existing position"})
            return None
        
        # Get account info to check buying power
        account = client.get_account()
        if 'error' in account:
            print_test_result("Create Market Order", False, error="Cannot get account info")
            return None
        
        buying_power = float(account.get('buying_power', 0))
        print(f"Buying Power: ${buying_power:,.2f}")
        
        # Create market order
        result = client.create_order(
            symbol=symbol,
            qty=qty,
            side='buy',
            type='market',
            time_in_force='day'
        )
        
        if 'error' in result:
            print_test_result("Create Market Order", False, error=result['error'])
            return None
        
        order_id = result.get('id')
        order_info = {
            "order_id": str(order_id) if order_id else None,
            "symbol": result.get('symbol'),
            "qty": float(result.get('qty', 0)),
            "side": str(result.get('side', '')) if result.get('side') else None,
            "order_type": str(result.get('order_type', '')) if result.get('order_type') else None,
            "status": str(result.get('status', '')) if result.get('status') else None,
            "submitted_at": str(result.get('submitted_at')) if result.get('submitted_at') else None
        }
        
        print(f"Order ID: {order_info['order_id']}")
        print(f"Symbol: {order_info['symbol']}")
        print(f"Quantity: {order_info['qty']}")
        print(f"Side: {order_info['side']}")
        print(f"Type: {order_info['order_type']}")
        print(f"Status: {order_info['status']}")
        
        print_test_result("Create Market Order", True, order_info)
        return {"result": result, "order_id": order_id}
        
    except Exception as e:
        print_test_result("Create Market Order", False, error=e)
        return None


def test_cancel_order(client, order_id):
    """Test cancelling an order"""
    print("\n" + "="*60)
    print(f"TEST: Cancel Order {order_id}")
    print("="*60)
    
    try:
        result = client.cancel_order(order_id)
        
        if 'error' in result:
            error_msg = result['error']
            # If order is already filled, that's actually a success (order executed)
            if isinstance(error_msg, dict) and error_msg.get('message', '').find('filled') != -1:
                print(f"Order {order_id} already filled (order executed successfully)")
                print_test_result("Cancel Order", True, {"order_id": str(order_id), "status": "filled", "note": "Order executed before cancellation"})
                return True
            else:
                print_test_result("Cancel Order", False, error=error_msg)
                return False
        
        print(f"Order {order_id} cancelled successfully")
        print_test_result("Cancel Order", True, {"order_id": str(order_id), "status": "cancelled"})
        return True
        
    except Exception as e:
        print_test_result("Cancel Order", False, error=e)
        return False


def test_get_open_orders(client):
    """Test getting open orders"""
    print("\n" + "="*60)
    print("TEST: Get Open Orders")
    print("="*60)
    
    try:
        orders = client.get_orders(status='open')
        
        if isinstance(orders, dict) and 'error' in orders:
            print_test_result("Get Open Orders", False, error=orders['error'])
            return []
        
        print(f"Found {len(orders)} open orders:")
        
        orders_summary = []
        for order in orders:
            order_info = {
                "order_id": order.get('id'),
                "symbol": order.get('symbol'),
                "qty": float(order.get('qty', 0)),
                "side": order.get('side'),
                "order_type": order.get('order_type'),
                "status": order.get('status')
            }
            orders_summary.append(order_info)
            
            print(f"  {order_info['order_id']}: {order_info['side']} {order_info['qty']} {order_info['symbol']} ({order_info['status']})")
        
        if len(orders) == 0:
            print("  No open orders")
        
        print_test_result("Get Open Orders", True, {"count": len(orders), "orders": orders_summary})
        return orders
        
    except Exception as e:
        print_test_result("Get Open Orders", False, error=e)
        return []


def main():
    """Run all tests"""
    print("="*60)
    print("ALPACA UTILITY TESTS")
    print("="*60)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    
    # Initialize client
    api_key = os.getenv('ALPACA_PAPER_API_KEY')
    secret_key = os.getenv('ALPACA_PAPER_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ ERROR: ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY must be set in .env")
        sys.exit(1)
    
    client = AlpacaAPI(api_key=api_key, secret_key=secret_key, paper=True)
    print(f"✅ Connected to Alpaca (Paper Trading)")
    
    # Run tests
    account_info = test_account_info(client)
    
    all_positions = test_get_all_positions(client)
    
    # Test getting specific positions
    test_symbols = ["AAPL", "MSFT", "NVDA", "SPY"]
    for symbol in test_symbols:
        test_get_specific_position(client, symbol)
    
    # Test getting open orders
    open_orders = test_get_open_orders(client)
    
    # Test creating a market order (only if we have buying power)
    if account_info and account_info.get('buying_power', 0) > 0:
        # Use a small quantity for testing (1 share of SPY)
        test_result = test_create_market_order(client, symbol="SPY", qty=1)
        
        # If order was created, test cancelling it
        if test_result and isinstance(test_result, dict) and test_result.get('order_id'):
            order_id = test_result['order_id']
            # Wait a moment for order to be processed
            import time
            time.sleep(2)
            test_cancel_order(client, str(order_id))
    else:
        print("\n⚠️  Skipping order creation test: insufficient buying power")
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    total_tests = len(test_results["tests"])
    passed_tests = sum(1 for t in test_results["tests"] if t["passed"])
    failed_tests = total_tests - passed_tests
    
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {failed_tests}")
    
    # Save results
    results_file = save_results()
    
    # Exit with error code if any tests failed
    if failed_tests > 0:
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)


if __name__ == '__main__':
    main()


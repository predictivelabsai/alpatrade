#!/usr/bin/env python3
"""Test script for TUI command processor"""
import asyncio
from datetime import datetime, timedelta
from tui.command_processor import CommandProcessor

class MockApp:
    def __init__(self):
        self.command_history = []
        self.current_strategy = None
        self.current_symbols = []

async def test_command():
    app = MockApp()
    processor = CommandProcessor(app)
    
    # Test help command
    print("=" * 80)
    print("Testing: help")
    print("=" * 80)
    result = await processor.process_command("help")
    print(result[:500] + "..." if len(result) > 500 else result)
    
    # Test backtest command
    print("\n" + "=" * 80)
    print("Testing: alpaca:backtest strategy:buy-the-dip lookback:1m")
    print("=" * 80)
    result = await processor.process_command("alpaca:backtest strategy:buy-the-dip lookback:1m")
    print(result[:1000] + "..." if len(result) > 1000 else result)

if __name__ == "__main__":
    asyncio.run(test_command())

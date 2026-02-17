#!/usr/bin/env python3
"""Capture screenshots of the TUI"""
import asyncio
import time
from textual.pilot import Pilot
from tui.app import StrategySimulatorApp

async def capture_screenshots():
    app = StrategySimulatorApp()
    
    async with app.run_test() as pilot:
        # Wait for app to load
        await pilot.pause(1)
        
        # Capture welcome screen
        await pilot.pause(0.5)
        app.save_screenshot("/home/ubuntu/strategy-simulator/screenshots/01_welcome.svg")
        
        # Type help command
        await pilot.press("h", "e", "l", "p")
        await pilot.press("enter")
        await pilot.pause(1)
        app.save_screenshot("/home/ubuntu/strategy-simulator/screenshots/02_help.svg")
        
        # Clear and run a backtest
        await pilot.press("ctrl+l")
        await pilot.pause(0.5)
        
        # Type backtest command
        command = "alpaca:backtest strategy:buy-the-dip lookback:1m"
        for char in command:
            await pilot.press(char)
            await pilot.pause(0.02)
        
        await pilot.pause(0.5)
        app.save_screenshot("/home/ubuntu/strategy-simulator/screenshots/03_command_typed.svg")
        
        # Execute command
        await pilot.press("enter")
        await pilot.pause(3)  # Wait for backtest to complete
        app.save_screenshot("/home/ubuntu/strategy-simulator/screenshots/04_backtest_results.svg")
        
        # Test status command
        await pilot.press("ctrl+l")
        await pilot.pause(0.5)
        await pilot.press("s", "t", "a", "t", "u", "s")
        await pilot.press("enter")
        await pilot.pause(1)
        app.save_screenshot("/home/ubuntu/strategy-simulator/screenshots/05_status.svg")
        
        # Test momentum strategy
        await pilot.press("ctrl+l")
        await pilot.pause(0.5)
        command2 = "alpaca:backtest strategy:momentum lookback:3m"
        for char in command2:
            await pilot.press(char)
            await pilot.pause(0.02)
        await pilot.press("enter")
        await pilot.pause(3)
        app.save_screenshot("/home/ubuntu/strategy-simulator/screenshots/06_momentum_results.svg")

if __name__ == "__main__":
    asyncio.run(capture_screenshots())
    print("Screenshots captured successfully!")

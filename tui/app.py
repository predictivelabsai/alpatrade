"""
AlpaTrade TUI Application
Re-exports StrategyCLI for backward compatibility.
The Rich-based CLI in strategy_cli.py is the primary interface.
"""
from tui.strategy_cli import StrategyCLI

# Backward-compatible alias
StrategySimulatorApp = StrategyCLI

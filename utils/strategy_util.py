"""
Strategy Utility Module
Central registry and factory for all trading strategies
"""

from typing import Dict, Callable, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class StrategyMetadata:
    """Metadata for a trading strategy"""
    name: str
    display_name: str
    description: str
    parameters: List[Dict[str, Any]]


class StrategyRegistry:
    """Registry for all available trading strategies"""
    
    _strategies: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def register(cls, name: str, metadata: StrategyMetadata, backtest_func: Callable):
        """
        Register a new strategy
        
        Args:
            name: Internal strategy name (e.g., 'buy_the_dip')
            metadata: Strategy metadata
            backtest_func: Backtest function for the strategy
        """
        cls._strategies[name] = {
            'metadata': metadata,
            'backtest_func': backtest_func
        }
    
    @classmethod
    def get_strategy(cls, name: str) -> Dict[str, Any]:
        """Get strategy by name"""
        if name not in cls._strategies:
            raise ValueError(f"Strategy '{name}' not found in registry")
        return cls._strategies[name]
    
    @classmethod
    def get_all_strategies(cls) -> Dict[str, Dict[str, Any]]:
        """Get all registered strategies"""
        return cls._strategies.copy()
    
    @classmethod
    def get_strategy_names(cls) -> List[str]:
        """Get list of all strategy names"""
        return list(cls._strategies.keys())
    
    @classmethod
    def execute_backtest(cls, strategy_name: str, **kwargs):
        """
        Execute backtest for a given strategy
        
        Args:
            strategy_name: Name of the strategy to backtest
            **kwargs: Strategy-specific parameters
            
        Returns:
            Tuple of (trades_df, metrics_dict)
        """
        strategy = cls.get_strategy(strategy_name)
        backtest_func = strategy['backtest_func']
        return backtest_func(**kwargs)


def get_all_strategies() -> Dict[str, Dict[str, Any]]:
    """Convenience function to get all registered strategies"""
    return StrategyRegistry.get_all_strategies()


def get_strategy_names() -> List[str]:
    """Convenience function to get all strategy names"""
    return StrategyRegistry.get_strategy_names()


def execute_strategy_backtest(strategy_name: str, **kwargs):
    """Convenience function to execute a strategy backtest"""
    return StrategyRegistry.execute_backtest(strategy_name, **kwargs)

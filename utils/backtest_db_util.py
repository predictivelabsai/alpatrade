#!/usr/bin/env python3
"""
Backtest Database Utilities

This module provides utilities for storing and retrieving backtest results
in the existing backtest_summary and individual trade tables.
"""

import os
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from decimal import Decimal

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.db.db_pool import DatabasePool
from sqlalchemy import text
import logging
backtest_logger = logging.getLogger("backtest_db_util")

class BacktestDatabaseUtil:
    """Database utilities for backtest operations"""
    
    def __init__(self):
        """Initialize the backtest database utility"""
        self.db_pool = DatabasePool()
        backtest_logger.info("Backtest database utility initialized")
    
    def store_backtest_summary(self, backtest_data: Dict[str, Any]) -> str:
        """Store backtest summary results in the database"""
        with self.db_pool.get_session() as session:
            # Generate run_id if not provided
            run_id = backtest_data.get('run_id', str(uuid.uuid4()))
            
            # Prepare backtest summary data
            summary_data = {
                'run_id': run_id,
                'timestamp': datetime.now(),
                'model_name': backtest_data.get('model_name', 'prediction_llm'),
                'start_date': datetime.fromisoformat(backtest_data['start_date'].replace('/', '-')),
                'end_date': datetime.fromisoformat(backtest_data['end_date'].replace('/', '-')),
                'initial_capital': float(backtest_data.get('initial_capital', 10000)),
                'final_capital': float(backtest_data.get('final_capital', 10000)),
                'total_pnl': float(backtest_data.get('total_pnl', 0)),
                'return_percent': float(backtest_data.get('return_percent', 0)),
                'total_trades': int(backtest_data.get('total_trades', 0)),
                'winning_trades': int(backtest_data.get('winning_trades', 0)),
                'losing_trades': int(backtest_data.get('losing_trades', 0)),
                'win_rate_percent': float(backtest_data.get('win_rate_percent', 0)),
                'max_drawdown': float(backtest_data.get('max_drawdown', 0)),
                'sharpe_ratio': float(backtest_data.get('sharpe_ratio', 0)),
                'news_articles_used': int(backtest_data.get('news_articles_used', 0)),
                'price_moves_used': int(backtest_data.get('price_moves_used', 0)),
                'database_version': backtest_data.get('database_version', 'v1.0'),
                'agent': backtest_data.get('agent', 'manus'),
                'annualized_return': float(backtest_data.get('annualized_return', 0.0)),
                'rundate': datetime.now().date(),
                'notes': backtest_data.get('notes', ''),
                'strategy_id': backtest_data.get('strategy_id')
            }
            
            # Insert backtest summary
            # Add strategy_id column if present; table must be altered separately
            insert_query = text("""
                INSERT INTO backtest_summary (
                    run_id, timestamp, model_name, start_date, end_date,
                    initial_capital, final_capital, total_pnl, return_percent,
                    total_trades, winning_trades, losing_trades, win_rate_percent,
                    max_drawdown, sharpe_ratio, news_articles_used, price_moves_used,
                    database_version, agent, annualized_return, rundate, notes, strategy_id
                ) VALUES (
                    :run_id, :timestamp, :model_name, :start_date, :end_date,
                    :initial_capital, :final_capital, :total_pnl, :return_percent,
                    :total_trades, :winning_trades, :losing_trades, :win_rate_percent,
                    :max_drawdown, :sharpe_ratio, :news_articles_used, :price_moves_used,
                    :database_version, :agent, :annualized_return, :rundate, :notes, :strategy_id
                )
            """)
            
            session.execute(insert_query, summary_data)
            
            backtest_logger.info(f"Stored backtest summary with run_id: {run_id}")
            return run_id
    
    def store_individual_trade(self, trade_data: Dict[str, Any], run_id: str) -> int:
        """Store individual trade result in the database"""
        with self.db_pool.get_session() as session:
            # Generate news_id if not provided (auto-generate as requested)
            news_id = trade_data.get('news_id', self._generate_news_id())
            
            # Prepare trade data
            trade_fields = {
                'published_date': datetime.fromisoformat(trade_data['published_date']) if isinstance(trade_data['published_date'], str) else trade_data['published_date'],
                'market': trade_data.get('market', 'US'),
                'entry_time': datetime.fromisoformat(trade_data['entry_time']) if isinstance(trade_data['entry_time'], str) else trade_data['entry_time'],
                'exit_time': datetime.fromisoformat(trade_data['exit_time']) if isinstance(trade_data['exit_time'], str) else trade_data['exit_time'],
                'ticker': trade_data['ticker'],
                'direction': trade_data['direction'],  # 'long' or 'short'
                'shares': int(trade_data.get('shares', 1)),
                'entry_price': float(trade_data['entry_price']),
                'exit_price': float(trade_data['exit_price']),
                'target_price': float(trade_data.get('target_price', 0)),
                'stop_price': float(trade_data.get('stop_price', 0)),
                'hit_target': bool(trade_data.get('hit_target', False)),
                'hit_stop': bool(trade_data.get('hit_stop', False)),
                'pnl': float(trade_data.get('pnl', 0)),
                'pnl_pct': float(trade_data.get('pnl_pct', 0)),
                'capital_after': float(trade_data.get('capital_after', 0)),
                'news_event': trade_data.get('news_event', 'unknown'),
                'link': trade_data.get('link', ''),
                'runid': run_id,
                'rundate': datetime.now(),
                'created_at': datetime.now(),
                'news_id': news_id,
                'agent': trade_data.get('agent', 'manus')
            }
            
            # Insert individual trade
            insert_query = text("""
                INSERT INTO individual_trades (
                    published_date, market, entry_time, exit_time, ticker, direction,
                    shares, entry_price, exit_price, target_price, stop_price,
                    hit_target, hit_stop, pnl, pnl_pct, capital_after,
                    news_event, link, runid, rundate, created_at, news_id, agent
                ) VALUES (
                    :published_date, :market, :entry_time, :exit_time, :ticker, :direction,
                    :shares, :entry_price, :exit_price, :target_price, :stop_price,
                    :hit_target, :hit_stop, :pnl, :pnl_pct, :capital_after,
                    :news_event, :link, :runid, :rundate, :created_at, :news_id, :agent
                ) RETURNING id
            """)
            
            result = session.execute(insert_query, trade_fields)
            trade_id = result.scalar()
            
            backtest_logger.info(f"Stored individual trade with id: {trade_id} for run_id: {run_id}")
            return trade_id
    
    def _generate_news_id(self) -> int:
        """Generate a unique news_id for trades (auto-generated as requested)"""
        # Use timestamp-based ID to ensure uniqueness
        timestamp = int(datetime.now().timestamp() * 1000000)  # microseconds
        return timestamp % 2147483647  # Keep within int4 range
    
    def get_backtest_summary(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve backtest summary by run_id"""
        with self.db_pool.get_session() as session:
            query = text("""
                SELECT * FROM backtest_summary WHERE run_id = :run_id
            """)
            
            result = session.execute(query, {'run_id': run_id})
            row = result.fetchone()
            
            if row:
                # Convert row to dictionary
                columns = result.keys()
                return dict(zip(columns, row))
            else:
                return None
    
    def get_individual_trades(self, run_id: str) -> List[Dict[str, Any]]:
        """Retrieve all individual trades for a run_id"""
        with self.db_pool.get_session() as session:
            query = text("""
                SELECT * FROM individual_trades 
                WHERE runid = :run_id 
                ORDER BY entry_time
            """)
            
            # Convert UUID to string if needed
            run_id_str = str(run_id) if hasattr(run_id, 'hex') else run_id
            
            result = session.execute(query, {'run_id': run_id_str})
            rows = result.fetchall()
            
            # Convert rows to list of dictionaries
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
    
    def get_recent_backtests(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent backtest summaries"""
        with self.db_pool.get_session() as session:
            query = text("""
                SELECT run_id, timestamp, model_name, start_date, end_date,
                       initial_capital, final_capital, total_pnl, return_percent, total_trades,
                       winning_trades, losing_trades, win_rate_percent, max_drawdown, 
                       sharpe_ratio, news_articles_used, price_moves_used, agent
                FROM backtest_summary 
                ORDER BY timestamp DESC 
                LIMIT :limit
            """)
            
            result = session.execute(query, {'limit': limit})
            rows = result.fetchall()
            
            # Convert rows to list of dictionaries
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
    
    def get_backtest_statistics(self) -> Dict[str, Any]:
        """Get overall backtest statistics"""
        with self.db_pool.get_session() as session:
            # Get summary statistics
            summary_query = text("""
                SELECT 
                    COUNT(*) as total_backtests,
                    AVG(return_percent) as avg_return,
                    AVG(win_rate_percent) as avg_win_rate,
                    AVG(sharpe_ratio) as avg_sharpe_ratio,
                    SUM(total_trades) as total_trades_all,
                    MIN(timestamp) as earliest_backtest,
                    MAX(timestamp) as latest_backtest
                FROM backtest_summary
            """)
            
            result = session.execute(summary_query)
            summary_row = result.fetchone()
            
            # Get trade statistics
            trade_query = text("""
                SELECT 
                    COUNT(*) as total_individual_trades,
                    AVG(pnl_pct) as avg_trade_return,
                    COUNT(CASE WHEN pnl > 0 THEN 1 END) as profitable_trades,
                    COUNT(DISTINCT ticker) as unique_tickers,
                    COUNT(DISTINCT runid) as runs_with_trades
                FROM individual_trades
            """)
            
            result = session.execute(trade_query)
            trade_row = result.fetchone()
            
            # Combine statistics
            stats = {}
            if summary_row:
                summary_columns = ['total_backtests', 'avg_return', 'avg_win_rate', 'avg_sharpe_ratio', 
                                 'total_trades_all', 'earliest_backtest', 'latest_backtest']
                for i, col in enumerate(summary_columns):
                    stats[col] = summary_row[i]
            
            if trade_row:
                trade_columns = ['total_individual_trades', 'avg_trade_return', 'profitable_trades', 
                               'unique_tickers', 'runs_with_trades']
                for i, col in enumerate(trade_columns):
                    stats[col] = trade_row[i]
            
            return stats
    
    def delete_backtest(self, run_id: str) -> bool:
        """Delete a backtest and all its associated trades"""
        with self.db_pool.get_session() as session:
            # Delete individual trades first (foreign key constraint)
            delete_trades_query = text("""
                DELETE FROM individual_trades WHERE runid = :run_id
            """)
            trades_result = session.execute(delete_trades_query, {'run_id': run_id})
            
            # Delete backtest summary
            delete_summary_query = text("""
                DELETE FROM backtest_summary WHERE run_id = :run_id
            """)
            summary_result = session.execute(delete_summary_query, {'run_id': run_id})
            
            backtest_logger.info(f"Deleted backtest {run_id}: {trades_result.rowcount} trades, {summary_result.rowcount} summary")
            return summary_result.rowcount > 0


# Convenience functions for easy import
def store_backtest_summary(backtest_data: Dict[str, Any]) -> str:
    """Store backtest summary - convenience function"""
    util = BacktestDatabaseUtil()
    return util.store_backtest_summary(backtest_data)

def store_individual_trade(trade_data: Dict[str, Any], run_id: str) -> int:
    """Store individual trade - convenience function"""
    util = BacktestDatabaseUtil()
    return util.store_individual_trade(trade_data, run_id)

def get_backtest_summary(run_id: str) -> Optional[Dict[str, Any]]:
    """Get backtest summary - convenience function"""
    util = BacktestDatabaseUtil()
    return util.get_backtest_summary(run_id)

def get_individual_trades(run_id: str) -> List[Dict[str, Any]]:
    """Get individual trades - convenience function"""
    util = BacktestDatabaseUtil()
    return util.get_individual_trades(run_id)

def get_recent_backtests(limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent backtests - convenience function"""
    util = BacktestDatabaseUtil()
    return util.get_recent_backtests(limit)

def get_backtest_statistics() -> Dict[str, Any]:
    """Get backtest statistics - convenience function"""
    util = BacktestDatabaseUtil()
    return util.get_backtest_statistics()


"""Pydantic request/response models for AlpaTrade API v2."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Existing models (originally in api_app.py, now canonical home)
# ---------------------------------------------------------------------------

class CmdRequest(BaseModel):
    command: str


class BacktestRequest(BaseModel):
    lookback: str = Field("3m", description="Lookback period, e.g. '3m', '6m', '1y'")
    symbols: Optional[str] = Field(None, description="Comma-separated symbols, e.g. 'AAPL,MSFT'")
    strategy: str = Field("buy_the_dip", description="Strategy name: buy_the_dip, vix, momentum, box_wedge")
    capital: Optional[float] = Field(None, description="Initial capital in USD")
    hours: Optional[str] = Field(None, description="'regular' or 'extended'")
    intraday_exit: Optional[bool] = Field(None, description="Use 5-min intraday bars for TP/SL exits")
    pdt: Optional[bool] = Field(None, description="Enforce PDT rule (default True, set False for >$25k accounts)")

    model_config = {"json_schema_extra": {
        "examples": [{"lookback": "3m", "strategy": "buy_the_dip", "capital": 10000}]
    }}


class PaperRequest(BaseModel):
    duration: str = Field("7d", description="Paper trading duration, e.g. '1h', '7d', '1m'")
    symbols: Optional[str] = None
    strategy: str = "buy_the_dip"
    poll: Optional[int] = Field(None, description="Poll interval in seconds")
    hours: Optional[str] = None
    email: Optional[bool] = Field(None, description="Send daily P&L email reports")
    pdt: Optional[bool] = None

    model_config = {"json_schema_extra": {
        "examples": [{"duration": "7d", "strategy": "buy_the_dip"}]
    }}


class ValidateRequest(BaseModel):
    run_id: str = Field(..., description="UUID of the run to validate")
    source: str = Field("backtest", description="'backtest' or 'paper'")


class FullCycleRequest(BaseModel):
    lookback: str = "3m"
    duration: str = "7d"
    symbols: Optional[str] = None
    strategy: str = "buy_the_dip"
    capital: Optional[float] = None
    hours: Optional[str] = None
    intraday_exit: Optional[bool] = None
    pdt: Optional[bool] = None
    poll: Optional[int] = None


class ReconcileRequest(BaseModel):
    window_days: int = Field(7, description="Number of days to reconcile")


class ApiResponse(BaseModel):
    """Legacy response wrapper (markdown string)."""
    result: str
    status: str


class AuthRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
    user_id: str
    email: str


# ---------------------------------------------------------------------------
# V2 Response Models — Trades
# ---------------------------------------------------------------------------

class TradeItem(BaseModel):
    id: Optional[int] = None
    run_id: str
    trade_type: str
    symbol: Optional[str] = None
    direction: Optional[str] = None
    shares: Optional[float] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    hit_target: Optional[bool] = None
    hit_stop: Optional[bool] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    total_fees: Optional[float] = None
    reason: Optional[str] = None


class TradesResponse(BaseModel):
    trades: List[TradeItem]
    total: int


# ---------------------------------------------------------------------------
# V2 Response Models — Runs
# ---------------------------------------------------------------------------

class RunItem(BaseModel):
    run_id: str
    mode: str
    strategy: Optional[str] = None
    strategy_slug: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class RunsResponse(BaseModel):
    runs: List[RunItem]
    total: int


# ---------------------------------------------------------------------------
# V2 Response Models — Backtest
# ---------------------------------------------------------------------------

class BestConfig(BaseModel):
    sharpe_ratio: Optional[float] = None
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    total_pnl: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = None
    max_drawdown: Optional[float] = None
    params: Optional[Dict[str, Any]] = None


class BacktestResponse(BaseModel):
    run_id: str
    strategy: str
    total_variations: int = 0
    best_config: Optional[BestConfig] = None
    status: str = "completed"


# ---------------------------------------------------------------------------
# V2 Response Models — Validation
# ---------------------------------------------------------------------------

class ValidationResponse(BaseModel):
    run_id: str
    status: str
    total_trades_checked: int = 0
    anomalies_found: int = 0
    anomalies_corrected: int = 0
    iterations_used: int = 0
    suggestions: List[str] = []


# ---------------------------------------------------------------------------
# V2 Response Models — Paper Trading
# ---------------------------------------------------------------------------

class PaperStartResponse(BaseModel):
    run_id: str
    status: str = "started"
    strategy: str
    symbols: Optional[List[str]] = None
    duration: str
    poll_interval: Optional[int] = None


# ---------------------------------------------------------------------------
# V2 Response Models — Full Cycle
# ---------------------------------------------------------------------------

class FullCyclePhase(BaseModel):
    status: str
    run_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


class FullCycleResponse(BaseModel):
    run_id: str
    status: str
    phases: Dict[str, FullCyclePhase] = {}


# ---------------------------------------------------------------------------
# V2 Response Models — Reconcile
# ---------------------------------------------------------------------------

class ReconcileResponse(BaseModel):
    run_id: str
    status: str
    total_issues: int = 0
    position_mismatches: List[Dict[str, Any]] = []
    trade_mismatches: List[Dict[str, Any]] = []
    pnl_comparison: Optional[Dict[str, Any]] = None
    missing_trades: List[Dict[str, Any]] = []
    extra_trades: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# V2 Response Models — Status
# ---------------------------------------------------------------------------

class AgentStatus(BaseModel):
    name: str
    status: str
    current_task: Optional[str] = None


class StatusResponse(BaseModel):
    run_id: Optional[str] = None
    mode: Optional[str] = None
    status: str
    agents: List[AgentStatus] = []
    started_at: Optional[datetime] = None
    elapsed_seconds: Optional[float] = None
    best_config: Optional[BestConfig] = None


# ---------------------------------------------------------------------------
# V2 Response Models — Stop / Logs
# ---------------------------------------------------------------------------

class StopResponse(BaseModel):
    stopped: bool
    message: str


class LogsResponse(BaseModel):
    lines: List[str]
    total_lines: int


# ---------------------------------------------------------------------------
# V2 Response Models — P&L
# ---------------------------------------------------------------------------

class PnlSymbolBreakdown(BaseModel):
    symbol: str
    total_pnl: float = 0
    total_fees: float = 0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    avg_pnl: Optional[float] = None


class DailyPnl(BaseModel):
    date: str
    pnl: float = 0
    trade_count: int = 0


class PnlResponse(BaseModel):
    run_id: str
    strategy: Optional[str] = None
    mode: Optional[str] = None
    total_pnl: float = 0
    total_return: Optional[float] = None
    total_fees: float = 0
    win_rate: Optional[float] = None
    winning_trades: int = 0
    losing_trades: int = 0
    total_trades: int = 0
    sharpe_ratio: Optional[float] = None
    per_symbol: List[PnlSymbolBreakdown] = []
    daily_pnl: List[DailyPnl] = []


# ---------------------------------------------------------------------------
# V2 Response Models — Report
# ---------------------------------------------------------------------------

class ReportSummaryItem(BaseModel):
    run_id: str
    mode: str
    strategy: Optional[str] = None
    strategy_slug: Optional[str] = None
    status: str
    initial_capital: Optional[float] = None
    total_pnl: Optional[float] = None
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    total_trades: Optional[int] = None
    data_start: Optional[datetime] = None
    data_end: Optional[datetime] = None
    run_date: Optional[datetime] = None


class ReportDetail(BaseModel):
    run_id: str
    mode: str
    strategy: Optional[str] = None
    strategy_slug: Optional[str] = None
    status: str
    initial_capital: Optional[float] = None
    final_capital: Optional[float] = None
    total_pnl: Optional[float] = None
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None
    data_start: Optional[datetime] = None
    data_end: Optional[datetime] = None
    run_date: Optional[datetime] = None


class TopStrategyItem(BaseModel):
    strategy_slug: str
    avg_sharpe: Optional[float] = None
    avg_return: Optional[float] = None
    avg_ann_return: Optional[float] = None
    avg_win_rate: Optional[float] = None
    avg_drawdown: Optional[float] = None
    total_trades: int = 0
    total_runs: int = 0
    avg_pnl: Optional[float] = None


# ---------------------------------------------------------------------------
# V2 Response Models — Positions
# ---------------------------------------------------------------------------

class PositionItem(BaseModel):
    id: Optional[int] = None
    run_id: str
    symbol: str
    side: str
    shares: float
    avg_entry_price: Optional[float] = None
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    cost_basis: Optional[float] = None
    status: str = "open"
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class PositionsResponse(BaseModel):
    positions: List[PositionItem]
    total: int

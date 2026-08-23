"""Pydantic request/response models for AlpaTrade API v2."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Existing models (originally in api_app.py, now canonical home)
# ---------------------------------------------------------------------------

class CmdRequest(BaseModel):
    command: str


class BacktestRequest(BaseModel):
    account_id: Optional[str] = Field(None, description="Specific AlpaTrade account_id snippet to run the backtest under (optional)")
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
    account_id: Optional[str] = Field(None, description="Specific AlpaTrade account_id UUID to paper trade under (optional)")
    duration: str = Field("7d", description="Paper trading duration, e.g. '1h', '7d', '1m'")
    symbols: Optional[str] = None
    strategy: str = "buy_the_dip"
    poll: Optional[int] = Field(None, description="Poll interval in seconds")
    hours: Optional[str] = None
    email: Optional[bool] = Field(None, description="Send daily P&L email reports")
    pdt: Optional[bool] = None
    params: Optional[Dict[str, Any]] = Field(
        None, description="Validated strategy parameters (used by scoped agent promotion)"
    )
    agent_name: Optional[str] = Field(None, exclude=True)
    agent_framework: Optional[str] = Field(None, exclude=True)
    source_run_id: Optional[str] = Field(None, exclude=True)

    model_config = {"json_schema_extra": {
        "examples": [{"duration": "7d", "strategy": "buy_the_dip"}]
    }}


class HermesBacktestRequest(BacktestRequest):
    """Backtest request accepted by the restricted Hermes broker."""

    objective: Dict[str, Any] = Field(default_factory=dict)


class HermesPaperRequest(BaseModel):
    """Start a saved candidate in paper mode only."""

    account_id: Optional[str] = None
    duration: str = "7d"
    poll: Optional[int] = None
    hours: Optional[str] = None
    email: Optional[bool] = None
    pdt: Optional[bool] = None
    notification_channel: str = Field(
        "in_app", description="Hermes advice delivery: in_app, email, both, or none"
    )


class ValidateRequest(BaseModel):
    run_id: str = Field(..., description="UUID of the run to validate")
    source: str = Field("backtest", description="'backtest' or 'paper'")
    account_id: Optional[str] = Field(None, description="Optional account override")


class FullCycleRequest(BaseModel):
    account_id: Optional[str] = None
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
    account_id: Optional[str] = None
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
    suggestions: List[str] = Field(default_factory=list)


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
    phases: Dict[str, FullCyclePhase] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# V2 Response Models — Reconcile
# ---------------------------------------------------------------------------

class ReconcileResponse(BaseModel):
    run_id: str
    status: str
    total_issues: int = 0
    position_mismatches: List[Dict[str, Any]] = Field(default_factory=list)
    trade_mismatches: List[Dict[str, Any]] = Field(default_factory=list)
    pnl_comparison: Optional[Dict[str, Any]] = None
    missing_trades: List[Dict[str, Any]] = Field(default_factory=list)
    extra_trades: List[Dict[str, Any]] = Field(default_factory=list)


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
    agents: List[AgentStatus] = Field(default_factory=list)
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
    per_symbol: List[PnlSymbolBreakdown] = Field(default_factory=list)
    daily_pnl: List[DailyPnl] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# API discovery and external agent contracts
# ---------------------------------------------------------------------------

class ApiLinks(BaseModel):
    swagger: str
    redoc: str
    openapi: str
    health: str
    agents: str


class ApiInfoResponse(BaseModel):
    name: str
    version: str
    status: Literal["ok"] = "ok"
    links: ApiLinks


class AgentDescriptor(BaseModel):
    slug: str
    name: str
    category: Literal["assistant", "research", "analysis", "trading", "orchestration"]
    description: str
    method: Literal["GET", "POST"]
    path: str
    access: Literal["authenticated", "public"] = "authenticated"
    execution: Literal["synchronous", "asynchronous", "streaming"]
    safety: Literal["read_only", "paper_only", "orchestration"]
    skills: List[str] = Field(
        ...,
        description="Stable, human-readable capabilities exposed by this agent.",
    )


class AgentCatalogResponse(BaseModel):
    agents: List[AgentDescriptor]
    total: int


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20_000)
    thread_id: str = Field("service_default", min_length=1, max_length=200)

    model_config = {"json_schema_extra": {
        "examples": [{"message": "Summarize my open positions", "thread_id": "portfolio-review-1"}]
    }}


class AgentChatResponse(BaseModel):
    thread_id: str
    response: str
    route: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical DeepAgents API
# ---------------------------------------------------------------------------

class DeepAgentMessageRequest(BaseModel):
    """One append-only client message for a durable DeepAgent thread."""

    id: str = Field(..., description="Stable client-generated UUID used for idempotency")
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=20_000)

    @field_validator("id")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        import uuid

        try:
            return str(uuid.UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("id must be a UUID") from exc

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class DeepAgentRequest(BaseModel):
    messages: List[DeepAgentMessageRequest] = Field(..., min_length=1, max_length=20)
    thread_id: Optional[str] = Field(None, description="Existing owned thread UUID")
    account_id: Optional[str] = Field(None, description="Optional owned Alpaca account UUID")
    stream: bool = False

    @field_validator("thread_id", "account_id")
    @classmethod
    def validate_optional_uuid(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        import uuid

        try:
            return str(uuid.UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("must be a UUID") from exc

    @model_validator(mode="after")
    def validate_message_batch(self):
        if self.messages[-1].role != "user":
            raise ValueError("the final message must have role 'user'")
        if sum(len(message.content) for message in self.messages) > 50_000:
            raise ValueError("messages may contain at most 50,000 characters total")
        identifiers = [message.id for message in self.messages]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("message ids must be unique within the request")
        return self

    model_config = {"json_schema_extra": {
        "examples": [{
            "messages": [{
                "id": "68d8968b-4ec1-44c3-9d0d-a3d519c8086b",
                "role": "user",
                "content": "Backtest buy the dip on AAPL and MSFT",
            }],
            "stream": False,
        }]
    }}


class DeepAgentOutputMessage(BaseModel):
    id: str
    role: Literal["assistant"] = "assistant"
    content: str


class DeepAgentTrace(BaseModel):
    call_id: str
    name: str
    status: Literal["started", "completed", "failed"]
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DeepAgentModelInfo(BaseModel):
    provider: str
    name: str


class DeepAgentResponse(BaseModel):
    id: str
    thread_id: str
    status: Literal["completed", "failed"]
    framework: Literal["deepagents"] = "deepagents"
    model: DeepAgentModelInfo
    messages: List[DeepAgentOutputMessage] = Field(default_factory=list)
    tools: List[DeepAgentTrace] = Field(default_factory=list)
    subagents: List[DeepAgentTrace] = Field(default_factory=list)
    cached: bool = False


class PremarketAgentRequest(BaseModel):
    refresh: bool = Field(False, description="Fetch a new scan instead of using the latest saved report")
    limit: int = Field(10, ge=1, le=50)


class PremarketAgentResponse(BaseModel):
    agent: str
    status: str
    report: Optional[Dict[str, Any]] = None
    top: Dict[str, Any] = Field(default_factory=dict)


class AlphaResearchRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=16, examples=["AAPL"])


class AlphaResearchResponse(BaseModel):
    run_id: str
    mode: Literal["growth", "value"]
    ticker: str
    status: str
    report: str
    saved: bool
    persistence_warning: Optional[str] = None


class AlphaComparisonResponse(BaseModel):
    ticker: str
    status: str
    growth: AlphaResearchResponse
    value: AlphaResearchResponse


class AutonomyScoutRequest(BaseModel):
    strategy: str = Field("btd", description="Strategy slug or registered strategy name")
    limit: int = Field(5, ge=1, le=20)
    account_id: Optional[str] = Field(None, description="Owned paper account UUID")


class AutonomyScoutResponse(BaseModel):
    status: Literal["queued", "no_candidates"]
    run_id: Optional[str] = None
    paper_only: bool = True

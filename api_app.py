"""FastAPI REST server for AlpaTrade — exposes CLI commands as JSON endpoints."""
import asyncio
import sys
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from tui.command_processor import CommandProcessor
from api_models import (
    # Existing / legacy
    CmdRequest, BacktestRequest, PaperRequest, ApiResponse,
    AuthRequest, RegisterRequest, AuthResponse,
    # V2 request models
    ValidateRequest, FullCycleRequest, ReconcileRequest,
    # V2 response models
    TradeItem, TradesResponse,
    RunItem, RunsResponse,
    BestConfig, BacktestResponse,
    ValidationResponse,
    PaperStartResponse,
    FullCyclePhase, FullCycleResponse,
    ReconcileResponse,
    AgentStatus, StatusResponse,
    StopResponse, LogsResponse,
    PnlSymbolBreakdown, DailyPnl, PnlResponse,
    ReportSummaryItem, ReportDetail, TopStrategyItem,
    PositionItem, PositionsResponse,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Lightweight app-state object (same interface CommandProcessor expects)
# ---------------------------------------------------------------------------

class _AppState:
    """Minimal stand-in for StrategyCLI — holds orchestrator state."""
    def __init__(self):
        self.command_history: list[str] = []
        self._orch = None
        self._bg_task = None
        self._bg_stop = threading.Event()
        self._suggested_command: str = ""

# Per-user state keyed by user_id (None key = anonymous)
_user_states: Dict[Optional[str], _AppState] = {}

def _get_app_state(user_id: Optional[str] = None) -> _AppState:
    """Get or create an _AppState for the given user."""
    if user_id not in _user_states:
        _user_states[user_id] = _AppState()
    return _user_states[user_id]

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[Dict]:
    """
    Decode JWT from Authorization header.
    Returns user payload dict or None (optional auth — unauthenticated requests pass through).
    """
    if not credentials:
        return None
    from utils.auth import decode_jwt_token
    payload = decode_jwt_token(credentials.credentials)
    return payload  # {"user_id": ..., "email": ..., ...} or None

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

tags_metadata = [
    {"name": "auth", "description": "User registration and login"},
    {"name": "agents", "description": "Agent lifecycle — backtest, paper trade, validate, reconcile, full cycle"},
    {"name": "data", "description": "Query runs, trades, reports, P&L"},
    {"name": "market", "description": "Market data — news, prices, profiles, movers"},
    {"name": "legacy", "description": "Legacy endpoints (markdown responses via CommandProcessor)"},
]

app = FastAPI(
    title="AlpaTrade API",
    version="2.0.0",
    description="Trading strategy simulator, backtester, and paper trader.",
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_command(command: str, user_id: Optional[str] = None) -> ApiResponse:
    """Execute a command through CommandProcessor and return ApiResponse."""
    state = _get_app_state(user_id)
    processor = CommandProcessor(state, user_id=user_id)
    try:
        result = await processor.process_command(command) or ""
        state.command_history.append(command)
        return ApiResponse(result=result, status="ok")
    except Exception as e:
        return ApiResponse(result=f"# Error\n\n```\n{e}\n```", status="error")

def _build_cmd(base: str, params: dict) -> str:
    """Build a command string from base and optional key:value params."""
    parts = [base]
    for key, val in params.items():
        if val is not None:
            if isinstance(val, bool):
                parts.append(f"{key}:{'true' if val else 'false'}")
            else:
                parts.append(f"{key}:{val}")
    return " ".join(parts)

def _uid(user: Optional[Dict]) -> Optional[str]:
    """Extract user_id from auth payload."""
    return user.get("user_id") if user else None

# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=AuthResponse, tags=["auth"])
async def auth_register(req: RegisterRequest):
    """Register a new user account."""
    from utils.auth import create_user, create_jwt_token
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = create_user(email=req.email, password=req.password, display_name=req.display_name)
    if not user:
        raise HTTPException(status_code=409, detail="Email already registered")
    token = create_jwt_token(user["user_id"], user["email"])
    return AuthResponse(token=token, user_id=user["user_id"], email=user["email"])


@app.post("/auth/login", response_model=AuthResponse, tags=["auth"])
async def auth_login(req: AuthRequest):
    """Authenticate and receive a JWT token."""
    from utils.auth import authenticate, create_jwt_token
    user = authenticate(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_jwt_token(user["user_id"], user["email"])
    return AuthResponse(token=token, user_id=user["user_id"], email=user["email"])


# ===========================================================================
# V2 STRUCTURED JSON ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Data endpoints — /v2/runs, /v2/trades, /v2/report, /v2/top, /v2/logs, /v2/pnl
# ---------------------------------------------------------------------------

@app.get("/v2/runs", response_model=RunsResponse, tags=["data"])
async def v2_runs(
    limit: int = Query(20, ge=1, le=200),
    user: Optional[Dict] = Depends(get_current_user),
):
    """List recent orchestrator runs."""
    from utils.db.db_pool import DatabasePool
    from sqlalchemy import text

    uid = _uid(user)
    pool = DatabasePool()
    with pool.get_session() as session:
        where_parts = []
        bind: Dict = {}
        if uid:
            where_parts.append("r.user_id = :user_id")
            bind["user_id"] = uid
        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        rows = session.execute(
            text(f"""
                SELECT r.run_id, r.mode, r.strategy, r.status,
                       r.started_at, r.completed_at,
                       bs.params->>'strategy_slug' AS strategy_slug
                FROM alpatrade.runs r
                LEFT JOIN alpatrade.backtest_summaries bs
                    ON bs.run_id = r.run_id AND bs.is_best = true
                {where_sql}
                ORDER BY r.created_at DESC
                LIMIT :lim
            """),
            {**bind, "lim": limit},
        ).fetchall()

    items = [
        RunItem(
            run_id=r[0], mode=r[1], strategy=r[2], status=r[3],
            started_at=r[4], completed_at=r[5], strategy_slug=r[6],
        )
        for r in rows
    ]
    return RunsResponse(runs=items, total=len(items))


@app.get("/v2/trades", response_model=TradesResponse, tags=["data"])
async def v2_trades(
    run_id: Optional[str] = None,
    trade_type: Optional[str] = Query(None, alias="type"),
    symbol: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    user: Optional[Dict] = Depends(get_current_user),
):
    """Query trades with optional filters."""
    from utils.db.db_pool import DatabasePool
    from sqlalchemy import text

    uid = _uid(user)
    where_parts: List[str] = []
    bind: Dict = {}
    if run_id:
        where_parts.append("run_id = :run_id")
        bind["run_id"] = run_id
    if trade_type:
        where_parts.append("trade_type = :trade_type")
        bind["trade_type"] = trade_type
    if symbol:
        where_parts.append("symbol = :symbol")
        bind["symbol"] = symbol.upper()
    if uid:
        where_parts.append("user_id = :user_id")
        bind["user_id"] = uid
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    pool = DatabasePool()
    with pool.get_session() as session:
        rows = session.execute(
            text(f"""
                SELECT id, run_id, trade_type, symbol, direction, shares,
                       entry_time, exit_time, entry_price, exit_price,
                       target_price, stop_price, hit_target, hit_stop,
                       pnl, pnl_pct, total_fees, reason
                FROM alpatrade.trades
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {**bind, "lim": limit},
        ).fetchall()

    items = [
        TradeItem(
            id=r[0], run_id=r[1], trade_type=r[2], symbol=r[3],
            direction=r[4], shares=float(r[5]) if r[5] else None,
            entry_time=r[6], exit_time=r[7],
            entry_price=float(r[8]) if r[8] else None,
            exit_price=float(r[9]) if r[9] else None,
            target_price=float(r[10]) if r[10] else None,
            stop_price=float(r[11]) if r[11] else None,
            hit_target=r[12], hit_stop=r[13],
            pnl=float(r[14]) if r[14] else None,
            pnl_pct=float(r[15]) if r[15] else None,
            total_fees=float(r[16]) if r[16] else None,
            reason=r[17],
        )
        for r in rows
    ]
    return TradesResponse(trades=items, total=len(items))


@app.get("/v2/report", response_model=List[ReportSummaryItem], tags=["data"])
async def v2_report_summary(
    trade_type: Optional[str] = Query(None, alias="type"),
    strategy: Optional[str] = None,
    limit: int = Query(10, ge=1, le=100),
    user: Optional[Dict] = Depends(get_current_user),
):
    """List run summaries (performance overview)."""
    from agents.report_agent import ReportAgent
    agent = ReportAgent()
    rows = agent.summary(trade_type=trade_type, limit=limit, user_id=_uid(user))
    return [ReportSummaryItem(**r) for r in (rows or [])]


@app.get("/v2/report/{run_id}", response_model=ReportDetail, tags=["data"])
async def v2_report_detail(run_id: str, user: Optional[Dict] = Depends(get_current_user)):
    """Detailed performance report for a single run."""
    from agents.report_agent import ReportAgent
    agent = ReportAgent()
    data = agent.detail(run_id, user_id=_uid(user))
    if not data:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return ReportDetail(**data)


@app.get("/v2/top", response_model=List[TopStrategyItem], tags=["data"])
async def v2_top(
    strategy: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    user: Optional[Dict] = Depends(get_current_user),
):
    """Rank strategy slugs by average performance."""
    from agents.report_agent import ReportAgent
    agent = ReportAgent()
    rows = agent.top_strategies(strategy=strategy, limit=limit, user_id=_uid(user))
    return [TopStrategyItem(**r) for r in (rows or [])]


@app.get("/v2/logs", response_model=LogsResponse, tags=["data"])
async def v2_logs(
    lines: int = Query(50, ge=1, le=500),
    user: Optional[Dict] = Depends(get_current_user),
):
    """Read paper trading log tail."""
    log_path = Path("data/paper_trade.log")
    if not log_path.exists():
        return LogsResponse(lines=[], total_lines=0)
    raw = log_path.read_text(errors="replace")
    all_lines = [ln for ln in raw.splitlines() if ln.strip() and ln.isprintable()]
    tail = all_lines[-lines:]
    return LogsResponse(lines=tail, total_lines=len(all_lines))


@app.get("/v2/pnl/{run_id}", response_model=PnlResponse, tags=["data"])
async def v2_pnl(run_id: str, user: Optional[Dict] = Depends(get_current_user)):
    """P&L breakdown for a specific run — per-symbol and daily."""
    from utils.db.db_pool import DatabasePool
    from sqlalchemy import text

    uid = _uid(user)
    pool = DatabasePool()
    with pool.get_session() as session:
        # Run metadata
        run_bind: Dict = {"run_id": run_id}
        user_filter = ""
        if uid:
            user_filter = " AND user_id = :user_id"
            run_bind["user_id"] = uid

        run_row = session.execute(
            text(f"SELECT mode, strategy, status FROM alpatrade.runs "
                 f"WHERE run_id = :run_id{user_filter}"),
            run_bind,
        ).fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        mode, strategy, status = run_row

        # Trades
        trades = session.execute(
            text("SELECT symbol, pnl, pnl_pct, total_fees, exit_time "
                 "FROM alpatrade.trades WHERE run_id = :run_id "
                 "ORDER BY exit_time ASC NULLS LAST"),
            {"run_id": run_id},
        ).fetchall()

        # Summary metrics
        summary = session.execute(
            text("SELECT sharpe_ratio, total_return, total_pnl, win_rate "
                 "FROM alpatrade.backtest_summaries "
                 "WHERE run_id = :run_id AND is_best = true LIMIT 1"),
            {"run_id": run_id},
        ).fetchone()

    if not trades:
        return PnlResponse(run_id=run_id, strategy=strategy, mode=mode)

    # Aggregate
    total_pnl = 0.0
    total_fees = 0.0
    wins = 0
    losses = 0
    by_symbol: Dict[str, Dict] = defaultdict(
        lambda: {"pnl": 0.0, "fees": 0.0, "count": 0, "wins": 0, "losses": 0}
    )
    by_date: Dict[str, Dict] = defaultdict(lambda: {"pnl": 0.0, "count": 0})

    for t in trades:
        sym = t[0] or "UNKNOWN"
        pnl_val = float(t[1] or 0)
        fee_val = float(t[3] or 0)
        total_pnl += pnl_val
        total_fees += fee_val
        if pnl_val > 0:
            wins += 1
        else:
            losses += 1
        by_symbol[sym]["pnl"] += pnl_val
        by_symbol[sym]["fees"] += fee_val
        by_symbol[sym]["count"] += 1
        if pnl_val > 0:
            by_symbol[sym]["wins"] += 1
        else:
            by_symbol[sym]["losses"] += 1

        if t[4]:  # exit_time
            d = t[4].strftime("%Y-%m-%d")
            by_date[d]["pnl"] += pnl_val
            by_date[d]["count"] += 1

    total = len(trades)
    win_rate = (wins / total * 100) if total else None
    sharpe = float(summary[0]) if summary and summary[0] else None
    total_return = float(summary[1]) if summary and summary[1] else None

    per_symbol = sorted(
        [
            PnlSymbolBreakdown(
                symbol=sym,
                total_pnl=s["pnl"],
                total_fees=s["fees"],
                trade_count=s["count"],
                win_count=s["wins"],
                loss_count=s["losses"],
                avg_pnl=s["pnl"] / s["count"] if s["count"] else None,
            )
            for sym, s in by_symbol.items()
        ],
        key=lambda x: x.total_pnl,
        reverse=True,
    )

    daily_pnl = [
        DailyPnl(date=d, pnl=v["pnl"], trade_count=v["count"])
        for d, v in sorted(by_date.items())
    ]

    return PnlResponse(
        run_id=run_id,
        strategy=strategy,
        mode=mode,
        total_pnl=total_pnl,
        total_return=total_return,
        total_fees=total_fees,
        win_rate=win_rate,
        winning_trades=wins,
        losing_trades=losses,
        total_trades=total,
        sharpe_ratio=sharpe,
        per_symbol=per_symbol,
        daily_pnl=daily_pnl,
    )


@app.get("/v2/positions", response_model=PositionsResponse, tags=["data"])
async def v2_positions(
    run_id: Optional[str] = None,
    status: Optional[str] = Query(None, description="'open' or 'closed'"),
    limit: int = Query(50, ge=1, le=500),
    user: Optional[Dict] = Depends(get_current_user),
):
    """Query positions with optional filters."""
    from utils.db.db_pool import DatabasePool
    from sqlalchemy import text

    uid = _uid(user)
    where_parts: List[str] = []
    bind: Dict = {}
    if run_id:
        where_parts.append("run_id = :run_id")
        bind["run_id"] = run_id
    if status:
        where_parts.append("status = :status")
        bind["status"] = status
    if uid:
        where_parts.append("user_id = :user_id")
        bind["user_id"] = uid
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    pool = DatabasePool()
    with pool.get_session() as session:
        rows = session.execute(
            text(f"""
                SELECT id, run_id, symbol, side, shares, avg_entry_price,
                       current_price, market_value, unrealized_pnl,
                       unrealized_pnl_pct, cost_basis, status,
                       opened_at, closed_at
                FROM alpatrade.positions
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {**bind, "lim": limit},
        ).fetchall()

    items = [
        PositionItem(
            id=r[0], run_id=r[1], symbol=r[2], side=r[3],
            shares=float(r[4]) if r[4] else 0,
            avg_entry_price=float(r[5]) if r[5] else None,
            current_price=float(r[6]) if r[6] else None,
            market_value=float(r[7]) if r[7] else None,
            unrealized_pnl=float(r[8]) if r[8] else None,
            unrealized_pnl_pct=float(r[9]) if r[9] else None,
            cost_basis=float(r[10]) if r[10] else None,
            status=r[11],
            opened_at=r[12], closed_at=r[13],
        )
        for r in rows
    ]
    return PositionsResponse(positions=items, total=len(items))


# ---------------------------------------------------------------------------
# Agent lifecycle endpoints — /v2/status, /v2/stop, /v2/backtest, etc.
# ---------------------------------------------------------------------------

@app.get("/v2/status", response_model=StatusResponse, tags=["agents"])
async def v2_status(user: Optional[Dict] = Depends(get_current_user)):
    """Current orchestrator / agent status."""
    uid = _uid(user)
    state = _get_app_state(uid)
    orch = state._orch

    if orch is None:
        # Check DB for most recent run
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text
            pool = DatabasePool()
            with pool.get_session() as session:
                bind: Dict = {}
                user_filter = ""
                if uid:
                    user_filter = " WHERE user_id = :user_id"
                    bind["user_id"] = uid
                row = session.execute(
                    text(f"SELECT run_id, mode, status, started_at "
                         f"FROM alpatrade.runs{user_filter} "
                         f"ORDER BY created_at DESC LIMIT 1"),
                    bind,
                ).fetchone()
            if row:
                return StatusResponse(
                    run_id=row[0], mode=row[1], status=row[2],
                    started_at=row[3],
                )
        except Exception:
            pass
        return StatusResponse(status="idle")

    mode = getattr(orch, '_mode', None) or getattr(orch.state, 'mode', None) or 'n/a'
    bg_running = state._bg_task and not state._bg_task.done()

    if bg_running:
        status_label = "running"
    elif state._bg_task and state._bg_task.done():
        status_label = "completed"
    else:
        status_label = "idle"

    agents_list = []
    if hasattr(orch, 'state') and hasattr(orch.state, 'agents'):
        for name, agent in orch.state.agents.items():
            agents_list.append(AgentStatus(
                name=name, status=agent.status,
                current_task=agent.current_task,
            ))

    elapsed = None
    started = getattr(orch.state, 'started_at', None) if hasattr(orch, 'state') else None
    if started:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    best = None
    if hasattr(orch, 'state') and orch.state.best_config:
        bc = orch.state.best_config
        best = BestConfig(
            sharpe_ratio=bc.get("sharpe_ratio"),
            total_return=bc.get("total_return"),
            annualized_return=bc.get("annualized_return"),
            total_pnl=bc.get("total_pnl"),
            win_rate=bc.get("win_rate"),
            total_trades=bc.get("total_trades"),
            max_drawdown=bc.get("max_drawdown"),
            params=bc.get("params"),
        )

    return StatusResponse(
        run_id=orch.run_id,
        mode=mode,
        status=status_label,
        agents=agents_list,
        started_at=started,
        elapsed_seconds=elapsed,
        best_config=best,
    )


@app.post("/v2/stop", response_model=StopResponse, tags=["agents"])
async def v2_stop(user: Optional[Dict] = Depends(get_current_user)):
    """Stop a running background task (paper trading)."""
    uid = _uid(user)
    state = _get_app_state(uid)
    if state._bg_task and not state._bg_task.done():
        state._bg_stop.set()
        state._bg_task.cancel()
        return StopResponse(stopped=True, message="Background task cancelled.")
    return StopResponse(stopped=False, message="No background task is running.")


@app.post("/v2/backtest", response_model=BacktestResponse, tags=["agents"])
async def v2_backtest(req: BacktestRequest, user: Optional[Dict] = Depends(get_current_user)):
    """Run a parameterized backtest. Synchronous — may take minutes."""
    from agents.orchestrator import Orchestrator

    uid = _uid(user)
    config = {
        "lookback": req.lookback,
        "strategy": req.strategy,
    }
    if req.symbols:
        config["symbols"] = [s.strip() for s in req.symbols.split(",")]
    if req.capital is not None:
        config["capital"] = req.capital
    if req.hours:
        config["hours"] = req.hours
    if req.intraday_exit is not None:
        config["intraday_exit"] = req.intraday_exit
    if req.pdt is not None:
        config["pdt"] = req.pdt

    orch = Orchestrator(user_id=uid)
    state = _get_app_state(uid)
    state._orch = orch

    result = await asyncio.to_thread(orch.run_backtest, config)

    best = None
    if result.get("best_config"):
        bc = result["best_config"]
        best = BestConfig(
            sharpe_ratio=bc.get("sharpe_ratio"),
            total_return=bc.get("total_return"),
            annualized_return=bc.get("annualized_return"),
            total_pnl=bc.get("total_pnl"),
            win_rate=bc.get("win_rate"),
            total_trades=bc.get("total_trades"),
            max_drawdown=bc.get("max_drawdown"),
            params=bc.get("params"),
        )

    return BacktestResponse(
        run_id=result.get("run_id", orch.run_id),
        strategy=req.strategy,
        total_variations=result.get("total_variations", 0),
        best_config=best,
        status=result.get("status", "completed"),
    )


@app.post("/v2/validate", response_model=ValidationResponse, tags=["agents"])
async def v2_validate(req: ValidateRequest, user: Optional[Dict] = Depends(get_current_user)):
    """Validate trades for a given run. Synchronous."""
    from agents.orchestrator import Orchestrator

    uid = _uid(user)
    orch = Orchestrator(user_id=uid)
    state = _get_app_state(uid)
    state._orch = orch

    result = await asyncio.to_thread(orch.run_validation, req.run_id, req.source)

    return ValidationResponse(
        run_id=req.run_id,
        status=result.get("status", "unknown"),
        total_trades_checked=result.get("total_trades_checked", 0),
        anomalies_found=result.get("anomalies_found", 0),
        anomalies_corrected=result.get("anomalies_corrected", 0),
        iterations_used=result.get("iterations_used", 0),
        suggestions=result.get("suggestions", []),
    )


@app.post("/v2/paper", response_model=PaperStartResponse, tags=["agents"])
async def v2_paper(req: PaperRequest, user: Optional[Dict] = Depends(get_current_user)):
    """Start paper trading in the background. Returns immediately."""
    from agents.orchestrator import Orchestrator, parse_duration

    uid = _uid(user)
    state = _get_app_state(uid)

    if state._bg_task and not state._bg_task.done():
        raise HTTPException(status_code=409, detail="Paper trading is already running")

    orch = Orchestrator(user_id=uid)
    state._orch = orch
    state._bg_stop = threading.Event()

    duration_sec = parse_duration(req.duration)
    config = {
        "strategy": req.strategy,
        "duration_seconds": duration_sec,
    }
    if req.symbols:
        config["symbols"] = [s.strip() for s in req.symbols.split(",")]
    if req.poll:
        config["poll_interval"] = req.poll
    if req.hours:
        config["hours"] = req.hours
    if req.email is not None:
        config["email"] = req.email
    if req.pdt is not None:
        config["pdt"] = req.pdt

    async def _run_paper():
        try:
            await asyncio.to_thread(orch.run_paper_trade, config, state._bg_stop)
        except asyncio.CancelledError:
            pass

    state._bg_task = asyncio.create_task(_run_paper())

    symbols = config.get("symbols")
    return PaperStartResponse(
        run_id=orch.run_id,
        status="started",
        strategy=req.strategy,
        symbols=symbols,
        duration=req.duration,
        poll_interval=req.poll,
    )


@app.post("/v2/full", response_model=FullCycleResponse, tags=["agents"])
async def v2_full(req: FullCycleRequest, user: Optional[Dict] = Depends(get_current_user)):
    """Run full cycle: backtest -> validate -> paper -> validate. Synchronous — long-running."""
    from agents.orchestrator import Orchestrator, parse_duration

    uid = _uid(user)
    config = {
        "lookback": req.lookback,
        "strategy": req.strategy,
        "duration_seconds": parse_duration(req.duration),
    }
    if req.symbols:
        config["symbols"] = [s.strip() for s in req.symbols.split(",")]
    if req.capital is not None:
        config["capital"] = req.capital
    if req.hours:
        config["hours"] = req.hours
    if req.intraday_exit is not None:
        config["intraday_exit"] = req.intraday_exit
    if req.pdt is not None:
        config["pdt"] = req.pdt
    if req.poll:
        config["poll_interval"] = req.poll

    orch = Orchestrator(user_id=uid)
    state = _get_app_state(uid)
    state._orch = orch

    result = await asyncio.to_thread(orch.run_full, config)

    phases = {}
    if isinstance(result.get("phases"), dict):
        for phase_name, phase_data in result["phases"].items():
            if isinstance(phase_data, dict):
                phases[phase_name] = FullCyclePhase(
                    status=phase_data.get("status", "unknown"),
                    run_id=phase_data.get("run_id"),
                    detail=phase_data,
                )
            else:
                phases[phase_name] = FullCyclePhase(status="unknown")

    return FullCycleResponse(
        run_id=result.get("run_id", orch.run_id),
        status=result.get("status", "completed"),
        phases=phases,
    )


@app.post("/v2/reconcile", response_model=ReconcileResponse, tags=["agents"])
async def v2_reconcile(req: ReconcileRequest, user: Optional[Dict] = Depends(get_current_user)):
    """Reconcile DB positions vs Alpaca holdings. Synchronous."""
    from agents.orchestrator import Orchestrator

    uid = _uid(user)
    orch = Orchestrator(user_id=uid)
    state = _get_app_state(uid)
    state._orch = orch

    config = {"window_days": req.window_days}
    result = await asyncio.to_thread(orch.run_reconciliation, config)

    return ReconcileResponse(
        run_id=result.get("run_id", orch.run_id),
        status=result.get("status", "unknown"),
        total_issues=result.get("total_issues", 0),
        position_mismatches=result.get("position_mismatches", []),
        trade_mismatches=result.get("trade_mismatches", []),
        pnl_comparison=result.get("pnl_comparison"),
        missing_trades=result.get("missing_trades", []),
        extra_trades=result.get("extra_trades", []),
    )


# ===========================================================================
# LEGACY ENDPOINTS (unchanged — return markdown via CommandProcessor)
# ===========================================================================

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/cmd", response_model=ApiResponse, tags=["legacy"])
async def cmd(req: CmdRequest, user: Optional[Dict] = Depends(get_current_user)):
    """Execute an arbitrary CLI command (returns markdown)."""
    return await _run_command(req.command.strip(), user_id=_uid(user))

@app.get("/runs", response_model=ApiResponse, tags=["legacy"])
async def runs(limit: int = 20, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command("runs", user_id=_uid(user))

@app.get("/trades", response_model=ApiResponse, tags=["legacy"])
async def trades(run_id: Optional[str] = None, type: Optional[str] = None,
                 limit: int = 20, user: Optional[Dict] = Depends(get_current_user)):
    parts = {"run-id": run_id, "type": type, "limit": limit}
    cmd_str = _build_cmd("agent:trades", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/report", response_model=ApiResponse, tags=["legacy"])
async def report(run_id: Optional[str] = None, type: Optional[str] = None,
                 strategy: Optional[str] = None, limit: int = 10,
                 user: Optional[Dict] = Depends(get_current_user)):
    parts = {"run-id": run_id, "type": type, "strategy": strategy, "limit": limit}
    cmd_str = _build_cmd("agent:report", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/top", response_model=ApiResponse, tags=["legacy"])
async def top(strategy: Optional[str] = None, limit: int = 20,
              user: Optional[Dict] = Depends(get_current_user)):
    parts = {"strategy": strategy, "limit": limit}
    cmd_str = _build_cmd("agent:top", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.post("/backtest", response_model=ApiResponse, tags=["legacy"])
async def backtest(req: BacktestRequest, user: Optional[Dict] = Depends(get_current_user)):
    parts = {
        "lookback": req.lookback, "symbols": req.symbols, "strategy": req.strategy,
        "capital": req.capital, "hours": req.hours, "intraday_exit": req.intraday_exit,
        "pdt": req.pdt,
    }
    cmd_str = _build_cmd("agent:backtest", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.post("/paper", response_model=ApiResponse, tags=["legacy"])
async def paper(req: PaperRequest, user: Optional[Dict] = Depends(get_current_user)):
    parts = {
        "duration": req.duration, "symbols": req.symbols, "strategy": req.strategy,
        "poll": req.poll, "hours": req.hours, "email": req.email, "pdt": req.pdt,
    }
    cmd_str = _build_cmd("agent:paper", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/status", response_model=ApiResponse, tags=["legacy"])
async def status(user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command("agent:status", user_id=_uid(user))

@app.get("/news", response_model=ApiResponse, tags=["market"])
async def news(ticker: Optional[str] = None, provider: Optional[str] = None,
               limit: int = 10, user: Optional[Dict] = Depends(get_current_user)):
    cmd_str = f"news:{ticker}" if ticker else "news"
    parts = {"provider": provider, "limit": limit}
    cmd_str = _build_cmd(cmd_str, parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/price", response_model=ApiResponse, tags=["market"])
async def price(ticker: str, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command(f"price:{ticker}", user_id=_uid(user))

@app.get("/profile", response_model=ApiResponse, tags=["market"])
async def profile(ticker: str, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command(f"profile:{ticker}", user_id=_uid(user))

@app.get("/movers", response_model=ApiResponse, tags=["market"])
async def movers(direction: Optional[str] = None, user: Optional[Dict] = Depends(get_current_user)):
    cmd_str = f"movers:{direction}" if direction else "movers"
    return await _run_command(cmd_str, user_id=_uid(user))

# ---------------------------------------------------------------------------
# Streaming chat SSE endpoint
# ---------------------------------------------------------------------------

_BROKER_KEYWORDS = {
    "buy", "sell", "order", "orders", "position", "positions",
    "holdings", "holding", "portfolio", "account", "balance",
    "buying power", "equity", "assets", "tradable",
}

def _is_broker_query(text: str) -> bool:
    """Return True if the input looks like a broker / trading interaction."""
    lower = text.lower()
    return any(kw in lower for kw in _BROKER_KEYWORDS)

@app.get("/chat")
async def chat_stream(question: str, thread_id: str = "api_default"):
    """SSE endpoint for streaming chat responses."""
    import json

    async def event_generator():
        is_broker = _is_broker_query(question)
        if is_broker:
            from utils.alpaca_agent import async_stream_response
        else:
            from utils.research_agent import async_stream_response

        async for event in async_stream_response(question, thread_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# Serve install.sh
# ---------------------------------------------------------------------------

@app.get("/install.sh")
async def install_sh():
    script_path = Path(__file__).parent / "install.sh"
    if script_path.exists():
        content = script_path.read_text()
    else:
        content = "#!/bin/bash\necho 'install.sh not found on server'\nexit 1\n"
    return PlainTextResponse(content, media_type="text/plain",
                             headers={"Content-Disposition": "attachment; filename=install.sh"})

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)

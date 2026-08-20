"""FastAPI REST server for AlpaTrade — exposes CLI commands as JSON endpoints."""
import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import sys
import threading
import time
import tomllib
import uuid
from importlib.metadata import PackageNotFoundError, version

logger = logging.getLogger(__name__)
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import (
    JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse,
)
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from tui.command_processor import CommandProcessor
from api_models import (
    # Existing / legacy
    CmdRequest, BacktestRequest, PaperRequest, HermesBacktestRequest,
    HermesPaperRequest, ApiResponse,
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
    ApiInfoResponse, ApiLinks,
    AgentDescriptor, AgentCatalogResponse,
    AgentChatRequest, AgentChatResponse,
    PremarketAgentRequest, PremarketAgentResponse,
    AlphaResearchRequest, AlphaResearchResponse, AlphaComparisonResponse,
    AutonomyScoutRequest, AutonomyScoutResponse,
)
from engine.agents.catalog import AGENT_CATALOG_ENTRIES

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
        self._subprocess_run_id: Optional[str] = None

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

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="User JWT returned by POST /auth/login or /auth/register.",
)
_service_api_key = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    scheme_name="ServiceApiKey",
    description="Trusted service key. Add X-User-Id for tenant-scoped endpoints.",
)


def _configured_service_keys() -> tuple[str, ...]:
    """Return configured service keys without ever logging their values."""
    raw = os.getenv("API_SERVICE_KEYS") or os.getenv("API_SERVICE_KEY") or ""
    return tuple(key.strip() for key in raw.split(",") if key.strip())


def _valid_service_key(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    return any(secrets.compare_digest(candidate, key) for key in _configured_service_keys())


def _valid_internal_signature(request: Request, user_id: str) -> bool:
    """Verify the web container's short-lived, JWT-secret-backed identity proof."""
    timestamp = request.headers.get("X-Internal-Timestamp", "")
    signature = request.headers.get("X-Internal-Signature", "")
    secret = os.getenv("JWT_SECRET", "")
    if not timestamp or not signature or not secret:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 60:
            return False
    except ValueError:
        return False
    expected = hmac.new(
        secret.encode(),
        f"{timestamp}:{request.method.upper()}:{request.url.path}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return secrets.compare_digest(signature, expected)


def _normalize_user_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="user_id must be a UUID") from exc

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    api_key: Optional[str] = Depends(_service_api_key),
) -> Optional[Dict]:
    """Resolve an optional JWT, service API key, or signed internal identity."""
    if credentials:
        from engine.auth import decode_jwt_token
        payload = decode_jwt_token(credentials.credentials)
        if payload:
            payload["user_id"] = _normalize_user_id(payload.get("user_id"))
            payload["auth_type"] = "jwt"
            return payload
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token")

    requested_uid = request.headers.get("X-User-Id")
    if api_key:
        if not _valid_service_key(api_key):
            raise HTTPException(status_code=401, detail="Invalid service API key")
        return {"user_id": _normalize_user_id(requested_uid), "auth_type": "service"}

    if requested_uid and _valid_internal_signature(request, requested_uid):
        return {"user_id": _normalize_user_id(requested_uid), "auth_type": "internal"}

    if requested_uid:
        raise HTTPException(
            status_code=401,
            detail="X-User-Id requires a service API key or valid internal signature",
        )

    return None


async def require_current_user(
    user: Optional[Dict] = Depends(get_current_user),
) -> Dict:
    """Require an authenticated user or service principal."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_hermes_user(
    x_hermes_key: Optional[str] = Header(None, alias="X-Hermes-Key"),
    x_hermes_delegation: Optional[str] = Header(None, alias="X-Hermes-Delegation"),
) -> Dict:
    """Authenticate Hermes without granting it the general AlpaTrade API key."""
    configured = os.getenv("ALPATRADE_HERMES_API_KEY", "")
    if not configured or not x_hermes_key or not secrets.compare_digest(
        configured, x_hermes_key
    ):
        raise HTTPException(status_code=401, detail="Invalid Hermes service key")
    if not x_hermes_delegation:
        raise HTTPException(status_code=401, detail="Missing Hermes delegation")
    try:
        from engine.agents.hermes_access import decode_hermes_delegation
        claims = decode_hermes_delegation(x_hermes_delegation)
        user_id = _normalize_user_id(claims.get("sub"))
    except Exception as exc:  # token details must not leak to the caller
        raise HTTPException(status_code=401, detail="Invalid or expired Hermes delegation") from exc
    return {
        "user_id": user_id,
        "auth_type": "hermes",
        "thread_id": claims.get("thread_id"),
    }


async def require_tenant_user(
    user: Dict = Depends(require_current_user),
) -> Dict:
    """Require a concrete user identity for tenant-scoped data or actions."""
    if not user.get("user_id"):
        raise HTTPException(
            status_code=400,
            detail="Service requests to this endpoint must include X-User-Id",
        )
    return user

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

tags_metadata = [
    {"name": "meta", "x-displayName": "Platform", "description": "API discovery and health"},
    {"name": "auth", "x-displayName": "Authentication", "description": "User registration and login"},
    {"name": "agents", "x-displayName": "Agent lifecycle", "description": "Agent lifecycle — status and cancellation"},
    {
        "name": "agent-invocation",
        "x-displayName": "Agent skills & invocation",
        "description": (
            "Typed service-to-service invocation for the primary DeepAgent and "
            "specialist research/autonomy agents. Each operation documents its "
            "skills, execution model, access boundary, and safety level."
        ),
    },
    {"name": "chat", "x-displayName": "Chat", "description": "DeepAgents chat, as JSON or Server-Sent Events"},
    {"name": "data", "x-displayName": "Data & reporting", "description": "Query runs, trades, reports, P&L"},
    {"name": "market", "x-displayName": "Market data", "description": "Market data — news, prices, profiles, movers"},
    {"name": "trading", "x-displayName": "Paper trading", "description": "Paper-only order placement"},
    {"name": "legacy", "x-displayName": "Legacy API", "description": "Legacy endpoints (markdown responses via CommandProcessor)"},
]

try:
    with (Path(__file__).parent / "pyproject.toml").open("rb") as pyproject_file:
        API_VERSION = str(tomllib.load(pyproject_file)["project"]["version"])
except (OSError, KeyError, tomllib.TOMLDecodeError):
    try:
        API_VERSION = version("alpatrade")
    except PackageNotFoundError:
        API_VERSION = "0.8.0"

API_DESCRIPTION = """
AlpaTrade's production REST API for research, backtesting, validation, paper trading,
reconciliation, reporting, and the primary LangChain DeepAgents assistant.

Use `Authorization: Bearer <JWT>` for user clients. Trusted services may use
`X-API-Key`; include `X-User-Id` only when acting on behalf of a specific user.
All order and autonomy endpoints are paper-only.
""".strip()

app = FastAPI(
    title="AlpaTrade API",
    version=API_VERSION,
    description=API_DESCRIPTION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    openapi_tags=tags_metadata,
    contact={"name": "Predictive Labs", "url": "https://alpatrade.chat/developers"},
    license_info={"name": "MIT", "identifier": "MIT"},
    servers=[{"url": "https://api.alpatrade.chat", "description": "Production"}],
)


def _cors_origins() -> list[str]:
    configured = os.getenv("API_CORS_ORIGINS", "")
    if configured.strip():
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "https://alpatrade.chat",
        "https://www.alpatrade.chat",
        "https://alpatrade.dev",
        "https://www.alpatrade.dev",
        "http://localhost:3000",
        "http://localhost:5001",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-API-Key", "X-User-Id",
        "X-Request-ID",
    ],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Propagate a bounded request id for service tracing."""
    request_id = (request.headers.get("X-Request-ID") or "").strip()[:128]
    request_id = request_id or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

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
        logger.warning("Legacy command failed for user %s: %s", user_id, e)
        return ApiResponse(result="# Error\n\nCommand execution failed.", status="error")

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


def _require_linked_paper_keys(user_id: str, account_id: Optional[str] = None):
    """Resolve an owned paper account or reject the user-scoped action."""
    from engine.auth import get_alpaca_keys

    keys = get_alpaca_keys(user_id, account_id)
    if not keys:
        detail = "Paper account is not linked to this user" if account_id else \
            "No linked Alpaca paper account"
        raise HTTPException(status_code=409, detail=detail)
    return keys


AGENT_CATALOG = tuple(AgentDescriptor(**entry) for entry in AGENT_CATALOG_ENTRIES)


def _prefers_html(request: Request) -> bool:
    """Return true only for explicit browser-style HTML navigation."""
    return "text/html" in request.headers.get("accept", "").lower()


def _agent_operation_docs(agent: AgentDescriptor) -> str:
    skills = "\n".join(f"- {skill}" for skill in agent.skills)
    return (
        "### Agent skills\n\n"
        f"{skills}\n\n"
        f"**Execution:** `{agent.execution}`  \n"
        f"**Access:** `{agent.access}`  \n"
        f"**Safety:** `{agent.safety}`"
    )


_base_openapi = app.openapi


def _documented_openapi():
    """Enrich generated OpenAPI with agent skills and ReDoc navigation groups."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = _base_openapi()
    schema["externalDocs"] = {
        "description": "AlpaTrade developer portal and integration guide",
        "url": "https://alpatrade.chat/developers",
    }
    schema["x-tagGroups"] = [
        {"name": "Agent APIs", "tags": ["agent-invocation", "agents", "chat"]},
        {"name": "Trading and data", "tags": ["trading", "data", "market"]},
        {"name": "Platform", "tags": ["auth", "meta"]},
        {"name": "Compatibility", "tags": ["legacy"]},
    ]
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
                # OpenAPI requires an explicit empty array for intentionally public
                # operations; absence would otherwise inherit root-level security.
                operation.setdefault("security", [])
    for agent in AGENT_CATALOG:
        operation = schema.get("paths", {}).get(agent.path, {}).get(agent.method.lower())
        if not operation:
            continue
        verb = "Stream" if agent.execution == "streaming" else "Invoke"
        operation["summary"] = f"{verb} {agent.name}"
        operation["tags"] = ["agent-invocation"]
        current = str(operation.get("description") or "").strip()
        operation["description"] = "\n\n".join(
            part for part in (current, _agent_operation_docs(agent)) if part
        )
        operation["x-agent-slug"] = agent.slug
        operation["x-agent-category"] = agent.category
        operation["x-agent-skills"] = agent.skills
        operation["x-agent-execution"] = agent.execution
        operation["x-agent-safety"] = agent.safety
        if agent.slug == "deep-agent":
            catalog_operation = schema["paths"]["/v2/agents"]["get"]
            catalog_operation["responses"]["200"]["content"]["application/json"][
                "example"
            ] = AgentCatalogResponse(
                agents=list(AGENT_CATALOG), total=len(AGENT_CATALOG)
            ).model_dump()
    app.openapi_schema = schema
    return schema


app.openapi = _documented_openapi


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    """Interactive API explorer for human developers."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="AlpaTrade API Explorer",
        swagger_ui_parameters={
            "deepLinking": True,
            "displayRequestDuration": True,
            "filter": True,
            "persistAuthorization": True,
        },
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_reference():
    """Searchable, three-panel API reference for human developers."""
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="AlpaTrade API Reference",
    )


@app.get("/openapi.json", include_in_schema=False)
async def openapi_document(request: Request):
    """Serve JSON to tools and send direct browser visits to the formatted reference."""
    if _prefers_html(request):
        return RedirectResponse("/redoc", status_code=307, headers={"Vary": "Accept"})
    return JSONResponse(app.openapi(), headers={"Vary": "Accept"})


@app.get("/", response_model=ApiInfoResponse, tags=["meta"])
async def api_info():
    """Human- and machine-readable API discovery document."""
    return ApiInfoResponse(
        name="AlpaTrade API",
        version=API_VERSION,
        links=ApiLinks(
            swagger="/docs", redoc="/redoc", openapi="/openapi.json",
            health="/health", agents="/v2/agents",
        ),
    )


@app.get(
    "/v2/agents",
    response_model=AgentCatalogResponse,
    tags=["agent-invocation"],
    summary="Discover callable agents and their skills",
    description=(
        "Machine-readable catalogue of every supported agent, its canonical endpoint, "
        "skills, access boundary, execution model, and safety level. Direct browser "
        "visits are redirected to the formatted ReDoc reference; API clients continue "
        "to receive this typed JSON document."
    ),
    responses={307: {"description": "Browser navigation to the formatted API reference"}},
)
async def v2_agent_catalog(request: Request, response: Response):
    """List callable agents and their canonical typed endpoints."""
    if _prefers_html(request):
        return RedirectResponse(
            "/redoc#tag/agent-invocation",
            status_code=307,
            headers={"Vary": "Accept"},
        )
    response.headers["Vary"] = "Accept"
    return AgentCatalogResponse(agents=list(AGENT_CATALOG), total=len(AGENT_CATALOG))

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
    user: Dict = Depends(require_tenant_user),
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
    user: Dict = Depends(require_tenant_user),
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
    user: Dict = Depends(require_tenant_user),
):
    """List run summaries (performance overview)."""
    from agents.report_agent import ReportAgent
    agent = ReportAgent()
    rows = agent.summary(trade_type=trade_type, limit=limit, user_id=_uid(user))
    return [ReportSummaryItem(**r) for r in (rows or [])]


@app.get("/v2/report/{run_id}", response_model=ReportDetail, tags=["data"])
async def v2_report_detail(run_id: str, user: Dict = Depends(require_tenant_user)):
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
    user: Dict = Depends(require_tenant_user),
):
    """Rank strategy slugs by average performance."""
    from agents.report_agent import ReportAgent
    agent = ReportAgent()
    rows = agent.top_strategies(strategy=strategy, limit=limit, user_id=_uid(user))
    return [TopStrategyItem(**r) for r in (rows or [])]


@app.get("/v2/logs", response_model=LogsResponse, tags=["data"])
async def v2_logs(
    lines: int = Query(50, ge=1, le=500),
    user: Dict = Depends(require_current_user),
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
async def v2_pnl(run_id: str, user: Dict = Depends(require_tenant_user)):
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


def _position_item_from_alpaca(position: Dict) -> PositionItem:
    """Map an Alpaca paper position to the mobile/API response contract."""
    side = position.get("side", "long")
    side = getattr(side, "value", side)
    side = str(side).lower().rsplit(".", 1)[-1]
    qty = float(position.get("qty", 0) or 0)
    unrealized_plpc = position.get("unrealized_plpc")
    return PositionItem(
        run_id="",
        symbol=str(position.get("symbol", "")),
        side=side,
        shares=abs(qty),
        avg_entry_price=float(position["avg_entry_price"])
        if position.get("avg_entry_price") not in (None, "") else None,
        current_price=float(position["current_price"])
        if position.get("current_price") not in (None, "") else None,
        market_value=float(position["market_value"])
        if position.get("market_value") not in (None, "") else None,
        unrealized_pnl=float(position["unrealized_pl"])
        if position.get("unrealized_pl") not in (None, "") else None,
        unrealized_pnl_pct=float(unrealized_plpc) * 100
        if unrealized_plpc not in (None, "") else None,
        cost_basis=float(position["cost_basis"])
        if position.get("cost_basis") not in (None, "") else None,
        status="open",
    )


def _live_position_items(user_id: Optional[str], limit: int) -> Optional[List[PositionItem]]:
    """Read current paper positions, returning None when the broker is unavailable."""
    try:
        from engine.auth import get_alpaca_keys
        from engine.brokers.alpaca import AlpacaAPI

        keys = get_alpaca_keys(user_id) if user_id else None
        if user_id and not keys:
            return None
        client = AlpacaAPI(*keys, paper=True) if keys else AlpacaAPI(paper=True)
        raw = client.get_positions()
        if not isinstance(raw, list):
            logger.warning("/v2/positions broker response was not a list: %s", raw)
            return None
        return [_position_item_from_alpaca(p) for p in raw[:limit]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("/v2/positions broker lookup failed; using DB ledger: %s", exc)
        return None


@app.get("/v2/positions", response_model=PositionsResponse, tags=["data"])
async def v2_positions(
    run_id: Optional[str] = None,
    status: Optional[str] = Query(None, description="'open' or 'closed'"),
    limit: int = Query(50, ge=1, le=500),
    user: Dict = Depends(require_tenant_user),
):
    """Return live paper positions, or query historical positions by run/status.

    The default request used by the mobile Portfolio screen reads Alpaca so
    prices and unrealized P&L are current. Requests for a specific run or for
    non-open history continue to use the database ledger.
    """
    from utils.db.db_pool import DatabasePool
    from sqlalchemy import text

    uid = _uid(user)
    if run_id is None and status in (None, "open"):
        live_items = _live_position_items(uid, limit)
        if live_items is not None:
            return PositionsResponse(positions=live_items, total=len(live_items))

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
async def v2_status(user: Dict = Depends(require_tenant_user)):
    """Current orchestrator / agent status."""
    import time as _time
    from utils.agent_runner import get_all_running_agents

    uid = _uid(user)
    state = _get_app_state(uid)
    orch = state._orch

    # 1) Check subprocess-based running agents (PID files)
    running = get_all_running_agents(user_id=uid)
    if running:
        agent_info = max(running, key=lambda r: r.get("started_at", 0))
        started_ts = agent_info.get("started_at")
        started_dt = datetime.fromtimestamp(started_ts, tz=timezone.utc) if started_ts else None
        elapsed = (_time.time() - started_ts) if started_ts else None

        # Attach best_config from in-memory orch if available (e.g. prior backtest)
        best = None
        if orch and hasattr(orch, 'state') and orch.state.best_config:
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
            run_id=agent_info["run_id"],
            mode=agent_info.get("mode", "paper"),
            status="running",
            agents=[],
            started_at=started_dt,
            elapsed_seconds=elapsed,
            best_config=best,
        )

    # 2) Check in-memory orchestrator state (backtest results, completed sessions)
    if orch is not None:
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
            try:
                if isinstance(started, str):
                    started = datetime.fromisoformat(started.replace("Z", "+00:00"))
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            except Exception:
                elapsed = None

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

    # 3) DB fallback — check most recent run
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            bind: Dict = {}
            user_filter = ""
            if uid:
                user_filter = " WHERE user_id = CAST(:user_id AS UUID)"
                bind["user_id"] = str(uid)
            row = session.execute(
                text(f"SELECT run_id, mode, status, started_at "
                     f"FROM alpatrade.runs{user_filter} "
                     f"ORDER BY created_at DESC LIMIT 1"),
                bind,
            ).fetchone()
        if row:
            return StatusResponse(
                run_id=str(row[0]), mode=row[1], status=row[2] or "unknown",
                started_at=row[3],
            )
    except Exception as e:
        logger.warning(f"/v2/status DB fallback error: {e}")

    return StatusResponse(status="idle")


@app.post("/v2/stop", response_model=StopResponse, tags=["agents"])
async def v2_stop(
    run_id: Optional[str] = Query(None, description="Specific run_id to stop. If omitted, stops the most recent agent."),
    user: Dict = Depends(require_tenant_user),
):
    """Stop a running background agent (subprocess or in-memory task)."""
    from utils.agent_runner import stop_agent, get_all_running_agents

    uid = _uid(user)
    state = _get_app_state(uid)

    target_run_id = run_id

    # Auto-detect target from running subprocess agents
    if not target_run_id:
        running = get_all_running_agents(user_id=uid)
        if running:
            target_run_id = max(running, key=lambda r: r.get("started_at", 0))["run_id"]

    # Try subprocess stop
    if target_run_id and stop_agent(target_run_id):
        if state._subprocess_run_id == target_run_id:
            state._subprocess_run_id = None
        return StopResponse(stopped=True, message=f"Agent {target_run_id} stopped.")

    # Fallback: legacy in-memory task stop
    if state._bg_task and not state._bg_task.done():
        state._bg_stop.set()
        state._bg_task.cancel()
        return StopResponse(stopped=True, message="Background task cancelled.")

    return StopResponse(stopped=False, message="No background task is running.")


@app.post("/v2/backtest", response_model=BacktestResponse, tags=["agents"])
async def v2_backtest(req: BacktestRequest, user: Dict = Depends(require_tenant_user)):
    """Run a parameterized backtest. Synchronous — may take minutes."""
    from agents.orchestrator import Orchestrator

    uid = _uid(user)
    if req.account_id:
        _require_linked_paper_keys(uid, req.account_id)
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

    orch = Orchestrator(user_id=uid, account_id=req.account_id)
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
async def v2_validate(req: ValidateRequest, user: Dict = Depends(require_tenant_user)):
    """Validate trades for a given run. Synchronous."""
    from agents.orchestrator import Orchestrator

    uid = _uid(user)
    if req.account_id:
        _require_linked_paper_keys(uid, req.account_id)
    orch = Orchestrator(user_id=uid, account_id=req.account_id)
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
async def v2_paper(req: PaperRequest, user: Dict = Depends(require_tenant_user)):
    """Start paper trading as an autonomous subprocess. Returns immediately."""
    from agents.orchestrator import Orchestrator, parse_duration
    from utils.agent_runner import spawn_agent, get_all_running_agents

    uid = _uid(user)
    _require_linked_paper_keys(uid, req.account_id)
    state = _get_app_state(uid)

    # Check for already-running paper agent (subprocess-based)
    running = get_all_running_agents(user_id=uid)
    if any(r.get("mode") == "paper" for r in running):
        raise HTTPException(status_code=409, detail="Paper trading is already running")

    # Legacy in-memory task check (backward compat)
    if state._bg_task and not state._bg_task.done():
        raise HTTPException(status_code=409, detail="Paper trading is already running")

    duration_sec = parse_duration(req.duration)
    config = {
        "strategy": req.strategy,
        "duration_seconds": duration_sec,
    }
    if req.params:
        config["params"] = req.params
    if req.agent_name:
        config["agent_name"] = req.agent_name
    if req.agent_framework:
        config["agent_framework"] = req.agent_framework
    if req.source_run_id:
        config["source_run_id"] = req.source_run_id
    if req.symbols:
        config["symbols"] = [s.strip() for s in req.symbols.split(",")]
    if req.poll:
        config["poll_interval_seconds"] = req.poll
    if req.hours:
        config["extended_hours"] = req.hours == "extended"
    if req.email is not None:
        config["email_notifications"] = req.email
    if req.pdt is not None:
        config["pdt_protection"] = req.pdt

    # Spawn as a detached subprocess — survives API restarts
    run_id = spawn_agent("paper", config, user_id=uid, account_id=req.account_id)
    state._subprocess_run_id = run_id

    # Set lightweight orch stub for status display (like CLI does)
    orch = Orchestrator(user_id=uid, account_id=req.account_id)
    orch._mode = "paper"
    orch.run_id = run_id
    state._orch = orch

    return PaperStartResponse(
        run_id=run_id,
        status="started",
        strategy=req.strategy,
        symbols=config.get("symbols"),
        duration=req.duration,
        poll_interval=req.poll,
    )


# ---------------------------------------------------------------------------
# Restricted Hermes broker
# ---------------------------------------------------------------------------

@app.post("/v2/hermes/backtests", tags=["hermes"])
async def hermes_backtest(
    req: HermesBacktestRequest,
    user: Dict = Depends(require_hermes_user),
):
    """Queue an owned backtest and return immediately."""
    from engine.agents.hermes_jobs import enqueue

    uid = _uid(user)
    if req.account_id:
        _require_linked_paper_keys(uid, req.account_id)
    config = {
        "lookback": req.lookback,
        "strategy": req.strategy,
        "symbols": [s.strip() for s in (req.symbols or "").split(",") if s.strip()],
        "objective": req.objective,
        "agent_name": "Hermes",
        "agent_framework": "hermes",
    }
    if req.capital is not None:
        config["initial_capital"] = req.capital
    if req.hours:
        config["extended_hours"] = req.hours == "extended"
    if req.intraday_exit is not None:
        config["intraday_exit"] = req.intraday_exit
    if req.pdt is not None:
        config["pdt_protection"] = req.pdt
    return enqueue(
        "backtest", uid, str(user["thread_id"]), config,
        account_id=req.account_id,
    )


@app.get("/v2/hermes/jobs", tags=["hermes"])
async def hermes_jobs(user: Dict = Depends(require_hermes_user)):
    """List queued, running, and completed jobs owned by this user."""
    from engine.agents.hermes_jobs import list_owned
    jobs = list_owned(_uid(user))
    return {"jobs": jobs, "total": len(jobs)}


@app.get("/v2/hermes/jobs/{job_id}", tags=["hermes"])
async def hermes_job(job_id: str, user: Dict = Depends(require_hermes_user)):
    """Inspect one job only when it belongs to the delegated user."""
    from engine.agents.hermes_jobs import get_owned
    job = get_owned(job_id, _uid(user))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/v2/hermes/candidates", tags=["hermes"])
async def hermes_candidates(user: Dict = Depends(require_hermes_user)):
    """List only the delegated user's saved candidates."""
    from sqlalchemy import text
    from utils.db.db_pool import DatabasePool

    with DatabasePool().get_session() as session:
        result = session.execute(
            text("""
                SELECT c.candidate_id, c.source_run_id, c.agent_name,
                       c.agent_framework, c.strategy, c.symbols, c.params,
                       c.metrics, c.objective, c.status, c.account_id,
                       c.user_id, u.display_name AS owner_name,
                       c.created_at, c.updated_at
                FROM alpatrade.strategy_candidates c
                JOIN alpatrade.users u ON u.user_id = c.user_id
                WHERE c.user_id = CAST(:user_id AS UUID)
                ORDER BY c.created_at DESC LIMIT 100
            """),
            {"user_id": _uid(user)},
        )
        rows = [dict(row) for row in result.mappings().all()]
    return {"candidates": rows, "total": len(rows)}


@app.get("/v2/hermes/runs/{run_id}", tags=["hermes"])
async def hermes_run(run_id: str, user: Dict = Depends(require_hermes_user)):
    """Inspect one run only when it belongs to the delegated user."""
    from sqlalchemy import text
    from utils.db.db_pool import DatabasePool

    with DatabasePool().get_session() as session:
        row = session.execute(
            text("""
                SELECT run_id, mode, strategy, strategy_slug, status, config,
                       results, agent_name, agent_framework, started_at, completed_at
                FROM alpatrade.runs
                WHERE run_id = :run_id AND user_id = CAST(:user_id AS UUID)
            """),
            {"run_id": run_id, "user_id": _uid(user)},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)


@app.post("/v2/hermes/candidates/{candidate_id}/paper", tags=["hermes"])
async def hermes_candidate_paper(
    candidate_id: str,
    req: HermesPaperRequest,
    user: Dict = Depends(require_hermes_user),
):
    """Queue owned candidate parameters for paper trading; live is not exposed."""
    from agents.orchestrator import parse_duration
    from engine.agents.hermes_jobs import enqueue
    from sqlalchemy import text
    from utils.db.db_pool import DatabasePool

    uid = _uid(user)
    with DatabasePool().get_session() as session:
        candidate = session.execute(
            text("""
                SELECT strategy, symbols, params, account_id, source_run_id
                FROM alpatrade.strategy_candidates
                WHERE candidate_id = CAST(:candidate_id AS UUID)
                  AND user_id = CAST(:user_id AS UUID)
            """),
            {"candidate_id": candidate_id, "user_id": uid},
        ).mappings().first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    account_id = req.account_id or (
        str(candidate["account_id"]) if candidate.get("account_id") else None
    )
    if not account_id:
        from engine.auth import get_user_accounts
        accounts = get_user_accounts(uid)
        account_id = accounts[0]["account_id"] if accounts else None
    _require_linked_paper_keys(uid, account_id)
    config = {
        "duration_seconds": parse_duration(req.duration),
        "symbols": candidate["symbols"] or [],
        "strategy": candidate["strategy"],
        "params": candidate["params"] or {},
        "source_run_id": candidate["source_run_id"],
        "agent_name": "Hermes",
        "agent_framework": "hermes",
    }
    if req.poll:
        config["poll_interval_seconds"] = req.poll
    if req.hours:
        config["extended_hours"] = req.hours == "extended"
    if req.email is not None:
        config["email_notifications"] = req.email
    if req.pdt is not None:
        config["pdt_protection"] = req.pdt
    job = enqueue(
        "paper", uid, str(user["thread_id"]), config,
        account_id=account_id, candidate_id=candidate_id,
    )
    with DatabasePool().get_session() as session:
        session.execute(
            text("""
                UPDATE alpatrade.strategy_candidates SET status = 'paper', updated_at = NOW()
                WHERE candidate_id = CAST(:candidate_id AS UUID)
                  AND user_id = CAST(:user_id AS UUID)
            """),
            {"candidate_id": candidate_id, "user_id": uid},
        )
    return {**job, "candidate_id": candidate_id,
            "agent_name": "Hermes", "agent_framework": "hermes"}


@app.post("/v2/full", response_model=FullCycleResponse, tags=["agents"])
async def v2_full(req: FullCycleRequest, user: Dict = Depends(require_tenant_user)):
    """Run full cycle: backtest -> validate -> paper -> validate. Synchronous — long-running."""
    from agents.orchestrator import Orchestrator, parse_duration

    uid = _uid(user)
    _require_linked_paper_keys(uid, req.account_id)
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

    orch = Orchestrator(user_id=uid, account_id=req.account_id)
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
async def v2_reconcile(req: ReconcileRequest, user: Dict = Depends(require_tenant_user)):
    """Reconcile DB positions vs Alpaca holdings. Synchronous."""
    from agents.orchestrator import Orchestrator

    uid = _uid(user)
    _require_linked_paper_keys(uid, req.account_id)
    orch = Orchestrator(user_id=uid, account_id=req.account_id)
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


# ---------------------------------------------------------------------------
# Typed external agent invocation
# ---------------------------------------------------------------------------

@app.post(
    "/v2/agents/chat/invoke",
    response_model=AgentChatResponse,
    tags=["agent-invocation"],
    summary="Invoke the primary DeepAgent and return one JSON response",
)
async def v2_invoke_chat(
    req: AgentChatRequest,
    user: Dict = Depends(require_current_user),
):
    """Run the same DeepAgents harness as web/mobile without requiring SSE parsing."""
    from engine.ai.chat_stream import api_history, stream_chat_events

    uid = str(user["user_id"]) if user.get("user_id") else None
    history = api_history(f"{uid}:{req.thread_id}")
    chunks: List[str] = []
    tools_used: List[str] = []
    route = None
    async for event in stream_chat_events(req.message, uid, req.thread_id, history):
        event_type = event.get("type")
        if event_type == "token" and event.get("text"):
            chunks.append(str(event["text"]))
        elif event_type == "agent_route":
            route = str(
                event.get("slug") or event.get("route") or event.get("agent") or ""
            ) or route
        elif event_type == "tool_start":
            tool = str(event.get("name") or event.get("tool") or "").strip()
            if tool and tool not in tools_used:
                tools_used.append(tool)
        elif event_type == "error":
            logger.warning("DeepAgent invocation failed: %s", event.get("message", "unknown"))
            raise HTTPException(status_code=502, detail="Agent invocation failed")
    return AgentChatResponse(
        thread_id=req.thread_id,
        response="".join(chunks).strip(),
        route=route,
        tools_used=tools_used,
    )


@app.post(
    "/v2/agents/premarket/invoke",
    response_model=PremarketAgentResponse,
    tags=["agent-invocation"],
)
async def v2_invoke_premarket(
    req: PremarketAgentRequest,
    user: Dict = Depends(require_current_user),
):
    """Run the read-only Premarket Agent."""
    from agents.premarket_agent import PremarketAgent

    result = await asyncio.to_thread(
        PremarketAgent().run, refresh=req.refresh, limit=req.limit,
    )
    return PremarketAgentResponse(**result)


def _alpha_response(result) -> AlphaResearchResponse:
    return AlphaResearchResponse(
        run_id=result.run_id,
        mode=result.mode,
        ticker=result.ticker,
        status=result.status,
        report=result.report,
        saved=result.saved,
        persistence_warning=result.persistence_warning,
    )


@app.post(
    "/v2/agents/alpha-growth/invoke",
    response_model=AlphaResearchResponse,
    tags=["agent-invocation"],
)
async def v2_invoke_alpha_growth(
    req: AlphaResearchRequest,
    user: Dict = Depends(require_current_user),
):
    """Run a read-only Growth methodology report."""
    from engine.research.alpha_agents import run_alpha_research

    try:
        result = await run_alpha_research("growth", req.ticker, _uid(user))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _alpha_response(result)


@app.post(
    "/v2/agents/alpha-value/invoke",
    response_model=AlphaResearchResponse,
    tags=["agent-invocation"],
)
async def v2_invoke_alpha_value(
    req: AlphaResearchRequest,
    user: Dict = Depends(require_current_user),
):
    """Run a read-only Value methodology report."""
    from engine.research.alpha_agents import run_alpha_research

    try:
        result = await run_alpha_research("value", req.ticker, _uid(user))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _alpha_response(result)


@app.post(
    "/v2/agents/alpha-compare/invoke",
    response_model=AlphaComparisonResponse,
    tags=["agent-invocation"],
)
async def v2_invoke_alpha_compare(
    req: AlphaResearchRequest,
    user: Dict = Depends(require_current_user),
):
    """Run Growth and Value agents over a shared evidence collection."""
    from engine.research.alpha_agents import run_alpha_comparison

    try:
        result = await run_alpha_comparison(req.ticker, _uid(user))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AlphaComparisonResponse(
        ticker=result.ticker,
        status=result.status,
        growth=_alpha_response(result.growth),
        value=_alpha_response(result.value),
    )


@app.post(
    "/v2/agents/autonomy-scout/invoke",
    response_model=AutonomyScoutResponse,
    tags=["agent-invocation"],
)
async def v2_invoke_autonomy_scout(
    req: AutonomyScoutRequest,
    user: Dict = Depends(require_current_user),
):
    """Scan candidates and enqueue the durable paper-only autonomy pipeline."""
    uid = _uid(user)
    if not uid:
        raise HTTPException(status_code=400, detail="X-User-Id is required for autonomy runs")
    from engine.auth import get_user_accounts

    accounts = get_user_accounts(uid)
    owned = {str(account["account_id"]) for account in accounts}
    account_id = req.account_id or (str(accounts[0]["account_id"]) if accounts else None)
    if not account_id:
        raise HTTPException(status_code=409, detail="No linked Alpaca paper account")
    if account_id not in owned:
        raise HTTPException(status_code=403, detail="Paper account is not owned by this user")

    from engine.autonomy import scout

    run_id = await asyncio.to_thread(
        scout.enqueue_run,
        strategy=req.strategy,
        limit=req.limit,
        user_id=uid,
        account_id=account_id,
    )
    return AutonomyScoutResponse(
        status="queued" if run_id else "no_candidates",
        run_id=run_id,
    )


# ===========================================================================
# LEGACY ENDPOINTS (unchanged — return markdown via CommandProcessor)
# ===========================================================================

@app.get("/health", tags=["meta"], summary="Liveness check")
async def health():
    return {"status": "ok"}

@app.post("/cmd", response_model=ApiResponse, tags=["legacy"])
async def cmd(req: CmdRequest, user: Dict = Depends(require_tenant_user)):
    """Execute an arbitrary CLI command (returns markdown)."""
    return await _run_command(req.command.strip(), user_id=_uid(user))

@app.get("/runs", response_model=ApiResponse, tags=["legacy"])
async def runs(limit: int = 20, user: Dict = Depends(require_tenant_user)):
    return await _run_command("runs", user_id=_uid(user))

@app.get("/trades", response_model=ApiResponse, tags=["legacy"])
async def trades(run_id: Optional[str] = None, type: Optional[str] = None,
                 limit: int = 20, user: Dict = Depends(require_tenant_user)):
    parts = {"run-id": run_id, "type": type, "limit": limit}
    cmd_str = _build_cmd("agent:trades", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/report", response_model=ApiResponse, tags=["legacy"])
async def report(run_id: Optional[str] = None, type: Optional[str] = None,
                 strategy: Optional[str] = None, limit: int = 10,
                 user: Dict = Depends(require_tenant_user)):
    parts = {"run-id": run_id, "type": type, "strategy": strategy, "limit": limit}
    cmd_str = _build_cmd("agent:report", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/top", response_model=ApiResponse, tags=["legacy"])
async def top(strategy: Optional[str] = None, limit: int = 20,
              user: Dict = Depends(require_tenant_user)):
    parts = {"strategy": strategy, "limit": limit}
    cmd_str = _build_cmd("agent:top", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.post("/backtest", response_model=ApiResponse, tags=["legacy"])
async def backtest(req: BacktestRequest, user: Dict = Depends(require_tenant_user)):
    parts = {
        "lookback": req.lookback, "symbols": req.symbols, "strategy": req.strategy,
        "capital": req.capital, "hours": req.hours, "intraday_exit": req.intraday_exit,
        "pdt": req.pdt,
    }
    cmd_str = _build_cmd("agent:backtest", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.post("/paper", response_model=ApiResponse, tags=["legacy"])
async def paper(req: PaperRequest, user: Dict = Depends(require_tenant_user)):
    parts = {
        "duration": req.duration, "symbols": req.symbols, "strategy": req.strategy,
        "poll": req.poll, "hours": req.hours, "email": req.email, "pdt": req.pdt,
    }
    cmd_str = _build_cmd("agent:paper", parts)
    return await _run_command(cmd_str, user_id=_uid(user))

@app.get("/status", response_model=ApiResponse, tags=["legacy"])
async def status(user: Dict = Depends(require_tenant_user)):
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
    """SSE endpoint for streaming chat responses (legacy)."""
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


@app.post(
    "/v2/chat",
    tags=["chat"],
    summary="Streaming chat (SSE) — same router as the web chat",
    openapi_extra={
        "security": [{}],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "msg": {"type": "string", "description": "The user message / prompt.",
                                    "example": "Show me my positions"},
                            "thread_id": {"type": "string",
                                          "description": "Conversation id for history continuity.",
                                          "example": "mobile-1"},
                        },
                        "required": ["msg"],
                    }
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {"msg": {"type": "string"}, "thread_id": {"type": "string"}},
                        "required": ["msg"],
                    }
                },
            },
        },
        "responses": {
            "200": {
                "description": (
                    "Server-Sent Events stream. Each event is `event: <type>` + `data: <json>`. "
                    "Types: session · agent_route · token · tool_start · tool_end · error · done. "
                    "`token.text` chunks concatenate into the assistant reply (markdown)."
                ),
                "content": {"text/event-stream": {"schema": {"type": "string"},
                            "example": ("event: session\\ndata: {\"sid\": \"mobile-1\"}\\n\\n"
                                        "event: token\\ndata: {\"text\": \"MSFT position: 2 shares\"}\\n\\n"
                                        "event: done\\ndata: {}\\n\\n")}},
            }
        },
    },
)
async def v2_chat(
    request: Request,
    user: Optional[Dict] = Depends(get_current_user),
):
    """Streaming chat for the mobile app — the SAME router as the web chat.

    Auth: optional `Authorization: Bearer <JWT>` (authed users trade under their own
    linked Alpaca account; anonymous falls back to the server's paper keys).

    Body (JSON or form-encoded): `msg` (or `message`), `thread_id` (or `sid`).

    Response: `text/event-stream` with named SSE events —
      session · agent_route · token · tool_start · tool_end · error · done
    (`data:` is JSON). This matches the web chat event contract.
    """
    import json as _json

    msg, thread_id = "", "mobile_default"
    if "application/json" in (request.headers.get("content-type") or ""):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        msg = (body.get("msg") or body.get("message") or "").strip()
        thread_id = body.get("thread_id") or body.get("sid") or thread_id
    else:
        form = await request.form()
        msg = (form.get("msg") or form.get("message") or "").strip()
        thread_id = form.get("thread_id") or form.get("sid") or thread_id

    thread_id = str(thread_id).strip()
    if not msg:
        raise HTTPException(status_code=422, detail="msg is required")
    if len(msg) > 20_000:
        raise HTTPException(status_code=413, detail="msg exceeds 20000 characters")
    if not thread_id or len(thread_id) > 200:
        raise HTTPException(status_code=422, detail="thread_id must be 1 to 200 characters")

    uid = str(user["user_id"]) if user and user.get("user_id") else None

    from engine.ai.chat_stream import stream_chat_events, api_history
    hist = api_history(f"{uid}:{thread_id}")

    async def gen():
        try:
            async for ev in stream_chat_events(msg, uid, thread_id, hist):
                etype = ev.pop("type", "token")
                yield f"event: {etype}\ndata: {_json.dumps(ev, default=str)}\n\n"
        except Exception as e:  # noqa: BLE001
            logger.warning("Streaming agent request failed: %s", e)
            yield f"event: error\ndata: {_json.dumps({'message': 'Agent request failed'})}\n\n"
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Paper order placement (market / limit) — for the mobile app
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field  # noqa: E402


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$", examples=["AAPL"])
    qty: float = Field(..., gt=0, examples=[1])
    side: Literal["buy", "sell"] = Field("buy", examples=["buy"])
    order_type: Literal["market", "limit"] = Field("market", examples=["limit"])
    limit_price: Optional[float] = Field(None, gt=0, examples=[180.0],
                                         description="Required for a limit order.")
    time_in_force: Literal["day", "gtc"] = Field("day", examples=["day"])


class OrderResponse(BaseModel):
    ok: bool
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    qty: Optional[float] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    limit_price: Optional[float] = None
    status: Optional[str] = None
    paper: bool = True
    error: Optional[str] = None


@app.post("/v2/order", response_model=OrderResponse, tags=["trading"],
          summary="Place a PAPER order (market or limit)")
async def v2_order(req: OrderRequest, user: Dict = Depends(require_tenant_user)):
    """Place a **paper** (simulated) market or limit order on the primary paper
    account linked to the authenticated user. No real money. For a limit order set `order_type=limit` and
    `limit_price`. Returns the created order id + status."""
    side = (req.side or "buy").lower()
    otype = (req.order_type or "market").lower()
    if side not in ("buy", "sell"):
        return OrderResponse(ok=False, error="side must be 'buy' or 'sell'")
    if otype not in ("market", "limit"):
        return OrderResponse(ok=False, error="order_type must be 'market' or 'limit'")
    if otype == "limit" and req.limit_price is None:
        return OrderResponse(ok=False, error="limit_price is required for a limit order")
    try:
        from engine.brokers.alpaca import AlpacaAPI
        keys = _require_linked_paper_keys(_uid(user))
        client = AlpacaAPI(*keys, paper=True)
        order = client.create_order(
            symbol=req.symbol.upper(), qty=req.qty, side=side, type=otype,
            time_in_force=(req.time_in_force or "day").lower(),
            limit_price=req.limit_price if otype == "limit" else None,
        )
        if isinstance(order, dict) and order.get("error"):
            return OrderResponse(ok=False, error=str(order["error"]))
        o = order if isinstance(order, dict) else {}
        return OrderResponse(
            ok=True, order_id=str(o.get("id", "")), symbol=req.symbol.upper(),
            qty=req.qty, side=side, order_type=otype,
            limit_price=req.limit_price if otype == "limit" else None,
            status=str(o.get("status", "submitted")),
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("Paper order failed for user %s: %s", _uid(user), e)
        return OrderResponse(ok=False, error="Broker request failed")


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

"""FastAPI REST server for AlpaTrade — exposes CLI commands as JSON endpoints."""
import asyncio
import sys
import threading
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Optional

from tui.command_processor import CommandProcessor

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

app = FastAPI(title="AlpaTrade API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CmdRequest(BaseModel):
    command: str

class BacktestRequest(BaseModel):
    lookback: str = "3m"
    symbols: Optional[str] = None
    strategy: str = "buy_the_dip"
    capital: Optional[float] = None
    hours: Optional[str] = None
    intraday_exit: Optional[bool] = None
    pdt: Optional[bool] = None

class PaperRequest(BaseModel):
    duration: str = "7d"
    symbols: Optional[str] = None
    strategy: str = "buy_the_dip"
    poll: Optional[int] = None
    hours: Optional[str] = None
    email: Optional[bool] = None
    pdt: Optional[bool] = None

class ApiResponse(BaseModel):
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
            # Booleans → true/false string
            if isinstance(val, bool):
                parts.append(f"{key}:{'true' if val else 'false'}")
            else:
                parts.append(f"{key}:{val}")
    return " ".join(parts)

# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=AuthResponse)
async def auth_register(req: RegisterRequest):
    from utils.auth import create_user, create_jwt_token
    if len(req.password) < 8:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = create_user(email=req.email, password=req.password, display_name=req.display_name)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Email already registered")
    token = create_jwt_token(user["user_id"], user["email"])
    return AuthResponse(token=token, user_id=user["user_id"], email=user["email"])


@app.post("/auth/login", response_model=AuthResponse)
async def auth_login(req: AuthRequest):
    from utils.auth import authenticate, create_jwt_token
    user = authenticate(req.email, req.password)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_jwt_token(user["user_id"], user["email"])
    return AuthResponse(token=token, user_id=user["user_id"], email=user["email"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _uid(user: Optional[Dict]) -> Optional[str]:
    """Extract user_id from auth payload."""
    return user.get("user_id") if user else None


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/cmd", response_model=ApiResponse)
async def cmd(req: CmdRequest, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command(req.command.strip(), user_id=_uid(user))

@app.get("/runs", response_model=ApiResponse)
async def runs(limit: int = 20, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command("runs", user_id=_uid(user))

@app.get("/trades", response_model=ApiResponse)
async def trades(run_id: Optional[str] = None, type: Optional[str] = None,
                 limit: int = 20, user: Optional[Dict] = Depends(get_current_user)):
    parts = {"run-id": run_id, "type": type, "limit": limit}
    cmd = _build_cmd("agent:trades", parts)
    return await _run_command(cmd, user_id=_uid(user))

@app.get("/report", response_model=ApiResponse)
async def report(run_id: Optional[str] = None, type: Optional[str] = None,
                 strategy: Optional[str] = None, limit: int = 10,
                 user: Optional[Dict] = Depends(get_current_user)):
    parts = {"run-id": run_id, "type": type, "strategy": strategy, "limit": limit}
    cmd = _build_cmd("agent:report", parts)
    return await _run_command(cmd, user_id=_uid(user))

@app.get("/top", response_model=ApiResponse)
async def top(strategy: Optional[str] = None, limit: int = 20,
              user: Optional[Dict] = Depends(get_current_user)):
    parts = {"strategy": strategy, "limit": limit}
    cmd = _build_cmd("agent:top", parts)
    return await _run_command(cmd, user_id=_uid(user))

@app.post("/backtest", response_model=ApiResponse)
async def backtest(req: BacktestRequest, user: Optional[Dict] = Depends(get_current_user)):
    parts = {
        "lookback": req.lookback,
        "symbols": req.symbols,
        "strategy": req.strategy,
        "capital": req.capital,
        "hours": req.hours,
        "intraday_exit": req.intraday_exit,
        "pdt": req.pdt,
    }
    cmd = _build_cmd("agent:backtest", parts)
    return await _run_command(cmd, user_id=_uid(user))

@app.post("/paper", response_model=ApiResponse)
async def paper(req: PaperRequest, user: Optional[Dict] = Depends(get_current_user)):
    parts = {
        "duration": req.duration,
        "symbols": req.symbols,
        "strategy": req.strategy,
        "poll": req.poll,
        "hours": req.hours,
        "email": req.email,
        "pdt": req.pdt,
    }
    cmd = _build_cmd("agent:paper", parts)
    return await _run_command(cmd, user_id=_uid(user))

@app.get("/status", response_model=ApiResponse)
async def status(user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command("agent:status", user_id=_uid(user))

@app.get("/news", response_model=ApiResponse)
async def news(ticker: Optional[str] = None, provider: Optional[str] = None,
               limit: int = 10, user: Optional[Dict] = Depends(get_current_user)):
    cmd = f"news:{ticker}" if ticker else "news"
    parts = {"provider": provider, "limit": limit}
    cmd = _build_cmd(cmd, parts)
    return await _run_command(cmd, user_id=_uid(user))

@app.get("/price", response_model=ApiResponse)
async def price(ticker: str, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command(f"price:{ticker}", user_id=_uid(user))

@app.get("/profile", response_model=ApiResponse)
async def profile(ticker: str, user: Optional[Dict] = Depends(get_current_user)):
    return await _run_command(f"profile:{ticker}", user_id=_uid(user))

@app.get("/movers", response_model=ApiResponse)
async def movers(direction: Optional[str] = None, user: Optional[Dict] = Depends(get_current_user)):
    cmd = f"movers:{direction}" if direction else "movers"
    return await _run_command(cmd, user_id=_uid(user))

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

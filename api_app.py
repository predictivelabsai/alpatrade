"""FastAPI REST server for AlpaTrade — exposes CLI commands as JSON endpoints."""
import asyncio
import sys
import threading
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional

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

app_state = _AppState()

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_command(command: str) -> ApiResponse:
    """Execute a command through CommandProcessor and return ApiResponse."""
    processor = CommandProcessor(app_state)
    try:
        result = await processor.process_command(command) or ""
        app_state.command_history.append(command)
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
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/cmd", response_model=ApiResponse)
async def cmd(req: CmdRequest):
    return await _run_command(req.command.strip())

@app.get("/runs", response_model=ApiResponse)
async def runs(limit: int = 20):
    return await _run_command("runs")

@app.get("/trades", response_model=ApiResponse)
async def trades(run_id: Optional[str] = None, type: Optional[str] = None, limit: int = 20):
    parts = {"run-id": run_id, "type": type, "limit": limit}
    cmd = _build_cmd("agent:trades", parts)
    return await _run_command(cmd)

@app.get("/report", response_model=ApiResponse)
async def report(run_id: Optional[str] = None, type: Optional[str] = None,
                 strategy: Optional[str] = None, limit: int = 10):
    parts = {"run-id": run_id, "type": type, "strategy": strategy, "limit": limit}
    cmd = _build_cmd("agent:report", parts)
    return await _run_command(cmd)

@app.get("/top", response_model=ApiResponse)
async def top(strategy: Optional[str] = None, limit: int = 20):
    parts = {"strategy": strategy, "limit": limit}
    cmd = _build_cmd("agent:top", parts)
    return await _run_command(cmd)

@app.post("/backtest", response_model=ApiResponse)
async def backtest(req: BacktestRequest):
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
    return await _run_command(cmd)

@app.post("/paper", response_model=ApiResponse)
async def paper(req: PaperRequest):
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
    return await _run_command(cmd)

@app.get("/status", response_model=ApiResponse)
async def status():
    return await _run_command("agent:status")

@app.get("/news", response_model=ApiResponse)
async def news(ticker: Optional[str] = None, provider: Optional[str] = None,
               limit: int = 10):
    cmd = f"news:{ticker}" if ticker else "news"
    parts = {"provider": provider, "limit": limit}
    cmd = _build_cmd(cmd, parts)
    return await _run_command(cmd)

@app.get("/price", response_model=ApiResponse)
async def price(ticker: str):
    return await _run_command(f"price:{ticker}")

@app.get("/profile", response_model=ApiResponse)
async def profile(ticker: str):
    return await _run_command(f"profile:{ticker}")

@app.get("/movers", response_model=ApiResponse)
async def movers(direction: Optional[str] = None):
    cmd = f"movers:{direction}" if direction else "movers"
    return await _run_command(cmd)

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

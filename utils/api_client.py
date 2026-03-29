"""
HTTP client for calling the AlpaTrade API from UI services.

When API_URL is set (e.g. in docker-compose), agent commands are routed
to the API container instead of running locally. This keeps paper trading
alive even when UI containers restart on deploy.
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

API_URL = os.environ.get("API_URL", "").rstrip("/")


def is_api_mode() -> bool:
    """Return True if UI should delegate agent commands to the API."""
    return bool(API_URL)


def _headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Build request headers."""
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if user_id:
        h["X-User-Id"] = str(user_id)
    return h


def _post(path: str, payload: Dict, user_id: Optional[str] = None,
          timeout: float = 600) -> Dict[str, Any]:
    """POST to API and return JSON response."""
    url = f"{API_URL}{path}"
    logger.info(f"API POST {url}")
    resp = httpx.post(url, json=payload, headers=_headers(user_id), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, params: Optional[Dict] = None,
         user_id: Optional[str] = None, timeout: float = 30) -> Dict[str, Any]:
    """GET from API and return JSON response."""
    url = f"{API_URL}{path}"
    logger.info(f"API GET {url}")
    resp = httpx.get(url, params=params, headers=_headers(user_id), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------
# Agent command wrappers — return markdown strings
# ------------------------------------------------------------------

def api_paper(params: Dict[str, str], user_id: Optional[str] = None,
              account_id: Optional[str] = None) -> str:
    """Start paper trading via API. Returns markdown result."""
    payload: Dict[str, Any] = {
        "strategy": params.get("strategy", "buy_the_dip"),
        "duration": params.get("duration", "7d"),
    }
    if params.get("symbols"):
        payload["symbols"] = params["symbols"]
    if params.get("poll"):
        payload["poll"] = int(params["poll"])
    if params.get("hours"):
        payload["hours"] = params["hours"]
    if params.get("email"):
        payload["email"] = params["email"].lower() not in ("false", "no", "0", "off")
    if params.get("pdt"):
        payload["pdt"] = params["pdt"].lower() not in ("false", "no", "0", "off")
    if account_id:
        payload["account_id"] = account_id

    data = _post("/v2/paper", payload, user_id=user_id)

    symbols = data.get("symbols") or []
    return (
        f"# Paper Trading Started\n\n"
        f"- **Run ID**: `{data['run_id']}`\n"
        f"- **Status**: {data['status']}\n"
        f"- **Strategy**: {data.get('strategy', '-')}\n"
        f"- **Symbols**: {', '.join(symbols) if symbols else 'default'}\n"
        f"- **Duration**: {data.get('duration', '-')}\n"
        f"- **Poll Interval**: {data.get('poll_interval') or 300}s\n\n"
        f"Running on API server. Use `agent:status` to monitor, `agent:stop` to cancel."
    )


def api_backtest(params: Dict[str, str], user_id: Optional[str] = None,
                 account_id: Optional[str] = None) -> str:
    """Run backtest via API. Blocks until complete."""
    payload: Dict[str, Any] = {
        "lookback": params.get("lookback", "3m"),
        "strategy": params.get("strategy", "buy_the_dip"),
    }
    if params.get("symbols"):
        payload["symbols"] = params["symbols"]
    if params.get("capital"):
        payload["capital"] = float(params["capital"])
    if params.get("hours"):
        payload["hours"] = params["hours"]
    if params.get("intraday_exit"):
        payload["intraday_exit"] = params["intraday_exit"].lower() in ("true", "yes", "1", "on")
    if params.get("pdt"):
        payload["pdt"] = params["pdt"].lower() not in ("false", "no", "0", "off")
    if account_id:
        payload["account_id"] = account_id

    data = _post("/v2/backtest", payload, user_id=user_id, timeout=600)

    md = (
        f"# Backtest Complete\n\n"
        f"- **Run ID**: `{data['run_id']}`\n"
        f"- **Strategy**: {data.get('strategy', '-')}\n"
        f"- **Variations**: {data.get('total_variations', 0)}\n"
        f"- **Status**: {data.get('status', '-')}\n"
    )
    best = data.get("best_config")
    if best:
        md += (
            f"\n## Best Configuration\n\n"
            f"| Metric | Value |\n|--------|-------|\n"
        )
        if best.get("sharpe_ratio") is not None:
            md += f"| Sharpe Ratio | {best['sharpe_ratio']:.2f} |\n"
        if best.get("total_return") is not None:
            md += f"| Total Return | {best['total_return']:.2f}% |\n"
        if best.get("total_pnl") is not None:
            md += f"| Total P&L | ${best['total_pnl']:,.2f} |\n"
        if best.get("win_rate") is not None:
            md += f"| Win Rate | {best['win_rate']:.1f}% |\n"
        if best.get("total_trades") is not None:
            md += f"| Trades | {best['total_trades']} |\n"
        if best.get("max_drawdown") is not None:
            md += f"| Max Drawdown | {best['max_drawdown']:.2f}% |\n"
    return md


def api_validate(params: Dict[str, str], user_id: Optional[str] = None,
                 account_id: Optional[str] = None) -> str:
    """Validate a run via API."""
    run_id = params.get("run-id")
    if not run_id:
        return "# Validate\n\nUsage: `agent:validate run-id:<uuid>`"

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "source": params.get("source", "backtest"),
    }
    if account_id:
        payload["account_id"] = account_id

    data = _post("/v2/validate", payload, user_id=user_id, timeout=300)

    return (
        f"# Validation Complete\n\n"
        f"- **Run ID**: `{data['run_id']}`\n"
        f"- **Status**: {data['status']}\n"
        f"- **Trades Checked**: {data.get('total_trades_checked', 0)}\n"
        f"- **Anomalies Found**: {data.get('anomalies_found', 0)}\n"
        f"- **Anomalies Corrected**: {data.get('anomalies_corrected', 0)}\n"
        f"- **Iterations**: {data.get('iterations_used', 0)}\n"
    )


def api_full(params: Dict[str, str], user_id: Optional[str] = None,
             account_id: Optional[str] = None) -> str:
    """Run full cycle via API. Blocks until complete."""
    payload: Dict[str, Any] = {
        "lookback": params.get("lookback", "3m"),
        "strategy": params.get("strategy", "buy_the_dip"),
        "duration": params.get("duration", "1m"),
    }
    if params.get("symbols"):
        payload["symbols"] = params["symbols"]
    if params.get("hours"):
        payload["hours"] = params["hours"]
    if params.get("pdt"):
        payload["pdt"] = params["pdt"].lower() not in ("false", "no", "0", "off")
    if account_id:
        payload["account_id"] = account_id

    data = _post("/v2/full", payload, user_id=user_id, timeout=600)

    md = (
        f"# Full Cycle Complete\n\n"
        f"- **Run ID**: `{data['run_id']}`\n"
        f"- **Status**: {data.get('status', '-')}\n"
    )
    phases = data.get("phases", {})
    if phases:
        md += "\n## Phases\n\n| Phase | Status | Run ID |\n|-------|--------|--------|\n"
        for name, info in phases.items():
            if isinstance(info, dict):
                md += f"| {name} | {info.get('status', '-')} | `{(info.get('run_id') or '-')[:12]}` |\n"
    return md


def api_reconcile(params: Dict[str, str], user_id: Optional[str] = None,
                  account_id: Optional[str] = None) -> str:
    """Reconcile via API."""
    window = params.get("window", "7d")
    window_days = int(window.replace("d", ""))

    payload: Dict[str, Any] = {"window_days": window_days}
    if account_id:
        payload["account_id"] = account_id

    data = _post("/v2/reconcile", payload, user_id=user_id, timeout=120)

    return (
        f"# Reconciliation Complete\n\n"
        f"- **Run ID**: `{data['run_id']}`\n"
        f"- **Status**: {data['status']}\n"
        f"- **Total Issues**: {data.get('total_issues', 0)}\n"
    )


def api_stop(user_id: Optional[str] = None) -> str:
    """Stop running agent via API."""
    data = _post("/v2/stop", {}, user_id=user_id)

    if data.get("stopped"):
        return f"# Stopped\n\n{data.get('message', 'Background task cancelled.')}"
    return f"# Stop\n\n{data.get('message', 'No background task is running.')}"


def api_status(user_id: Optional[str] = None) -> str:
    """Get agent status via API."""
    data = _get("/v2/status", user_id=user_id)

    status = data.get("status", "unknown")
    if status == "idle":
        return "# Agent Status\n\nNo agents currently running."

    md = (
        f"# Agent Status\n\n"
        f"- **Run ID**: `{data.get('run_id', '-')}`\n"
        f"- **Mode**: {data.get('mode', '-')}\n"
        f"- **Status**: {status}\n"
    )
    if data.get("elapsed_seconds"):
        elapsed = int(data["elapsed_seconds"])
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            md += f"- **Elapsed**: {hours}h {mins}m {secs}s\n"
        else:
            md += f"- **Elapsed**: {mins}m {secs}s\n"

    agents = data.get("agents", [])
    if agents:
        md += "\n| Agent | Status | Detail |\n|-------|--------|--------|\n"
        for a in agents:
            md += f"| {a.get('name', '-')} | {a.get('status', '-')} | {a.get('detail', '-')} |\n"
    return md

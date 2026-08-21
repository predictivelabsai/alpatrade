"""Tenant-scoped tools and native specialist definitions for DeepAgents."""

from __future__ import annotations

import hashlib
import json
import re
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from typing import Any, Optional

from langchain.tools import ToolRuntime, tool
from sqlalchemy import text

from engine.db.pool import DatabasePool


@dataclass(frozen=True)
class DeepAgentContext:
    """Trusted request context injected by the API, never supplied by the model."""

    user_id: Optional[str]
    account_id: Optional[str]
    thread_id: str
    request_message_id: str
    response_id: str
    auth_type: str
    request_id: str
    current_user_text: str
    public_only: bool = False


_ACTIVE_DEEPAGENT_CONTEXT: ContextVar[Optional[DeepAgentContext]] = ContextVar(
    "active_deepagent_context", default=None
)


def _bind_deepagent_context(context: DeepAgentContext) -> Token:
    """Carry trusted context through DeepAgents' nested native task runnable."""
    return _ACTIVE_DEEPAGENT_CONTEXT.set(context)


def _reset_deepagent_context(token: Token) -> None:
    _ACTIVE_DEEPAGENT_CONTEXT.reset(token)


_ACTION_VERBS = re.compile(
    r"\b(run|queue|start|execute|place|submit|buy|sell|trade|cancel|stop|"
    r"reconcile|validate|launch|backtest|apply|approve|proceed)\b",
    re.IGNORECASE,
)
_ADVISORY_PATTERNS = re.compile(
    r"\b(hypothetical(?:ly)?|what\s+(?:if|would|happens|about)|how\s+would|"
    r"should|would|(?:can|could|may)\s+i|do\s+i|explain|describe|"
    r"(?:tell|show)\s+me\s+(?:how|whether)|how\s+(?:do|can)\s+i|"
    r"do\s+you\s+think|thoughts?\s+(?:about|on)|good\s+idea|advisable|"
    r"safe\s+to|is\s+it\s+a\s+good|(?:do|did)\s+not|"
    r"don['’]t|didn['’]t|never|if\s+i|suppose|imagine|considering)\b",
    re.IGNORECASE,
)
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def explicit_action_intent(text_value: str) -> bool:
    """Conservative deterministic gate for tools with side effects."""
    text_value = " ".join((text_value or "").split())
    return bool(_ACTION_VERBS.search(text_value)) and not bool(
        _ADVISORY_PATTERNS.search(text_value)
    )


def _context(runtime: ToolRuntime[DeepAgentContext]) -> DeepAgentContext:
    context = getattr(runtime, "context", None) or _ACTIVE_DEEPAGENT_CONTEXT.get()
    if isinstance(context, dict):
        return DeepAgentContext(**context)
    if not isinstance(context, DeepAgentContext):
        raise PermissionError("Trusted tenant context is unavailable.")
    return context


def _require_tenant(runtime: ToolRuntime[DeepAgentContext]) -> DeepAgentContext:
    context = _context(runtime)
    if context.public_only or not context.user_id:
        raise PermissionError("This tool requires tenant authentication.")
    return context


def _require_action(runtime: ToolRuntime[DeepAgentContext]) -> DeepAgentContext:
    context = _require_tenant(runtime)
    if not explicit_action_intent(context.current_user_text):
        raise PermissionError(
            "No action was taken because the final user message was advisory or hypothetical."
        )
    return context


def _ticker(value: str) -> str:
    value = (value or "").upper().strip()
    if not _SYMBOL.fullmatch(value):
        raise ValueError("ticker must be a valid symbol")
    return value


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _sanitize_job_output(value: Any) -> Any:
    """Remove secret/error-shaped fields before a checkpoint reaches a model."""
    if isinstance(value, dict):
        clean = {}
        for key, item in list(value.items())[:100]:
            lowered = str(key).lower()
            if any(marker in lowered for marker in (
                "api_key", "secret", "credential", "password", "token",
            )):
                continue
            if any(marker in lowered for marker in (
                "error", "exception", "traceback",
            )):
                clean["status"] = "failed"
                continue
            clean[key] = _sanitize_job_output(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_job_output(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 4_000:
        return value[:4_000] + "…"
    return _json_safe(value)


def _sanitize_advisor_report(value: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a report without turning its generation error_code into job failure."""
    report = dict(value)
    report.pop("error_code", None)
    return _sanitize_job_output(report)


def _call_id(runtime: ToolRuntime[DeepAgentContext], tool_name: str) -> str:
    provided = getattr(runtime, "tool_call_id", None)
    if provided:
        return str(provided)
    context = _context(runtime)
    seed = f"{context.response_id}:{context.request_message_id}:{tool_name}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _dedupe_key(context: DeepAgentContext, call_id: str, tool_name: str) -> str:
    return f"{context.response_id}:{context.request_message_id}:{call_id}:{tool_name}"


def _client_order_id(context: DeepAgentContext, call_id: str, tool_name: str) -> str:
    seed = _dedupe_key(context, call_id, tool_name)
    return f"dap-{hashlib.sha256(seed.encode()).hexdigest()[:40]}"


def _broker(context: DeepAgentContext):
    from engine.auth import get_alpaca_keys
    from engine.brokers.alpaca import AlpacaAPI

    keys = get_alpaca_keys(context.user_id, _effective_account_id(context))
    if not keys:
        raise PermissionError("No owned linked Alpaca paper account is available.")
    client = AlpacaAPI(api_key=keys[0], secret_key=keys[1], paper=True)
    if not client.is_paper:
        raise PermissionError("Only paper trading is permitted.")
    return client


def _effective_account_id(context: DeepAgentContext) -> Optional[str]:
    if context.account_id:
        return context.account_id
    if not context.user_id:
        return None
    with DatabasePool().get_session() as session:
        account_id = session.execute(text("""
            SELECT account_id FROM alpatrade.user_accounts
            WHERE user_id = :uid AND is_active = TRUE
            ORDER BY created_at ASC LIMIT 1
        """), {"uid": context.user_id}).scalar()
    return str(account_id) if account_id else None


def _reserve_action(
    context: DeepAgentContext,
    runtime: ToolRuntime[DeepAgentContext],
    tool_name: str,
    *,
    order_client_id: Optional[str] = None,
):
    from engine.ai.deepagent_store import PostgresDeepAgentStore

    call_id = _call_id(runtime, tool_name)
    record = PostgresDeepAgentStore().reserve_action(
        user_id=context.user_id or "",
        response_id=context.response_id,
        request_message_id=context.request_message_id,
        tool_call_id=call_id,
        tool_name=tool_name,
        order_client_id=order_client_id,
    )
    return call_id, record


def _finish_action(context: DeepAgentContext, action_id: str, status: str,
                   job_id: Optional[str] = None) -> None:
    from engine.ai.deepagent_store import PostgresDeepAgentStore

    PostgresDeepAgentStore().finish_action(
        context.user_id or "", action_id, status, job_id=job_id
    )


def _enqueue(
    runtime: ToolRuntime[DeepAgentContext],
    tool_name: str,
    kind: str,
    config: dict[str, Any],
    account_id_override: Optional[str] = None,
) -> dict[str, Any]:
    from engine.autonomy import queue

    context = _require_action(runtime)
    call_id, action = _reserve_action(context, runtime, tool_name)
    paper_capable = kind in {"deepagent_paper", "deepagent_full", "full"}
    if not action.created and action.job_id:
        return {
            "job_id": action.job_id,
            "status": action.status,
            "cached": True,
            "paper_only": paper_capable,
        }
    account_id = account_id_override or (
        _effective_account_id(context) if paper_capable else context.account_id
    )
    # A process may have died between queue insertion and linking the action row.
    # Reissuing the same dedupe key safely returns the existing job in that case.
    job_id = queue.enqueue(
        kind=kind,
        config=config,
        user_id=context.user_id,
        account_id=account_id,
        dedupe_key=_dedupe_key(context, call_id, tool_name),
    )
    _finish_action(context, action.action_id, "queued", job_id=job_id)
    return {
        "job_id": job_id,
        "status": "queued",
        "cached": not action.created,
        "paper_only": paper_capable,
    }


# ---------------------------------------------------------------------------
# Common fast-read tools
# ---------------------------------------------------------------------------

@tool
def get_market_price(ticker: str) -> dict[str, Any]:
    """Get the latest price and recent daily change for one public-market ticker."""
    import yfinance as yf

    symbol = _ticker(ticker)
    history = yf.Ticker(symbol).history(period="5d", interval="1d")
    if history.empty:
        return {"ticker": symbol, "status": "unavailable"}
    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) > 1 else latest
    close = float(latest["Close"])
    prior = float(previous["Close"])
    return {
        "ticker": symbol,
        "price": close,
        "change": close - prior,
        "change_percent": ((close / prior) - 1) * 100 if prior else None,
        "open": float(latest["Open"]),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "volume": int(latest["Volume"]),
    }


@tool
def search_market_news(ticker: str = "", query: str = "", limit: int = 10) -> list[dict]:
    """Search recent public press releases by ticker or headline text."""
    from engine.publicmarkets.news import search_news

    return search_news(query=query[:100], ticker=_ticker(ticker) if ticker else "",
                       limit=max(1, min(limit, 20)))


@tool
def list_linked_accounts(runtime: ToolRuntime[DeepAgentContext]) -> list[dict]:
    """List metadata for the authenticated user's active linked accounts."""
    from engine.auth import get_user_accounts

    context = _require_tenant(runtime)
    return [
        {
            "account_id": account["account_id"],
            "account_name": account["account_name"],
            "is_active": account["is_active"],
            "created_at": account["created_at"],
        }
        for account in get_user_accounts(context.user_id or "")
    ]


@tool
def get_account_summary(runtime: ToolRuntime[DeepAgentContext]) -> dict[str, Any]:
    """Get summary balances from the caller's linked Alpaca paper account."""
    context = _require_tenant(runtime)
    result = _broker(context).get_account()
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError("The paper account summary is temporarily unavailable.")
    allowed = (
        "id", "status", "currency", "cash", "portfolio_value", "equity",
        "buying_power", "daytrade_count", "pattern_day_trader",
    )
    return {key: _json_safe(result.get(key)) for key in allowed if key in result}


@tool
def get_positions(runtime: ToolRuntime[DeepAgentContext]) -> list[dict[str, Any]]:
    """Get open positions from the caller's linked Alpaca paper account."""
    context = _require_tenant(runtime)
    result = _broker(context).get_positions()
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError("Paper positions are temporarily unavailable.")
    allowed = (
        "symbol", "asset_class", "qty", "side", "market_value", "cost_basis",
        "unrealized_pl", "unrealized_plpc", "current_price", "avg_entry_price",
    )
    return [
        {key: _json_safe(position.get(key)) for key in allowed if key in position}
        for position in (result or [])
    ]


@tool
def get_recent_runs(limit: int = 10,
                    runtime: ToolRuntime[DeepAgentContext] = None) -> list[dict]:
    """List the authenticated user's recent strategy runs in the selected account scope."""
    context = _require_tenant(runtime)
    clauses = ["user_id = :uid"]
    params: dict[str, Any] = {"uid": context.user_id, "limit": max(1, min(limit, 50))}
    if context.account_id:
        clauses.append("account_id = :aid")
        params["aid"] = context.account_id
    with DatabasePool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT run_id, mode, strategy, status, started_at, completed_at
            FROM alpatrade.runs WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC LIMIT :limit
        """), params).fetchall()
    return [
        {"run_id": row[0], "mode": row[1], "strategy": row[2], "status": row[3],
         "started_at": row[4], "completed_at": row[5]}
        for row in rows
    ]


@tool
def get_job_status(job_id: str,
                   runtime: ToolRuntime[DeepAgentContext] = None) -> dict[str, Any]:
    """Get status for one durable DeepAgent/autonomy job owned by the caller."""
    from engine.autonomy.store import get_run_for_user

    context = _require_tenant(runtime)
    row = get_run_for_user(job_id, context.user_id or "", context.account_id)
    if row is None:
        raise ValueError("job not found")
    return _sanitize_job_output(row)


# ---------------------------------------------------------------------------
# Market-research specialist tools
# ---------------------------------------------------------------------------

def _market_research():
    # This module is the still-canonical market research implementation pending
    # its engine extraction; callers never receive provider credentials.
    from utils.market_research_util import MarketResearch

    return MarketResearch()


@tool
def get_analyst_ratings(ticker: str) -> str:
    """Get public analyst recommendations and targets for a ticker."""
    return _market_research().analysts(ticker=_ticker(ticker))


@tool
def get_company_profile(ticker: str) -> str:
    """Get a public company profile, sector, industry, and market capitalization."""
    return _market_research().profile(ticker=_ticker(ticker))


@tool
def get_company_financials(ticker: str, period: str = "annual") -> str:
    """Get public annual or quarterly company financials."""
    if period not in {"annual", "quarterly"}:
        raise ValueError("period must be annual or quarterly")
    return _market_research().financials(ticker=_ticker(ticker), period=period)


@tool
def get_market_movers(direction: str = "both") -> str:
    """Get current public-market gainers, losers, or both."""
    if direction not in {"gainers", "losers", "both"}:
        raise ValueError("direction must be gainers, losers, or both")
    return _market_research().movers(direction=direction)


@tool
def compare_valuation(tickers: list[str]) -> str:
    """Compare public valuation metrics for up to ten ticker symbols."""
    symbols = [_ticker(value) for value in tickers[:10]]
    if not symbols:
        raise ValueError("at least one ticker is required")
    return _market_research().valuation(tickers=symbols)


@tool
def get_premarket_movers(
    limit: int = 10,
    date: str = "",
    sector: str = "",
    ticker: str = "",
    chart: str = "auto",
    refresh: bool = False,
) -> str:
    """Read latest/historical premarket breadth, movers, or one ticker.

    Dates use YYYY-MM-DD. ``sector`` and ``ticker`` cannot be combined. Charts
    are auto, breadth, movers, or none. The external scheduler owns refreshes.
    """
    from agents.premarket_agent import PremarketAgent
    from engine.research.premarket import PremarketValidationError, SchedulerManagedError

    try:
        return PremarketAgent().report(
            limit=max(1, min(limit, 50)),
            date=date or None,
            sector=sector or None,
            ticker=ticker or None,
            chart=chart,
            refresh=refresh,
        )
    except SchedulerManagedError as exc:
        return f"# Premarket screening\n\n`{exc.code}`: {exc}"
    except PremarketValidationError as exc:
        return f"# Premarket screening\n\nRequest error: {exc}"
    except Exception:  # noqa: BLE001
        return "# Premarket screening\n\nPremarket scheduler data is unavailable."


@tool
async def run_alpha_growth(ticker: str,
                           runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Run an evidence-backed Alpha Growth analysis for a ticker."""
    from engine.research.alpha_agents import run_alpha_research

    context = _context(runtime)
    result = await run_alpha_research("growth", _ticker(ticker), context.user_id)
    return asdict(result)


@tool
async def run_alpha_value(ticker: str,
                          runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Run an evidence-backed Alpha Value analysis for a ticker."""
    from engine.research.alpha_agents import run_alpha_research

    context = _context(runtime)
    result = await run_alpha_research("value", _ticker(ticker), context.user_id)
    return asdict(result)


@tool
async def run_alpha_compare(ticker: str,
                            runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Run paired Growth and Value analyses from shared evidence."""
    from engine.research.alpha_agents import run_alpha_comparison

    context = _context(runtime)
    result = await run_alpha_comparison(_ticker(ticker), context.user_id)
    return asdict(result)


@tool
def get_sec_filings(ticker: str, form_type: str = "", limit: int = 10) -> dict:
    """Get recent SEC filings for a public company."""
    from engine.publicmarkets.edgar import get_company_filings

    return get_company_filings(_ticker(ticker), form_type=form_type[:16],
                               limit=max(1, min(limit, 30)))


@tool
def get_sec_financial_facts(ticker: str) -> dict:
    """Get SEC XBRL financial facts for a public company."""
    from engine.publicmarkets.edgar import get_financial_facts

    return get_financial_facts(_ticker(ticker))


@tool
def get_sector_performance(years: int = 5) -> dict:
    """Get annual returns for the eleven major US sector ETFs."""
    from engine.publicmarkets.market_intel import sector_returns

    return sector_returns(max(1, min(years, 10)))


@tool
def get_ipo_market(limit: int = 20) -> dict:
    """Get recently priced IPOs and post-IPO performance."""
    from engine.publicmarkets.ipo import ipo_map_data

    return ipo_map_data(max(1, min(limit, 100)))


@tool
def get_ipo_pipeline(limit: int = 20) -> list[dict]:
    """Get upcoming and pre-IPO companies from the public pipeline."""
    from engine.publicmarkets.ipo import ipo_pipeline_data

    return ipo_pipeline_data(max(1, min(limit, 100)))


@tool
def get_top_funds(limit: int = 15) -> list[dict]:
    """Get the largest institutional managers from public 13F data."""
    from engine.publicmarkets.hedge_funds import top_funds

    return top_funds(max(1, min(limit, 40)))


@tool
def get_activist_filings(ticker: str = "", limit: int = 15) -> list[dict]:
    """Get recent public activist and Schedule 13D filings."""
    from engine.publicmarkets.hedge_funds import activist_filings

    return activist_filings(_ticker(ticker) if ticker else "", max(1, min(limit, 30)))


@tool
def get_press_releases(query: str = "", ticker: str = "", limit: int = 15) -> list[dict]:
    """Search recent public company press releases."""
    from engine.publicmarkets.news import search_news

    return search_news(query=query[:100], ticker=_ticker(ticker) if ticker else "",
                       limit=max(1, min(limit, 30)))


@tool
def get_spacs(limit: int = 15) -> list[dict]:
    """Get public SPAC trust, NAV-premium, target, and status data."""
    from engine.publicmarkets.spacs import spac_list

    return spac_list(limit=max(1, min(limit, 50)))


@tool
def get_prediction_research(industry: str = "", event: str = "",
                            min_samples: int = 5) -> dict:
    """Analyze predicted versus realized market moves by event and industry."""
    from engine.research.data import correlation_summary

    summary = correlation_summary(
        industry[:100], event[:100], max(2, min(min_samples, 100))
    )
    # Individual prediction rows can be both large and unnecessarily identifying.
    # The agent only needs aggregate evidence for research and comparison.
    return {
        "count": summary.get("count", 0),
        "correlation": summary.get("correlation"),
        "mae": summary.get("mae"),
        "matrix": (summary.get("matrix") or [])[:100],
        "events": (summary.get("events") or [])[:100],
        "industries": (summary.get("industries") or [])[:100],
    }


# ---------------------------------------------------------------------------
# Portfolio specialist tools
# ---------------------------------------------------------------------------

@tool
def get_recent_trades(limit: int = 20,
                      runtime: ToolRuntime[DeepAgentContext] = None) -> list[dict]:
    """List recent trades owned by the authenticated user and selected account."""
    context = _require_tenant(runtime)
    clauses = ["user_id = :uid"]
    params: dict[str, Any] = {"uid": context.user_id, "limit": max(1, min(limit, 100))}
    if context.account_id:
        clauses.append("account_id = :aid")
        params["aid"] = context.account_id
    with DatabasePool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT run_id, trade_type, symbol, direction, shares, entry_time,
                   exit_time, entry_price, exit_price, pnl, total_fees
            FROM alpatrade.trades WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC LIMIT :limit
        """), params).fetchall()
    keys = ("run_id", "trade_type", "symbol", "direction", "shares", "entry_time",
            "exit_time", "entry_price", "exit_price", "pnl", "total_fees")
    return [dict(zip(keys, map(_json_safe, row))) for row in rows]


@tool
def get_run_report(run_id: str,
                   runtime: ToolRuntime[DeepAgentContext] = None) -> dict[str, Any]:
    """Get one stored run report, enforcing caller and optional-account ownership."""
    context = _require_tenant(runtime)
    clauses = ["run_id = :rid", "user_id = :uid"]
    params: dict[str, Any] = {"rid": run_id, "uid": context.user_id}
    if context.account_id:
        clauses.append("account_id = :aid")
        params["aid"] = context.account_id
    with DatabasePool().get_session() as session:
        row = session.execute(text(f"""
            SELECT run_id, mode, strategy, status, config, results,
                   started_at, completed_at
            FROM alpatrade.runs WHERE {' AND '.join(clauses)}
        """), params).fetchone()
    if row is None:
        raise ValueError("run not found")
    keys = ("run_id", "mode", "strategy", "status", "config", "results",
            "started_at", "completed_at")
    return _sanitize_job_output(dict(zip(keys, map(_json_safe, row))))


@tool
def get_strategy_rankings(trade_type: str = "backtest", limit: int = 10,
                          runtime: ToolRuntime[DeepAgentContext] = None) -> list[dict]:
    """Rank strategies using only the authenticated user's stored results."""
    from agents.report_agent import ReportAgent

    context = _require_tenant(runtime)
    if trade_type not in {"backtest", "paper"}:
        raise ValueError("trade_type must be backtest or paper")
    return ReportAgent().top_strategies(
        trade_type=trade_type,
        limit=max(1, min(limit, 25)),
        user_id=context.user_id,
        account_id=context.account_id,
    ) or []


@tool
def get_pnl_summary(run_id: str,
                    runtime: ToolRuntime[DeepAgentContext] = None) -> dict[str, Any]:
    """Get persisted P&L rows for an owned run."""
    context = _require_tenant(runtime)
    clauses = ["p.run_id = :rid", "p.user_id = :uid"]
    params: dict[str, Any] = {"rid": run_id, "uid": context.user_id}
    if context.account_id:
        clauses.append("p.account_id = :aid")
        params["aid"] = context.account_id
    with DatabasePool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT p.symbol, p.trade_count, p.win_count, p.loss_count,
                   p.total_pnl, p.total_fees, p.total_return_pct, p.win_rate
            FROM alpatrade.pnl_summary p
            WHERE {' AND '.join(clauses)} ORDER BY p.symbol NULLS FIRST
        """), params).fetchall()
    return {"run_id": run_id, "rows": [
        {"symbol": row[0], "trade_count": row[1], "win_count": row[2],
         "loss_count": row[3], "total_pnl": _json_safe(row[4]),
         "total_fees": _json_safe(row[5]), "total_return_pct": _json_safe(row[6]),
         "win_rate": _json_safe(row[7])}
        for row in rows
    ]}


@tool
def get_job_events(job_id: str, limit: int = 30,
                   runtime: ToolRuntime[DeepAgentContext] = None) -> list[dict]:
    """Get sanitized phase events for one owned durable job."""
    from engine.autonomy.store import get_events_for_user

    context = _require_tenant(runtime)
    return get_events_for_user(job_id, context.user_id or "", limit, context.account_id)


@tool
def get_job_results(job_id: str,
                    runtime: ToolRuntime[DeepAgentContext] = None) -> list[dict]:
    """Get sanitized checkpointed phase results for one owned durable job."""
    from engine.autonomy.store import get_step_results_for_user

    context = _require_tenant(runtime)
    rows = get_step_results_for_user(
        job_id, context.user_id or "", context.account_id
    )
    return [_sanitize_job_output(row) for row in rows]


@tool
def get_latest_advisor_report(
    runtime: ToolRuntime[DeepAgentContext] = None,
) -> dict[str, Any]:
    """Get the latest persisted daily advisor report for the selected paper account."""
    from engine.reporting.advisor import list_reports_for_user

    context = _require_tenant(runtime)
    account_id = _effective_account_id(context)
    rows = list_reports_for_user(
        context.user_id or "", account_id=account_id, limit=1
    )
    return _sanitize_advisor_report(rows[0]) if rows else {
        "status": "unavailable",
        "message": "No daily advisor report has been generated for this account yet.",
    }


@tool
def get_advisor_history(
    limit: int = 10,
    runtime: ToolRuntime[DeepAgentContext] = None,
) -> list[dict[str, Any]]:
    """List persisted daily advisor reports for the selected paper account."""
    from engine.reporting.advisor import list_reports_for_user

    context = _require_tenant(runtime)
    rows = list_reports_for_user(
        context.user_id or "",
        account_id=_effective_account_id(context),
        limit=max(1, min(int(limit), 50)),
    )
    return [_sanitize_advisor_report(row) for row in rows]


# ---------------------------------------------------------------------------
# Strategy, paper-trading, and orchestration actions
# ---------------------------------------------------------------------------

@tool
def queue_backtest(strategy: str = "buy_the_dip", symbols: list[str] | None = None,
                   lookback: str = "3m",
                   runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Queue a durable grid-search backtest after an explicit user instruction."""
    config = {
        "strategy": strategy[:64],
        "symbols": [_ticker(symbol) for symbol in (symbols or [])[:25]],
        "lookback": lookback[:16],
    }
    if not config["symbols"]:
        config.pop("symbols")
    return _enqueue(runtime, "queue_backtest", "deepagent_backtest", config)


@tool
def queue_advisor_backtest(
    report_id: str,
    recommendation_id: str,
    runtime: ToolRuntime[DeepAgentContext] = None,
) -> dict:
    """Queue the exact stored advisor test grid after an explicit user instruction."""
    from engine.reporting.advisor import recommendation_config

    context = _require_action(runtime)
    config = recommendation_config(
        report_id,
        recommendation_id,
        context.user_id or "",
        account_id=context.account_id,
    )
    source_account_id = str(
        config.pop("_advisor_account_id", context.account_id or "") or ""
    ) or None
    return _enqueue(
        runtime,
        "queue_advisor_backtest",
        "deepagent_backtest",
        config,
        account_id_override=source_account_id,
    )


@tool
def validate_run(run_id: str, source: str = "backtest",
                 runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Synchronously validate an owned backtest or paper run after explicit intent."""
    from agents.orchestrator import Orchestrator

    context = _require_action(runtime)
    if source not in {"backtest", "paper_trade", "paper"}:
        raise ValueError("source must be backtest or paper")
    with DatabasePool().get_session() as session:
        owned = session.execute(text("""
            SELECT 1 FROM alpatrade.runs
            WHERE run_id = :rid AND user_id = :uid
              AND (:aid IS NULL OR account_id = CAST(:aid AS UUID))
        """), {"rid": run_id, "uid": context.user_id,
               "aid": context.account_id}).scalar()
    if not owned:
        raise ValueError("run not found")
    normalized_source = (
        "paper_trade" if source in {"paper", "paper_trade"} else "backtest"
    )
    return Orchestrator(
        user_id=context.user_id, account_id=context.account_id
    ).run_validation(run_id=run_id, source=normalized_source)


@tool
def compare_strategy_results(limit: int = 10,
                             runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Compare the caller's backtest and paper strategy rankings."""
    context = _require_tenant(runtime)
    from agents.report_agent import ReportAgent

    report = ReportAgent()
    bounded = max(1, min(limit, 25))
    return {
        "backtest": report.top_strategies(
            trade_type="backtest", limit=bounded, user_id=context.user_id,
            account_id=context.account_id,
        ) or [],
        "paper": report.top_strategies(
            trade_type="paper", limit=bounded, user_id=context.user_id,
            account_id=context.account_id,
        ) or [],
    }


@tool
def place_paper_order(symbol: str, qty: float, side: str = "buy",
                      order_type: str = "market", limit_price: float | None = None,
                      runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Place an idempotent equity order in the caller's linked paper account."""
    context = _require_action(runtime)
    symbol = _ticker(symbol)
    side = side.lower()
    order_type = order_type.lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if order_type not in {"market", "limit"}:
        raise ValueError("order_type must be market or limit")
    if qty <= 0:
        raise ValueError("qty must be positive")
    if order_type == "limit" and (limit_price is None or limit_price <= 0):
        raise ValueError("a positive limit_price is required for a limit order")
    call_id = _call_id(runtime, "place_paper_order")
    client_order_id = _client_order_id(context, call_id, "place_paper_order")
    _, action = _reserve_action(
        context, runtime, "place_paper_order", order_client_id=client_order_id
    )
    if not action.created:
        return {
            "status": action.status,
            "client_order_id": action.order_client_id,
            "cached": True,
            "paper_only": True,
        }
    try:
        result = _broker(context).create_order(
            symbol=symbol, qty=qty, side=side, type=order_type,
            limit_price=limit_price, client_order_id=client_order_id,
        )
    except Exception as exc:
        _finish_action(context, action.action_id, "failed")
        raise RuntimeError("The paper order was not accepted; inspect the paper account.") from exc
    if not isinstance(result, dict) or result.get("error"):
        _finish_action(context, action.action_id, "failed")
        raise RuntimeError("The paper order was not accepted; inspect the paper account.")
    _finish_action(context, action.action_id, "completed")
    return {
        "status": str(result.get("status", "accepted")),
        "order_id": str(result.get("id", "")),
        "client_order_id": client_order_id,
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "paper_only": True,
        "cached": False,
    }


@tool
def list_index_option_contracts(underlying: str, contract_type: str = "",
                                limit: int = 20,
                                runtime: ToolRuntime[DeepAgentContext] = None) -> list[dict]:
    """List supported European-style index option contracts in the paper account."""
    from engine.brokers.index_options import list_contracts

    context = _require_tenant(runtime)
    client = _broker(context)
    return list_contracts(client.trading_client, underlying,
                          contract_type=contract_type or None,
                          limit=max(1, min(limit, 50)))


@tool
def place_index_option_paper_order(symbol: str, qty: int, side: str = "buy",
                                   limit_price: float | None = None,
                                   runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Place an idempotent supported index-option order in paper trading only."""
    from engine.brokers.index_options import submit_order

    context = _require_action(runtime)
    call_id = _call_id(runtime, "place_index_option_paper_order")
    client_order_id = _client_order_id(
        context, call_id, "place_index_option_paper_order"
    )
    _, action = _reserve_action(
        context, runtime, "place_index_option_paper_order",
        order_client_id=client_order_id,
    )
    if not action.created:
        return {"status": action.status, "client_order_id": action.order_client_id,
                "cached": True, "paper_only": True}
    client = _broker(context)
    try:
        result = submit_order(
            client.trading_client, symbol=symbol, qty=qty, side=side,
            limit_price=limit_price, client_order_id=client_order_id,
        )
    except Exception as exc:
        _finish_action(context, action.action_id, "failed")
        raise RuntimeError("The paper index-option order was not accepted.") from exc
    _finish_action(context, action.action_id, "completed")
    return {
        "status": str(result.get("status", "accepted")),
        "order_id": str(result.get("id", "")),
        "client_order_id": client_order_id,
        "paper_only": True,
        "cached": False,
    }


@tool
def queue_paper_session(strategy: str = "buy_the_dip",
                        symbols: list[str] | None = None,
                        duration_seconds: int = 3600,
                        runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Queue a cancellable paper-trading session after explicit user intent."""
    context = _require_action(runtime)
    _broker(context)  # prove owned credentials now; workers never fall back to env
    config = {
        "strategy": strategy[:64],
        "symbols": [_ticker(symbol) for symbol in (symbols or [])[:25]],
        "duration_seconds": max(30, min(int(duration_seconds), 604800)),
    }
    if not config["symbols"]:
        config.pop("symbols")
    return _enqueue(runtime, "queue_paper_session", "deepagent_paper", config)


@tool
def queue_paper_from_backtest(
    run_id: str,
    duration_seconds: int = 3600,
    runtime: ToolRuntime[DeepAgentContext] = None,
) -> dict:
    """Queue paper trading from an owned, completed, non-empty validated backtest."""
    context = _require_action(runtime)
    _broker(context)
    effective_account_id = _effective_account_id(context)
    with DatabasePool().get_session() as session:
        row = session.execute(text("""
            SELECT r.strategy, r.config, bs.params
            FROM alpatrade.runs r
            JOIN alpatrade.backtest_summaries bs
              ON bs.run_id = r.run_id AND bs.is_best = TRUE
            WHERE r.run_id = :rid AND r.user_id = :uid
              AND r.mode = 'backtest' AND r.status = 'completed'
              AND COALESCE(bs.total_trades, 0) > 0
              AND (r.account_id IS NULL OR r.account_id = CAST(:aid AS UUID))
              AND EXISTS (
                  SELECT 1 FROM alpatrade.validations v
                  WHERE v.run_id = r.run_id AND v.user_id = r.user_id
                    AND v.source = 'backtest'
                    AND v.status IN ('passed', 'corrected')
                    AND COALESCE(v.total_checked, 0) > 0
              )
            ORDER BY bs.created_at DESC LIMIT 1
        """), {
            "rid": run_id,
            "uid": context.user_id,
            "aid": effective_account_id,
        }).fetchone()
    if not row:
        raise ValueError(
            "backtest must be owned, completed, non-empty, and validated before paper trading"
        )
    stored_config = dict(row[1] or {}) if isinstance(row[1], dict) else {}
    best_params = dict(row[2] or {}) if isinstance(row[2], dict) else {}
    strategy_name = str(
        row[0] or stored_config.get("strategy") or "buy_the_dip"
    )
    if strategy_name != "buy_the_dip":
        raise ValueError(
            "paper-from-backtest currently supports only buy_the_dip; no session was queued"
        )
    if not best_params:
        raise ValueError("the validated backtest has no stored best parameters")
    config = {
        "strategy": strategy_name,
        "lookback": str(stored_config.get("lookback") or "3m")[:16],
        "duration_seconds": max(30, min(int(duration_seconds), 604800)),
        "approved_best_config": {"params": best_params},
        "source_backtest_run_id": str(run_id),
        "email_notifications": False,
    }
    symbols = best_params.get("symbols") or stored_config.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [item.strip() for item in symbols.split(",") if item.strip()]
    if symbols:
        config["symbols"] = [_ticker(symbol) for symbol in list(symbols)[:25]]
    return _enqueue(
        runtime, "queue_paper_from_backtest", "deepagent_paper", config
    )


@tool
def reconcile_account(window_days: int = 7,
                      runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Synchronously reconcile caller-owned DB records with the linked paper account."""
    from agents.reconcile_agent import ReconcileAgent
    from engine.auth import get_alpaca_keys

    context = _require_action(runtime)
    effective_account_id = _effective_account_id(context)
    keys = get_alpaca_keys(context.user_id or "", effective_account_id)
    if not keys:
        raise PermissionError("No owned linked Alpaca paper account is available.")
    return ReconcileAgent(
        user_id=context.user_id,
        account_id=effective_account_id,
        alpaca_api_key=keys[0],
        alpaca_secret_key=keys[1],
    ).run({"window_days": max(1, min(window_days, 90))})


@tool
def cancel_job(job_id: str,
               runtime: ToolRuntime[DeepAgentContext] = None) -> dict[str, Any]:
    """Cancel an owned queued job or signal an active paper session to stop safely."""
    from engine.autonomy import queue

    context = _require_action(runtime)
    cancelled = queue.cancel(job_id, context.user_id or "", context.account_id)
    return {"job_id": job_id, "status": "cancelled" if cancelled else "not_cancellable"}


@tool
def queue_full_cycle(strategy: str = "buy_the_dip", symbols: list[str] | None = None,
                     lookback: str = "3m", paper_duration_seconds: int = 3600,
                     runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Queue Backtest, Validate, Paper, Validate, Reconcile, and Report phases."""
    context = _require_action(runtime)
    _broker(context)
    config = {
        "strategy": strategy[:64],
        "symbols": [_ticker(symbol) for symbol in (symbols or [])[:25]],
        "lookback": lookback[:16],
        "duration_seconds": max(30, min(int(paper_duration_seconds), 604800)),
        "validation_gate": "strict",
    }
    if not config["symbols"]:
        config.pop("symbols")
    return _enqueue(runtime, "queue_full_cycle", "deepagent_full", config)


@tool
def queue_autonomy_scout(strategy: str = "btd", limit: int = 5,
                         runtime: ToolRuntime[DeepAgentContext] = None) -> dict:
    """Queue the paper-only autonomous scout and risk-gated workflow."""
    context = _require_action(runtime)
    _broker(context)
    config = {"strategy": strategy[:64], "limit": max(1, min(limit, 20))}
    return _enqueue(runtime, "queue_autonomy_scout", "full", config)


COORDINATOR_TOOLS = (
    get_market_price,
    search_market_news,
    list_linked_accounts,
    get_account_summary,
    get_positions,
    get_recent_runs,
    get_job_status,
    get_latest_advisor_report,
)

MARKET_RESEARCH_TOOLS = (
    get_market_price, search_market_news, get_analyst_ratings, get_company_profile,
    get_company_financials, get_market_movers, compare_valuation,
    get_premarket_movers, run_alpha_growth, run_alpha_value, run_alpha_compare,
    get_sec_filings, get_sec_financial_facts, get_sector_performance,
    get_ipo_market, get_ipo_pipeline, get_top_funds, get_activist_filings,
    get_press_releases, get_spacs, get_prediction_research,
)

PORTFOLIO_TOOLS = (
    list_linked_accounts, get_account_summary, get_positions, get_recent_runs,
    get_recent_trades, get_run_report, get_strategy_rankings, get_pnl_summary,
    get_job_status, get_job_events, get_job_results,
    get_latest_advisor_report, get_advisor_history,
)

STRATEGY_TOOLS = (
    queue_backtest, queue_advisor_backtest, validate_run, compare_strategy_results,
    get_recent_runs, get_run_report, get_job_status, get_job_events, get_job_results,
)

PAPER_TRADING_TOOLS = (
    place_paper_order, list_index_option_contracts, place_index_option_paper_order,
    queue_paper_session, queue_paper_from_backtest, reconcile_account, cancel_job,
    get_account_summary,
    get_positions, get_job_status, get_job_events,
    get_job_results,
)

ORCHESTRATOR_TOOLS = (
    queue_full_cycle, queue_autonomy_scout, cancel_job, get_job_status,
    get_job_events, get_job_results, get_run_report,
)

ADVISOR_TOOLS = (
    get_latest_advisor_report,
    get_advisor_history,
)


def advisor_subagent_spec(*, include_report_tools: bool = True) -> dict[str, Any]:
    """Return the read-only advisor used by interactive and scheduled DeepAgents."""
    return {
        "name": "trading-advisor",
        "description": (
            "Read-only daily paper-strategy and risk advisor grounded in persisted reports."
        ),
        "system_prompt": (
            "You are the tenant-scoped trading advisor. Review paper strategy and risk "
            "evidence, never issue instrument-level buy/sell calls, and never claim an "
            "action occurred. When JSON evidence and allowed candidate IDs are supplied, "
            "use only those facts and IDs; never invent parameter values or causal claims. "
            "Copy a selected candidate's supplied rationale exactly into its explanation. "
            "For review or urgent evidence, rank every supplied candidate exactly once. "
            "Always distinguish broker-account P&L from AlpaTrade-attributed P&L and explain "
            "why no parameter change is justified when no candidate is eligible. When "
            "presenting a persisted report, include its account name, session date, evidence "
            "window, data-quality warnings, approval requirement, and paper-trading disclaimer."
        ),
        "tools": ADVISOR_TOOLS if include_report_tools else (),
    }


def specialist_subagents() -> list[dict[str, Any]]:
    """Return the only native subagents available to the coordinator."""
    common = (
        "Never expose credentials, raw exceptions, or cross-tenant data. "
        "All execution is paper-only. Use tools for facts; do not invent results."
    )
    return [
        {
            "name": "market-research",
            "description": "Public market, company, SEC, institutional, IPO, and prediction research.",
            "system_prompt": (
                f"You are the market research specialist. {common} For premarket work, "
                "separate observed facts, stored catalyst evidence, watch conditions, and "
                "liquidity or gap-reversal risks. Do not provide trade calls, levels, or instructions."
            ),
            "tools": MARKET_RESEARCH_TOOLS,
        },
        {
            "name": "portfolio-analyst",
            "description": "Caller-owned account, positions, trades, P&L, reports, runs, and jobs.",
            "system_prompt": f"You are the tenant-scoped portfolio analyst. {common}",
            "tools": PORTFOLIO_TOOLS,
        },
        {
            "name": "strategy-lab",
            "description": "Queue backtests, validate owned runs, and compare strategy results.",
            "system_prompt": f"You are the strategy lab specialist. {common}",
            "tools": STRATEGY_TOOLS,
        },
        {
            "name": "paper-trader",
            "description": "Paper-only equities/index-options actions, sessions, reconciliation, and monitoring.",
            "system_prompt": f"You are the paper-trading specialist. {common}",
            "tools": PAPER_TRADING_TOOLS,
        },
        {
            "name": "orchestrator",
            "description": "Queue and inspect the full multi-agent workflow and autonomy scout.",
            "system_prompt": f"You coordinate durable paper-only workflows. {common}",
            "tools": ORCHESTRATOR_TOOLS,
        },
        advisor_subagent_spec(),
    ]


def public_research_tools() -> tuple[Any, ...]:
    """Anonymous compatibility chat receives no tenant or action tools."""
    return MARKET_RESEARCH_TOOLS

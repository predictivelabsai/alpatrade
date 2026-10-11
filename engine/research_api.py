"""Mobile research routes sharing the web application's canonical services."""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from engine.leaderboard import perf, store
from engine.publicmarkets import hedge_funds as hf


class StrategyInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    skill_md: str = Field(default="", max_length=60000)
    author_name: str = Field(default="", max_length=60)
    is_public: bool = False


class StrategyView(BaseModel):
    id: int
    name: str
    description: str | None = None
    skill_md: str | None = None
    kind: str | None = None
    source: str | None = None
    source_url: str | None = None
    is_public: bool | None = None
    cloned_from_id: int | None = None
    author: str
    metrics: dict[str, Any]
    methodology: str
    rank: int | None = None
    is_owner: bool = False


class StrategyList(BaseModel):
    strategies: list[StrategyView]
    total: int | None = None


class StrategyId(BaseModel):
    id: int


class CloneResult(StrategyId):
    created: bool


class BacktestJob(BaseModel):
    job_id: str


class BacktestStatus(BaseModel):
    state: Literal["running", "done", "error"]
    message: str | None = None
    markdown: str | None = None
    strategy_id: int


class FundScreen(BaseModel):
    rows: list[dict[str, Any]]
    period: str
    periods: list[dict[str, Any]]
    holds_unmapped: bool = False


class FundPerformance(BaseModel):
    funds: list[dict[str, Any]]
    labels: list[str]
    spy: dict[str, Any] = Field(default_factory=dict)
    computed_at: str | None = None
    method: Literal["quarter_end", "follow_filing"]
    note: str


def strategy_payload(row):
    # Explicit allowlist: no owner IDs, email addresses or broker account data.
    metrics = perf.strategy_metrics(row)
    return {**{k: row.get(k) for k in (
        "id", "name", "description", "skill_md", "kind", "source", "source_url",
        "is_public", "cloned_from_id")}, "author": store.author_of(row),
        "metrics": metrics, "methodology": perf.annualised_tip(metrics)}


def research_router(require_user, optional_user):
    router = APIRouter(prefix="/v2", tags=["research"])

    @router.get("/leaderboard", response_model=StrategyList)
    def leaderboard(q: str = Query("", max_length=160),
                    kind: Literal["", "live", "backtest"] = "",
                    limit: int = Query(100, ge=1, le=200)):
        rows = [strategy_payload(row) for row in store.list_public()]
        rows.sort(key=lambda row: (perf.rank_key(row["metrics"]), row["id"]))
        rows = [dict(row, rank=i + 1) for i, row in enumerate(rows)]
        rows = [row for row in rows if (not kind or row["kind"] == kind) and
                q.casefold() in f'{row["name"]} {row["description"]} {row["author"]}'.casefold()]
        return {"strategies": rows[:limit], "total": len(rows)}

    @router.get("/strategies", response_model=StrategyList)
    def mine(user=Depends(require_user)):
        return {"strategies": [strategy_payload(r) for r in store.list_for_user(user["user_id"])]}

    @router.get("/strategies/{sid}", response_model=StrategyView)
    def strategy(sid: int, user=Depends(optional_user)):
        row = store.get_visible(sid, user["user_id"] if user else None)
        if not row:
            raise HTTPException(404, "Strategy not found")
        return dict(strategy_payload(row), is_owner=bool(user and row["user_id"] == str(user["user_id"])))

    @router.post("/strategies", status_code=201, response_model=StrategyId)
    def create(body: StrategyInput, user=Depends(require_user)):
        try:
            sid = store.create(user["user_id"], **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": sid}

    @router.put("/strategies/{sid}")
    def update(sid: int, body: StrategyInput, user=Depends(require_user)):
        try:
            updated = store.update(sid, user["user_id"], **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not updated:
            raise HTTPException(404, "Strategy not found")
        return {"id": sid}

    @router.delete("/strategies/{sid}")
    def delete(sid: int, user=Depends(require_user)):
        if not store.delete(sid, user["user_id"]):
            raise HTTPException(404, "Strategy not found")
        return {"deleted": True}

    @router.post("/strategies/{sid}/clone", response_model=CloneResult)
    def clone(sid: int, user=Depends(require_user)):
        from engine.leaderboard.clone_bt import clone_strategy
        result = clone_strategy(sid, user)
        if result is None:
            raise HTTPException(404, "Strategy not found")
        return {"id": result[0], "created": result[1]}

    @router.post("/strategies/{sid}/backtest", status_code=202, response_model=BacktestJob)
    def backtest(sid: int, user=Depends(require_user)):
        from engine.leaderboard.clone_bt import start_backtest
        row = store.get(sid)
        if not row or row["user_id"] != str(user["user_id"]):
            raise HTTPException(404, "Strategy not found")
        return {"job_id": start_backtest(sid, str(user["user_id"]))}

    @router.get("/strategy-backtests/{job_id}", response_model=BacktestStatus)
    def backtest_status(job_id: str, user=Depends(require_user)):
        from engine.leaderboard.clone_bt import JOBS
        job = JOBS.get(job_id)
        if not job or job["key"].split(":", 1)[0] != str(user["user_id"]):
            raise HTTPException(404, "Backtest not found")
        return {key: job.get(key) for key in ("state", "message", "markdown", "strategy_id")}

    @router.get("/hedge-funds", response_model=FundScreen)
    def funds(q: str = Query("", max_length=160), period: str = "",
              min_aum: Literal["", "100m", "1b", "10b", "100b", "lt100m"] = "",
              pos: Literal["", "concentrated", "focused", "diversified", "broad"] = "",
              rtype: Literal["holdings", "holdings_only", "combination", "notice", "any"] = "holdings",
              holds: str = Query("", max_length=16), perf_only: bool = False,
              sort: Literal["aum", "positions", "name", "filed", "ttm"] = "aum",
              limit: int = Query(50, ge=1, le=200), user=Depends(require_user)):
        periods = hf.filing_periods()
        result = hf.screen_13f(period=period or hf.default_period(periods), q=q,
                              min_aum=min_aum, pos=pos, rtype=rtype, holds=holds,
                              perf_only=perf_only, sort=sort, limit=limit)
        return dict(result, periods=periods)

    @router.get("/hedge-funds/performance", response_model=FundPerformance)
    def performance(method: Literal["quarter_end", "follow_filing"] = "quarter_end",
                    user=Depends(require_user)):
        return dict(hf.performance_rows(method), method=method,
                    note="Estimated from 13F holdings; not reported fund performance.")

    @router.get("/hedge-funds/activists")
    def activists(ticker: str = Query("", max_length=16),
                  limit: int = Query(25, ge=1, le=100), user=Depends(require_user)):
        return {"filings": hf.activist_filings(ticker=ticker, limit=limit)}

    @router.get("/ipos")
    def ipos(limit: int = Query(100, ge=1, le=300), user=Depends(require_user)):
        from engine.publicmarkets.ipo import ipo_map_data
        return ipo_map_data(limit)

    @router.get("/ipos/pipeline")
    def pipeline(limit: int = Query(100, ge=1, le=200), user=Depends(require_user)):
        from engine.publicmarkets.ipo import ipo_pipeline_data
        return {"ipos": ipo_pipeline_data(limit)}

    return router

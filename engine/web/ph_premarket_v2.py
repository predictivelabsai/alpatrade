"""Premarket research views and HTTP endpoints for the migrated service."""
from __future__ import annotations

from fasthtml.common import A, Div, H1, Input, Label, Link, Nav, Option, P, Script, Select, Span, Button
from starlette.requests import Request
from starlette.responses import JSONResponse

from engine import premarket_data as data
from engine.web.ph_layout import page


def screen(user: dict | None, view: str = "overview", ticker: str = ""):
    if not data.enabled():
        from starlette.responses import RedirectResponse
        return RedirectResponse("/premarket", status_code=302)
    tabs = [("Overview", "/premarket", "overview"), ("Sector Details", "/premarket/sectors", "sectors"),
            ("Historical Data", "/premarket/history", "history"), ("Find a Stock", "/premarket/stocks", "search")]
    title = {"overview": "Premarket", "sectors": "Sector details", "history": "Historical premarket",
             "search": "Find a stock", "stock": ticker.upper()}.get(view, "Premarket")
    body = Div(
        Div(H1(title), P("US stocks before the opening bell", cls="pmv-sub"), cls="pmv-heading"),
        Nav(*[A(label, href=href, cls="active" if key == view else "",
                aria_current="page" if key == view else None) for label, href, key in tabs],
            aria_label="Premarket research", cls="pmv-tabs"),
        Div(Label("Trading date", Input(type="date", id="pmv-date", max=data.now_et().date().isoformat())),
            Label("Sector", Select(Option("All sectors", value=""), id="pmv-sector"), id="pmv-sector-label"),
            Label("Top movers", Select(*[Option(str(i), value=str(i), selected=i == 10) for i in range(3, 26)],
                                       id="pmv-limit"), id="pmv-limit-label"),
            Label("Ticker or company", Input(type="search", id="pmv-search", placeholder="Search companies",
                                             autocomplete="off"), id="pmv-search-label"),
            Button("Refresh data", id="pmv-refresh", type="button", cls="pmv-button"),
            cls="pmv-controls"),
        Div("Loading premarket research…", id="pmv-status", role="status", aria_live="polite"),
        Div(id="pmv-notices"), Div(id="pmv-content", aria_busy="true"),
        id="premarket-v2", cls="pmv", data_view=view, data_ticker=ticker.upper(),
        data_signed_in="true" if user else "false", data_today=data.now_et().date().isoformat(),
    )
    return page("premarket", Link(rel="stylesheet", href="/static/premarket.css?v=0.27.0"), body,
                Script(src="/static/premarket.js?v=0.27.0", defer=True), user=user,
                title=f"{title} · AlpaTrade", right_news=False)


def response_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, LookupError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    if isinstance(exc, PermissionError):
        return JSONResponse({"error": str(exc)}, status_code=403)
    return JSONResponse({"error": "Premarket research is temporarily unavailable. Try again shortly."}, status_code=503)


def public_payload(report: dict, limit: int = 10) -> dict:
    from engine.premarket import _json_safe, top_movers
    # Full narratives and minute bars are loaded only on a stock-detail page.
    def compact(value):
        if isinstance(value, dict):
            return {key: compact(item) for key, item in value.items()
                    if key not in {"rows", "history", "ai_reasoning", "ai_sources", "catalysts"}}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value
    return _json_safe(compact({**report, "top": top_movers(report, min(max(limit, 1), 25))}))


def detail_payload(payload: dict) -> dict:
    from engine.premarket import _json_safe
    from engine.premarket_analysis import markdown_html, safe_url
    for analysis in payload.get("analyses", []):
        analysis["html"] = markdown_html(analysis["text"])
        analysis["sources"] = [source for source in analysis.get("sources", []) if safe_url(source.get("url"))]
    return _json_safe(payload)


def register(app, rt, resolve_user):
    @rt("/premarket/sectors", methods=["GET"])
    def sectors(session):
        return screen(resolve_user(session), "sectors")

    @rt("/premarket/history", methods=["GET"])
    def history(session):
        return screen(resolve_user(session), "history")

    @rt("/premarket/stocks", methods=["GET"])
    def stocks(session):
        return screen(resolve_user(session), "search")

    @rt("/premarket/stocks/{ticker}", methods=["GET"])
    def stock(ticker: str, session):
        return screen(resolve_user(session), "stock", ticker)

    @rt("/premarket/companies", methods=["GET"])
    def companies(q: str = ""):
        if not data.enabled():
            return JSONResponse({"error": "The migrated screener is not enabled."}, status_code=404)
        try:
            return JSONResponse({"rows": data.search_companies(q)})
        except Exception as exc:
            return response_error(exc)

    @rt("/premarket/stocks/{ticker}/data", methods=["GET"])
    def stock_data(ticker: str, date: str = "", run_id: str = ""):
        if not data.enabled():
            return JSONResponse({"error": "The migrated screener is not enabled."}, status_code=404)
        try:
            if run_id:
                from engine.premarket import flatten
                report = data.report_by_run(run_id)
                stock = next((row for row in flatten(report) if row["ticker"] == ticker.upper()), None)
                if stock is None:
                    raise LookupError("Stock not found in this scan.")
                payload = {"stock": stock, "trading_date": stock.get("scan_date", date),
                           "history": stock.get("history", []), "analyses": [], "can_analyze": False,
                           "notices": ["Showing the original saved scan; its prices and timestamps are preserved."]}
            else:
                payload = data.stock_detail(ticker, date)
            return JSONResponse(detail_payload(payload))
        except Exception as exc:
            return response_error(exc)

    @app.post("/premarket/stocks/{ticker}/analysis")
    async def analysis(request: Request):
        if not data.enabled():
            return JSONResponse({"error": "The migrated screener is not enabled."}, status_code=404)
        user = resolve_user(request.session)
        if not user:
            return JSONResponse({"error": "Sign in to generate commentary.", "signin": "/signin"}, status_code=401)
        # JSON-only requests plus same-origin validation protect session-funded actions.
        from urllib.parse import urlsplit
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"error": "Cross-origin requests are not allowed."}, status_code=403)
        if "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"error": "Send a JSON request."}, status_code=415)
        try:
            import asyncio
            from engine.premarket_jobs import request_analysis
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("date"), str) or not body["date"]:
                raise ValueError("A trading date is required.")
            result = await asyncio.to_thread(request_analysis, request.path_params["ticker"],
                                             body["date"], str(user["user_id"]))
            return JSONResponse(result, status_code=200 if result["status"] == "completed" else 202)
        except Exception as exc:
            return response_error(exc)

    @rt("/premarket/jobs/{job_id}", methods=["GET"])
    def job_status(job_id: str):
        if not data.enabled():
            return JSONResponse({"error": "The migrated screener is not enabled."}, status_code=404)
        try:
            from engine.premarket_jobs import public_job
            return JSONResponse(public_job(job_id))
        except Exception as exc:
            return response_error(exc)

    return ["/premarket/sectors", "/premarket/history", "/premarket/stocks", "/premarket/stocks/{ticker}",
            "/premarket/companies", "/premarket/stocks/{ticker}/data",
            "/premarket/stocks/{ticker}/analysis", "/premarket/jobs/{job_id}"]

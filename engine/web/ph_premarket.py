"""Compatibility routes for the canonical Research premarket experience."""
from __future__ import annotations

from starlette.responses import JSONResponse, RedirectResponse


def _payload(report, limit: int = 10):
    """Retain the old helper shape for callers that already hold a report."""
    if not report:
        return {
            "error": "No scheduler premarket snapshot is available.",
            "summary": {},
            "sectors": {},
            "top": {"gainers": [], "fallers": [], "movers": []},
        }
    if report.get("top"):
        result = dict(report)
        result["top"] = {
            key: list(report["top"].get(key, []))[:max(1, min(limit, 50))]
            for key in ("gainers", "fallers", "movers")
        }
        return result
    from engine.premarket import top_movers
    return {**report, "top": top_movers(report, max(1, min(limit, 50)))}


def register(app, rt):
    @rt("/premarket", methods=["GET"])
    def premarket_get():
        return RedirectResponse("/research/premarket", status_code=308)

    @rt("/premarket/data", methods=["GET"])
    def premarket_data(
        limit: int = 10,
        date: str = "",
        sector: str = "",
        ticker: str = "",
        chart: str = "auto",
    ):
        from engine.research.premarket import (
            PremarketValidationError,
            build_chart_payload,
            read_premarket,
        )

        try:
            snapshot = read_premarket(
                selected_date=date or None,
                sector=sector or None,
                ticker=ticker or None,
                top_n=limit,
            )
            return JSONResponse({
                **snapshot,
                "chart": build_chart_payload(snapshot, chart),
            })
        except PremarketValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception:  # noqa: BLE001
            return JSONResponse(
                {"error": "Premarket scheduler data is unavailable."}, status_code=503,
            )

    @app.post("/premarket/scan")
    async def premarket_scan():
        return JSONResponse(
            {
                "error": "scheduler_managed",
                "message": "Premarket snapshots are refreshed only by the Finespresso scheduler.",
            },
            status_code=409,
        )

    return ["/premarket", "/premarket/data", "/premarket/scan"]

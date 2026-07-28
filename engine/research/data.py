"""Read-only, schema-qualified access to the shared Finespresso data."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from math import sqrt
from typing import Any

from sqlalchemy import text

from engine.db.pool import DatabasePool
from engine.research.events import normalize_event


def _rows(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    with DatabasePool().get_session() as session:
        return [dict(r) for r in session.execute(text(sql), params or {}).mappings()]


def relation_exists(name: str) -> bool:
    rows = _rows("""SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema='public' AND table_name=:name
    ) AS present""", {"name": name})
    return bool(rows and rows[0]["present"])


def premarket_runs(limit: int = 30) -> list[dict]:
    return _rows("""SELECT run_id, timestamp, scan_type, total_stocks_scanned,
        total_up_movements, total_down_movements
        FROM public.premarket_scan_runs ORDER BY timestamp DESC LIMIT :limit""",
                 {"limit": max(1, min(limit, 100))})


def premarket_snapshot(run_id: str | None = None, limit: int = 1000) -> list[dict]:
    clause = "r.run_id=:run_id" if run_id else (
        "r.run_id=(SELECT run_id FROM public.premarket_scan_runs ORDER BY timestamp DESC LIMIT 1)"
    )
    return _rows(f"""SELECT r.ticker, r.company_name, r.sector, r.industry, r.prev_close,
        r.premarket_close, r.movement_abs, r.movement_pct, r.premarket_high,
        r.premarket_low, r.ai_reasoning, r.ai_sources, r.history, r.data_source, r.timestamp
        FROM public.premarket_scan_results r WHERE {clause}
        ORDER BY ABS(r.movement_pct) DESC NULLS LAST LIMIT :limit""",
                 {"run_id": run_id, "limit": max(1, min(limit, 2500))})


def news_feed(*, market: str = "", publisher: str = "", ticker: str = "",
              days: int = 7, limit: int = 100) -> list[dict]:
    market_publishers = {
        "nordics": "%country_%", "euronext": "%euronext%", "baltics": "%baltic%",
        "biotech": "%biotech%", "us": "%globenewswire%",
    }
    conditions = ["COALESCE(n.published_date_gmt,n.published_date) >= NOW()-(:days * INTERVAL '1 day')"]
    params: dict[str, Any] = {"days": max(1, min(days, 3650)), "limit": max(1, min(limit, 500))}
    if market.lower() in market_publishers:
        conditions.append("LOWER(COALESCE(n.publisher,'')) LIKE :market")
        params["market"] = market_publishers[market.lower()]
    if publisher:
        conditions.append("LOWER(COALESCE(n.publisher,'')) LIKE :publisher")
        params["publisher"] = f"%{publisher.lower()}%"
    if ticker:
        conditions.append("UPPER(COALESCE(n.ticker,n.yf_ticker,''))=:ticker")
        params["ticker"] = ticker.upper()
    return _rows(f"""SELECT n.id, COALESCE(n.title_en,n.title) title, n.link, n.company,
        COALESCE(n.published_date_gmt,n.published_date) published, n.event, n.industry,
        n.publisher, COALESCE(n.ticker,n.yf_ticker) ticker, n.predicted_side,
        COALESCE(n.llm_predicted_move,n.predicted_move) predicted_move
        FROM public.news n WHERE {' AND '.join(conditions)}
        ORDER BY COALESCE(n.published_date_gmt,n.published_date) DESC LIMIT :limit""", params)


def correlation_data(industry: str = "", event: str = "", limit: int = 20000) -> list[dict]:
    rows = _rows("""SELECT n.event, n.industry, COALESCE(n.llm_predicted_move,n.predicted_move) predicted,
        pm.nextday_price_change_percentage actual
        FROM public.news n JOIN public.price_moves_data pm ON pm.news_id=n.id
        WHERE n.event IS NOT NULL
          AND COALESCE(n.llm_predicted_move,n.predicted_move) IS NOT NULL
          AND pm.nextday_price_change_percentage IS NOT NULL
        LIMIT :limit""", {"limit": max(1, min(limit, 100000))})
    for row in rows:
        row["normalized_event"] = normalize_event(row["event"])
    if industry:
        rows = [r for r in rows if (r["industry"] or "") == industry]
    if event:
        rows = [r for r in rows if r["normalized_event"] == event]
    return rows


def _corr(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den = sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def correlation_summary(industry: str = "", event: str = "", min_samples: int = 5) -> dict:
    rows = correlation_data(industry, event)
    pairs = [(float(r["predicted"]), float(r["actual"])) for r in rows]
    grouped: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for row, pair in zip(rows, pairs):
        grouped[(row["normalized_event"], row["industry"] or "Unknown")].append(pair)
    cells = [{"event": key[0], "industry": key[1], "count": len(values),
              "correlation": _corr(values)}
             for key, values in grouped.items() if len(values) >= max(2, min_samples)]
    return {
        "count": len(pairs), "correlation": _corr(pairs),
        "mae": sum(abs(x - y) for x, y in pairs) / len(pairs) if pairs else None,
        "points": [{"event": r["normalized_event"], "industry": r["industry"] or "Unknown",
                    "predicted": float(r["predicted"]), "actual": float(r["actual"])} for r in rows],
        "matrix": cells,
        "events": sorted({r["normalized_event"] for r in rows}),
        "industries": sorted({r["industry"] or "Unknown" for r in rows}),
    }


def model_results() -> dict:
    binary = _rows("""SELECT event, model_id, accuracy, precision, recall, f1, test_sample,
        cv_folds, model_type, model_category, version FROM public.classifier_predictions
        ORDER BY accuracy DESC NULLS LAST""") if relation_exists("classifier_predictions") else []
    regression = _rows("""SELECT event, model_id, mae, r2, rmse, test_sample, cv_folds,
        model_type, model_category, version FROM public.regressor_predictions
        ORDER BY r2 DESC NULLS LAST""") if relation_exists("regressor_predictions") else []
    return {"binary": binary, "regression": regression}


def news_timing(days: int = 30, market: str = "") -> dict:
    rows = news_feed(days=days, market=market, limit=500)
    hours = [0] * 24
    sessions = {"Premarket": 0, "Regular": 0, "After-hours": 0}
    for row in rows:
        dt = row["published"]
        if not dt:
            continue
        hours[dt.hour] += 1
        label = "Premarket" if dt.hour < 9 else ("Regular" if dt.hour < 16 else "After-hours")
        sessions[label] += 1
    return {"hours": hours, "sessions": sessions, "count": len(rows), "days": days}

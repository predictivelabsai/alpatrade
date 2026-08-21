"""Read-only Premarket Agent over scheduler-owned normalized snapshots."""
from __future__ import annotations

from datetime import date

from engine.research.premarket import (
    SchedulerManagedError,
    build_chart_payload,
    commentary_markdown,
    read_premarket,
    report_markdown,
)


class PremarketAgent:
    """Expose ranked scheduler snapshots without refreshing or trading."""

    name = "Premarket Agent"

    def run(
        self,
        refresh: bool = False,
        limit: int = 10,
        date: date | str | None = None,
        sector: str | None = None,
        ticker: str | None = None,
        chart: str = "auto",
    ) -> dict:
        if refresh:
            raise SchedulerManagedError()
        snapshot = read_premarket(
            selected_date=date,
            sector=sector,
            ticker=ticker,
            top_n=limit,
        )
        return {
            "agent": self.name,
            "status": snapshot["status"],
            "report": snapshot,
            "top": snapshot["top"],
            "effective_date": snapshot["effective_date"],
            "as_of": snapshot["as_of"],
            "freshness": snapshot["freshness"],
            "commentary": commentary_markdown(snapshot),
            "chart": build_chart_payload(snapshot, chart),
        }

    def report(
        self,
        limit: int = 8,
        date: date | str | None = None,
        sector: str | None = None,
        ticker: str | None = None,
        chart: str = "auto",
        refresh: bool = False,
    ) -> str:
        if refresh:
            raise SchedulerManagedError()
        snapshot = read_premarket(
            selected_date=date,
            sector=sector,
            ticker=ticker,
            top_n=limit,
        )
        return report_markdown(snapshot, chart)

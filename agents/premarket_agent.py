"""Read-only premarket intelligence agent."""
from __future__ import annotations

from engine.premarket import latest_report, scan_premarket, summary_markdown, top_movers


class PremarketAgent:
    """Owns premarket scans and exposes their ranked intelligence."""

    name = "Premarket Agent"

    def run(self, refresh: bool = False, limit: int = 10) -> dict:
        report = scan_premarket(top_n=limit) if refresh else latest_report()
        return {
            "agent": self.name,
            "status": "complete" if report else "no_data",
            "report": report,
            "top": top_movers(report, limit) if report else {
                "gainers": [], "fallers": [], "movers": [],
            },
        }

    def report(self, limit: int = 8) -> str:
        return summary_markdown(limit)

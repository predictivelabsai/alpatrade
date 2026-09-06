"""Small shared primitives for resilient, data-dense FastHTML tables."""
from __future__ import annotations

from fasthtml.common import Div, P


def responsive_table(table, *, label: str = "Results"):
    """Contain wide tables on phones while preserving desktop table semantics."""
    return Div(table, cls="data-table-scroll", role="region", tabindex="0",
               aria_label=label)


def empty_state(message: str, *, action: str = "Adjust the filters and try again."):
    """A consistent, actionable empty state for public-market data screens."""
    return Div(P(message, cls="data-empty-title"), P(action, cls="data-empty-help"),
               cls="data-empty", role="status", aria_live="polite")

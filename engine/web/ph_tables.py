"""Small shared primitives for resilient, data-dense FastHTML tables."""
from __future__ import annotations

from fasthtml.common import A, Details, Div, P, Span, Summary


def responsive_table(table, *, label: str = "Results", mobile_cards: bool = False):
    """Contain wide tables on phones while preserving desktop table semantics."""
    cls = "data-table-scroll mobile-card-table" if mobile_cards else "data-table-scroll"
    return Div(table, cls=cls, role="region", tabindex="0",
               aria_label=label)


def empty_state(message: str, *, action: str = "Adjust the filters and try again."):
    """A consistent, actionable empty state for public-market data screens."""
    return Div(P(message, cls="data-empty-title"), P(action, cls="data-empty-help"),
               cls="data-empty", role="status", aria_live="polite")


def research_card(*, title: str, meta: str, details: str = "", href: str = ""):
    """A touch-friendly mobile summary with secondary research on demand."""
    # Keep the whole summary as a dependable disclosure target on touch devices.
    # The source link appears in the expanded content instead of intercepting a tap.
    title_node = Span(title)
    detail_nodes = [P(details, cls="research-card-detail")] if details else []
    if href:
        detail_nodes.append(A("Open source", href=href, target="_blank", rel="noopener", cls="research-card-link"))
    return Details(Summary(Div(title_node, Span(meta, cls="research-card-meta"), cls="research-card-summary")),
                   Div(*detail_nodes, cls="research-card-body"), cls="research-card")


def research_cards(cards):
    return Div(*cards, cls="mobile-research-cards", aria_label="Research results")

"""SPAC screener — reads the shared liquidround.spac_data table.

Trust size, NAV premium, target, status per SPAC. AlpaTrade consumes it read-only.
"""
from __future__ import annotations

from sqlalchemy import text

from engine.db.pool import DatabasePool


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def spac_list(status: str = "", limit: int = 100) -> list[dict]:
    """SPACs, optionally filtered by status, ordered by trust size."""
    where, params = ["1=1"], {"lim": limit}
    if status:
        where.append("status ILIKE :st")
        params["st"] = f"%{status}%"
    with DatabasePool().get_session() as s:
        rows = s.execute(text(f"""
            SELECT ticker, company_name, sponsor, status, trust_size, trust_per_share,
                   current_price, nav_premium_pct, target_name, target_sector, warrant_ticker
            FROM liquidround.spac_data
            WHERE {' AND '.join(where)}
            ORDER BY trust_size DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [{"ticker": r[0], "company": r[1], "sponsor": r[2], "status": r[3],
             "trust_size": _f(r[4]), "trust_per_share": _f(r[5]), "price": _f(r[6]),
             "nav_premium_pct": _f(r[7]), "target": r[8], "target_sector": r[9],
             "warrant": r[10]} for r in rows]


def spac_summary(limit: int = 15) -> str:
    rows = spac_list(limit=limit)
    if not rows:
        return "# SPACs\n\nNo SPAC data available."

    def _b(v):
        return f"${v/1e6:.0f}M" if v else "—"
    md = ["# SPACs — trust, status, targets", "",
          "| Ticker | Sponsor | Status | Trust | NAV prem. | Target |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        prem = f"{r['nav_premium_pct']:+.1f}%" if r["nav_premium_pct"] is not None else "—"
        md.append(f"| {r['ticker'] or ''} | {(r['sponsor'] or '')[:20]} | {r['status'] or ''} | "
                  f"{_b(r['trust_size'])} | {prem} | {(r['target'] or '—')[:24]} |")
    return "\n".join(md)

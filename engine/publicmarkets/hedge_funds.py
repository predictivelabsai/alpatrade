"""Hedge-fund / institutional 13F tools.

Reads the shared hedgefolio schema (13F coverpage / summarypage / submission /
per-security infotable for ~11k filers, plus activist 13D filings) and the
alpatrade.hf13f_* tables (EDGAR-ingested holdings for a curated fund set, CUSIP ->
ticker map, cached 13F-implied performance; see sql/38_hedge_fund_13f.sql).
We surface: top managers by AUM, fund search, a 13F filer screener (period,
AUM, positions, report type, holds-ticker), 13F-implied returns, and activist filings.
"""
from __future__ import annotations

from functools import lru_cache
import math
import re

from sqlalchemy import text

from engine.db.pool import DatabasePool


def _f(v):
    try:
        value = float(v)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return 0.0


def top_funds(limit: int = 40) -> list[dict]:
    """Largest institutional managers by latest-quarter 13F portfolio value."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (cp.filingmanager_name)
                   cp.filingmanager_name, sp.table_value_total, sp.table_entry_total,
                   cp.report_calendar_or_quarter
            FROM hedgefolio.coverpage cp
            JOIN hedgefolio.summarypage sp USING (accession_number)
            WHERE sp.table_value_total IS NOT NULL AND sp.table_value_total > 0
            ORDER BY cp.filingmanager_name, cp.report_calendar_or_quarter DESC
        """)).fetchall()
    funds = [{"name": r[0], "value": _f(r[1]), "holdings": int(_f(r[2]) or 0), "period": str(r[3] or "")}
             for r in rows]
    funds.sort(key=lambda f: (f["value"] is not None, f["value"] or 0.0), reverse=True)
    return funds[:limit]


def fund_search(query: str, limit: int = 20) -> list[dict]:
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (cp.filingmanager_name)
                   cp.filingmanager_name, sp.table_value_total, sp.table_entry_total,
                   cp.report_calendar_or_quarter
            FROM hedgefolio.coverpage cp
            JOIN hedgefolio.summarypage sp USING (accession_number)
            WHERE cp.filingmanager_name ILIKE :q AND sp.table_value_total IS NOT NULL
            ORDER BY cp.filingmanager_name, cp.report_calendar_or_quarter DESC
            LIMIT :lim
        """), {"q": f"%{query}%", "lim": limit}).fetchall()
    return [{"name": r[0], "value": _f(r[1]), "holdings": int(_f(r[2]) or 0), "period": str(r[3] or "")}
            for r in rows]


def _ticker_for_cik(cik: str | None) -> str:
    """Resolve a subject CIK through the SEC's cached company ticker list."""
    if not cik:
        return ""
    try:
        from engine.publicmarkets.edgar import _ticker_to_cik_map
        normalized = str(int(cik)).zfill(10)
        return next((ticker for ticker, value in _ticker_to_cik_map().items()
                     if value == normalized), "")
    except Exception:  # noqa: BLE001 - a missing ticker must not hide the filing
        return ""


_SUBJECT_NAME_RE = re.compile(
    r"SUBJECT COMPANY:.*?COMPANY CONFORMED NAME:\s*(?P<name>[^\r\n]+)", re.DOTALL)
_SUBJECT_CIK_RE = re.compile(
    r"SUBJECT COMPANY:.*?CENTRAL INDEX KEY:\s*(?P<cik>\d+)", re.DOTALL)
_FILER_NAME_RE = re.compile(
    r"FILED BY:.*?COMPANY CONFORMED NAME:\s*(?P<name>[^\r\n]+)", re.DOTALL)
_ACCEPTED_RE = re.compile(r"ACCEPTANCE-DATETIME(?:>|:)\s*(?P<value>\d{14})")


@lru_cache(maxsize=512)
def _filing_metadata(url: str) -> dict[str, str]:
    """Read only an EDGAR document header for missing subject/time metadata."""
    if not url:
        return {}
    try:
        from engine.publicmarkets.edgar import _get
        response = _get(url, headers={"Accept": "text/plain", "Range": "bytes=0-16383"})
        header = response.content.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - surface the database row even if EDGAR is busy
        return {}
    name = _SUBJECT_NAME_RE.search(header)
    cik = _SUBJECT_CIK_RE.search(header)
    filer = _FILER_NAME_RE.search(header)
    accepted = _ACCEPTED_RE.search(header)
    timestamp = accepted.group("value") if accepted else ""
    return {"subject": name.group("name").strip() if name else "",
            "subject_cik": cik.group("cik") if cik else "",
            "filer": filer.group("name").strip() if filer else "",
            "filed_at": (f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} "
                         f"{timestamp[8:10]}:{timestamp[10:12]} ET") if timestamp else ""}


def activist_filings(ticker: str = "", form: str = "", limit: int = 25,
                     sort: str = "latest") -> list[dict]:
    """Recent activist / 13D filings, enriched from their SEC document headers."""
    where = "WHERE is_activist = TRUE"
    # Fetch extra candidates for ticker filtering because legacy rows often have
    # no populated subject_ticker.  The document-header cache makes repeats cheap.
    params: dict = {"lim": max(50, min(limit * 4 if ticker else limit, 100))}
    if form:
        where += " AND form_type = :form"
        params["form"] = form
    with DatabasePool().get_session() as s:
        rows = s.execute(text(f"""
            SELECT filer_name, subject_name, subject_ticker, subject_cik, form_type, filing_date, filing_url
            FROM hedgefolio.activist_filing {where}
            ORDER BY filing_date DESC LIMIT :lim
        """), params).fetchall()
    filings = []
    for row in rows:
        metadata = _filing_metadata(row[6])
        subject_cik = row[3] or metadata.get("subject_cik", "")
        subject = row[1] or metadata.get("subject", "")
        subject_ticker = row[2] or _ticker_for_cik(subject_cik)
        filings.append({"filer": metadata.get("filer") or row[0], "subject": subject, "ticker": subject_ticker,
                        "form": row[4], "date": str(row[5] or ""),
                        "filed_at": metadata.get("filed_at") or str(row[5] or ""), "url": row[6]})
    if ticker:
        filings = [filing for filing in filings if filing["ticker"] == ticker.upper().strip()]
    if sort == "oldest":
        filings.sort(key=lambda filing: filing["filed_at"])
    elif sort == "target":
        filings.sort(key=lambda filing: (filing["subject"] or "").lower())
    elif sort == "filer":
        filings.sort(key=lambda filing: (filing["filer"] or "").lower())
    else:
        filings.sort(key=lambda filing: filing["filed_at"], reverse=True)
    return filings[:limit]


# --------------------------------------------------------------------------- 13F screener

AUM_BUCKETS = {"": (None, None), "100m": (1e8, None), "1b": (1e9, None),
               "10b": (1e10, None), "100b": (1e11, None), "lt100m": (None, 1e8)}
POSITION_BUCKETS = {"": (None, None), "concentrated": (1, 20), "focused": (21, 100),
                    "diversified": (101, 500), "broad": (501, None)}
REPORT_TYPES = {"holdings": ("13F HOLDINGS REPORT", "13F COMBINATION REPORT"),
                "holdings_only": ("13F HOLDINGS REPORT",),
                "combination": ("13F COMBINATION REPORT",),
                "notice": ("13F NOTICE",),
                "any": ("13F HOLDINGS REPORT", "13F COMBINATION REPORT", "13F NOTICE")}
SCREEN_SORTS = ("aum", "positions", "name", "filed", "ttm")
METHOD_LABELS_UI = {"quarter_end": "13F-implied (held from quarter end)",
                    "follow_filing": "Follow-the-filing (bought day after filing)"}


def filing_periods(min_filers: int = 1) -> list[dict]:
    """13F report quarters available in hedgefolio, newest first, with filer counts."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT report_calendar_or_quarter, COUNT(*) FROM hedgefolio.coverpage
            WHERE report_calendar_or_quarter IS NOT NULL
            GROUP BY 1 HAVING COUNT(*) >= :m ORDER BY 1 DESC
        """), {"m": min_filers}).fetchall()
    return [{"period": str(r[0]), "filers": int(r[1])} for r in rows]


def default_period(periods: list[dict]) -> str:
    """Latest quarter with broad coverage (the dataset lags; partial quarters are thin)."""
    for p in periods:
        if p["filers"] >= 1000:
            return p["period"]
    return periods[0]["period"] if periods else ""


def cusip_variants(cusips) -> list[str]:
    """Stored CUSIPs are sometimes missing leading zeros — match both forms."""
    out = set()
    for c in cusips:
        if c:
            out.add(c)
            out.add(c.lstrip("0") or c)
    return sorted(out)


def cusips_for_ticker(ticker: str) -> list[str]:
    t = (ticker or "").upper().strip().replace(".", "-").replace("/", "-")
    if not t:
        return []
    try:
        with DatabasePool().get_session() as s:
            rows = s.execute(text("""SELECT cusip FROM alpatrade.hf13f_cusip_map
                                     WHERE ticker = :t AND status = 'mapped'"""), {"t": t}).scalars().all()
    except Exception:  # noqa: BLE001 - table may not be migrated yet
        return []
    return cusip_variants(rows)


def build_screen_sql(q: str = "", min_aum: str = "", pos: str = "", rtype: str = "holdings",
                     holds_cusips: list[str] | None = None, perf_ciks: list[str] | None = None,
                     sort: str = "aum") -> tuple[str, dict]:
    """SQL + params for the 13F filer screener (one row per filer CIK for :period).

    Duplicate filings for a period (amendments) collapse to the original 13F-HR,
    else the latest amendment."""
    where, params = [], {}
    lo, hi = AUM_BUCKETS.get(min_aum, (None, None))
    if lo is not None:
        where.append("f.value >= :aum_lo")
        params["aum_lo"] = lo
    if hi is not None:
        where.append("COALESCE(f.value, 0) < :aum_hi")
        params["aum_hi"] = hi
    plo, phi = POSITION_BUCKETS.get(pos, (None, None))
    if plo is not None:
        where.append("f.positions >= :pos_lo")
        params["pos_lo"] = plo
    if phi is not None:
        where.append("f.positions <= :pos_hi")
        params["pos_hi"] = phi
    if q:
        where.append("f.name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if holds_cusips is not None:
        where.append("""EXISTS (SELECT 1 FROM hedgefolio.infotable i
                        WHERE i.accession_number = f.accession_number AND i.cusip = ANY(:cusips)
                          AND COALESCE(i.put_call, '') = '')""")
        params["cusips"] = list(holds_cusips) or ["__none__"]
    if perf_ciks is not None:
        where.append("f.cik = ANY(:perf_ciks)")
        params["perf_ciks"] = list(perf_ciks) or ["__none__"]
    params["rtypes"] = list(REPORT_TYPES.get(rtype, REPORT_TYPES["holdings"]))
    order = {"aum": "f.value DESC NULLS LAST", "positions": "f.positions DESC NULLS LAST",
             "name": "f.name ASC", "filed": "f.filing_date DESC NULLS LAST"}.get(sort, "f.value DESC NULLS LAST")
    sql = f"""
        WITH f AS (
            SELECT DISTINCT ON (s.cik) s.cik, cp.accession_number, cp.filingmanager_name AS name,
                   cp.report_calendar_or_quarter AS period, s.filing_date, s.submission_type,
                   cp.report_type, sp.table_value_total AS value, sp.table_entry_total AS positions
            FROM hedgefolio.coverpage cp
            JOIN hedgefolio.submission s USING (accession_number)
            LEFT JOIN hedgefolio.summarypage sp USING (accession_number)
            WHERE cp.report_calendar_or_quarter = :period AND cp.report_type = ANY(:rtypes)
            ORDER BY s.cik, (s.submission_type IN ('13F-HR', '13F-NT')) DESC, s.filing_date DESC
        )
        SELECT f.cik, f.accession_number, f.name, f.period, f.filing_date, f.submission_type,
               f.report_type, f.value, f.positions
        FROM f {("WHERE " + " AND ".join(where)) if where else ""}
        ORDER BY {order} LIMIT :lim"""
    return sql, params


def _thousands_candidates(rows) -> list[str]:
    """Only small average positions (< $2M) can be $-thousand reports in disguise;
    skipping the big filers keeps the median check cheap (BlackRock has 50k rows)."""
    out = []
    for accession, value, positions in rows:
        if value is not None and positions and float(value) / int(positions) < 2_000_000:
            out.append(accession)
    return out


def _thousands_flags(accessions: list[str]) -> set[str]:
    """Accessions whose values look reported in $ thousands (median value/share < $0.50)."""
    if not accessions:
        return set()
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT accession_number,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY value::float / NULLIF(ssh_prn_amt, 0))
            FROM hedgefolio.infotable
            WHERE accession_number = ANY(:a) AND ssh_prn_amt_type = 'SH'
              AND COALESCE(put_call, '') = '' AND ssh_prn_amt > 0
            GROUP BY accession_number
        """), {"a": accessions}).fetchall()
    return {r[0] for r in rows if r[1] is not None and r[1] < 0.5}


def screen_13f(period: str = "", q: str = "", min_aum: str = "", pos: str = "",
               rtype: str = "holdings", holds: str = "", perf_only: bool = False,
               sort: str = "aum", limit: int = 50) -> dict:
    """Run the 13F screener. Returns {rows, period, holds_unmapped, error}."""
    perf = performance_by_cik()
    holds_cusips = cusips_for_ticker(holds) if holds else None
    result = {"rows": [], "period": period, "holds_unmapped": bool(holds) and not holds_cusips}
    if holds and not holds_cusips:
        return result
    perf_ciks = list(perf) if (perf_only or sort == "ttm") else None
    sql, params = build_screen_sql(q, min_aum, pos, rtype, holds_cusips, perf_ciks,
                                   sort if sort in SCREEN_SORTS else "aum")
    params.update({"period": period, "lim": max(1, min(int(limit), 200))})
    with DatabasePool().get_session() as s:
        rows = s.execute(text(sql), params).fetchall()
    thousands = _thousands_flags(_thousands_candidates((r[1], r[7], r[8]) for r in rows))
    out = []
    for r in rows:
        value = _f(r[7]) if r[7] is not None else None
        scaled = r[1] in thousands
        if scaled and value is not None:
            value *= 1000
        p = perf.get(r[0], {})
        out.append({"cik": r[0], "name": r[2], "period": str(r[3] or ""), "filed": str(r[4] or ""),
                    "form": r[5], "report_type": r[6], "value": value, "value_scaled": scaled,
                    "positions": int(r[8]) if r[8] is not None else None,
                    "ttm": p.get("TTM"), "last_year": p.get("last_year")})
    if sort == "ttm":
        out.sort(key=lambda x: ((x["ttm"] or {}).get("fund") is None,
                                -((x["ttm"] or {}).get("fund") or 0.0)))
    result["rows"] = out
    return result

# --------------------------------------------------------------------------- 13F-implied performance


def performance_rows(method: str = "quarter_end") -> dict:
    """Cached 13F-implied returns for the curated funds (alpatrade.hf13f_performance).

    Returns {funds: [{cik, name, latest_period, latest_filed, value, positions,
    returns: {label: {fund, spy, coverage}}}], labels: [...], spy: {label: r},
    computed_at}. Empty when the job hasn't run / table is missing."""
    try:
        with DatabasePool().get_session() as s:
            prow = s.execute(text("""
                SELECT p.cik, fu.display_name, p.period_label, p.period_kind, p.fund_return,
                       p.spy_return, p.coverage, p.start_date, p.end_date, p.computed_at
                FROM alpatrade.hf13f_performance p JOIN alpatrade.hf13f_funds fu USING (cik)
                WHERE p.method = :m ORDER BY fu.display_name, p.start_date
            """), {"m": method}).fetchall()
            latest = s.execute(text("""
                SELECT DISTINCT ON (cik) cik, period_of_report, filing_date, value_total_usd, n_positions
                FROM alpatrade.hf13f_filings WHERE form_type = '13F-HR'
                ORDER BY cik, period_of_report DESC, value_total_usd DESC NULLS LAST, filing_date DESC
            """)).fetchall()
            funds_all = s.execute(text(
                "SELECT cik, display_name FROM alpatrade.hf13f_funds ORDER BY display_name")).fetchall()
    except Exception:  # noqa: BLE001 - migration not applied yet -> section shows n/a
        return {"funds": [], "labels": [], "spy": {}, "computed_at": None}
    latest_by = {r[0]: r for r in latest}
    funds: dict[str, dict] = {}
    for cik, name in funds_all:
        lr = latest_by.get(cik)
        funds[cik] = {"cik": cik, "name": name, "returns": {},
                      "latest_period": str(lr[1]) if lr else "", "latest_filed": str(lr[2]) if lr else "",
                      "value": _f(lr[3]) if lr and lr[3] is not None else None,
                      "positions": int(lr[4]) if lr and lr[4] is not None else None}
    labels: dict[str, tuple] = {}
    spy: dict[str, float | None] = {}
    computed_at = None
    for cik, _name, label, kind, fr, sr, cov, sd, ed, cat in prow:
        funds[cik]["returns"][label] = {"fund": fr, "spy": sr, "coverage": cov,
                                        "start": str(sd), "end": str(ed)}
        order = (0 if kind == "year" else 1 if kind == "ytd" else 2, label)
        labels[label] = order
        if sr is not None:
            spy.setdefault(label, sr)
        computed_at = max(computed_at, cat) if computed_at else cat
    ordered = [lbl for lbl, _ in sorted(labels.items(), key=lambda kv: kv[1])]
    return {"funds": list(funds.values()), "labels": ordered, "spy": spy,
            "computed_at": str(computed_at)[:16] if computed_at else None}


def performance_by_cik(method: str = "quarter_end") -> dict[str, dict]:
    """cik -> {'TTM': {...}, 'last_year': {...,'label'}} for the screener columns."""
    data = performance_rows(method)
    years = [lbl for lbl in data["labels"] if lbl.isdigit()]
    last_year = years[-1] if years else None
    out = {}
    for f in data["funds"]:
        if not any(r.get("fund") is not None for r in f["returns"].values()):
            continue  # no estimate yet -> not "with 13F-implied returns"
        entry = {}
        if "TTM" in f["returns"]:
            entry["TTM"] = f["returns"]["TTM"]
        if last_year and last_year in f["returns"]:
            entry["last_year"] = dict(f["returns"][last_year], label=last_year)
        out[f["cik"]] = entry
    return out


def _b(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v/1e12:.2f}T" if v >= 1e12 else (f"${v/1e9:.1f}B" if v >= 1e9 else f"${v/1e6:.0f}M")


def top_funds_summary(limit: int = 15) -> str:
    funds = top_funds(limit)
    if not funds:
        return "# Hedge funds\n\nNo 13F data available."
    md = ["# Top institutional managers (13F AUM)", "",
          "| # | Manager | Portfolio value | Holdings | Period |",
          "|---|---|---|---|---|"]
    for i, f in enumerate(funds, 1):
        md.append(f"| {i} | {f['name'][:38]} | {_b(f['value'])} | {f['holdings']:,} | {f['period'][:10]} |")
    return "\n".join(md)


def activist_summary(ticker: str = "", limit: int = 15) -> str:
    rows = activist_filings(ticker, limit)
    if not rows:
        return f"# Activist filings{f' — {ticker.upper()}' if ticker else ''}\n\nNone found."
    md = [f"# Activist filings{f' — {ticker.upper()}' if ticker else ''}", "",
          "| Date | Filer | Target | Ticker | Form |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['date'][:10]} | {(r['filer'] or '')[:30]} | {(r['subject'] or '')[:26]} | "
                  f"{r['ticker'] or ''} | {r['form'] or ''} |")
    return "\n".join(md)

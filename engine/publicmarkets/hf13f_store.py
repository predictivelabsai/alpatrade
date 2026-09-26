"""DB layer + batch job for 13F holdings and 13F-implied performance.

Tables: sql/38_hedge_fund_13f.sql. Run via scripts/hedge_fund_13f.py.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import logging

import pandas as pd
from sqlalchemy import text

from engine.db.pool import DatabasePool
from engine.publicmarkets import hf13f
from engine.publicmarkets.hf13f_perf import Filing, Position, avg_coverage, daily_returns, summarize

log = logging.getLogger(__name__)


def _session():
    return DatabasePool().get_session()

# --------------------------------------------------------------------------- ingest


def ingest_fund(cik: str, display_name: str, since: date, refresh: bool = False) -> dict:
    """Pull every 13F-HR(/A) with period >= since for one fund (plus its affiliate
    filers in hf13f.ALT_CIKS) into alpatrade.hf13f_*."""
    cik10 = str(int(cik)).zfill(10)
    name, refs = hf13f.list_13f_filings(cik, since)
    for alt in hf13f.ALT_CIKS.get(cik10, []):
        refs += hf13f.list_13f_filings(alt, since)[1]
    with _session() as s:
        s.execute(text("""
            INSERT INTO alpatrade.hf13f_funds (cik, name, display_name, is_starter)
            VALUES (:c, :n, :d, TRUE)
            ON CONFLICT (cik) DO UPDATE SET name = EXCLUDED.name, display_name = EXCLUDED.display_name
        """), {"c": cik10, "n": name or display_name, "d": display_name})
        have = set(s.execute(text(
            "SELECT accession_number FROM alpatrade.hf13f_filings WHERE cik = :c"),
            {"c": cik10}).scalars().all())
        s.commit()
    added = 0
    for ref in refs:
        if ref.accession in have and not refresh:
            continue
        try:
            amendment_type, url, rows = hf13f.fetch_filing(ref)
        except Exception as exc:  # noqa: BLE001 - keep going; report the gap
            log.warning("fetch failed %s %s: %s", cik10, ref.accession, exc)
            continue
        mult = hf13f.infer_value_multiplier(rows, ref.filing_date)
        total = sum(r["value"] for r in rows) * mult
        with _session() as s:
            s.execute(text("DELETE FROM alpatrade.hf13f_filings WHERE accession_number = :a"),
                      {"a": ref.accession})
            s.execute(text("""
                INSERT INTO alpatrade.hf13f_filings (accession_number, cik, form_type, amendment_type,
                    period_of_report, filing_date, value_multiplier, value_total_usd, n_positions,
                    info_table_url, filer_cik)
                VALUES (:a, :c, :f, :at, :p, :fd, :m, :t, :n, :u, :fc)
            """), {"a": ref.accession, "c": cik10, "fc": None if ref.cik == cik10 else ref.cik,
                   "f": ref.form_type, "at": amendment_type,
                   "p": ref.period_of_report, "fd": ref.filing_date, "m": mult, "t": total,
                   "n": len(rows), "u": url})
            if rows:
                # One round trip per filing (row-by-row executemany is far too slow
                # against the remote shared Postgres for 3k-position filers).
                s.execute(text("""
                    INSERT INTO alpatrade.hf13f_holdings (accession_number, row_no, cusip, issuer,
                        title_of_class, value_usd, shares, sh_prn_type, put_call)
                    SELECT :a, * FROM unnest(CAST(:i AS int[]), CAST(:cu AS text[]), CAST(:iss AS text[]),
                        CAST(:tc AS text[]), CAST(:v AS numeric[]), CAST(:sh AS numeric[]),
                        CAST(:st AS text[]), CAST(:pc AS text[]))
                """), {"a": ref.accession, "i": list(range(len(rows))),
                       "cu": [r["cusip"] for r in rows],
                       "iss": [(r["issuer"] or "")[:300] for r in rows],
                       "tc": [(r["title_of_class"] or "")[:120] for r in rows],
                       "v": [r["value"] * mult for r in rows], "sh": [r["shares"] for r in rows],
                       "st": [r["sh_prn_type"][:8] for r in rows], "pc": [r["put_call"] for r in rows]})
            s.commit()
        added += 1
    with _session() as s:
        s.execute(text("UPDATE alpatrade.hf13f_funds SET last_ingested_at = NOW() WHERE cik = :c"),
                  {"c": cik10})
        s.commit()
    return {"cik": cik10, "name": name, "filings_seen": len(refs), "filings_added": added}

# --------------------------------------------------------------------------- CUSIPs


def cusips_needing_map(extra_top_n: int = 0, retry_days: int = 30) -> list[str]:
    """Unmapped CUSIPs from starter holdings (+ optionally the N most widely held
    CUSIPs in the latest hedgefolio quarter, so the 'holds ticker' filter works)."""
    with _session() as s:
        cusips = set(s.execute(text("""
            SELECT DISTINCT h.cusip FROM alpatrade.hf13f_holdings h
            WHERE COALESCE(h.put_call, '') = '' AND COALESCE(h.sh_prn_type, 'SH') = 'SH'
        """)).scalars().all())
        if extra_top_n:
            period = s.execute(text("""
                SELECT report_calendar_or_quarter FROM hedgefolio.coverpage
                GROUP BY 1 HAVING COUNT(*) > 1000 ORDER BY 1 DESC LIMIT 1""")).scalar()
            if period:
                top = s.execute(text("""
                    SELECT i.cusip FROM hedgefolio.infotable i
                    JOIN hedgefolio.coverpage cp USING (accession_number)
                    WHERE cp.report_calendar_or_quarter = :p AND COALESCE(i.put_call, '') = ''
                    GROUP BY i.cusip ORDER BY COUNT(DISTINCT i.accession_number) DESC LIMIT :n
                """), {"p": period, "n": extra_top_n}).scalars().all()
                cusips |= {hf13f.normalize_cusip(c) for c in top if hf13f.normalize_cusip(c)}
        done = set(s.execute(text("""
            SELECT cusip FROM alpatrade.hf13f_cusip_map
            WHERE status = 'mapped' OR resolved_at > NOW() - make_interval(days => :d)
        """), {"d": retry_days}).scalars().all())
    return sorted(cusips - done)


def save_cusip_map(mapping: dict[str, dict]) -> int:
    if not mapping:
        return 0
    with _session() as s:
        s.execute(text("""
            INSERT INTO alpatrade.hf13f_cusip_map (cusip, ticker, name, security_type, status, resolved_at)
            VALUES (:c, :t, :n, :st, :s, NOW())
            ON CONFLICT (cusip) DO UPDATE SET ticker = EXCLUDED.ticker, name = EXCLUDED.name,
                security_type = EXCLUDED.security_type, status = EXCLUDED.status, resolved_at = NOW()
        """), [{"c": c, "t": m["ticker"], "n": (m["name"] or "")[:300] or None,
                "st": m["security_type"], "s": m["status"]} for c, m in mapping.items()])
        s.commit()
    return len(mapping)


def map_cusips(extra_top_n: int = 0, limit: int | None = None) -> dict:
    todo = cusips_needing_map(extra_top_n)
    if limit:
        todo = todo[:limit]
    mapped = 0
    for i in range(0, len(todo), 200):  # persist progressively
        res = hf13f.map_cusips_openfigi(todo[i:i + 200])
        save_cusip_map(res)
        mapped += sum(1 for v in res.values() if v["status"] == "mapped")
        log.info("cusip map %d/%d (mapped so far %d)", min(i + 200, len(todo)), len(todo), mapped)
    return {"requested": len(todo), "mapped": mapped, "issuer_fallback": issuer_prefix_fallback()}


NON_COMMON_CLASS_RX = r"\m(WTS?|WARR\w*|RIGHTS?|RTS?|UNITS?|PFD|PREF\w*|NOTES?|DEB\w*|BONDS?)\M|\*W"


def issuer_prefix_fallback() -> int:
    """Old CUSIPs (reverse splits, re-domiciles) stop resolving on OpenFIGI. When an
    unmapped common-share CUSIP shares its 6-char issuer id with a mapped one, reuse
    that ticker (Yahoo's adjusted history is continuous across the CUSIP change).
    Warrant/right/unit/preferred/note rows are never mapped this way."""
    with _session() as s:
        n = s.execute(text("""
            WITH src AS (
                SELECT DISTINCT ON (LEFT(cusip, 6)) LEFT(cusip, 6) AS issuer, ticker, name
                FROM alpatrade.hf13f_cusip_map
                WHERE status = 'mapped' AND source = 'openfigi' AND ticker IS NOT NULL
                ORDER BY LEFT(cusip, 6), cusip
            ), eligible AS (
                SELECT m.cusip FROM alpatrade.hf13f_cusip_map m
                WHERE m.status = 'unmapped'
                  AND NOT EXISTS (
                      SELECT 1 FROM alpatrade.hf13f_holdings h WHERE h.cusip = m.cusip
                        AND (h.title_of_class ~* :rx
                             OR COALESCE(h.put_call, '') <> ''))
            )
            UPDATE alpatrade.hf13f_cusip_map u
            SET ticker = src.ticker, name = src.name, status = 'mapped', source = 'issuer6', resolved_at = NOW()
            FROM src, eligible
            WHERE u.cusip = eligible.cusip AND LEFT(u.cusip, 6) = src.issuer
        """), {"rx": NON_COMMON_CLASS_RX}).rowcount
        s.commit()
    return int(n or 0)

# --------------------------------------------------------------------------- prices


def download_prices(tickers: list[str], start: date, end: date | None = None) -> pd.DataFrame:
    """Split/dividend-adjusted daily closes from Yahoo (yfinance), chunked."""
    import yfinance as yf
    frames = []
    tickers = sorted(set(tickers))
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        try:
            df = yf.download(chunk, start=start.isoformat(),
                             end=(end or date.today() + timedelta(days=1)).isoformat(),
                             auto_adjust=True, progress=False, threads=True, group_by="column")
        except Exception as exc:  # noqa: BLE001
            log.warning("yfinance chunk failed: %s", exc)
            continue
        if df is None or df.empty:
            continue
        close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(
            columns={"Close": chunk[0]})
        frames.append(close)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.sort_index()

# --------------------------------------------------------------------------- compute


def load_fund_filings(cik: str) -> dict[date, list[dict]]:
    """period -> list of filing dicts with mapped rows."""
    with _session() as s:
        frows = s.execute(text("""
            SELECT accession_number, form_type, amendment_type, period_of_report, filing_date,
                   COALESCE(filer_cik, cik)
            FROM alpatrade.hf13f_filings WHERE cik = :c ORDER BY period_of_report, filing_date
        """), {"c": cik}).fetchall()
        hrows = s.execute(text("""
            SELECT h.accession_number, h.cusip, h.value_usd, h.put_call, h.sh_prn_type, m.ticker
            FROM alpatrade.hf13f_holdings h
            JOIN alpatrade.hf13f_filings f USING (accession_number)
            LEFT JOIN alpatrade.hf13f_cusip_map m ON m.cusip = h.cusip AND m.status = 'mapped'
            WHERE f.cik = :c
        """), {"c": cik}).fetchall()
    by_acc: dict[str, list[dict]] = defaultdict(list)
    for a, cu, v, pc, st, t in hrows:
        by_acc[a].append({"cusip": cu, "value": float(v), "put_call": pc, "sh_prn_type": st,
                          "ticker": t})
    periods: dict[date, list[dict]] = defaultdict(list)
    for a, form, at, period, fdate, filer in frows:
        periods[period].append({"accession": a, "form_type": form, "amendment_type": at,
                                "filing_date": fdate, "filer": filer, "rows": by_acc.get(a, [])})
    return dict(periods)


def _long_value(rows: list[dict]) -> float:
    return sum(r["value"] for r in rows
               if not (r.get("put_call") or "") and (r.get("sh_prn_type") or "SH") == "SH")


def build_filings(periods: dict[date, list[dict]], method: str) -> list[Filing]:
    """One Filing per quarter. With affiliate filers, the larger long book wins."""
    out = []
    for period, all_fs in sorted(periods.items()):
        best = None
        for filer in sorted({f.get("filer") for f in all_fs}, key=str):
            fs = [f for f in all_fs if f.get("filer") == filer]
            originals = [f for f in fs if f["form_type"] == "13F-HR"]
            first_known = min(f["filing_date"] for f in (originals or fs))
            as_of = first_known if method == "follow_filing" else None
            rows = hf13f.effective_holdings(fs, as_of=as_of)
            if rows and (best is None or _long_value(rows) > best[0]):
                best = (_long_value(rows), first_known, rows)
        if best is None:
            continue
        _, first_known, rows = best
        out.append(Filing(period, first_known, [Position(r["cusip"], r["value"], r["ticker"],
                                                         r["put_call"], r["sh_prn_type"]) for r in rows]))
    return out


def cached_prices(tickers: list[str], start: date, cache_path: str | None) -> pd.DataFrame:
    """download_prices with an optional local pickle cache (dev reruns); only
    tickers missing from the cache are fetched, and the cache must be from today."""
    import os
    cached = None
    if cache_path and os.path.exists(cache_path):
        cached = pd.read_pickle(cache_path)
        if cached.empty or cached.index.min() > pd.Timestamp(start) or \
                date.fromtimestamp(os.path.getmtime(cache_path)) != date.today():
            cached = None
    missing = sorted(set(tickers) - set(cached.columns if cached is not None else []))
    fresh = download_prices(missing, start) if missing else pd.DataFrame()
    prices = fresh if cached is None else (cached if fresh.empty else cached.join(fresh, how="outer"))
    if cache_path and not prices.empty:
        # Remember tickers Yahoo had nothing for, so reruns don't refetch them.
        for t in missing:
            if t not in prices.columns:
                prices[t] = float("nan")
        prices.to_pickle(cache_path)
    return prices


def compute_performance(ciks: list[str] | None = None, prices: pd.DataFrame | None = None,
                        first_year: int | None = None, price_cache: str | None = None) -> dict:
    with _session() as s:
        funds = s.execute(text("SELECT cik, display_name FROM alpatrade.hf13f_funds ORDER BY cik")).fetchall()
    if ciks:
        funds = [f for f in funds if f[0] in ciks]
    per_fund = {}
    tickers = {"SPY"}
    earliest = date.today()
    for cik, name in funds:
        periods = load_fund_filings(cik)
        built = {m: build_filings(periods, m) for m in hf13f.METHODS}
        per_fund[cik] = (name, built)
        for fl in built.values():
            for f in fl:
                earliest = min(earliest, f.period_of_report)
                tickers |= {p.ticker for p in f.positions if p.ticker}
    if prices is None:
        prices = cached_prices(sorted(tickers), earliest - timedelta(days=10), price_cache)
    if "SPY" not in prices.columns:
        raise RuntimeError("SPY prices unavailable — cannot compute")
    report = {}
    for cik, (name, built) in per_fund.items():
        rows_out, periods_out = [], []
        for method, filings in built.items():
            if not filings:
                continue
            daily, periods = daily_returns(filings, prices, method)
            fy = first_year or (filings[0].period_of_report.year + 1)
            for r in summarize(daily, prices["SPY"], first_year=fy):
                cov, n = avg_coverage(periods, r["start"], r["end"])
                rows_out.append({"cik": cik, "m": method, "l": r["label"], "k": r["kind"],
                                 "s": r["start"], "e": r["end"], "f": r["fund"], "b": r["spy"],
                                 "cov": cov, "n": n})
            for p in periods:
                periods_out.append({"cik": cik, "m": method, "p": p.period_of_report, "s": p.start,
                                    "e": p.end, "f": p.fund_return, "b": p.spy_return,
                                    "cov": p.coverage, "np": p.n_priced, "n": p.n_positions})
        with _session() as s:
            s.execute(text("DELETE FROM alpatrade.hf13f_performance WHERE cik = :c"), {"c": cik})
            s.execute(text("DELETE FROM alpatrade.hf13f_period_returns WHERE cik = :c"), {"c": cik})
            if rows_out:
                s.execute(text("""
                    INSERT INTO alpatrade.hf13f_performance (cik, method, period_label, period_kind,
                        start_date, end_date, fund_return, spy_return, coverage, quarters_used)
                    VALUES (:cik, :m, :l, :k, :s, :e, :f, :b, :cov, :n)"""), rows_out)
            if periods_out:
                s.execute(text("""
                    INSERT INTO alpatrade.hf13f_period_returns (cik, method, period_of_report, start_date,
                        end_date, fund_return, spy_return, coverage, n_priced, n_positions)
                    VALUES (:cik, :m, :p, :s, :e, :f, :b, :cov, :np, :n)"""), periods_out)
            s.commit()
        report[name] = {r["l"]: (r["f"], r["b"]) for r in rows_out if r["m"] == "quarter_end"}
    return report

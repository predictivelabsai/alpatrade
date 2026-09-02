"""Public shareable backtest report pages (``/r/{id}``). register(app, rt).

Two data sources dispatch on the id, one page shape:

* a ``alpatrade.runs`` UUID → the grid-search backtest users produce in chat,
  rendered from ``backtest_summaries`` (is_best) / ``runs.results`` via
  :func:`engine.web.onboarding.best_backtest_for_run` plus the ``trades`` table;
* a ``backtest-results/<slug>/`` folder name → the methodology backtester's
  artifact folder, rendered as ``report.md`` (verbatim, client-side markdown)
  plus ``summary.json`` metric cards.

Pages are public and unlisted — uuids are unguessable, there is no nav entry,
and **no user identity ever reaches the page** (``user=None`` always; the
route never calls ``get_user_by_id``). The hypothetical-results disclosure is
imported verbatim from :mod:`engine.backtest.artifacts` and rendered twice.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from fastcore.xml import to_xml
from fasthtml.common import Div, NotStr, Style
from starlette.responses import HTMLResponse

from engine.web import onboarding
from engine.web.ph_layout import page

_CSS = """
.report{width:100%;max-width:900px;margin:0 auto;padding:1rem 1rem 3rem;overflow-y:auto}
.report h1{font-size:1.3rem;margin:.2rem 0 .15rem}
.report .r-sub{color:var(--ink-muted);font-size:.8rem;margin:0 0 .3rem}
.report .r-strap{color:var(--ink-dim);font-size:.78rem;margin:0 0 1rem}
.report .disc{border:1px solid var(--line-br);border-left:3px solid var(--accent);
 background:var(--bg-elev);border-radius:.5rem;padding:.7rem .9rem;font-size:.78rem;
 color:var(--ink-muted);margin:.8rem 0}
.report .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
 gap:.6rem;margin:1rem 0}
.report .card{background:var(--bg-elev);border:1px solid var(--line);border-radius:.55rem;
 padding:.6rem .7rem}
.report .card .k{display:block;font-size:.64rem;text-transform:uppercase;
 letter-spacing:.07em;color:var(--ink-dim)}
.report .card .v{font-size:1.02rem;font-weight:650;font-variant-numeric:tabular-nums}
.report .card .v.pos{color:#147a4b}.report .card .v.neg{color:#b43b35}
.report .meta{font-size:.8rem;color:var(--ink-muted);margin:.6rem 0}
.report .meta code{font-family:var(--font-mono);font-size:.74rem}
.report section{background:var(--bg-elev);border:1px solid var(--line);
 border-radius:.6rem;padding:.9rem 1rem;margin:1rem 0}
.report section h2{font-size:.95rem;margin:.1rem 0 .6rem}
.report .rpt-body{font-size:.86rem;line-height:1.55;color:var(--ink)}
.report .rpt-body pre{overflow-x:auto;background:var(--bg);border:1px solid var(--line);
 border-radius:.4rem;padding:.6rem;font-size:.76rem}
.report .rpt-body code{font-family:var(--font-mono);font-size:.8em}
.report .rpt-body table{border-collapse:collapse;width:100%;font-size:.8rem;margin:.6rem 0}
.report .rpt-body th,.report .rpt-body td{border:1px solid var(--line);
 padding:.35rem .5rem;text-align:left}
.report .rpt-body blockquote{border-left:3px solid var(--line-br);
 margin:.5rem 0;padding:.1rem 0 .1rem .8rem;color:var(--ink-muted)}
.report .trades{overflow-x:auto}
.report .trades table{width:100%;border-collapse:collapse;font-size:.8rem;
 font-variant-numeric:tabular-nums}
.report .trades th,.report .trades td{padding:.45rem .55rem;border-bottom:1px solid var(--line);
 text-align:left;white-space:nowrap}
.report .trades th{font-size:.64rem;text-transform:uppercase;letter-spacing:.07em;
 color:var(--ink-dim)}
.report .trades tr:last-child td{border-bottom:none}
.report .pos{color:#147a4b;font-weight:650}.report .neg{color:#b43b35;font-weight:650}
.report .r-missing{background:var(--bg-elev);border:1px solid var(--line);
 border-radius:.6rem;padding:2.2rem 1.4rem;text-align:center;color:var(--ink-muted)}
"""

_MAX_FILE_BYTES = 2_000_000
_TRADE_CAP = 50

# A uuid matches the folder-slug grammar too, so uuid dispatch comes first.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")

_METRIC_LABELS = (
    ("total_return", "Total return"),
    ("sharpe", "Sharpe"),
    ("sharpe_ratio", "Sharpe"),
    ("max_drawdown", "Max drawdown"),
    ("win_rate", "Win rate"),
    ("annualized_return", "Annualized"),
    ("total_trades", "Trades"),
)


def is_run_uuid(rid: str) -> bool:
    return bool(_UUID_RE.match(str(rid or "")))


def is_folder_slug(rid: str) -> bool:
    rid = str(rid or "")
    # A uuid also matches the slug grammar; uuid dispatch wins, so the slug
    # predicate excludes them to keep each predicate unambiguous.
    return ".." not in rid and bool(_SLUG_RE.match(rid)) \
        and not is_run_uuid(rid)


def _fmt_pct(value, *, signed=False) -> str:
    """Percent-format a value that is ALREADY in percent units."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    txt = f"{v:+.1f}%" if signed else f"{v:.1f}%"
    return txt


def _num(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _cards(metrics: dict, *, ratios: bool) -> str:
    """Metric cards from a metrics dict. ``ratios=True`` (the folder path)
    scales return/drawdown/win-rate ratios to percent; the DB path stores
    them as percents already (backtester_util multiplies by 100)."""
    out = ["<div class='cards'>"]
    seen = set()
    for key, label in _METRIC_LABELS:
        if key in seen or key not in metrics or metrics[key] is None:
            continue
        seen.add(key)
        value = metrics[key]
        if key == "total_trades":
            out.append(f"<div class='card'><span class='k'>{label}</span>"
                       f"<span class='v'>{_esc(value)}</span></div>")
        elif key in ("sharpe", "sharpe_ratio"):
            out.append(f"<div class='card'><span class='k'>{label}</span>"
                       f"<span class='v'>{_num(value)}</span></div>")
        elif key in ("total_return", "annualized_return", "max_drawdown",
                     "win_rate"):
            v = float(value) * 100 if ratios else float(value)
            cls = "neg" if key == "max_drawdown" or v < 0 else "pos"
            out.append(
                f"<div class='card'><span class='k'>{label}</span>"
                f"<span class='v {cls}'>{_fmt_pct(v, signed=True)}</span></div>")
    out.append("</div>")
    return "".join(out)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _trades_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    shown = rows[:_TRADE_CAP]
    trs = []
    for t in shown:
        pnl = t.get("pnl")
        try:
            pnl_cls = "pos" if float(pnl) >= 0 else "neg"
            pnl_txt = f"{float(pnl):+.2f}"
        except (TypeError, ValueError):
            pnl_cls, pnl_txt = "", "—"

        def fmt_price(p):
            try:
                return f"{float(p):.2f}"
            except (TypeError, ValueError):
                return "—"
        entered = str(t.get("entry_time") or "")[:16].replace("T", " ")
        trs.append(
            "<tr>"
            f"<td>{_esc(t.get('symbol'))}</td>"
            f"<td>{_esc(t.get('direction') or '')}</td>"
            f"<td class='num'>{_esc(t.get('shares'))}</td>"
            f"<td class='num'>{fmt_price(t.get('entry_price'))}</td>"
            f"<td class='num'>{fmt_price(t.get('exit_price'))}</td>"
            f"<td class='num'><span class='{pnl_cls}'>{pnl_txt}</span></td>"
            f"<td>{_esc(entered)}</td>"
            "</tr>")
    more = ""
    if len(rows) > _TRADE_CAP:
        more = (f"<p class='r-sub'>First {_TRADE_CAP} of {len(rows)} trades "
                "shown.</p>")
    return (
        "<section><h2>Trades</h2><div class='trades'><table>"
        "<tr><th>Symbol</th><th>Side</th><th>Shares</th><th>Entry</th>"
        "<th>Exit</th><th>P/L</th><th>Entered</th></tr>"
        + "".join(trs) + "</table></div>" + more + "</section>")


def _assumptions_block(cfg: dict) -> str:
    """What the grid path's ``runs.config`` actually carries, plus generic
    true sentences — never an assumption the run didn't make."""
    cfg = cfg if isinstance(cfg, dict) else {}
    bits = []
    if cfg.get("symbols"):
        bits.append("Symbols: " + ", ".join(str(s) for s in cfg["symbols"]))
    for key in ("lookback", "interval", "benchmark"):
        if cfg.get(key):
            bits.append(f"{key.replace('_', ' ').title()}: {cfg[key]}")
    sentences = (
        "Fills, fees and slippage are modeled by the backtest engine; results "
        "are simulated and do not reflect live execution.")
    return "".join(
        [f"<section><h2>Assumptions</h2><p class='rpt-body'>"]
        + [f"{_esc(b)}<br>" for b in bits]
        + [_esc(sentences), "</p></section>"])


def _md_payload(md: str) -> str:
    """Neutralize a markdown payload for embedding in a type="text/markdown"
    script tag: strip live-content vectors, then break any closing-script
    sequence so the browser cannot end the data block early."""
    md = re.sub(r"(?i)<script\b[^>]*>.*?</script\s*>", "", md or "", flags=re.S)
    md = re.sub(r"(?i)<script\b[^>]*>?", "", md)
    md = re.sub(r"(?i)javascript\s*:", "", md)
    return md.replace("</script", "<\\/script")


_MD_RUNNER = """
<script>
(function () {
  var el = document.getElementById('rpt-md');
  var body = document.getElementById('rpt-body');
  if (!el || !body) return;
  var md = el.textContent || '';
  if (window.marked && window.marked.parse) {
    try { body.innerHTML = window.marked.parse(md); return; } catch (e) {}
  }
  body.textContent = md;
})();
</script>
"""


def _report_shell(title: str, inner: str, md: str = "") -> str:
    """Common page top: heading, strapline, disclosure callout — and the
    markdown payload + client-side runner when ``md`` is provided."""
    from engine.backtest.artifacts import DISCLOSURE
    body = [
        f"<h1>{_esc(title)}</h1>",
        "<p class='r-sub'>Hypothetical historical simulation. Research and "
        "educational use only — not investment advice.</p>",
        f"<div class='disc marked'>{_esc_md_para(DISCLOSURE)}</div>",
    ]
    body.append(inner)
    if md:
        body.append(
            "<section><h2>Methodology report</h2>"
            "<div class='rpt-body marked' id='rpt-body'></div></section>"
            f"<script id='rpt-md' type='text/markdown'>{_md_payload(md)}</script>"
            + _MD_RUNNER)
    body.append(
        "<section><h2>Disclosure</h2>"
        f"<div class='rpt-body marked'>{_esc_md_para(DISCLOSURE)}</div></section>")
    return "".join(body)


def _esc_md_para(text: str) -> str:
    """Escape the disclosure for plain-HTML rendering (no markdown needed:
    it is one paragraph plus a bold lead)."""
    text = _esc(text).replace("\n\n", "<br><br>").replace("\n", "<br>")
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


_IDENTITY_KEYS = ("user_id", "email", "account_id", "owner", "token")


def _strip_identity(mapping: dict) -> dict:
    """Defense-in-depth: identity keys must never reach the public page."""
    return {k: v for k, v in mapping.items()
            if str(k).lower() not in _IDENTITY_KEYS}


def db_report_html(payload: dict | None) -> str:
    if not payload:
        return ""
    title = str(payload.get("strategy_slug") or payload.get("strategy")
                or "Backtest report")
    cfg = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    inner = [
        _cards(metrics, ratios=False),
        f"<p class='meta'>Parameters: <code>{_esc(onboarding.format_params(_strip_identity(params))) or '—'}</code></p>",
        _assumptions_block(_strip_identity(cfg)),
        _trades_table(payload.get("trades") or []),
    ]
    return _report_shell(title, "".join(inner))


def folder_report_html(payload: dict | None) -> str:
    if not payload:
        return ""
    summary = payload.get("summary") or {}
    core = (summary.get("reproducible_core") or {})
    metrics = dict(core.get("metrics") or {})
    rt = core.get("round_trip") or {}
    if rt.get("win_rate") is not None:
        metrics.setdefault("win_rate", rt.get("win_rate"))
    if rt.get("trades") is not None:
        metrics.setdefault("total_trades", rt.get("trades"))
    title = f"{summary.get('strategy_name') or 'Backtest'} — " \
            f"{summary.get('symbols') and ', '.join(summary['symbols']) or ''}".strip(" —")
    inner = [
        "<p class='meta'>"
        f"Period {_esc(str(summary.get('start') or '')[:10])} → "
        f"{_esc(str(summary.get('end') or '')[:10])} · "
        f"Interval {_esc(summary.get('timeframe') or '')} · "
        f"Initial cash {_esc(summary.get('initial_cash') or '')}"
        "</p>",
        _cards(metrics, ratios=True),
    ]
    assumptions = summary.get("assumptions") or []
    if assumptions:
        inner.append(
            "<section><h2>Assumptions</h2><p class='rpt-body'>"
            + "".join(_esc(a) + "<br>" for a in assumptions)
            + "</p></section>")
    return _report_shell(title, "".join(inner), md=payload.get("report_md") or "")


# ---------------------------------------------------------------------------
# IO layer — thin, failure-tolerant; every failure path is a 404.
# ---------------------------------------------------------------------------

_RUN_SQL = """
    SELECT run_id, strategy, strategy_slug, status, config, results,
           started_at, completed_at
    FROM alpatrade.runs
    WHERE run_id = :r AND mode = 'backtest'
"""

_SUMMARY_SQL = """
    SELECT params, total_return, total_pnl, win_rate, total_trades,
           sharpe_ratio, max_drawdown, annualized_return
    FROM alpatrade.backtest_summaries
    WHERE run_id = :r AND is_best
    ORDER BY created_at DESC
    LIMIT 1
"""

_TRADES_SQL = """
    SELECT symbol, direction, shares, entry_time, exit_time,
           entry_price, exit_price, pnl
    FROM alpatrade.trades
    WHERE run_id = :r AND trade_type = 'backtest'
    ORDER BY entry_time
    LIMIT :cap
"""


def _load_db_report(run_id: str) -> dict | None:
    """Public report payload for a grid-path run — mode='backtest' only
    (the gate against exposing paper runs), no user_id anywhere."""
    from sqlalchemy import text

    from utils.db.db_pool import DatabasePool
    try:
        with DatabasePool().get_session() as session:
            run = session.execute(
                text(_RUN_SQL), {"r": run_id}).mappings().first()
            if not run:
                return None
            payload = dict(run)
            summary = session.execute(
                text(_SUMMARY_SQL), {"r": run_id}).mappings().first()
            if summary and summary.get("total_return") is not None:
                payload["params"] = summary.get("params")
                payload["metrics"] = {
                    k: summary.get(k) for k in (
                        "total_return", "total_pnl", "win_rate",
                        "total_trades", "sharpe_ratio", "max_drawdown",
                        "annualized_return") if summary.get(k) is not None}
            payload["trades"] = [
                dict(t) for t in session.execute(
                    text(_TRADES_SQL),
                    {"r": run_id, "cap": _TRADE_CAP + 1}).mappings().all()]
        # Grid path without summaries rows → fall back to the helper that
        # unions the orchestrator's runs.results best_config shape.
        if not payload.get("metrics"):
            best = onboarding.best_backtest_for_run(run_id) or {}
            payload["params"] = payload.get("params") or best.get("params")
            payload["metrics"] = best
        cfg = payload.get("config")
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:  # noqa: BLE001
                cfg = {}
        payload["config"] = cfg if isinstance(cfg, dict) else {}
        params = payload.get("params")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:  # noqa: BLE001
                params = {}
        payload["params"] = params if isinstance(params, dict) else {}
        payload.pop("results", None)  # never rendered
        return payload
    except Exception:  # noqa: BLE001
        return None


def _read_capped(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _load_folder_report(rid: str, root: str | Path = "backtest-results") -> dict | None:
    """Read ONLY summary.json + report.md from one artifact folder, with a
    resolved-path containment check (the folder must be a direct child of
    root). raw/, normalized/ and the CSVs are never touched."""
    try:
        root_p = Path(root).resolve()
        target = (root_p / rid).resolve()
        if target.parent != root_p or not target.is_dir():
            return None
        summary_txt = _read_capped(target / "summary.json")
        if not summary_txt:
            return None
        summary = json.loads(summary_txt)
        if not isinstance(summary, dict):
            return None
        report_md = _read_capped(target / "report.md") or ""
        return {"summary": summary, "report_md": report_md}
    except Exception:  # noqa: BLE001
        return None


def _not_found(rid: str) -> HTMLResponse:
    body = Div(
        NotStr(
            "<h1>Report not found</h1>"
            "<p class='r-sub'>This report does not exist or is no longer "
            "shared. Links look like <code>/r/&lt;id&gt;</code> — check the "
            "link you were sent.</p>"),
        cls="report")
    page_html = page("backtests", Style(_CSS), body, user=None,
                     title="Report not found · AlpaTrade", right_news=False)
    return HTMLResponse(to_xml(page_html), status_code=404)


def register(app, rt):
    @rt("/r/{rid}", methods=["GET"])
    def report_get(rid: str):
        rid = str(rid or "")
        if is_run_uuid(rid):
            payload = _load_db_report(rid)
            if payload is None:
                return _not_found(rid)
            inner_html = db_report_html(payload)
        elif is_folder_slug(rid):
            payload = _load_folder_report(rid)
            if payload is None:
                return _not_found(rid)
            inner_html = folder_report_html(payload)
        else:
            return _not_found(rid)
        body = Div(NotStr(inner_html), cls="report")
        return page("backtests", Style(_CSS), body, user=None,
                    title="Backtest report · AlpaTrade", right_news=False)

    return ["/r/{rid}"]
"""Backtests & paper runs — user-scoped run history pages (``/backtests``, ``/paper``).

Phase 2 of the Start Here plan: the Trade section of the nav pointed at pages
that only described strategies; this gives those destinations a real surface.
One renderer, two tabs, driven by ``alpatrade.runs`` plus the best-variation
lookup in :mod:`engine.web.onboarding` (which already handles the two storage
paths: backtest_summaries rows and the orchestrator's runs.results JSON).
Read-only plus deploy CTAs — the page never mutates a run.
"""
from __future__ import annotations

import html
import json

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web import onboarding
from engine.web.ph_layout import page

_CSS = """
.runs{width:100%;max-width:1180px;margin:auto;padding:0 1rem 3rem}
.runs-head{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap;margin:.4rem 0 1rem}
.runs h1{font-size:1.35rem;margin:0}
.runs-head .muted{display:block;color:var(--ink-muted);font-size:.8rem}
.runs-tabs{display:flex;margin-left:auto}
.runs-tabs a{border:1px solid var(--line);background:var(--bg-elev);color:var(--ink-muted);
 border-radius:0;text-decoration:none;padding:.48rem .8rem;font-size:.8rem}
.runs-tabs a:first-child{border-radius:.45rem 0 0 .45rem}
.runs-tabs a:last-child{border-radius:0 .45rem .45rem 0}
.runs-tabs a.active{background:var(--accent);color:var(--bg-elev);border-color:var(--accent)}
.runs-tblwrap{overflow-x:auto;border:1px solid var(--line);border-radius:.65rem}
@media(max-width:720px){.runs-tblwrap{border-radius:.65rem}}
.runs table{width:100%;border-collapse:collapse;background:var(--bg-elev);
 font-size:.84rem;font-variant-numeric:tabular-nums}
.runs th,.runs td{padding:.6rem .7rem;border-bottom:1px solid var(--line);text-align:left;
 white-space:nowrap}
.runs th{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim)}
.runs tr:last-child td{border-bottom:none}
.runs td.num{text-align:right}
.runs .slug{font-family:var(--font-mono);font-size:.76rem;color:var(--ink)}
.runs .status{font-size:.72rem;border-radius:.9rem;padding:.15rem .55rem;
 border:1px solid var(--line-br);color:var(--ink-muted)}
.runs .status.running{border-color:var(--accent);color:var(--accent)}
.runs .status.stale,.runs .status.error,.runs .status.failed{border-color:#b43b35;color:#b43b35}
.runs .ret-pos{color:#147a4b;font-weight:650}.runs .ret-neg{color:#b43b35;font-weight:650}
.runs .empty{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;
 padding:2.2rem 1.4rem;text-align:center}
.runs .empty p{color:var(--ink-muted);font-size:.88rem}
.runs .deploy{display:inline-block;background:var(--accent);color:var(--bg-elev);
 text-decoration:none;border-radius:.4rem;padding:.42rem .7rem;font-size:.74rem;font-weight:650}
.runs .deploy:hover{background:var(--accent-deep);text-decoration:none}
.runs .run-id{font-family:var(--font-mono);font-size:.68rem;color:var(--ink-dim)}
.runs .share{color:var(--accent);text-decoration:none;font-size:.74rem;margin-right:.5rem}
.runs .share:hover{text-decoration:underline}
.runs .copy{border:1px solid var(--line);background:var(--bg-elev);color:var(--ink-muted);
 border-radius:.4rem;padding:.32rem .5rem;font-size:.7rem;cursor:pointer}
.runs .copy:hover{border-color:var(--accent);color:var(--accent)}
"""

_LIMIT = 25

_RUN_SQL = """
    SELECT r.run_id, r.mode, r.strategy, r.strategy_slug, r.status,
           r.started_at, r.completed_at,
           s.params, s.total_return, s.sharpe_ratio
    FROM alpatrade.runs r
    LEFT JOIN alpatrade.backtest_summaries s
           ON s.run_id = r.run_id AND s.is_best
    WHERE r.mode = :mode AND r.user_id = :uid
    ORDER BY r.created_at DESC
    LIMIT :limit
"""

_MODE_EMPTY = {
    "backtest": (
        "<p>No backtests yet. Run one from the <a href='/dashboard'>Start Here</a> card, "
        "or just say <i>backtest buy-the-dip on AAPL</i> in the chat composer.</p>"),
    "paper": (
        "<p>No paper runs yet. Backtest a strategy first — the deploy step appears on "
        "the <a href='/dashboard'>dashboard</a> and the <a href='/backtests'>backtests "
        "list</a> once a run exists.</p>"),
}


def _list_runs(mode: str, user_id: str) -> list[dict]:
    """The user's most recent runs of one mode, with best-variation params."""
    from sqlalchemy import text

    from utils.db.db_pool import DatabasePool
    try:
        with DatabasePool().get_session() as session:
            rows = session.execute(
                text(_RUN_SQL),
                {"mode": mode, "uid": user_id, "limit": _LIMIT},
            ).mappings().all()
            out = []
            for r in rows:
                row = dict(r)
                params = row.get("params")
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except Exception:  # noqa: BLE001
                        params = {}
                row["params"] = params if isinstance(params, dict) else {}
                # Orchestrator-path runs carry their best config in runs.results.
                if mode == "backtest" and not row["params"]:
                    fb = _best_from_results(str(row["run_id"]))
                    if fb:
                        row["params"] = fb
                out.append(row)
        return out
    except Exception:  # noqa: BLE001
        return []


def _best_from_results(run_id: str) -> dict:
    """Best-variation params from the orchestrator path's runs.results JSON."""
    from sqlalchemy import text

    from utils.db.db_pool import DatabasePool
    try:
        with DatabasePool().get_session() as session:
            r = session.execute(
                text("SELECT results FROM alpatrade.runs WHERE run_id = :r"),
                {"r": run_id},
            ).mappings().first()
        res = (r or {}).get("results")
        if not res:
            return {}
        if isinstance(res, str):
            res = json.loads(res)
        params = (res.get("best_config") or {}).get("params") or {}
        return params if isinstance(params, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _params_summary(params: dict) -> str:
    return onboarding.format_params(params)


def _bt_row(r: dict) -> str:
    params = r.get("params") or {}
    slug = str(r.get("strategy_slug") or r.get("strategy") or "backtest")
    status = html.escape(str(r.get("status") or "unknown"))
    started = str(r.get("started_at") or "")[:16].replace("T", " ")

    params_txt = _params_summary(params) if params else "—"
    ret = r.get("total_return")
    ret_html = '<span class="muted">—</span>'
    if ret is not None:
        cls = "ret-pos" if ret >= 0 else "ret-neg"
        ret_html = f"<span class='{cls}'>{ret:+.1f}%</span>"
    sharpe = r.get("sharpe_ratio")
    sh = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else "—"

    cmd = onboarding.paper_deploy_command({
        "strategy": r.get("strategy") or "",
        "params": params,
    })
    action = (f"<a class='deploy' href='{onboarding.autorun_url(cmd)}'>Deploy to paper</a>"
              if cmd else "")
    share = (f"<a class='share' href='/r/{html.escape(str(r['run_id']))}'>Share</a>"
             f"<button class='copy' type='button' "
             f"onclick=\"navigator.clipboard.writeText(location.origin+'/r/"
             f"{html.escape(str(r['run_id']))}');this.textContent='Copied'\">Copy link</button>")
    return (
        f"<tr><td class='slug'>{html.escape(str(r.get('strategy_slug') or r.get('strategy') or 'backtest'))}</td>"
        f"<td class='num'>{ret_html}</td><td class='num'>{sh}</td>"
        f"<td>{params_txt}</td><td>{html.escape(started)}</td>"
        f"<td><span class='status {status}'>{status}</span></td><td>{action}</td>"
        f"<td>{share}</td>"
        f"<td><span class='run-id'>{html.escape(str(r['run_id'])[:8])}</span></td></tr>")


def _paper_row(r: dict) -> str:
    status = html.escape(str(r.get("status") or "unknown"))
    started = str(r.get("started_at") or "")[:16].replace("T", " ")
    ended = str(r.get("completed_at") or "")[:16].replace("T", " ")
    return (
        f"<tr><td class='slug'>{html.escape(str(r.get('strategy') or 'paper'))}</td>"
        f"<td>{html.escape(started)}</td><td>{html.escape(ended)}</td>"
        f"<td><span class='status {status}'>{status}</span></td>"
        f"<td><span class='run-id'>{html.escape(str(r['run_id'])[:8])}</span></td></tr>")


def _render(mode: str, rows: list[dict]) -> str:
    tabs = (
        "<div class='runs-tabs'>"
        f"<a class='{'active' if mode == 'backtest' else ''}' href='/backtests'>Backtests</a>"
        f"<a class='{'active' if mode == 'paper' else ''}' href='/paper'>Paper runs</a>"
        "</div>"
    )
    title = "Backtests" if mode == "backtest" else "Paper runs"
    sub = ("Your grid-searched strategies, ready to deploy"
           if mode == "backtest" else "Your live paper-trading sessions")
    head = (
        f"<div class='runs-head'><div><h1>{title}</h1>"
        f"<span class='muted'>{sub}</span></div>"
        f"{tabs}</div>"
    )
    if not rows:
        body = f"<div class='empty'>{_MODE_EMPTY[mode]}</div>"
    elif mode == "backtest":
        rows_html = "".join(_bt_row(r) for r in rows)
        body = (
            "<div class='runs-tblwrap'><table><thead><tr>"
            "<th>Strategy</th><th>Return</th><th>Sharpe</th><th>Best params</th>"
            "<th>Started</th><th>Status</th><th></th><th>Share</th><th>Run</th>"
            "</tr></thead><tbody>" + rows_html + "</tbody></table></div>"
            "<p class='muted' style='font-size:.72rem'>Latest "
            f"{len(rows)} backtest runs for your login.</p>"
        )
    else:
        rows_html = "".join(_paper_row(r) for r in rows)
        body = (
            "<div class='runs-tblwrap'><table><thead><tr>"
            "<th>Strategy</th><th>Started</th><th>Ended</th><th>Status</th><th>Run</th>"
            "</tr></thead><tbody>" + rows_html + "</tbody></table></div>"
            "<p class='muted' style='font-size:.72rem'>Latest "
            f"{len(rows)} paper runs for your login.</p>"
        )
    return f"<div class='runs'>{head}{body}</div>"


def register(app, rt):
    @rt("/backtests")
    def backtests_get(session):
        user_id = session.get("user_id")
        if not user_id:
            return RedirectResponse("/signin", status_code=303)
        rows = _list_runs("backtest", str(user_id))
        try:
            from engine.auth import get_user_by_id
            user = get_user_by_id(str(user_id))
        except Exception:  # noqa: BLE001
            user = None
        center = Div(NotStr(_render("backtest", rows)))
        return page("backtests", Style(_CSS), center, user=user,
                    title="Backtests · AlpaTrade", right_news=False)

    @rt("/paper")
    def paper_get(session):
        user_id = session.get("user_id")
        if not user_id:
            return RedirectResponse("/signin", status_code=303)
        rows = _list_runs("paper", str(user_id))
        try:
            from engine.auth import get_user_by_id
            user = get_user_by_id(str(user_id))
        except Exception:  # noqa: BLE001
            user = None
        center = Div(NotStr(_render("paper", rows)))
        return page("paper", Style(_CSS), center, user=user,
                    title="Paper runs · AlpaTrade", right_news=False)

    return ["/backtests", "/paper"]
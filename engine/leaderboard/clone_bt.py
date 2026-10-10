"""Clone a Leaderboard strategy into the user's own PAPER strategy and backtest it.

* ``clone_strategy(src_id, user)``: idempotent — one clone per (user, source); creates the
  private ``alpatrade.user_strategies`` copy (``cloned_from_id`` = source, "Shown as" = the
  user's email local part) and an ``alpatrade.user_strategy_configs`` row (template + params,
  ``mode`` paper/simulated, ``is_live`` FALSE by DB constraint, active). Never touches
  ``alpatrade.strategy_configs`` / ``strategy_allocations`` (the live runner's tables).
* ``start_backtest(strategy_id, user_id, overrides, thread_id)``: background job on the fixed
  backtester (utils.buy_the_dip ≥ v0.33.6 with fees + slippage for BTD; engine.backtest.templates
  / breakout for Chat With Traders templates). Results (total, simple ×252 annualised, Sharpe,
  max DD, trades, win rate, vs SPY + equity curve + engine stamp + audit_input) are stored on
  the clone's ``backtest_metrics`` so ``scripts/audit_backtest.py --strategy-id`` can audit
  them, and posted as an assistant message into the user's chat conversation.
No code path here places orders (paper or live).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

log = logging.getLogger("leaderboard.clone")

BTD = "buy_the_dip"
PAPER_TEMPLATES = {BTD}          # templates the paper bot can trade today
BT_START = "2016-01-04"
CAPITAL = 10_000.0
MAX_POINTS = 400
_schema_ok = False
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ── schema / db ─────────────────────────────────────────────────────────────
def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def ensure_schema() -> None:
    global _schema_ok
    if _schema_ok:
        return
    from pathlib import Path
    from sqlalchemy import text
    sql = (Path(__file__).resolve().parents[2] / "sql" / "47_user_strategy_configs.sql").read_text()
    with _pool().get_session() as s:
        s.execute(text(sql))
    _schema_ok = True


# ── spec ────────────────────────────────────────────────────────────────────
def spec_of(row: dict) -> tuple[str, dict, dict]:
    """(template, params, execution) from the strategy's skill Parameters block."""
    from engine.leaderboard.skill import extract_params
    block = extract_params((row or {}).get("skill_md") or "") or {}
    p = dict(block.get("params") or {})
    t = (block.get("template") or p.pop("template", None) or "").strip()
    if not t:
        bm = (row or {}).get("backtest_metrics") or {}
        bt = str(bm.get("template") or "") if isinstance(bm, dict) else ""
        t = BTD if (BTD in bt or {"dip", "tp", "sl"} <= set(p)) else (bt.split()[0] if bt else BTD)
    if t == "dip" and {"tp", "sl"} <= set(p):   # BTD params under the generic name
        t = BTD
    return t, p, dict(block.get("execution") or {})


def paper_supported(template: str) -> bool:
    return template in PAPER_TEMPLATES


def has_paper_keys(user_id: str) -> bool:
    """Alpaca paper keys saved for the user (alpatrade.user_accounts); never decrypts them."""
    try:
        from sqlalchemy import text
        with _pool().get_session() as s:
            return bool(s.execute(text("SELECT 1 FROM alpatrade.user_accounts WHERE user_id = CAST(:u AS UUID) "
                                       "AND is_active AND alpaca_api_key_enc IS NOT NULL LIMIT 1"),
                                  {"u": str(user_id)}).scalar())
    except Exception:  # noqa: BLE001
        return False


def paper_status(template: str, user_id: str) -> dict:
    """What the page says about paper trading (never live)."""
    if not paper_supported(template):
        return {"mode": "simulated", "label": f"Paper trading isn't available for the {template} template yet "
                "— backtests work; paper bots currently run buy-the-dip strategies only.", "keys": None}
    if has_paper_keys(user_id):
        return {"mode": "paper", "label": "Paper — active on your Alpaca paper account (never live).", "keys": True}
    return {"mode": "simulated", "label": "Paper (simulated) — connect Alpaca paper keys to start trading.",
            "keys": False}


# ── clone ───────────────────────────────────────────────────────────────────
def existing_clone(src_id: int, user_id: str) -> Optional[int]:
    from sqlalchemy import text
    with _pool().get_session() as s:
        v = s.execute(text("SELECT id FROM alpatrade.user_strategies WHERE user_id = CAST(:u AS UUID) "
                           "AND cloned_from_id = :s ORDER BY id LIMIT 1"), {"u": str(user_id), "s": int(src_id)}).scalar()
    return int(v) if v else None


def get_config(strategy_id: int, user_id: str) -> Optional[dict]:
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        r = s.execute(text("SELECT id, template, params, execution, mode, is_live, is_active FROM "
                           "alpatrade.user_strategy_configs WHERE user_strategy_id = :i AND user_id = CAST(:u AS UUID)"),
                      {"i": int(strategy_id), "u": str(user_id)}).mappings().first()
    if not r:
        return None
    d = dict(r)
    for k in ("params", "execution"):
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def upsert_config(strategy_id: int, user_id: str, template: str, params: dict, execution: dict,
                  mode: str) -> None:
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text("""
            INSERT INTO alpatrade.user_strategy_configs (user_id, user_strategy_id, template, params,
                   execution, mode, is_live, is_active)
            VALUES (CAST(:u AS UUID), :i, :t, CAST(:p AS JSONB), CAST(:e AS JSONB), :m, FALSE, TRUE)
            ON CONFLICT (user_strategy_id) DO UPDATE SET params = EXCLUDED.params,
                   execution = EXCLUDED.execution, mode = EXCLUDED.mode, updated_at = NOW()
        """), {"u": str(user_id), "i": int(strategy_id), "t": template[:32], "p": json.dumps(params, default=str),
               "e": json.dumps(execution, default=str), "m": mode})


def clone_strategy(src_id: int, user: dict) -> Optional[tuple[int, bool]]:
    """(clone id, created?) or None if the source isn't visible to the user."""
    from engine.leaderboard import store
    uid = str(user["user_id"])
    src = store.get_visible(src_id, uid)
    if not src:
        return None
    if src["user_id"] == uid:          # own strategy: no copy, just make sure it has a config
        new_id, created = int(src["id"]), False
    else:
        prev = existing_clone(src_id, uid)
        if prev:
            new_id, created = prev, False
        else:
            new_id = store.clone(src_id, uid, author_name=store.default_author(user))
            created = True
            from sqlalchemy import text
            with _pool().get_session() as s:   # backtested copy: figures are a backtest, never live
                s.execute(text("UPDATE alpatrade.user_strategies SET kind = 'backtest', source = :src, "
                               "source_url = :url, backtest_metrics = NULL, live_strategy_slug = NULL "
                               "WHERE id = :i AND user_id = CAST(:u AS UUID)"),
                          {"src": src.get("source"), "url": src.get("source_url"), "i": new_id, "u": uid})
    if not get_config(new_id, uid):
        t, p, ex = spec_of(src)
        upsert_config(new_id, uid, t, p, ex, paper_status(t, uid)["mode"])
    return new_id, created


# ── backtest engines ────────────────────────────────────────────────────────
def _pct(v):
    v = float(v)
    return v / 100 if v >= 1 else v


def _spy_close(start: str, end: str) -> dict:
    import yfinance as yf
    px = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    return {d.date().isoformat(): float(v) for d, v in px.items()}


def _btd(params: dict, start: str, end: str, progress) -> dict:
    import utils.buy_the_dip as btd
    syms = [str(s).upper() for s in (params.get("symbols") or ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"])][:25]
    kw = dict(dip_threshold=_pct(params.get("dip", 0.03)), take_profit=_pct(params.get("tp", 0.08)),
              stop_loss=_pct(params.get("sl", 0.015)), hold_days=int(params.get("max_hold", params.get("hold_days", 3))),
              min_hold_days=int(params.get("min_hold", 0)), position_size=float(params.get("pos_frac", 1 / max(len(syms), 1))))
    progress(f"Running buy-the-dip on {len(syms)} symbols, {start} → {end} (fees + 10 bps slippage)…")
    res = btd.backtest_buy_the_dip(syms, datetime.fromisoformat(start), datetime.fromisoformat(end),
                                   initial_capital=CAPITAL, data_source="yfinance",
                                   include_taf_fees=True, include_cat_fees=True, **kw)
    if res is None:
        raise RuntimeError("no market data for these symbols")
    t, _m, e = res
    curve = [(str(ts)[:10], float(v)) for ts, v in zip(e["timestamp"], e["equity"])] if len(e) else []
    return {"curve": curve, "trades": int(len(t)),
            "win_rate_pct": float((t["pnl"] > 0).mean() * 100) if len(t) else None,
            "fees_paid": float(t["total_fees"].sum()) if len(t) and "total_fees" in t else 0.0,
            "universe": ", ".join(syms), "used_params": kw, "slippage_bps": 10.0,
            "engine_desc": "utils.buy_the_dip (v0.33.6+: true equity, stop-before-target, gapped stops)"}


def _bars(symbols: list[str], start: str, end: str) -> dict:
    import pandas as pd
    import yfinance as yf
    df = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False, group_by="ticker",
                     threads=True)
    out = {}
    for s in symbols:
        try:
            d = df[s] if len(symbols) > 1 else df
            d = d.rename(columns={"Open": "o", "High": "h", "Low": "l", "Close": "c", "Volume": "v"})[["o", "h", "l", "c", "v"]].dropna()
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            if len(d):
                out[s] = d
        except Exception:  # noqa: BLE001
            continue
    return out


def _universe(params: dict) -> list[str]:
    syms = params.get("symbols")
    if isinstance(syms, list) and syms:
        return [str(s).upper() for s in syms][:600]
    from pathlib import Path
    f = Path(__file__).resolve().parents[2] / "data" / "cwt" / "bars" / "universe_sp500.csv"
    if f.exists():
        import pandas as pd
        return pd.read_csv(f)["symbol"].tolist()
    import io
    import pandas as pd
    import requests
    html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                        headers={"User-Agent": "Mozilla/5.0 AlpaTrade"}, timeout=30).text
    return sorted(str(s).replace(".", "-") for s in pd.read_html(io.StringIO(html))[0]["Symbol"])


def _template(template: str, params: dict, start: str, end: str, progress) -> dict:
    from engine.backtest import templates
    syms = _universe(params)
    progress(f"Loading daily bars for {len(syms)} symbols + SPY…")
    warm = (date.fromisoformat(start) - timedelta(days=420)).isoformat()
    bars = _bars(syms + ["SPY"], warm, end)
    spy = bars.pop("SPY")
    progress(f"Running the {template} template on {len(bars)} symbols…")
    if template == "breakout":
        from dataclasses import fields
        from engine.backtest import breakout
        names = {f.name for f in fields(breakout.BreakoutParams)}
        p = breakout.BreakoutParams(**{k: v for k, v in params.items() if k in names})
        r = breakout.run(bars, spy, start, end, p)
    else:
        p = templates.RuleParams.from_dict({**params, "template": template})
        r = templates.run(bars, spy, start, end, p)
    eq = r["equity"]
    curve = [(str(d.date()), float(v) / float(eq.iloc[0]) * CAPITAL) for d, v in eq.items()]
    return {"curve": curve, "trades": int(r.get("trades") or 0), "win_rate_pct": r.get("win_rate_pct"),
            "fees_paid": r.get("fees_paid"), "universe": f"{len(bars)} symbols"
            + (" (S&P 500 current members — survivorship bias)" if not params.get("symbols") else ""),
            "used_params": json.loads(json.dumps(p.to_dict(), default=str)),
            "slippage_bps": float(getattr(p, "slippage_bps", 10.0) or 10.0),
            "engine_desc": f"engine.backtest.{'breakout' if template == 'breakout' else 'templates'} ({template})"}


def compute(template: str, params: dict, start: str = BT_START, end: Optional[str] = None,
            progress: Callable[[str], None] = lambda m: None) -> dict:
    """Run the matching engine and return leaderboard-shaped ``backtest_metrics``."""
    import math
    from engine.reporting.annualize import trading_days_between
    from utils.engine_stamp import stamp
    end = end or date.today().isoformat()
    raw = _btd(params, start, end, progress) if template == BTD else _template(template, params, start, end, progress)
    curve = raw["curve"]
    if len(curve) < 2:
        raise RuntimeError("the backtest produced no equity curve")
    progress("Computing metrics vs SPY…")
    spy = _spy_close((date.fromisoformat(curve[0][0]) - timedelta(days=10)).isoformat(), end)
    ks = sorted(spy)

    def spy_on(d):
        import bisect
        i = bisect.bisect_right(ks, d) - 1
        return spy[ks[i]] if i >= 0 else None
    eq = [v for _, v in curve]
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    mu = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    a, b = curve[0][0], curve[-1][0]
    days = trading_days_between(date.fromisoformat(a), date.fromisoformat(b)) or len(curve)
    tot = eq[-1] / eq[0] - 1
    s0, s1 = spy_on(a), spy_on(b)
    spy_tot = (s1 / s0 - 1) if s0 and s1 else None
    ann = tot * 252 / days
    spy_ann = spy_tot * 252 / days if spy_tot is not None else None
    pts = curve if len(curve) <= MAX_POINTS else curve[::max(1, len(curve) // MAX_POINTS)] + [curve[-1]]
    st = stamp(template)
    return {
        "period_start": a, "period_end": b, "trading_days": days,
        "total_return_pct": tot * 100, "annualised_pct": ann * 100,
        "spy_return_pct": None if spy_tot is None else spy_tot * 100,
        "spy_annualised_pct": None if spy_ann is None else spy_ann * 100,
        "alpha_pct": None if spy_tot is None else (tot - spy_tot) * 100,
        "alpha_annualised_pct": None if spy_ann is None else (ann - spy_ann) * 100,
        "sharpe": (mu / sd * math.sqrt(252)) if sd else None, "max_drawdown_pct": mdd * 100,
        "trades": raw["trades"], "win_rate_pct": raw["win_rate_pct"], "fees_paid": raw.get("fees_paid"),
        "universe": raw["universe"], "template": f"{template} — {raw['engine_desc']}",
        "test": {}, "episodes": [],
        "equity_curve": {"dates": [d for d, _ in pts], "equity": [round(v, 2) for _, v in pts],
                         "spy": [spy_on(d) for d, _ in pts]},
        "engine_stamp": st,
        "audit_input": {"engine": st["engine"], "label": "research", "params": raw["used_params"],
                        "slippage_bps": raw["slippage_bps"], "fees_recorded": True,
                        "same_bar_policy": "stop_first", "engine_stamp": st},
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ── jobs ────────────────────────────────────────────────────────────────────
def save_metrics(strategy_id: int, user_id: str, bm: dict) -> None:
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text("UPDATE alpatrade.user_strategies SET backtest_metrics = CAST(:b AS JSONB), kind = 'backtest', "
                       "updated_at = NOW() WHERE id = :i AND user_id = CAST(:u AS UUID)"),
                  {"b": json.dumps(bm, default=str), "i": int(strategy_id), "u": str(user_id)})


def _f(v, fmt="{:+.1f}%"):
    return "—" if v is None else fmt.format(v)


def result_markdown(s: dict, bm: dict, cfg: dict, status: dict) -> str:
    sid = int(s["id"])
    chart = {"type": "strategy_vs_spy", "title": f"{s['name']} vs SPY (backtest, base 100)",
             **bm.get("equity_curve", {})}
    rows = [("Total return", _f(bm.get("total_return_pct")), _f(bm.get("spy_return_pct"))),
            ("Annualised (simple ×252)", _f(bm.get("annualised_pct")), _f(bm.get("spy_annualised_pct"))),
            ("Sharpe", _f(bm.get("sharpe"), "{:.2f}"), "—"),
            ("Max drawdown", _f(bm.get("max_drawdown_pct")), "—"),
            ("Trades · win rate", f"{bm.get('trades') or 0} · {_f(bm.get('win_rate_pct'), '{:.0f}%')}", "—")]
    table = "| Metric | Strategy | SPY |\n|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    audit = ""
    try:
        from engine.leaderboard.audit_gate import audit_strategy
        rep = audit_strategy({**s, "kind": "backtest", "backtest_metrics": bm})
        if rep is not None:
            audit = f"\n\n**Backtest audit:** {rep.status}" + (f" — {'; '.join(rep.reasons[:3])}" if rep.reasons else "")
    except Exception:  # noqa: BLE001
        pass
    p = json.dumps(cfg.get("params") or {}, default=str)
    return (f"### Backtest: {s['name']}\n\n"
            f"{bm['period_start']} → {bm['period_end']} · {bm['trading_days']} trading days · "
            f"template `{(cfg.get('template') or '')}` · fees + slippage on · alpha vs SPY "
            f"**{_f(bm.get('alpha_pct'))}** (annualised {_f(bm.get('alpha_annualised_pct'))})\n\n{table}{audit}\n\n"
            f"Universe: {bm.get('universe')}. Params: `{p[:600]}`\n\n"
            f"**Status:** {status['label']}"
            + ("" if status.get("keys") is not False else " [Connect Alpaca paper keys](/settings)")
            + f"\n\n[Open the strategy page](/strategies/{sid}) · Ask me to change a parameter and rerun, e.g. "
            f"*\"change the stop to 2% and rerun strategy #{sid}\"*. Hypothetical backtest, not investment advice.\n\n"
            f"__CHART_DATA__{json.dumps(chart, default=str)}__END_CHART__")


def run_job(strategy_id: int, user_id: str, overrides: Optional[dict] = None,
            progress: Callable[[str], None] = lambda m: None) -> tuple[str, dict]:
    """Synchronous: (markdown, metrics). Owner-only; updates the config with ``overrides``."""
    from engine.leaderboard import store
    s = store.get(strategy_id)
    if not s or s["user_id"] != str(user_id):
        raise PermissionError("strategy not found in your strategies")
    cfg = get_config(strategy_id, user_id)
    if not cfg:
        t, p, ex = spec_of(s)
        upsert_config(strategy_id, user_id, t, p, ex, paper_status(t, user_id)["mode"])
        cfg = get_config(strategy_id, user_id)
    if overrides:
        cfg["params"] = {**cfg["params"], **overrides}
        upsert_config(strategy_id, user_id, cfg["template"], cfg["params"], cfg["execution"], cfg["mode"])
    bm = compute(cfg["template"], cfg["params"], progress=progress)
    save_metrics(strategy_id, user_id, bm)
    status = paper_status(cfg["template"], user_id)
    return result_markdown(s, bm, cfg, status), bm


def start_backtest(strategy_id: int, user_id: str, overrides: Optional[dict] = None,
                   thread_id: Optional[str] = None) -> str:
    """Start (or join a running) background job; on completion the result is saved into the
    chat thread, so it reaches the user even if the stream was interrupted."""
    key = f"{user_id}:{strategy_id}"
    with _LOCK:
        for jid, j in JOBS.items():
            if j["key"] == key and j["state"] == "running" and not overrides:
                return jid
        jid = uuid.uuid4().hex[:12]
        JOBS[jid] = {"key": key, "state": "running", "message": "Starting backtest…", "started": time.time(),
                     "markdown": None, "error": None, "thread_id": thread_id, "strategy_id": int(strategy_id)}

    def prog(m):
        JOBS[jid]["message"] = m

    def work():
        j = JOBS[jid]
        try:
            md, _ = run_job(strategy_id, user_id, overrides, prog)
            j.update(state="done", markdown=md)
        except Exception as exc:  # noqa: BLE001
            log.warning("clone backtest %s failed: %s", strategy_id, exc)
            md = f"Backtest of strategy #{strategy_id} failed: {exc}"
            j.update(state="error", error=str(exc), markdown=md)
        if thread_id:
            try:
                from engine.ai.chat_store import save_conversation, save_message
                save_conversation(thread_id, user_id=str(user_id))
                save_message(thread_id, "assistant", j["markdown"],
                             metadata={"agent": "Backtest", "framework": "command", "dispatch": "strategy_backtest",
                                       "strategy_id": int(strategy_id),
                                       "follow_ups": [f"Change the stop to 2% and rerun strategy #{strategy_id}",
                                                      f"Explain the rules of strategy #{strategy_id}"]})
            except Exception as exc:  # noqa: BLE001
                log.warning("could not post backtest to chat: %s", exc)
    threading.Thread(target=work, daemon=True, name=f"clone-bt-{jid}").start()
    return jid

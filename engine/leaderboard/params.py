"""Versioned, user-editable strategy parameters + walk-forward gate (v0.51.0).

Flow (owner only, buy-the-dip template):

1. ``ensure_baseline`` snapshots the strategy's current ``user_strategy_configs.params`` as
   version 1 (status ``baseline``) the first time the Parameters page / chat tools touch it.
2. Every edit (form, chat confirmation, API) goes through ``utils.btd_rules.validate_params`` and
   inserts a NEW draft version (``create_version``). Nothing running changes.
3. ``start_wf`` runs the walk-forward (engine/leaderboard/walkforward.py, parity backtester) in a
   background thread; results are stored in ``alpatrade.strategy_wf_runs`` and cached by
   (params, live params, data date), so re-running an unchanged version is instant.
4. ``apply_version``:
   * paper: immediately. The paper activation's ``params_version_id`` is set; when no live
     activation is running a different version, the strategy config row is updated too (that
     row is what un-versioned runners read).
   * live: only with a COMPLETED walk-forward run for that version AND a typed ``LIVE``
     confirmation (same UX as Activate Live), and only after the live sleeve rules accept the
     new universe. Sets the live activation's version and the config row.
   Every apply / edit is logged to ``alpatrade.activation_events`` (event ``params_*``).

Editing never touches a live activation directly. Admins can list every version (``admin_versions``).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from utils import btd_rules as R

log = logging.getLogger("leaderboard.params")
_schema_ok = False
WF_STALE_S = 20 * 60
RUNNABLE_LIVE = ("pending_runner", "active", "paused")
RUNNABLE_PAPER = ("pending_runner", "active", "paused", "queued")
_LOCK = threading.Lock()
_RUNNING: Dict[int, threading.Thread] = {}


class ParamsError(Exception):
    pass


def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def ensure_schema() -> None:
    global _schema_ok
    if _schema_ok:
        return
    from pathlib import Path
    from sqlalchemy import text
    from engine.leaderboard.activate import ensure_schema as act_schema
    act_schema()
    sql = (Path(__file__).resolve().parents[2] / "sql" / "56_strategy_param_versions.sql").read_text()
    with _pool().get_session() as s:
        s.execute(text(sql))
    _schema_ok = True


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v if v is not None else None)


class SqlRepo:
    """All SQL lives here (tests swap in a fake)."""

    def _rows(self, sql: str, p: dict) -> List[dict]:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            return [dict(r) for r in s.execute(text(sql), p).mappings().all()]

    def _exec(self, sql: str, p: dict):
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            r = s.execute(text(sql), p)
            try:
                return [dict(x) for x in r.mappings().all()]
            except Exception:  # noqa: BLE001
                return []

    def strategy(self, sid: int) -> Optional[dict]:
        from engine.leaderboard import store
        return store.get(int(sid))

    def config(self, sid: int, uid: str) -> Optional[dict]:
        from engine.leaderboard import clone_bt
        return clone_bt.get_config(int(sid), str(uid))

    def write_config_params(self, sid: int, uid: str, params: dict) -> None:
        self._exec("UPDATE alpatrade.user_strategy_configs SET params = CAST(:p AS JSONB), updated_at = NOW() "
                   "WHERE user_strategy_id = :i AND user_id = CAST(:u AS UUID)",
                   {"p": json.dumps(params, default=str), "i": int(sid), "u": str(uid)})

    def versions(self, sid: int) -> List[dict]:
        rows = self._rows("SELECT * FROM alpatrade.strategy_param_versions WHERE user_strategy_id = :i ORDER BY version",
                          {"i": int(sid)})
        for r in rows:
            r["params"], r["diff"] = _j(r["params"]), _j(r["diff"])
            r["user_id"] = str(r["user_id"])
        return rows

    def insert_version(self, uid: str, sid: int, params: dict, status: str, parent_id: Optional[int],
                       source: str, note: str, diff: list) -> dict:
        rows = self._exec("""
            INSERT INTO alpatrade.strategy_param_versions (user_id, user_strategy_id, version, params, status,
                   parent_id, source, note, diff, created_by)
            SELECT CAST(:u AS UUID), :i, COALESCE(MAX(version), 0) + 1, CAST(:p AS JSONB), :st, :par, :src, :n,
                   CAST(:d AS JSONB), CAST(:u AS UUID)
            FROM alpatrade.strategy_param_versions WHERE user_strategy_id = :i
            RETURNING *""", {"u": str(uid), "i": int(sid), "p": json.dumps(params, default=str), "st": status,
                             "par": parent_id, "src": source[:16], "n": (note or "")[:300],
                             "d": json.dumps(diff, default=str)})
        r = rows[0]
        r["params"], r["diff"], r["user_id"] = _j(r["params"]), _j(r["diff"]), str(r["user_id"])
        return r

    def activations(self, sid: int, uid: str) -> Dict[str, dict]:
        rows = self._rows("SELECT id, mode, status, account_ref, allocation_usd, cid_prefix, params_version_id, "
                          "params_applied_at FROM alpatrade.user_strategy_activations "
                          "WHERE user_strategy_id = :i AND user_id = CAST(:u AS UUID)", {"i": int(sid), "u": str(uid)})
        return {r["mode"]: r for r in rows}

    def set_activation_version(self, aid: int, vid: int) -> None:
        self._exec("UPDATE alpatrade.user_strategy_activations SET params_version_id = :v, params_applied_at = NOW(), "
                   "updated_at = NOW() WHERE id = :a", {"v": int(vid), "a": int(aid)})

    def wf_runs(self, vid: int) -> List[dict]:
        rows = self._rows("SELECT * FROM alpatrade.strategy_wf_runs WHERE version_id = :v ORDER BY id DESC", {"v": int(vid)})
        for r in rows:
            r["result"] = _j(r["result"])
        return rows

    def wf_run(self, rid: int) -> Optional[dict]:
        rows = self._rows("SELECT * FROM alpatrade.strategy_wf_runs WHERE id = :r", {"r": int(rid)})
        if rows:
            rows[0]["result"] = _j(rows[0]["result"])
            rows[0]["user_id"] = str(rows[0]["user_id"])
        return rows[0] if rows else None

    def wf_done_by_key(self, key: str) -> Optional[dict]:
        rows = self._rows("SELECT * FROM alpatrade.strategy_wf_runs WHERE cache_key = :k AND status = 'done' "
                          "ORDER BY id DESC LIMIT 1", {"k": key})
        if rows:
            rows[0]["result"] = _j(rows[0]["result"])
        return rows[0] if rows else None

    def wf_insert(self, uid: str, sid: int, vid: int, key: str, status: str, result=None, cached=False,
                  progress: str = "") -> int:
        rows = self._exec("""INSERT INTO alpatrade.strategy_wf_runs (user_id, user_strategy_id, version_id, cache_key,
                   status, result, cached, progress, finished_at)
                   VALUES (CAST(:u AS UUID), :i, :v, :k, :st, CAST(:r AS JSONB), :c, :pg,
                           CASE WHEN :st = 'done' THEN NOW() END) RETURNING id""",
                          {"u": str(uid), "i": int(sid), "v": int(vid), "k": key, "st": status,
                           "r": json.dumps(result, default=str) if result is not None else None, "c": bool(cached),
                           "pg": progress[:300]})
        return int(rows[0]["id"])

    def wf_update(self, rid: int, **kw) -> None:
        sets, p = [], {"r": int(rid)}
        for k, v in kw.items():
            if k == "result":
                sets.append("result = CAST(:result AS JSONB)"); p["result"] = json.dumps(v, default=str)
            else:
                sets.append(f"{k} = :{k}"); p[k] = v[:500] if isinstance(v, str) else v
        if kw.get("status") in ("done", "error"):
            sets.append("finished_at = NOW()")
        self._exec(f"UPDATE alpatrade.strategy_wf_runs SET {', '.join(sets)} WHERE id = :r", p)

    def log_event(self, uid: str, event: str, meta: dict) -> None:
        try:
            self._exec("""INSERT INTO alpatrade.activation_events (user_id, event, first_at, meta)
                          VALUES (CAST(:u AS UUID), :e, NOW(), CAST(:m AS JSONB))
                          ON CONFLICT (user_id, event) DO UPDATE SET meta = EXCLUDED.meta""",
                       {"u": str(uid), "e": event[:32], "m": json.dumps(meta, default=str)})
        except Exception as exc:  # noqa: BLE001
            log.warning("activation_events log failed: %s", type(exc).__name__)

    def admin_versions(self, limit: int = 300) -> List[dict]:
        rows = self._rows("""
            SELECT v.id, v.user_strategy_id, v.version, v.status, v.source, v.note, v.diff, v.created_at,
                   u.email, s.name AS strategy_name,
                   (SELECT string_agg(a.mode, ',') FROM alpatrade.user_strategy_activations a
                     WHERE a.params_version_id = v.id AND a.status <> 'deactivated') AS applied_to,
                   (SELECT w.status FROM alpatrade.strategy_wf_runs w WHERE w.version_id = v.id ORDER BY w.id DESC LIMIT 1) AS wf_status
            FROM alpatrade.strategy_param_versions v
            JOIN alpatrade.user_strategies s ON s.id = v.user_strategy_id
            LEFT JOIN alpatrade.users u ON u.user_id = v.user_id
            ORDER BY v.created_at DESC LIMIT :n""", {"n": int(limit)})
        for r in rows:
            r["diff"] = _j(r["diff"])
        return rows


repo: Any = SqlRepo()


# ── ownership ────────────────────────────────────────────────────────────────
def _owned(sid: int, uid: str) -> tuple[dict, dict]:
    s = repo.strategy(int(sid))
    if not s or str(s.get("user_id")) != str(uid):
        raise ParamsError("That strategy isn't one of yours. Clone it first.")
    cfg = repo.config(int(sid), str(uid))
    if not cfg:
        from engine.leaderboard import clone_bt
        t, p, ex = clone_bt.spec_of(s)
        clone_bt.upsert_config(int(sid), str(uid), t, p, ex, clone_bt.paper_status(t, str(uid))["mode"])
        cfg = repo.config(int(sid), str(uid))
    if not cfg or (cfg.get("template") or "") != "buy_the_dip":
        raise ParamsError("Editable parameters are available for buy-the-dip strategies only.")
    return s, cfg


def _lenient(params: dict) -> dict:
    """Baseline from a stored config: validated if possible, else defaults + the stored values."""
    try:
        return R.validate_params(params or {})
    except R.ParamError:
        return {**R.param_defaults(), **{k: v for k, v in (params or {}).items() if v is not None}}


# ── versions ────────────────────────────────────────────────────────────────
def ensure_baseline(sid: int, uid: str) -> List[dict]:
    _, cfg = _owned(sid, uid)
    vs = repo.versions(int(sid))
    if not vs:
        repo.insert_version(str(uid), int(sid), _lenient(cfg.get("params") or {}), "baseline", None, "baseline",
                            "Parameters before editing (current config)", [])
        vs = repo.versions(int(sid))
    return vs


def latest(sid: int, uid: str) -> dict:
    return ensure_baseline(sid, uid)[-1]


def live_version(sid: int, uid: str, versions: Optional[List[dict]] = None, acts: Optional[dict] = None) -> Optional[dict]:
    """The version the LIVE activation runs (its params_version_id, else the baseline), None if no live."""
    acts = acts if acts is not None else repo.activations(int(sid), str(uid))
    a = acts.get("live")
    if not a or a.get("status") not in RUNNABLE_LIVE:
        return None
    vs = versions if versions is not None else ensure_baseline(sid, uid)
    if a.get("params_version_id"):
        return next((v for v in vs if v["id"] == a["params_version_id"]), None)
    return vs[0] if vs else None


def propose(sid: int, uid: str, changes: Dict[str, Any], base_version_id: Optional[int] = None) -> dict:
    """Validate ``changes`` on top of the latest (or given) version. Writes nothing.
    {'ok', 'params', 'diff': [(k, old, new)], 'errors': {k: msg}, 'base': version}."""
    vs = ensure_baseline(sid, uid)
    base = next((v for v in vs if v["id"] == base_version_id), vs[-1]) if base_version_id else vs[-1]
    unknown = [k for k in (changes or {}) if k not in R.PARAM_SPEC]
    if unknown:
        return {"ok": False, "errors": {k: "not an editable parameter" for k in unknown}, "base": base, "diff": [],
                "params": base["params"]}
    try:
        new = R.validate_params(changes, base=base["params"])
    except R.ParamError as exc:
        return {"ok": False, "errors": exc.errors, "base": base, "diff": [], "params": base["params"]}
    return {"ok": True, "params": new, "diff": R.diff_params(base["params"], new), "errors": {}, "base": base}


def create_version(sid: int, uid: str, changes: Dict[str, Any], *, source: str = "ui", note: str = "",
                   base_version_id: Optional[int] = None) -> dict:
    """New DRAFT version (never touches an activation). Returns {'ok', 'version'|'errors', 'diff', 'unchanged'}."""
    p = propose(sid, uid, changes, base_version_id)
    if not p["ok"]:
        return p
    if not p["diff"]:
        return {**p, "unchanged": True, "version": p["base"]}
    v = repo.insert_version(str(uid), int(sid), p["params"], "draft", p["base"]["id"], source, note,
                            [list(x) for x in p["diff"]])
    repo.log_event(str(uid), f"params_edit_{v['id']}", {"strategy_id": int(sid), "version": v["version"],
                                                        "source": source, "diff": [list(x) for x in p["diff"]]})
    return {**p, "version": v, "unchanged": False}


def overview(sid: int, uid: str) -> dict:
    """Everything the Parameters page needs."""
    s, cfg = _owned(sid, uid)
    vs = ensure_baseline(sid, uid)
    acts = repo.activations(int(sid), str(uid))
    lv = live_version(sid, uid, vs, acts)
    pa = acts.get("paper")
    paper_v = None
    if pa and pa.get("status") in RUNNABLE_PAPER:
        paper_v = next((v for v in vs if v["id"] == pa.get("params_version_id")), vs[0])
    wf = {}
    for v in vs[-12:]:
        runs = repo.wf_runs(v["id"])
        wf[v["id"]] = _fresh(runs[0]) if runs else None
    return {"strategy": s, "config": cfg, "versions": vs, "latest": vs[-1], "activations": acts,
            "live_version": lv, "paper_version": paper_v, "wf": wf}


# ── walk-forward ─────────────────────────────────────────────────────────────
def _fresh(run: dict) -> dict:
    """A 'running' row whose thread died (restart) reads as error after WF_STALE_S."""
    if run and run.get("status") == "running":
        import datetime as _dt
        ts = run.get("created_at")
        if ts is not None and (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds() > WF_STALE_S \
                and int(run["id"]) not in _RUNNING:
            run = {**run, "status": "error", "error": "interrupted (server restart) - run it again"}
    return run


def wf_done(vid: int) -> Optional[dict]:
    for r in repo.wf_runs(int(vid)):
        if r.get("status") == "done":
            return r
    return None


def start_wf(sid: int, uid: str, vid: Optional[int] = None, *, loader: Optional[Callable] = None,
             runner: Optional[Callable] = None, background: bool = True) -> dict:
    """Start (or reuse) the walk-forward run for a version. {'run_id', 'cached', 'status'}."""
    from engine.leaderboard import walkforward as WF
    vs = ensure_baseline(sid, uid)
    v = next((x for x in vs if x["id"] == vid), None) if vid else vs[-1]
    if not v:
        raise ParamsError("Unknown version.")
    lv = live_version(sid, uid, vs)
    live_params = lv["params"] if lv else vs[0]["params"]
    asof = WF.data_asof()
    key = WF.cache_key(v["params"], live_params, asof)
    for r in repo.wf_runs(v["id"]):
        r = _fresh(r)
        if r["cache_key"] == key and r["status"] in ("running", "done"):
            return {"run_id": int(r["id"]), "cached": r["status"] == "done", "status": r["status"], "version": v}
    hit = repo.wf_done_by_key(key)
    if hit:
        rid = repo.wf_insert(str(uid), int(sid), v["id"], key, "done", hit["result"], cached=True, progress="cached")
        return {"run_id": rid, "cached": True, "status": "done", "version": v}
    rid = repo.wf_insert(str(uid), int(sid), v["id"], key, "running", None, progress="Loading market data…")

    def work():
        try:
            bars = (loader or WF.load_bars)(list(v["params"]["symbols"]) + list(live_params.get("symbols") or []), asof)
            last = [0.0]

            def prog(msg, partial):
                if time.monotonic() - last[0] > 1.0:
                    last[0] = time.monotonic()
                    repo.wf_update(rid, progress=msg, result={**partial, "partial": True})
            res = (runner or WF.run_wf)(v["params"], live_params, bars, prog, asof)
            res["compare_label"] = f"live v{lv['version']}" if lv else f"current v{vs[0]['version']}"
            repo.wf_update(rid, status="done", progress="done", result=res)
        except Exception as exc:  # noqa: BLE001
            log.warning("wf run %s failed: %s", rid, exc)
            repo.wf_update(rid, status="error", error=str(exc)[:500], progress="error")
        finally:
            _RUNNING.pop(rid, None)
    if background:
        t = threading.Thread(target=work, daemon=True, name=f"wf-{rid}")
        _RUNNING[rid] = t
        t.start()
    else:
        work()
    return {"run_id": rid, "cached": False, "status": "running" if background else repo.wf_run(rid)["status"],
            "version": v}


def wf_status(rid: int, uid: str, admin: bool = False) -> Optional[dict]:
    r = repo.wf_run(int(rid))
    if not r or (not admin and str(r["user_id"]) != str(uid)):
        return None
    return _fresh(r)


def wf_summary_md(res: dict, version: Optional[int] = None) -> str:
    """Markdown table of a walk-forward result (chat + docs)."""
    def f(x, fmt="{:+.1f}%"):
        return "—" if x is None else fmt.format(x)
    lines = [f"**Walk-forward{f' of v{version}' if version else ''}** on the parity backtester "
             f"(data to {res.get('asof')}, $10k per window).", "",
             "| Window | Return | Sharpe | Max DD | Live version | SPY |", "|---|---|---|---|---|---|"]
    for name, sg in (res.get("segments") or {}).items():
        c, lv, sp = sg["cand"], sg["live"], sg["spy"]
        lines.append(f"| {name} | {f(c['total_pct'])} | {f(c['sharpe'], '{:.2f}')} | {f(c['max_dd_pct'])} | "
                     f"{f(lv['total_pct'])} / {f(lv['sharpe'], '{:.2f}')} | {f(sp['total_pct'])} / {f(sp['sharpe'], '{:.2f}')} |")
    o = res.get("oos") or {}
    if o.get("cand"):
        lines.append(f"| OOS test years chained | {f(o['cand']['total_pct'])} | {f(o['cand']['sharpe'], '{:.2f}')} | "
                     f"{f(o['cand']['max_dd_pct'])} | {f((o.get('live') or {}).get('total_pct'))} / "
                     f"{f((o.get('live') or {}).get('sharpe'), '{:.2f}')} | {f((o.get('spy') or {}).get('total_pct'))} / "
                     f"{f((o.get('spy') or {}).get('sharpe'), '{:.2f}')} |")
    folds = res.get("folds") or []
    if folds:
        lines += ["", "Rolling 3y fit → 1y test (test-year return, candidate / live / SPY): " + ", ".join(
            f"{x['test'][0][:4]} {f(x['cand']['total_pct'], '{:+.0f}%')}/{f(x['live']['total_pct'], '{:+.0f}%')}/"
            f"{f(x['spy']['total_pct'], '{:+.0f}%')}" for x in folds)]
    return "\n".join(lines)


# ── apply ───────────────────────────────────────────────────────────────────
def apply_version(sid: int, uid: str, vid: int, mode: str, confirm: str = "", *,
                  plan_check: Optional[Callable[[list], List[str]]] = None) -> dict:
    """Apply a version to the paper or live activation. Live: needs a completed walk-forward run
    for this version and confirm == 'LIVE'. Returns {'ok', 'message', 'errors'}."""
    vs = ensure_baseline(sid, uid)
    v = next((x for x in vs if x["id"] == int(vid)), None)
    if not v:
        return {"ok": False, "errors": ["Unknown version."]}
    acts = repo.activations(int(sid), str(uid))
    live = acts.get("live") if (acts.get("live") or {}).get("status") in RUNNABLE_LIVE else None
    lv = live_version(sid, uid, vs, acts)
    meta = {"strategy_id": int(sid), "version_id": v["id"], "version": v["version"], "mode": mode}
    if mode == "paper":
        pa = acts.get("paper") if (acts.get("paper") or {}).get("status") in RUNNABLE_PAPER else None
        if pa:
            repo.set_activation_version(pa["id"], v["id"])
        wrote = False
        if not live or (lv and lv["id"] == v["id"]):
            repo.write_config_params(int(sid), str(uid), v["params"])
            wrote = True
        repo.log_event(str(uid), f"params_apply_{v['id']}_paper", {**meta, "activation_id": (pa or {}).get("id"),
                                                                  "config_updated": wrote})
        msg = (f"v{v['version']} applied to paper" + (" — your paper bot uses it from its next pass." if pa else
               ". It becomes the strategy's paper settings; press Activate Paper to run it.")
               + ("" if wrote else " Live keeps running its current version."))
        return {"ok": True, "message": msg, "errors": []}
    if mode != "live":
        return {"ok": False, "errors": ["mode must be paper or live"]}
    errors = []
    if not live:
        errors.append("This strategy has no live activation. Use Activate Live first (it starts with the current settings).")
    if not wf_done(v["id"]):
        errors.append(f"Run the walk-forward backtest of v{v['version']} first (it must complete before going live).")
    if (confirm or "").strip().upper() != "LIVE":
        errors.append("Type LIVE to confirm real-money trading with these parameters.")
    if not errors and plan_check is not None:
        errors += plan_check(list(v["params"]["symbols"]))
    if errors:
        return {"ok": False, "errors": errors}
    repo.set_activation_version(live["id"], v["id"])
    repo.write_config_params(int(sid), str(uid), v["params"])
    repo.log_event(str(uid), f"params_apply_{v['id']}_live", {**meta, "activation_id": live["id"],
                                                             "previous_version_id": (lv or {}).get("id")})
    return {"ok": True, "errors": [], "message": f"v{v['version']} applied to your LIVE strategy. The live runner uses it "
            "from its next pass (entries 15:45-15:55 ET); open positions keep their entry stops/targets."}


def live_universe_check(sid: int, uid: str) -> Callable[[list], List[str]]:
    """Sleeve rules for a changed universe (disjoint from the account's other live sleeves)."""
    def check(symbols: list) -> List[str]:
        try:
            from engine.leaderboard import activate
            acts = repo.activations(int(sid), str(uid))
            alloc = float((acts.get("live") or {}).get("allocation_usd") or 0) or None
            plan = activate.live_plan(int(sid), str(uid), alloc, universe_override=symbols)
        except Exception as exc:  # noqa: BLE001
            return [f"Could not validate the live account: {type(exc).__name__}"]
        return [e for e in plan.get("errors") or []
                if "universe" in e.lower() or "overlap" in e.lower() or "symbol" in e.lower()]
    return check


def admin_versions(limit: int = 300) -> List[dict]:
    return repo.admin_versions(limit)


def fmt_value(k: str, v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if v == "" and k == "regime_filter":
        return "off"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def diff_md(diff: list) -> str:
    if not diff:
        return "_No changes._"
    rows = ["| Parameter | Current | New |", "|---|---|---|"]
    for k, a, b in diff:
        lbl = R.PARAM_SPEC.get(k, {}).get("label", k)
        rows.append(f"| {lbl} (`{k}`) | {fmt_value(k, a)} | **{fmt_value(k, b)}** |")
    return "\n".join(rows)

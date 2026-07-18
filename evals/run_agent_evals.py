#!/usr/bin/env python3
"""Autonomy-agent eval harness — deterministic + structural grading, per-dimension report.

Complements ``evals/run_evals.py`` (chat tools / CLI). This one evaluates the *agent
team*: the risk policy on replayed portfolio states, promotion decisions, and scout
candidate invariants. Most cases have a right answer, so they are graded by pure
functions (no LLM) — fast and offline (except the ``scout`` dimension, which reads live
market data and asserts only structural invariants).

Run:  python evals/run_agent_evals.py            # all cases
      python evals/run_agent_evals.py --skip-scout
Output: eval-results/agent-evals-<ts>.csv + a printed per-dimension summary.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

CASES = ROOT / "evals" / "autonomy_cases.json"
OUT_DIR = ROOT / "eval-results"


def _approx(a, b, tol=0.01) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def grade_risk_policy(case: dict) -> tuple[bool, str]:
    from engine.autonomy.policy import evaluate, Candidate, PortfolioState, RiskLimits
    c = Candidate(**{"strategy_slug": "btd", **case["candidate"]})
    st = PortfolioState(**case.get("state", {"equity": 0, "open_positions": 0, "gross_exposure": 0}))
    limits = RiskLimits(**case["limits"]) if case.get("limits") else RiskLimits()
    d = evaluate(c, st, limits, kill_switch=bool(case.get("kill_switch")))
    exp = case["expect"]
    if d.admit != exp["admit"]:
        return False, f"admit={d.admit} expected {exp['admit']} ({d.reason})"
    if "reason_contains" in exp and exp["reason_contains"].lower() not in d.reason.lower():
        return False, f"reason {d.reason!r} lacks {exp['reason_contains']!r}"
    if "sized_notional" in exp and not _approx(d.sized_notional, exp["sized_notional"]):
        return False, f"sized {d.sized_notional} expected {exp['sized_notional']}"
    return True, d.reason


def grade_promotion(case: dict) -> tuple[bool, str]:
    from engine.autonomy.promote import should_promote
    ok, reason = should_promote(case["metrics"])
    exp = case["expect"]
    if ok != exp["promote"]:
        return False, f"promote={ok} expected {exp['promote']} ({reason})"
    if "reason_contains" in exp and exp["reason_contains"].lower() not in reason.lower():
        return False, f"reason {reason!r} lacks {exp['reason_contains']!r}"
    return True, reason


def grade_scout(case: dict) -> tuple[bool, str]:
    from engine.autonomy import scout
    p = case.get("params", {})
    cands = scout.scan(strategy=p.get("strategy", "btd"), limit=p.get("limit", 5),
                       position_pct=p.get("position_pct", 0.10), equity=p.get("equity"))
    exp = case["expect"]
    if not cands:
        return True, "SKIP (no live market data)"
    if len(cands) < exp.get("min_count", 1):
        return False, f"only {len(cands)} candidates"
    if exp.get("all_paper") and any(c.is_live for c in cands):
        return False, "a candidate is marked live (paper-only violated)"
    if "sized_notional" in exp and any(not _approx(c.intended_notional, exp["sized_notional"]) for c in cands):
        return False, f"notional != {exp['sized_notional']}"
    return True, f"{len(cands)} valid paper candidates"


_GRADERS = {"risk_policy": grade_risk_policy, "promotion": grade_promotion, "scout": grade_scout}


def main() -> int:
    ap = argparse.ArgumentParser(description="AlpaTrade autonomy-agent evals")
    ap.add_argument("--skip-scout", action="store_true", help="skip live-market scout cases")
    args = ap.parse_args()

    cases = json.loads(CASES.read_text())["cases"]
    rows, by_dim = [], defaultdict(lambda: [0, 0])
    for case in cases:
        dim = case["dimension"]
        if args.skip_scout and dim == "scout":
            continue
        grader = _GRADERS.get(dim)
        try:
            ok, detail = grader(case) if grader else (False, f"no grader for {dim}")
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"ERROR: {e}"
        by_dim[dim][0] += int(ok)
        by_dim[dim][1] += 1
        rows.append({"id": case["id"], "dimension": dim, "grade": case.get("grade", ""),
                     "result": "PASS" if ok else "FAIL", "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {dim:12} {case['id']:32} {detail}")

    passed = sum(1 for r in rows if r["result"] == "PASS")
    total = len(rows)
    print("\n" + "=" * 60)
    print(f"AUTONOMY AGENT EVALS  {passed}/{total} = {100*passed/max(total,1):.1f}%")
    for dim, (p, t) in sorted(by_dim.items()):
        print(f"  {dim:14} {p}/{t}   {100*p/max(t,1):.1f}%")
    print("=" * 60)

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = OUT_DIR / f"agent-evals-{ts}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "dimension", "grade", "result", "detail"])
        w.writeheader(); w.writerows(rows)
    print(f"CSV: {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Engine/version stamp recorded on every run (alpatrade.runs.config.engine_stamp) and on every
published backtest (backtest_metrics.engine_stamp). The backtest audit fails a result whose
stamp is missing or older than the engine's minimum valid version.

buy_the_dip results before b47e6de (v0.33.6: true-equity total_return, stop-before-target,
gapped-stop fills, 10 bps default slippage) are invalid.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
MIN_VALID = {"buy_the_dip": ("0.33.6", "b47e6de")}


@lru_cache(maxsize=1)
def app_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    return m.group(1) if m else "0"


@lru_cache(maxsize=1)
def git_sha() -> Optional[str]:
    import os
    for k in ("SOURCE_COMMIT", "GIT_SHA", "GITHUB_SHA"):   # Coolify / CI
        if os.environ.get(k):
            return os.environ[k][:12]
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def engine_for(strategy: Optional[str]) -> str:
    s = (strategy or "").lower()
    return "buy_the_dip" if ("buy_the_dip" in s or s.startswith("btd") or "dip" == s) else (s or "unknown")


def stamp(strategy_or_engine: Optional[str] = "buy_the_dip") -> dict:
    return {"engine": engine_for(strategy_or_engine), "engine_version": app_version(), "git_sha": git_sha()}


def _v(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3]) or (0,)


def is_valid(st: Optional[dict]) -> tuple[bool, str]:
    """(ok, reason). Engines with a minimum version need a stamp at or above it."""
    eng = (st or {}).get("engine")
    if eng in MIN_VALID:
        need, sha = MIN_VALID[eng]
        have = (st or {}).get("engine_version")
        if not have:
            return False, f"no engine/version stamp: {eng} results before {sha} (v{need}) are invalid"
        if _v(have) < _v(need):
            return False, f"{eng} v{have} predates the {sha} (v{need}) backtester fix: result invalid"
        return True, f"{eng} v{have} ≥ v{need} ({sha})"
    if not st or not st.get("engine_version"):
        return False, "no engine/version stamp"
    return True, f"{eng} v{st['engine_version']}"

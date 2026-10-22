"""Paper buy-the-dip = the LIVE runner on paper keys (v0.50.0).

There is no separate paper strategy logic any more: ``PaperRunner`` is ``utils.live_btd_runner.Runner``
(same rules module ``utils/btd_rules``, same event schedule, same broker-side stops/OCO, same
client-order-id scheme) pointed at https://paper-api.alpaca.markets with paper keys, its own
state/lease key (``btd-paper:<account>``) and a recorder that writes mode 'paper'.

Used by scripts/run_paper_strategy.py (PAPER_STRATEGY_ENABLED service) and by
agents/paper_trade_agent.PaperTradeAgent for strategy ``buy_the_dip``. User paper activations
(e.g. Kairi's activation 5) already run the same Runner via utils/user_live_runner.UserRunner(paper=True).
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

from utils.live_btd_config import REQUIRED_PARAM_KEYS, ConfigResult, ConfigError, coerce_params
from utils.live_btd_config import resolve as resolve_config
from utils.live_btd_runner import PassStop, Runner, code_version, state_dir
from utils.live_btd_state import RunnerStateStore

PAPER_BASE = "https://paper-api.alpaca.markets"


class PaperRunner(Runner):
    def __init__(self, api_key: str, secret_key: str, *, strategy: str, database_url: Optional[str],
                 execute: bool = True, log: Optional[logging.Logger] = None, user_email: Optional[str] = None,
                 role: str = "primary", instance: Optional[str] = None):
        if not api_key or not secret_key:
            raise PassStop("paper keys missing")
        self.a = SimpleNamespace(live=execute, ignore_hours=False, role=role, instance=instance, strategy=strategy,
                                 lease_ttl_min=8.0, takeover_min=12.0)
        self.log = log or logging.getLogger("btd.paper")
        self.execute = bool(execute)
        self.paper = True
        self.env = {}
        self.db_url = database_url
        self.user_email = user_email or os.environ.get("BTD_USER_EMAIL", "kaljuvee@gmail.com")
        self.base = PAPER_BASE
        self.headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
        self.role, self.instance = role, instance or os.environ.get("BTD_INSTANCE") or socket.gethostname()
        self.strategy = strategy
        self.account_no = None
        self.here = os.path.join(state_dir(), "paper")
        os.makedirs(self.here, exist_ok=True)
        self.state_path = os.path.join(self.here, "state.json")
        self._store = None; self._store_acct = None

    def recorder(self):
        from utils.user_live_runner import PaperRecorder
        return PaperRecorder(self.db_url, self.user_email, log=self.log)

    def load_sleeves(self, account_number, primary_name):
        return None, []                        # paper account: one strategy, whole account

    def store(self, account_number):
        if not self.db_url or not account_number:
            return None
        if self._store is None or self._store_acct != account_number:
            self._store = RunnerStateStore(self.db_url, f"btd-paper:{account_number}", instance=self.instance,
                                           role=self.role, log=self.log, lease_ttl_s=self.a.lease_ttl_min * 60,
                                           takeover_s=self.a.takeover_min * 60, code_version=code_version())
            self._store_acct = account_number
            try:
                self._store.seed({"positions": {}, "rec": {"pending": []}}, None)   # no-op when it exists
            except Exception as exc:  # noqa: BLE001
                self.log.warning("paper state seed failed: %s", exc)
        return self._store

    def alert(self, subject, lines):
        self.log.error("ALERT (paper, log only) %s: %s", subject, " | ".join(lines))


def paper_config(strategy: str, database_url: Optional[str], params: Optional[Dict[str, Any]] = None) -> ConfigResult:
    """The SAME strategy_configs row as live (by name) unless explicit params are given; explicit
    params (research only) must be a COMPLETE rule set incl. ``execution`` (v0.55.0: no code defaults)."""
    if params:
        params = dict(params); execution = params.pop("execution", None)
        P = coerce_params(params)
        missing = [k for k in REQUIRED_PARAM_KEYS if k not in P]
        if missing or not execution:
            raise ConfigError(f"explicit paper params incomplete: missing {', '.join(missing) or 'execution'}")
        from utils.live_btd_config import merge_execution
        return ConfigResult(params=P, execution=merge_execution(execution), sources={k: "request" for k in params},
                            source="request", db_ok=True, name=strategy, version=0)
    return resolve_config(strategy, {}, database_url=database_url)


def run_paper(runner: PaperRunner, cfg_loader: Callable[[], ConfigResult], *, duration_s: float,
              stop_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Run the live event scheduler against the paper account for ``duration_s`` seconds."""
    from utils.live_btd_scheduler import ConfigCache, Scheduler
    cache = ConfigCache(cfg_loader, lambda: None, log_fn=runner.log_config)
    sched = Scheduler(runner, cache)
    t = threading.Thread(target=sched.loop, daemon=True, name="btd-paper-scheduler")
    t.start()
    end = time.monotonic() + max(0.0, float(duration_s))
    while time.monotonic() < end and t.is_alive():
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(1.0)
    sched.stop.set(); t.join(timeout=300)
    return {"engine": "live_btd_runner (paper keys)", "account": runner.account_no, "strategy": runner.strategy}

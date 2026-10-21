"""v0.50.0 daily backtest-vs-live parity check (pure compare) + paper uses the live runner."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.btd_parity_daily import compare, kind_of  # noqa: E402
from btd_fixtures import DEFAULT_PARAMS  # noqa: E402

P = {**DEFAULT_PARAMS, "symbols": ["AAA", "BBB"], "pos_frac": 0.2}


def bars():
    days = [f"2026-09-{d:02d}" for d in range(1, 26)]
    out = {"AAA": [{"t": d, "o": 100, "h": 101, "l": 99, "c": 100} for d in days],
           "BBB": [{"t": d, "o": 50, "h": 51, "l": 49.5, "c": 50} for d in days]}
    out["AAA"].append({"t": "2026-09-28", "o": 99, "h": 99.5, "l": 95.0, "c": 95.5})   # dip >3% -> entry
    out["BBB"].append({"t": "2026-09-28", "o": 49.6, "h": 50, "l": 47.0, "c": 49.8})     # stop 49.25 hit intraday
    return out


OPEN = {"BBB": {"qty": 10.0, "avg": 50.0, "entry": "2026-09-25"}}


def orders(buy=True, sell_kind="stop"):
    o = []
    if buy:
        o.append({"symbol": "AAA", "side": "buy", "type": "market", "filled_qty": "2", "filled_avg_price": "95.6",
                  "filled_at": "2026-09-28T19:45:10Z", "client_order_id": "btd-AAA-20260928"})
    if sell_kind:
        o.append({"symbol": "BBB", "side": "sell", "type": "stop" if sell_kind == "stop" else "market",
                  "filled_qty": "10", "filled_avg_price": "49.20", "filled_at": "2026-09-28T15:10:00Z",
                  "client_order_id": "btdps-BBB-20260928g"})
    return o


def test_matching_day_is_ok():
    out = compare("2026-09-28", P, orders(), bars(), OPEN, 10_000, 9_500)
    assert out["ok"], out["divergences"]
    assert out["summary"]["bt_buys"] == ["AAA"] and out["summary"]["bt_sells"] == {"BBB": "SL"}


def test_missing_live_entry_and_exit_are_reported():
    out = compare("2026-09-28", P, orders(buy=False, sell_kind=None), bars(), OPEN, 10_000, 9_500)
    msgs = " | ".join(d["msg"] for d in out["divergences"])
    assert not out["ok"] and "AAA: bought in backtest only" in msgs and "BBB: backtest exit SL" in msgs


def test_kind_of():
    assert kind_of({"type": "stop", "client_order_id": "btdps-X-1g"}) == "stop"
    assert kind_of({"type": "limit", "client_order_id": "btdtp-X-1"}) == "target"
    assert kind_of({"type": "market", "client_order_id": "btdx-X-1"}) == "market"


def test_paper_runner_is_the_live_runner_on_paper_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("BTD_STATE_DIR", str(tmp_path))
    from utils.btd_paper_runner import PAPER_BASE, PaperRunner, paper_config
    from utils.live_btd_runner import Runner
    r = PaperRunner("k", "s", strategy="buy_the_dip_mag7_minhold_live", database_url=None)
    assert isinstance(r, Runner) and type(r)._run is Runner._run and r.base == PAPER_BASE
    from btd_fixtures import DEFAULT_EXECUTION as DX
    cfg = paper_config("x", None, {**P, "symbols": "AAPL", "dip": 3, "tp": 8, "sl": 1.5, "min_hold": 3, "max_hold": 3,
                                   "pos_frac": 0.142857, "execution": DX})
    assert cfg.db_ok and cfg.params["sl"] == 1.5 and cfg.params["regime_filter"] == ""


def test_paper_agent_buy_the_dip_delegates_to_live_runner(monkeypatch):
    import agents.paper_trade_agent as pta
    seen = {}
    monkeypatch.setattr(pta.PaperTradeAgent, "_run_btd_shared",
                        lambda self, req, syms, res, dur, ev: seen.setdefault("ok", (syms, res)) and {"session_id": "s"})
    out = pta.PaperTradeAgent(alpaca_api_key="k", alpaca_secret_key="s").run(
        {"strategy": "buy_the_dip", "symbols": ["AAPL"], "duration_seconds": 0})
    assert "ok" in seen and out["session_id"] == "s"

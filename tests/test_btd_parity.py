"""CI parity gate (v0.50.0): the SAME price history through the event backtester and the REAL
live Runner (utils/live_btd_runner.Runner._run, every scheduled event of every session, against
the mocked Alpaca in tests/btd_fake_alpaca.py) must produce identical trades. Any drift in
entries, stops, targets, holds, sizing, exposure cap, regime filter or exemptions fails the build.
Paper uses the same Runner (UserRunner(paper=True) / PaperRunner), so it is covered too."""
import copy
import logging
import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import utils.live_btd_runner as LR  # noqa: E402
from btd_fake_alpaca import ET, FakeAlpaca  # noqa: E402
from utils import btd_event_backtest as BT  # noqa: E402
from utils.live_btd_config import DEFAULT_EXECUTION, DEFAULT_PARAMS, ConfigResult  # noqa: E402
from utils.live_btd_scheduler import session_events  # noqa: E402
from utils.live_btd_state import LeaseResult  # noqa: E402

SYMS = ["AAA", "BBB", "CCC", "DDD"]


def trading_days(start: date, n: int):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5: out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def synth(days, seed, syms):
    rnd = random.Random(seed); bars = {}
    for i, s in enumerate(syms):
        px = 100.0 + 20 * i; out = []
        for d in days:
            o = px * math.exp(rnd.gauss(0, 0.018))                       # overnight gaps
            c = o * math.exp(rnd.gauss(0, 0.022))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.012)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.012)))
            out.append({"t": d, "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2)})
            px = c
        bars[s] = out
    return bars


class FakeStore:
    def __init__(self): self.state = {"positions": {}}
    def acquire(self): return LeaseResult(ok=True, act=True, reason="test", state=copy.deepcopy(self.state),
                                          version=1, deadline_mono=float("inf"))
    peek = acquire
    def save(self, st): self.state = copy.deepcopy(st); return True


class FakeRunner(LR.Runner):
    def __init__(self, fake, tmp):
        self.a = SimpleNamespace(live=True, ignore_hours=False, role="primary", instance="parity",
                                 strategy="parity", lease_ttl_min=8, takeover_min=12)
        self.log = logging.getLogger("parity"); self.execute = True
        self.here = str(tmp); self.state_path = str(tmp / "state.json")
        self.env = {}; self.db_url = None; self.user_email = "t@alpatrade-test.invalid"
        self.account_no = fake.account; self.base = "https://fake-trading"; self.role = "primary"
        self.instance = "parity"; self.strategy = "parity"; self.headers = {}
        self.fake = fake; self._st = FakeStore(); self.alerts = []
    def get(self, url, **q): return self.fake.get(url, **q)
    def post_order(self, body): return self.fake.post(body)
    def broker_call(self, m, p, body=None): return self.fake.call(m, p, body)
    def store(self, acct): return self._st
    def recorder(self): return None
    def alert(self, subject, lines): self.alerts.append((subject, lines))


def run_live(bars, P, days, start, cash, tmp, monkeypatch, exempt=None):
    fake = FakeAlpaca(bars, days, cash)
    r = FakeRunner(fake, tmp)
    cfg = ConfigResult(params=P, execution=DEFAULT_EXECUTION, sources={}, source="test", db_ok=True,
                       name="parity", version=1)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None): return fake.now.astimezone(tz) if tz else fake.now
    monkeypatch.setattr(LR, "datetime", _DT)
    monkeypatch.setattr(LR.time, "sleep", lambda *_: None)
    monkeypatch.setenv("BTD_STOP_EXEMPT", exempt or "")
    for d in [x for x in days if x >= start]:
        fake.set_day(d)
        dd = date.fromisoformat(d)
        sess = {"open": datetime.combine(dd, datetime.min.time().replace(hour=9, minute=30), ET),
                "close": datetime.combine(dd, datetime.min.time().replace(hour=16), ET)}
        opened = touched = False
        for ev in session_events(sess, P["entry_window"], P["close_window"], protect=True):
            if not opened and ev.at >= sess["open"]:
                fake.now = sess["open"]; fake.open_print(); opened = True
            if opened and not touched and ev.at >= sess["open"] + timedelta(minutes=30):
                fake.intraday(); touched = True     # whole-day range before the first hourly check
            fake.now = ev.at
            res = r.run([ev.kind if ev.kind != "protect" else "protect"], cfg)
            assert res.code in (0, None), (d, ev.key, res.code, res.reason)
        fake.end_of_day()
    return fake, r


def live_trades(fake):
    """Pair fills into round trips (one position per symbol at a time)."""
    out, cur = [], {}
    for f in fake.fills:
        s = f["sym"]
        if f["side"] == "buy":
            cur[s] = {"sym": s, "entry_date": f["day"], "qty": round(f["qty"], 6), "entry_px": round(f["px"], 4),
                      "sold": 0.0, "proceeds": 0.0}
        else:
            t = cur[s]; t["sold"] += f["qty"]; t["proceeds"] += f["qty"] * f["px"]
            if t["sold"] >= t["qty"] - 1e-6:
                out.append((s, t["entry_date"], t["qty"], t["entry_px"], f["day"], round(t["proceeds"] / t["sold"], 4)))
                del cur[s]
    return out, sorted(cur)


def bt_trades(res):
    return ([(t.sym, t.entry_date, round(t.qty, 6), round(t.entry_px, 4), t.exit_date, round(t.exit_px, 4))
             for t in res.trades], sorted({t.sym for t in []}))


PARAMS = {**DEFAULT_PARAMS, "symbols": SYMS, "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
          "pos_frac": 1 / 7}


@pytest.mark.parametrize("seed,extra,exempt", [
    (1, {}, None),
    (2, {}, None),
    (3, {"max_exposure": 3000.0}, None),
    (4, {"pos_frac": 0.3}, None),                         # whole shares + fraction (OCO + frac stop)
    (5, {"min_hold": 1, "max_hold": 5}, None),            # TP/OCO days before the time exit
    (6, {}, "AAA:2026-12-31"),                            # exemption: time exit only
])
def test_backtest_equals_live_runner(seed, extra, exempt, tmp_path, monkeypatch):
    days = trading_days(date(2026, 6, 1), 70)
    bars = synth(days, seed, SYMS)
    P = {**PARAMS, **extra}
    start = days[25]
    fake, r = run_live(bars, P, days, start, 10_000.0, tmp_path, monkeypatch, exempt)
    bt = BT.run(bars, P, start, days[-1], 10_000.0, exempt_spec=exempt)
    lt, lopen = live_trades(fake)
    btt, _ = bt_trades(bt)
    assert len(lt) >= 5, "scenario should trade"
    key = lambda x: (x[1], x[0], x[4])  # noqa: E731
    lt, btt = sorted(lt, key=key), sorted(btt, key=key)
    assert [x[:3] + (x[4],) for x in lt] == [x[:3] + (x[4],) for x in btt]      # same trades, qty, days
    for a, b in zip(lt, btt):                                                    # same prices (float noise)
        assert abs(a[3] - b[3]) < 1e-3 and abs(a[5] - b[5]) < 1e-3, (a, b)
    assert sorted(fake.pos) == sorted(bt.open_positions)
    eq_bt = bt.equity[-1][1]
    eq_live = fake.cash + sum(p["qty"] * fake.cur[s] for s, p in fake.pos.items())
    assert abs(eq_bt - eq_live) < 0.05
    assert not [a for a in r.alerts if any("UNPROTECTED" in x for x in a[1])]



def test_regime_filter_parity(tmp_path, monkeypatch):
    days = trading_days(date(2026, 6, 1), 70)
    bars = synth(days, 7, SYMS + ["IDX"])
    P = {**PARAMS, "regime_filter": "IDX"}
    start = days[25]
    fake, r = run_live(bars, P, days, start, 10_000.0, tmp_path, monkeypatch)
    bt = BT.run({s: bars[s] for s in SYMS}, P, start, days[-1], 10_000.0, regime_bars={"IDX": bars["IDX"]})
    lt, _ = live_trades(fake)
    btt, _ = bt_trades(bt)
    key = lambda x: (x[1], x[0], x[4])  # noqa: E731
    assert bt.blocked, "regime filter should block some days"
    assert [x[:3] + (x[4],) for x in sorted(lt, key=key)] == [x[:3] + (x[4],) for x in sorted(btt, key=key)]
    assert not any(t[1] in bt.blocked for t in lt)


# v0.51.0: every user-editable rule key goes through the same parity gate
def _compare(fake, bt, r, allow_unprotected=False):
    lt, _ = live_trades(fake)
    btt, _ = bt_trades(bt)
    key = lambda x: (x[1], x[0], x[4])  # noqa: E731
    lt, btt = sorted(lt, key=key), sorted(btt, key=key)
    assert [x[:3] + (x[4],) for x in lt] == [x[:3] + (x[4],) for x in btt]
    for a, b in zip(lt, btt):
        assert abs(a[3] - b[3]) < 1e-3 and abs(a[5] - b[5]) < 1e-3, (a, b)
    assert sorted(fake.pos) == sorted(bt.open_positions)
    eq_live = fake.cash + sum(p["qty"] * fake.cur[s] for s, p in fake.pos.items())
    assert abs(bt.equity[-1][1] - eq_live) < 0.05
    if not allow_unprotected:   # exit_day: the first stop can be rejected (price already below) -> alert + open sell
        assert not [a for a in r.alerts if any("UNPROTECTED" in x for x in a[1])]
    return lt


@pytest.mark.parametrize("seed,extra", [
    (11, {"stop_mode": "atr", "stop_k": 1.0, "tp_mult": 2.0}),
    (12, {"stop_mode": "stdev", "stop_k": 1.5, "tp_mult": 0.0}),
    (13, {"stop_timing": "exit_day", "min_hold": 2, "max_hold": 4}),
    (14, {"vol_filter": "atr", "vol_max": 3.2}),
    (15, {"max_exposure_pct": 30.0}),
    (16, {"stop_mode": "atr", "stop_k": 0.8, "tp_mult": 3.0, "pos_frac": 0.3, "min_hold": 1, "max_hold": 5}),
])
def test_user_param_keys_parity(seed, extra, tmp_path, monkeypatch):
    days = trading_days(date(2026, 6, 1), 70)
    bars = synth(days, seed, SYMS)
    P = {**PARAMS, **extra}
    start = days[25]
    fake, r = run_live(bars, P, days, start, 10_000.0, tmp_path, monkeypatch)
    bt = BT.run(bars, P, start, days[-1], 10_000.0)
    lt = _compare(fake, bt, r, allow_unprotected=extra.get("stop_timing") == "exit_day")
    assert len(lt) >= 3, "scenario should trade"
    base = BT.run(bars, PARAMS, start, days[-1], 10_000.0)
    assert bt_trades(bt)[0] != bt_trades(base)[0], "the key must change behaviour in this scenario"


def test_spy_vol_filter_and_sma_regime_parity(tmp_path, monkeypatch):
    days = trading_days(date(2026, 6, 1), 70)
    bars = synth(days, 17, SYMS + ["SPY"])
    P = {**PARAMS, "vol_filter": "spy_atr", "vol_max": 2.6, "regime_filter": "SPY", "regime_mode": "sma",
         "regime_sma": 10}
    start = days[25]
    fake, r = run_live(bars, P, days, start, 10_000.0, tmp_path, monkeypatch)
    bt = BT.run({s: bars[s] for s in SYMS}, P, start, days[-1], 10_000.0, regime_bars={"SPY": bars["SPY"]})
    assert bt.blocked, "filters should block some days"
    reasons = set(v.split()[1] for v in bt.blocked.values())
    _compare(fake, bt, r)
    assert reasons, reasons

"""CI parity gate (v0.50.0): the SAME price history through the event backtester and the REAL
live Runner (utils/live_btd_runner.Runner._run, every scheduled event of every session, against
the mocked Alpaca in tests/btd_fake_alpaca.py) must produce identical trades. Any drift in
entries, stops, targets, holds, sizing, exposure cap, regime filter or exemptions fails the build.
Paper uses the same Runner (UserRunner(paper=True) / PaperRunner), so it is covered too."""
import copy
import logging
import math
import random
import re
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
from btd_fixtures import DEFAULT_EXECUTION, DEFAULT_PARAMS  # noqa: E402
from utils.live_btd_config import ConfigResult  # noqa: E402
from utils.live_btd_scheduler import session_events  # noqa: E402
from utils.btd_rules import stop_exempt_map  # noqa: E402
from utils.live_btd_state import LeaseResult  # noqa: E402

SYMS = ["AAA", "BBB", "CCC", "DDD"]


def trading_days(start: date, n: int):
    """NYSE sessions (weekends and full-day holidays skipped, e.g. Fri 2026-07-03)."""
    from engine.reporting.annualize import nyse_holidays
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5 and d not in nyse_holidays(d.year): out.append(d.isoformat())
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
    P = {**P, "stop_exempt": exempt or {}}          # v0.55.0: exemptions are DB params
    cfg.params = P
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
        # v0.52.x: the post pass ran while the prior-session DAY stops were still 'new'; after
        # they expire every carried position must hold a next-session sell (stop / exit).
        ex = set(stop_exempt_map(P, dd))
        fake.overnight_gaps = getattr(fake, "overnight_gaps", []) + [
            (d, s) for s, p in fake.pos.items()
            if p["qty"] > 1e-9 and s not in ex and fake._held(s) + 1e-6 < p["qty"]]
    return fake, r


def live_trades(fake):
    """Pair fills into round trips (one position per symbol at a time)."""
    out, cur = [], {}
    for f in fake.fills:
        s = f["sym"]
        if f["side"] == "buy":
            m = re.search(r"-(\d{8})$", f["cid"])      # entry cid carries the TRADE day (v0.55.0 ext buys)
            ed = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else f["day"]
            cur[s] = {"sym": s, "entry_date": ed, "qty": round(f["qty"], 6), "entry_px": round(f["px"], 4),
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
        assert not getattr(fake, "overnight_gaps", []), fake.overnight_gaps[:5]
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


# v0.53.0: hold age = NYSE trading sessions, one definition for backtest, paper and live
def test_hold_age_trading_sessions():
    from utils import btd_rules as R
    fri, mon = date(2026, 10, 16), date(2026, 10, 19)
    assert R.hold_age(fri, fri) == 0 and R.hold_age(fri, mon) == 1        # weekend does not count
    assert R.hold_age(fri, date(2026, 10, 21)) == 3
    assert not R.time_exit_due(fri, mon, 3) and R.time_exit_due(fri, date(2026, 10, 21), 3)
    assert not R.exit_eligible(fri, date(2026, 10, 20), 3) and R.exit_eligible(fri, date(2026, 10, 21), 3)
    # holiday: Thu 2026-07-02 buy; Fri 07-03 (Jul 4 observed) closed -> Mon 07-06 is session 1
    thu = date(2026, 7, 2)
    assert R.hold_age(thu, date(2026, 7, 6)) == 1 and R.hold_age(thu, date(2026, 7, 8)) == 3
    # Thanksgiving (closed) + half day Fri 11-27 counts as a session
    assert R.hold_age(date(2026, 11, 25), date(2026, 11, 27)) == 1
    # exit_day stop timing follows the same session count
    P = {"stop_timing": "exit_day", "min_hold": 2}
    assert not R.stop_live(fri, date(2026, 10, 19), P) and R.stop_live(fri, date(2026, 10, 20), P)


@pytest.mark.parametrize("seed,extra", [
    (22, {}),
    (27, {"dip": 1.5, "stop_timing": "exit_day", "min_hold": 2, "max_hold": 4}),
])
def test_hold_over_weekend_and_holiday_parity(seed, extra, tmp_path, monkeypatch):
    """Window spans weekends and the Jul 3 2026 holiday. Wide TP/SL -> exits are time exits only,
    so every round trip must last exactly max_hold NYSE sessions in BOTH backtest and live."""
    from utils import btd_rules as R
    days = trading_days(date(2026, 5, 15), 50)
    assert "2026-07-03" not in days
    bars = synth(days, seed, SYMS)
    P = {**PARAMS, "tp": 60.0, "sl": 40.0, "dip": 1.0, **extra}
    start = days[25]
    fake, r = run_live(bars, P, days, start, 10_000.0, tmp_path, monkeypatch)
    bt = BT.run(bars, P, start, days[-1], 10_000.0)
    lt = _compare(fake, bt, r, allow_unprotected=True)
    assert len(lt) >= 3, "scenario should trade"
    ages = {R.hold_age(date.fromisoformat(t[1]), date.fromisoformat(t[4])) for t in lt}
    assert ages == {P["max_hold"]}, ages
    assert any(date.fromisoformat(t[1]).weekday() == 4 for t in lt), "needs a Friday buy"
    assert any(t[1] <= "2026-07-02" < t[4] for t in lt), "needs a hold across the holiday"


# ================================================================ v0.55.0: 24/5 (extended sessions)
import utils.btd_rules as RR  # noqa: E402
from utils.live_btd_scheduler import ext_events  # noqa: E402


def synth_ext(bars, days, seed, shock=None):
    """5-min extended-session bars (ts = bar END, ET) bridging each close to the next open:
    {sym: {day: [(ts, o, h, l, c), ...]}} covering 16:05 .. 09:30 next session. ``shock`` =
    {(sym, day): pct} drops the post session of that day by pct (an after-hours breach)."""
    rnd = random.Random(seed); out = {}
    for s, bl in bars.items():
        by = {b["t"]: b for b in bl}; out[s] = {}
        for d, nd in zip(days, days[1:]):
            c0, o1 = float(by[d]["c"]), float(by[nd]["o"])
            t = datetime.combine(date.fromisoformat(d), datetime.min.time().replace(hour=16, minute=5), ET)
            end = datetime.combine(date.fromisoformat(nd), datetime.min.time().replace(hour=9, minute=30), ET)
            n = int((end - t).total_seconds() // 300) + 1
            k = (shock or {}).get((s, d), 0.0)
            px, rows = c0, []
            for i in range(n):
                frac = (i + 1) / n
                tgt = c0 + (o1 - c0) * frac
                if k and i < 40: tgt *= (1 - k / 100 * min(1, (i + 1) / 6))
                o = px; px = tgt * math.exp(rnd.gauss(0, 0.002))
                h = max(o, px) * (1 + abs(rnd.gauss(0, 0.001))); l = min(o, px) * (1 - abs(rnd.gauss(0, 0.001)))
                rows.append((t + timedelta(minutes=5 * i), round(o, 2), round(h, 2), round(l, 2), round(px, 2)))
            out[s][d] = rows
    return out


def run_live_ext(bars, xw, P, days, start, cash, tmp, monkeypatch, execution):
    """run_live + the scheduler's 'ext' events between sessions (same Runner path as paper/live)."""
    fake = FakeAlpaca(bars, days, cash)
    r = FakeRunner(fake, tmp)
    cfg = ConfigResult(params=P, execution=execution, sources={}, source="test", db_ok=True, name="parity", version=7)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None): return fake.now.astimezone(tz) if tz else fake.now
    monkeypatch.setattr(LR, "datetime", _DT)
    monkeypatch.setattr(LR.time, "sleep", lambda *_: None)
    run_days = [x for x in days if x >= start]
    for d, nd in zip(run_days, run_days[1:] + [None]):
        fake.set_day(d)
        dd = date.fromisoformat(d)
        sess = {"open": datetime.combine(dd, datetime.min.time().replace(hour=9, minute=30), ET),
                "close": datetime.combine(dd, datetime.min.time().replace(hour=16), ET)}
        opened = touched = False
        for ev in session_events(sess, P["entry_window"], P["close_window"], protect=True):
            if not opened and ev.at >= sess["open"]:
                fake.now = sess["open"]; fake.open_print(); opened = True
            if opened and not touched and ev.at >= sess["open"] + timedelta(minutes=30):
                fake.intraday(); touched = True
            fake.now = ev.at
            res = r.run([ev.kind], cfg)
            assert res.code in (0, None), (d, ev.key, res.code, res.reason)
        fake.end_of_day()
        if nd is None:
            break
        bars_at = {s: {b[0]: b for b in xw.get(s, {}).get(d, [])} for s in xw}
        sched = {e.at for dd2 in (d, nd) for e in ext_events(
            {"open": datetime.combine(date.fromisoformat(dd2), datetime.min.time().replace(hour=9, minute=30), ET),
             "close": datetime.combine(date.fromisoformat(dd2), datetime.min.time().replace(hour=16), ET)},
            overnight_tonight=(date.fromisoformat(dd2) + timedelta(days=1)).isoformat() in days)}
        for ts in sorted({t for m in bars_at.values() for t in m}):
            fake.ext_tick(ts, bars_at)
            if ts in sched and RR.session_of(ts) != "regular":
                res = r.run(["ext"], cfg)
                assert res.code in (0, None), (d, ts, res.code, res.reason)
    return fake, r


EXT_EXEC = {**DEFAULT_EXECUTION, "extended_hours_exit": {**DEFAULT_EXECUTION["extended_hours_exit"], "enabled": True}}


def _ext_case(seed, mode, tmp_path, monkeypatch, shock_n=6, extra=None):
    days = trading_days(date(2026, 6, 1), 60)
    bars = synth(days, seed, SYMS)
    rnd = random.Random(seed + 100)
    shock = {(rnd.choice(SYMS), rnd.choice(days[28:-2])): 4.0 for _ in range(shock_n)}
    xw = synth_ext(bars, days, seed, shock)
    P = {**PARAMS, "session_mode": mode, **(extra or {})}
    start = days[25]
    fake, r = run_live_ext(bars, xw, P, days, start, 10_000.0, tmp_path, monkeypatch, EXT_EXEC)
    bt = BT.run(bars, P, start, days[-1], 10_000.0, ext_windows=xw, execution=EXT_EXEC, config_version=7)
    return fake, r, bt


@pytest.mark.parametrize("seed", [21, 22, 23])
def test_ext_stops_parity_after_hours_breach(seed, tmp_path, monkeypatch):
    """stops_24_5: an after-hours drop through the stop is sold in the extended session by the live
    Runner (cancel resting stop -> ext DAY limit -> reprice -> market at the open) exactly like the
    backtester."""
    fake, r, bt = _ext_case(seed, "stops_24_5", tmp_path, monkeypatch)
    lt = _compare(fake, bt, r, allow_unprotected=True)
    assert bt.ext_exits >= 1, "scenario should include an extended-hours stop exit"
    ext_fills = [f for f in fake.fills if f["cid"].split("-")[-1] in ("e", "r1", "r2") or "-e-" in f["cid"]]
    assert len(ext_fills) == bt.ext_exits
    assert bt.config_version == 7 and lt


@pytest.mark.parametrize("seed", [31, 32])
def test_full_24_5_parity(seed, tmp_path, monkeypatch):
    """full_24_5: entries, take-profits, stops in post/overnight/pre sessions -- same trades."""
    fake, r, bt = _ext_case(seed, "full_24_5", tmp_path, monkeypatch, extra={"min_hold": 1, "max_hold": 4, "tp": 3.0})
    _compare(fake, bt, r, allow_unprotected=True)
    assert any(t.entry_date and t.entry_px for t in bt.trades)


def test_regular_mode_ignores_ext_bars(tmp_path, monkeypatch):
    """session_mode=regular: identical to the pre-v0.55 replay even when ext bars are supplied."""
    days = trading_days(date(2026, 6, 1), 60); bars = synth(days, 5, SYMS)
    xw = synth_ext(bars, days, 5, {("AAA", days[30]): 6.0})
    P = {**PARAMS, "session_mode": "regular"}
    a = BT.run(bars, P, days[25], days[-1], 10_000.0, ext_windows=xw, execution=EXT_EXEC)
    b = BT.run(bars, PARAMS, days[25], days[-1], 10_000.0)
    assert [(t.sym, t.exit_date, t.exit_px) for t in a.trades] == [(t.sym, t.exit_date, t.exit_px) for t in b.trades]
    assert a.ext_exits == 0

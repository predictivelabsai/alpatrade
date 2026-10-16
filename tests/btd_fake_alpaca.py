"""Mocked Alpaca (trading + data API) for the backtest/live parity test (v0.50.0).

Fills follow the shared market model in utils.btd_rules (slippage, gap fills, TAF+CAT) so the
only thing the parity test can catch is a difference in STRATEGY decisions. It enforces the
broker rules the runner must respect: GTC rejected for fractional qty, sell stop must be below
the last price, sells limited to qty_available, duplicate client_order_id, DAY orders expire at
the end of their session (DAY orders placed after the close belong to the next session).
"""
from __future__ import annotations

import itertools
import json
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

import utils.btd_rules as R

ET = ZoneInfo("America/New_York")
_ids = itertools.count(1)


def _err(code: int, msg: str):
    r = requests.Response(); r.status_code = code; r._content = json.dumps({"message": msg}).encode()
    e = requests.HTTPError(f"{code} {msg}"); e.response = r
    return e


class FakeAlpaca:
    def __init__(self, bars: Dict[str, List[Dict[str, Any]]], days: List[str], cash: float,
                 slippage_bps: float = R.DEFAULT_SLIPPAGE_BPS, account: str = "PARITY1"):
        self.by = {s: {str(b["t"])[:10]: b for b in v} for s, v in bars.items()}
        self.days, self.cash, self.slip, self.account = days, float(cash), slippage_bps, account
        self.pos: Dict[str, Dict[str, float]] = {}
        self.orders: List[Dict[str, Any]] = []
        self.fills: List[Dict[str, Any]] = []
        self.day: Optional[str] = None
        self.now = datetime(2000, 1, 1, tzinfo=ET)
        self.cur: Dict[str, float] = {}

    # ---------------------------------------------------------------- market clock / prices
    def is_open(self) -> bool:
        t = self.now.astimezone(ET)
        return self.day == t.date().isoformat() and time(9, 30) <= t.time() < time(16, 0)

    def session_of_new_order(self) -> str:
        t = self.now.astimezone(ET)
        if self.day == t.date().isoformat() and t.time() < time(16, 0):
            return self.day
        nxt = [d for d in self.days if d > (self.day or "")]
        return nxt[0] if nxt else "9999-12-31"

    def set_day(self, d: str):
        self.day = d
        for s, by in self.by.items():
            prev = [k for k in sorted(by) if k < d]
            if prev: self.cur[s] = float(by[prev[-1]]["c"])

    def open_print(self):
        for s, by in self.by.items():
            if self.day in by: self.cur[s] = float(by[self.day]["o"])
        for o in self._open():
            if o["side"] == "sell" and o["type"] == "stop" and o["_session_ok"](self.day):
                f = R.stop_fill_at_open(float(o["stop_price"]), self.cur[o["symbol"]])
                if f is not None: self._fill(o, R.slip_sell(f, self.slip))
            elif o["type"] == "market" and o["_session_ok"](self.day):
                self._fill(o, R.slip_sell(self.cur[o["symbol"]], self.slip) if o["side"] == "sell"
                           else R.slip_buy(self.cur[o["symbol"]], self.slip))

    def intraday(self):
        for o in self._open():
            if o["side"] == "sell" and o["type"] == "stop":
                b = self.by[o["symbol"]].get(self.day)
                f = b and R.stop_fill_intraday(float(o["stop_price"]), float(b["l"]))
                if f: self._fill(o, R.slip_sell(f, self.slip))
        for o in self._open():
            if o["side"] == "sell" and o["type"] == "limit":
                b = self.by[o["symbol"]].get(self.day)
                f = b and R.limit_fill_intraday(float(o["limit_price"]), float(b["h"]))
                if f: self._fill(o, f)
        for s, by in self.by.items():
            if self.day in by: self.cur[s] = float(by[self.day]["c"])

    def end_of_day(self):
        for o in self._open():
            if o["time_in_force"] == "day" and o["_session"] <= self.day:
                o["status"] = "expired"

    # ---------------------------------------------------------------- order book
    def _open(self):
        return [o for o in self.orders if o["status"] in ("new", "accepted", "held")]

    def _held(self, sym):
        return sum(float(o["qty"]) for o in self._open() if o["symbol"] == sym and o["side"] == "sell"
                   and o.get("_leg_of") is None)

    def _fill(self, o, px):
        sym = o["symbol"]
        if o["side"] == "buy":
            qty = round(float(o["notional"]) / px, 9)
            p = self.pos.setdefault(sym, {"qty": 0.0, "avg": 0.0})
            p["avg"] = (p["avg"] * p["qty"] + px * qty) / (p["qty"] + qty); p["qty"] = round(p["qty"] + qty, 9)
            self.cash -= float(o["notional"]) + R.buy_fees(qty)
        else:
            qty = float(o["qty"]); p = self.pos[sym]
            self.cash += qty * px - R.sell_fees(qty)
            p["qty"] = round(p["qty"] - qty, 9)
            if p["qty"] <= 1e-9: del self.pos[sym]
        o.update(status="filled", filled_qty=str(qty), filled_avg_price=str(px), filled_at=self.now.isoformat())
        self.fills.append({"day": self.day, "sym": sym, "side": o["side"], "qty": qty, "px": px,
                           "type": o["type"], "cid": o["client_order_id"]})
        sib = o.get("_oco")
        if sib is not None and sib["status"] in ("new", "accepted", "held"):
            sib["status"] = "canceled"
        par = o.get("_leg_of")
        if par is not None:
            par["status"] = "filled"

    def post(self, body):
        cid = body.get("client_order_id")
        if any(o["client_order_id"] == cid for o in self.orders):
            return {}
        sym, side = body["symbol"], body["side"]
        if side == "sell":
            qty = float(body["qty"])
            if body.get("time_in_force") == "gtc" and abs(qty - round(qty)) > 1e-9:
                raise _err(422, "fractional orders must be DAY orders (time_in_force)")
            have = self.pos.get(sym, {}).get("qty", 0.0) - self._held(sym)
            if qty > have + 1e-9:
                raise _err(403, f"insufficient qty available for order (requested: {qty}, available: {have})")
            stop = body.get("stop_price") or (body.get("stop_loss") or {}).get("stop_price")
            if stop and float(stop) >= self.cur[sym]:
                raise _err(422, "stop price must be less than current price")
        sess = self.session_of_new_order()
        o = {"id": f"o{next(_ids)}", "client_order_id": cid, "symbol": sym, "side": side, "type": body["type"],
             "qty": body.get("qty"), "notional": body.get("notional"), "time_in_force": body["time_in_force"],
             "stop_price": body.get("stop_price"), "limit_price": body.get("limit_price"),
             "order_class": body.get("order_class"), "status": "new", "filled_qty": "0", "filled_avg_price": None,
             "_session": sess, "_session_ok": (lambda d, s=sess: d >= s), "legs": []}
        self.orders.append(o)
        if body.get("order_class") == "oco":
            o["limit_price"] = body["take_profit"]["limit_price"]
            leg = dict(o, id=f"o{next(_ids)}", client_order_id=cid + "-sl", type="stop", limit_price=None,
                       stop_price=body["stop_loss"]["stop_price"], order_class=None, legs=[], _leg_of=o)
            o["_oco"], leg["_oco"] = leg, o
            o["legs"] = [leg]; self.orders.append(leg)
        if o["type"] == "market" and self.is_open():
            px = self.cur[sym]
            self._fill(o, R.slip_buy(px, self.slip) if side == "buy" else R.slip_sell(px, self.slip))
        return self._pub(o)

    def call(self, method, path, body=None):
        if method == "DELETE" and path.startswith("/v2/orders/"):
            oid = path.rsplit("/", 1)[1]
            for o in self.orders:
                if o["id"] == oid and o["status"] in ("new", "accepted", "held"):
                    o["status"] = "canceled"
                    for leg in o.get("legs") or []:
                        if leg["status"] in ("new", "accepted", "held"): leg["status"] = "canceled"
                    par = o.get("_leg_of")
                    if par is not None and par["status"] in ("new", "accepted", "held"): par["status"] = "canceled"
            return {}
        raise _err(400, f"unsupported {method} {path}")

    @staticmethod
    def _pub(o):
        out = {k: v for k, v in o.items() if not k.startswith("_") and k != "legs"}
        out["legs"] = [FakeAlpaca._pub(x) for x in o.get("legs") or []]
        return out

    # ---------------------------------------------------------------- GET routing
    def _position(self, s):
        p = self.pos[s]; px = self.cur[s]
        return {"symbol": s, "qty": f"{p['qty']:.9f}".rstrip("0").rstrip("."),
                "qty_available": f"{max(0.0, p['qty'] - self._held(s)):.9f}".rstrip("0").rstrip(".") or "0",
                "avg_entry_price": str(p["avg"]), "current_price": str(px), "market_value": str(p["qty"] * px),
                "unrealized_pl": str(p["qty"] * (px - p["avg"])), "unrealized_plpc": str(px / p["avg"] - 1)}

    def get(self, url, **q):
        path = url.split("://", 1)[1].split("/", 1)[1] if "://" in url else url
        path = "/" + path
        if path == "/v2/clock":
            t = self.now.astimezone(ET); d = t.date().isoformat()
            nxt = [x for x in self.days if x > d or (x == d and t.time() < time(9, 30))]
            nd = date.fromisoformat(nxt[0]) if nxt else t.date() + timedelta(days=1)
            cd = date.fromisoformat(self.day) if self.is_open() else nd
            return {"is_open": self.is_open(),
                    "next_open": datetime.combine(nd, time(9, 30), ET).isoformat(),
                    "next_close": datetime.combine(cd, time(16, 0), ET).isoformat()}
        if path == "/v2/account":
            eq = self.cash + sum(p["qty"] * self.cur[s] for s, p in self.pos.items())
            return {"account_number": self.account, "equity": str(eq), "cash": str(self.cash),
                    "non_marginable_buying_power": str(self.cash), "buying_power": str(self.cash),
                    "daytrade_count": 0, "pattern_day_trader": False, "trading_blocked": False,
                    "account_blocked": False}
        if path == "/v2/positions":
            return [self._position(s) for s in sorted(self.pos)]
        if path.startswith("/v2/positions/"):
            s = path.rsplit("/", 1)[1]
            if s not in self.pos: raise _err(404, "position does not exist")
            return self._position(s)
        if path == "/v2/orders":
            st = q.get("status", "open"); syms = set(str(q.get("symbols") or "").split(",")) - {""}
            src = self._open() if st == "open" else [o for o in self.orders if o["status"] not in ("new", "accepted", "held")]
            src = [o for o in src if o.get("_leg_of") is None]
            return [self._pub(o) for o in src if not syms or o["symbol"] in syms]
        if path == "/v2/orders:by_client_order_id":
            for o in self.orders:
                if o["client_order_id"] == q.get("client_order_id"): return self._pub(o)
            raise _err(404, "order not found")
        if path.startswith("/v2/orders/"):
            oid = path.rsplit("/", 1)[1]
            for o in self.orders:
                if o["id"] == oid: return self._pub(o)
            raise _err(404, "order not found")
        if path.startswith("/v2/assets/"):
            return {"symbol": path.rsplit("/", 1)[1], "tradable": True, "fractionable": True}
        if path == "/v2/stocks/snapshots":
            out = {}
            for s in str(q["symbols"]).split(","):
                if s not in self.by: continue
                ks = [k for k in sorted(self.by[s]) if k <= (self.day or "")]
                today = self.by[s].get(self.day)
                prev = self.by[s][ks[-2]] if today and len(ks) > 1 else (self.by[s][ks[-1]] if ks else {})
                out[s] = {"latestTrade": {"p": self.cur.get(s)},
                          "dailyBar": ({"t": self.day + "T04:00:00Z", "c": self.cur.get(s)} if today and self.is_open()
                                       else {"t": (ks[-1] if ks else "") + "T04:00:00Z", "c": float((self.by[s].get(ks[-1]) or {}).get("c", 0)) if ks else 0}),
                          "prevDailyBar": {"c": float(prev.get("c", 0)) if prev else 0}}
            return out
        if path == "/v2/stocks/bars":
            start = str(q.get("start"))[:10]
            return {"bars": {s: [dict(self.by[s][k], t=k + "T04:00:00Z") for k in sorted(self.by[s])
                                 if start <= k <= (self.day or "")]
                             for s in str(q["symbols"]).split(",") if s in self.by}}
        if "/quotes/latest" in path:
            s = path.split("/v2/stocks/")[1].split("/")[0]
            return {"quote": {"bp": self.cur.get(s), "ap": self.cur.get(s)}}
        raise _err(404, f"fake: no route {path}")

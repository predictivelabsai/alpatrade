"""Per-account strategy sleeves: several live strategies share one Alpaca account, each with
its own cash allocation and its own client_order_id prefix (sql/46_strategy_allocations.sql).

Model
  * ``alpatrade.strategy_allocations`` has one row per (account_number, strategy_name):
    ``allocation_usd`` (NULL = "the rest of the account") and ``cid_prefix``.
  * The PRIMARY strategy (the one the scheduler/runner is started with, today the Mag-7 BTD)
    needs no row: prefix ``btd`` and allocation NULL. With no other sleeves its sleeve is
    therefore the whole account and sizing/buying power are byte-identical to before.
  * Every other active row is a SLEEVE run inside the same runner pass, under the same DB
    lease/heartbeat, with its own sub-state ``state["sleeves"][name]`` and its own
    ``alpatrade.runs`` row.

Attribution: every order a strategy places carries its prefix: entries ``<p>-SYM-YYYYMMDD``,
exits ``<p>tp-``/``<p>sl-``/``<p>x-``. Prefixes are validated so that none is a prefix of
another's exit tags (e.g. ``btd`` vs ``s7btd`` never collide because matching is anchored at
the start of the id).

Buying power: a strategy may only buy while
    own_exposure + own_pending_buys + notional <= sleeve value
and, as before, never beyond the account's cash / non-marginable buying power (cash only).
Position size = pos_frac x sleeve value (sleeve value = allocation_usd, or for a NULL
allocation equity - sum(other allocations)).

Overlap guard: Alpaca nets positions per symbol, so two sleeves of one account must have
disjoint universes; ``validate_allocations`` enforces it and the runner also refuses to buy
a symbol another sleeve holds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

PRIMARY_PREFIX = "btd"
_PREFIX_RE = re.compile(r"^[a-z][a-z0-9]{1,11}$")


class AllocationError(ValueError):
    pass


@dataclass
class Sleeve:
    strategy_name: str
    cid_prefix: str
    allocation_usd: Optional[float]      # None = rest of the account
    is_primary: bool = False

    # ---------------------------------------------------------------- client ids
    def entry_cid(self, sym: str, d) -> str:
        return f"{self.cid_prefix}-{sym}-{d:%Y%m%d}"

    def exit_prefixes(self) -> tuple:
        p = self.cid_prefix
        return (f"{p}tp-", f"{p}sl-", f"{p}x-")

    def exit_cids(self, sym: str, entry_date: str) -> Dict[str, str]:
        d = entry_date.replace("-", "")
        p = self.cid_prefix
        return {"oco": f"{p}tp-{sym}-{d}", "stop": f"{p}sl-{sym}-{d}", "market": f"{p}x-{sym}-{d}"}

    def owns_cid(self, cid: Optional[str]) -> bool:
        cid = cid or ""
        return cid.startswith(f"{self.cid_prefix}-") or cid.startswith(self.exit_prefixes())

    def entry_cid_re(self):
        return re.compile(rf"^{re.escape(self.cid_prefix)}-([A-Z.]+)-(\d{{8}})$")


PRIMARY = Sleeve("primary", PRIMARY_PREFIX, None, True)


def sleeve_value(sleeve: Sleeve, equity: float, others: Iterable[Sleeve]) -> float:
    """Dollar size of the sleeve. NULL allocation = equity minus every other fixed allocation."""
    if sleeve.allocation_usd is not None:
        return float(sleeve.allocation_usd)
    rest = sum(float(o.allocation_usd or 0) for o in others if o is not sleeve)
    return max(0.0, float(equity) - rest)


def buying_power(*, sleeve_val: float, own_exposure: float, own_pending: float,
                 account_avail: float) -> float:
    """Cash this strategy may still deploy: min(account cash-only BP, sleeve headroom)."""
    return max(0.0, min(float(account_avail), float(sleeve_val) - own_exposure - own_pending))


def validate_allocations(rows: List[Dict[str, Any]], *, equity: float, cash: Optional[float] = None,
                         universes: Optional[Dict[str, List[str]]] = None) -> List[str]:
    """Return a list of human-readable problems ([] = valid).

    rows: [{"strategy_name", "cid_prefix", "allocation_usd" (None|number), "is_active"}].
    Rules: allocation >= 0; sum of fixed active allocations <= equity; prefixes valid,
    unique and not colliding with ``btd`` (the primary); active universes disjoint.
    ``cash`` is informational: an allocation above current free cash is allowed (the sleeve
    simply can't buy until cash frees up, it never uses margin) but flagged as a warning by
    the caller.
    """
    errs: List[str] = []
    active = [r for r in rows if r.get("is_active", True)]
    total = 0.0
    seen_prefix: Dict[str, str] = {}
    for r in rows:
        name = r.get("strategy_name") or "?"
        a = r.get("allocation_usd")
        if a is not None:
            try:
                a = float(a)
            except (TypeError, ValueError):
                errs.append(f"{name}: allocation must be a number"); continue
            if a < 0:
                errs.append(f"{name}: allocation must be >= 0")
            if r.get("is_active", True):
                total += a
        p = (r.get("cid_prefix") or "").strip()
        if not _PREFIX_RE.match(p):
            errs.append(f"{name}: cid_prefix {p!r} must be 2-12 chars [a-z0-9], starting with a letter")
        elif p == PRIMARY_PREFIX and not r.get("is_primary"):
            errs.append(f"{name}: cid_prefix 'btd' is reserved for the primary strategy")
        elif p in seen_prefix:
            errs.append(f"{name}: cid_prefix {p!r} already used by {seen_prefix[p]}")
        else:
            seen_prefix[p] = name
    if equity is not None and total > float(equity) + 1e-6:
        errs.append(f"allocations total ${total:,.2f} exceed account equity ${float(equity):,.2f}")
    if universes:
        owner: Dict[str, str] = {}
        for r in active:
            for s in universes.get(r.get("strategy_name"), []) or []:
                if s in owner and owner[s] != r.get("strategy_name"):
                    errs.append(f"{s} is in both {owner[s]} and {r.get('strategy_name')} (one strategy per symbol per account)")
                owner.setdefault(s, r.get("strategy_name"))
    return errs


# ------------------------------------------------------------------------ DB
def load_sleeves(engine, account_number: str, primary_name: str) -> List[Sleeve]:
    """Active non-primary sleeves for an account (empty list if the table is missing)."""
    from sqlalchemy import text
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT strategy_name, cid_prefix, allocation_usd FROM alpatrade.strategy_allocations "
            "WHERE account_number = :a AND is_active AND strategy_name <> :p ORDER BY id"),
            {"a": str(account_number), "p": primary_name}).all()
    return [Sleeve(r[0], r[1], None if r[2] is None else float(r[2])) for r in rows]


def primary_allocation(engine, account_number: str, primary_name: str) -> Optional[float]:
    from sqlalchemy import text
    with engine.connect() as c:
        r = c.execute(text(
            "SELECT allocation_usd FROM alpatrade.strategy_allocations "
            "WHERE account_number = :a AND strategy_name = :p AND is_active"),
            {"a": str(account_number), "p": primary_name}).first()
    return None if not r or r[0] is None else float(r[0])

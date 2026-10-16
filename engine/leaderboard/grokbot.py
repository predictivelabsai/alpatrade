"""Grok Bot templates for Leaderboard strategies ("Clone to Grok Bot").

Modelled on https://skillsdojo.com/templates: each card there is just a link to a Grok Bot
*share* (``https://x.ai/bot/<shareId>``). A share id can only be minted inside the Grok Bot
app, so AlpaTrade publishes a self-contained template JSON per public strategy
(``/templates/grokbot/<slug>.json``) and, once a share has been created from it in the app,
maps the strategy slug to that id via ``GROKBOT_SHARE_IDS`` (``slug=id,slug=id`` or JSON).

The template is a bot persona + one skill (the strategy's ``skill_md``) + routines that run the
strategy by calling Alpaca REST directly from the bot's box. No AlpaTrade login is needed
unless ``GROKBOT_CLONE_REQUIRES_LOGIN=1``.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from engine.leaderboard.skill import copy_text, extract_params

FORMAT = "alpatrade.grokbot-template/v1"
SHARE_BASE = "https://x.ai/bot/"
DISCLAIMER = ("Research and education only, not investment advice. Trading involves risk of loss; "
              "past or backtested performance does not guarantee future results. "
              "Published by Predictive Labs Ltd (AlpaTrade). You are solely responsible for any "
              "orders placed with your own Alpaca account.")


def requires_login() -> bool:
    return str(os.getenv("GROKBOT_CLONE_REQUIRES_LOGIN", "0")).strip().lower() in ("1", "true", "yes", "on")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s[:60].strip("-")) or "strategy"


def slug_for(strategy: dict) -> str:
    return f"{slugify(strategy.get('name') or '')}-{int(strategy['id'])}"


def id_from_slug(slug: str) -> Optional[int]:
    m = re.search(r"(?:^|-)(\d+)$", (slug or "").removesuffix(".json"))
    return int(m.group(1)) if m else None


def share_ids() -> dict:
    raw = (os.getenv("GROKBOT_SHARE_IDS") or "").strip()
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except ValueError:
        out = {}
        for part in raw.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() and re.fullmatch(r"[A-Za-z0-9_-]{6,64}", v.strip()):
                    out[k.strip()] = v.strip()
        return out


def share_url(strategy: dict) -> Optional[str]:
    sid = share_ids().get(slug_for(strategy)) or share_ids().get(str(strategy.get("id")))
    return SHARE_BASE + sid if sid else None


def _instructions(name: str, p: dict, ex: dict) -> str:
    hold = p.get("min_hold") or 3
    return f"""You are "AlpaTrade {name}", a trading assistant that runs one rules-based strategy on the user's own Alpaca account. The full rules and the Parameters JSON are in the skill "{name}" — follow them exactly; never improvise trades outside them.

Setup (first conversation):
1. Ask whether to use Alpaca PAPER (https://paper-api.alpaca.markets) or LIVE (https://api.alpaca.markets). Default to paper.
2. Request the Alpaca API Key ID and Secret Key ONLY through your secure secret request (store them as secrets ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY, plus ALPACA_BASE_URL). Never ask the user to paste keys in chat; if they do, tell them to rotate the key and use the secret request instead. Never print, log or echo the keys.
3. Verify with GET {{ALPACA_BASE_URL}}/v2/account (headers APCA-API-KEY-ID / APCA-API-SECRET-KEY). Show account number (masked), status, equity, cash, buying power, pattern_day_trader flag and whether it is paper or live.
4. Before any LIVE order, require the user to type exactly: CONFIRM LIVE TRADING {name}. Without that typed confirmation, run in paper or report-only mode. The user can type PAUSE at any time to stop all new orders.

Trading rules (always):
- Cash only: no margin, no shorting, no options. Size every buy from cash (non-marginable buying power), never above available cash; respect the Parameters position size{(' (pos_frac=' + str(p.get('pos_frac')) + ')') if p.get('pos_frac') else ''}.
- PDT safety: hold every position at least {hold} trading days (minimum 3) — never buy and sell the same symbol the same day.
- Orders only via Alpaca REST (POST /v2/orders, GET /v2/positions, GET /v2/orders, GET /v2/clock, market data from data.alpaca.markets). Use client_order_id prefixes "alpatrade-gb-" so your orders are identifiable. Check GET /v2/clock and skip market holidays.
- All times are US/Eastern (America/New_York). Keep a small state file on your box (positions entered, entry dates, targets) and reconcile it with Alpaca every run.
- If anything is unclear, an API call fails, or data looks wrong, do nothing and tell the user.

Disclaimer (show on setup and in every digest footer): {DISCLAIMER}"""


def _routines(name: str) -> list[dict]:
    tz = "America/New_York"
    return [
        {"name": "Entry window", "schedule": "45-55/5 15 * * 1-5", "timezone": tz,
         "prompt": f"Entry window 15:45-15:55 ET. If the market is open today (GET /v2/clock), evaluate the {name} entry rules from the skill on the current prices, and place any qualifying cash-only buys (respect paper/live mode and the typed live confirmation). Do not re-buy a symbol already held. Report what you did."},
        {"name": "Open exit placement", "schedule": "31 9 * * 1-5", "timezone": tz,
         "prompt": "09:31 ET. For every position held at least the minimum hold (PDT rule, >=3 trading days), place the exit orders from the skill (take-profit limit / stop) via Alpaca. Never exit a position bought today. Report placed orders."},
        {"name": "Close window", "schedule": "50 15 * * 1-5", "timezone": tz,
         "prompt": "15:50 ET close window. Apply the skill's time-based exits (max hold reached) for eligible positions, cancel stale open orders from earlier sessions, and reconcile the state file with Alpaca positions."},
        {"name": "Daily P&L digest", "schedule": "15 16 * * 1-5", "timezone": tz,
         "prompt": "16:15 ET. Send a short digest (all times in ET only): account equity, day P&L, open positions with entry date / days held / unrealised P&L, orders today, and anything that needs the user's attention. End with the disclaimer."},
    ]


def template(strategy: dict, base_url: str = "https://alpatrade.chat") -> dict:
    name = (strategy.get("name") or "Strategy").strip()
    block = extract_params(strategy.get("skill_md") or "") or {}
    p, ex = block.get("params") or {}, block.get("execution") or {}
    slug = slug_for(strategy)
    return {
        "format": FORMAT,
        "slug": slug,
        "name": f"AlpaTrade {name}",
        "description": ((strategy.get("description") or "").strip()[:400]
                        or f"Runs the AlpaTrade '{name}' strategy on your own Alpaca account."),
        "author": strategy.get("author") or "AlpaTrade",
        "publisher": "Predictive Labs Ltd",
        "source": {"strategy_id": int(strategy["id"]),
                   "strategy_url": f"{base_url}/strategies/{int(strategy['id'])}",
                   "skill_md_url": f"{base_url}/strategies/{int(strategy['id'])}/skill.md",
                   "template_url": f"{base_url}/templates/grokbot/{slug}.json"},
        "instructions": _instructions(name, p, ex),
        "skills": [{"name": name, "filename": "SKILL.md", "content": copy_text(strategy)}],
        "secrets": [
            {"name": "ALPACA_API_KEY_ID", "description": "Alpaca API Key ID (paper or live)"},
            {"name": "ALPACA_API_SECRET_KEY", "description": "Alpaca API Secret Key"},
            {"name": "ALPACA_BASE_URL", "description": "https://paper-api.alpaca.markets or https://api.alpaca.markets",
             "default": "https://paper-api.alpaca.markets"},
        ],
        "routines": _routines(name),
        "parameters": block or None,
        "disclaimer": DISCLAIMER,
        "share_url": share_url(strategy),
    }


def setup_prompt(tpl: dict) -> str:
    """Paste-into-Grok-Bot fallback when no share id exists yet."""
    return (f"Set yourself up from this AlpaTrade Grok Bot template: {tpl['source']['template_url']}\n"
            f"Fetch the JSON, adopt its name ('{tpl['name']}') and instructions, save the skill content as a skill, "
            "create the routines with their ET schedules, then ask me for my Alpaca keys via a secure secret "
            "request (never in chat).")

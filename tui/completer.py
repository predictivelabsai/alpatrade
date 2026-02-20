"""Tab-completion for the Rich CLI."""

import readline

COMMANDS = {
    "help": {},
    "status": {},
    "trades": {},
    "runs": {},
    "clear": {},
    "exit": {},
    "agent:backtest": {
        "lookback": ["1m", "3m", "6m", "1y"],
        "symbols": None,
        "hours": ["regular", "extended"],
        "intraday_exit": ["true", "false"],
        "pdt": ["true", "false"],
        "capital": None,
        "strategy": ["buy_the_dip", "momentum"],
    },
    "agent:validate": {
        "run-id": None,
        "source": ["backtest", "paper_trade"],
    },
    "agent:paper": {
        "duration": ["1h", "6h", "1d", "7d", "30d"],
        "symbols": None,
        "poll": None,
        "hours": ["regular", "extended"],
        "email": ["true", "false"],
        "pdt": ["true", "false"],
        "strategy": ["buy_the_dip", "momentum"],
    },
    "agent:full": {
        "lookback": ["1m", "3m", "6m", "1y"],
        "duration": ["1h", "6h", "1d", "7d", "30d"],
        "symbols": None,
        "hours": ["regular", "extended"],
        "intraday_exit": ["true", "false"],
        "pdt": ["true", "false"],
        "capital": None,
        "strategy": ["buy_the_dip", "momentum"],
    },
    "agent:reconcile": {"window": ["7d", "14d", "30d"]},
    "agent:report": {
        "run-id": None,
        "type": ["backtest", "paper"],
        "limit": None,
    },
    "agent:status": {},
    "agent:runs": {},
    "agent:trades": {"run-id": None, "type": ["backtest", "paper_trade"], "limit": None},
    "agent:stop": {},
    "agent:logs": {"lines": ["20", "50", "100"]},
    "news": {"limit": ["5", "10", "20"], "provider": ["xai", "tavily", "polygon"]},
    "profile": {},
    "financials": {"period": ["annual", "quarterly"]},
    "price": {},
    "movers": {},
    "analysts": {},
    "valuation": {},
    "alpaca:backtest": {
        "strategy": ["buy-the-dip", "momentum"],
        "lookback": ["1m", "3m", "6m", "1y"],
        "symbols": None,
        "capital": None,
        "position": None,
        "dip": None,
        "hold": None,
        "takeprofit": None,
        "stoploss": None,
        "interval": ["1d", "1h"],
        "data_source": ["massive"],
    },
}


def setup_completer():
    """Configure readline with tab-completion. Handles both GNU readline and libedit."""
    completer = CommandCompleter()
    readline.set_completer(completer.complete)
    readline.set_completer_delims(readline.get_completer_delims().replace(":", ""))

    # libedit (macOS / some Linux) uses different bind syntax than GNU readline
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


class CommandCompleter:
    def __init__(self):
        self._matches = []

    def complete(self, text, state):
        """Readline callback: called with state=0,1,2... until None."""
        if state == 0:
            line = readline.get_line_buffer().lstrip()
            self._matches = self._get_matches(text, line)
        return self._matches[state] if state < len(self._matches) else None

    def _get_matches(self, text, line):
        # Support optional "/" prefix (e.g. "/agent:backtest")
        stripped_line = line.lstrip("/")
        stripped_text = text.lstrip("/")
        # Keep the prefix that's already in text so readline replaces correctly
        prefix = text[: len(text) - len(stripped_text)]

        parts = stripped_line.split()

        # Case 1: Completing command name (first word)
        if not parts or (len(parts) == 1 and not stripped_line.endswith(" ")):
            return [prefix + cmd + " " for cmd in sorted(COMMANDS) if cmd.startswith(stripped_text)]

        # Case 2: Command known, completing parameters
        # Support colon syntax: "news:TSLA" → base command "news"
        cmd = parts[0].lower()
        cmd_base = cmd.split(":")[0]
        if cmd not in COMMANDS and cmd_base in COMMANDS:
            cmd = cmd_base
        if cmd not in COMMANDS:
            return []
        param_defs = COMMANDS[cmd]
        if not param_defs:
            return []

        # Which param keys are already used?
        used = {p.partition(":")[0].lower() for p in parts[1:] if ":" in p}

        # Case 2a: text contains ":" → completing a value
        if ":" in text:
            key, _, partial = text.partition(":")
            values = param_defs.get(key.lower())
            if values:
                return [f"{key}:{v} " for v in values if v.startswith(partial)]
            return []

        # Case 2b: completing a param key (offer "key:" for unused params)
        return [f"{k}:" for k in sorted(param_defs) if k.startswith(text) and k not in used]

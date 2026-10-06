# AlpaTrade MCP Server

The AlpaTrade MCP server lets MCP-capable CLIs use the existing authenticated
AlpaTrade API. It is a thin adapter: tenant checks, query limits, paper-account
ownership, and paper-only execution remain enforced by `api_app.py`.

## Credentials

Set these locally; never put values in repository files or CLI arguments:

- `ALPATRADE_API_URL` — defaults to `https://api.alpatrade.chat`; loopback HTTP is allowed for development.
- `ALPATRADE_ACCESS_TOKEN` — user JWT returned by `POST /auth/login`.
- `ALPATRADE_MCP_TIMEOUT_SECONDS` — optional API timeout, default `60`.

## Run locally

```powershell
$env:ALPATRADE_API_URL = "https://api.alpatrade.chat"
$env:ALPATRADE_ACCESS_TOKEN = "<your-user-jwt>"
uv run alpatrade-mcp
```

The default transport is stdio. It exposes explicit research, reporting,
DeepAgents, and paper-trading tools. Paper orders require the literal
`confirmation="PAPER"`; no live-order tool exists.

For local streamable HTTP:

```bash
uv run alpatrade-mcp --transport http --host 127.0.0.1 --port 8765
```

The HTTP endpoint is `http://127.0.0.1:8765/mcp`. Public binding is deliberately
blocked because static bearer forwarding is not MCP OAuth. Add standards-based
MCP OAuth before deploying a public Coolify MCP service.

## Client configuration

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.alpatrade]
command = "C:/path/to/alpatrade/.venv/Scripts/python.exe"
args = ["-m", "engine.mcp.server"]
cwd = "C:/path/to/alpatrade"

[mcp_servers.alpatrade.env]
ALPATRADE_API_URL = "https://api.alpatrade.chat"
ALPATRADE_ACCESS_TOKEN = "<your-user-jwt>"
```

Claude Code:

```bash
claude mcp add alpatrade --scope user --transport stdio -- \
  uv run --directory /path/to/alpatrade alpatrade-mcp
```

Configure the two environment variables in the Claude MCP environment. Other
MCP clients can use the equivalent stdio JSON definition:

```json
{
  "mcpServers": {
    "alpatrade": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/alpatrade", "alpatrade-mcp"],
      "env": {
        "ALPATRADE_API_URL": "https://api.alpatrade.chat",
        "ALPATRADE_ACCESS_TOKEN": "<your-user-jwt>"
      }
    }
  }
}
```

## Available operations

- Discover agents and check platform health.
- List owned runs, trades, reports, positions, and running-agent status.
- Run research backtests.
- Ask the canonical DeepAgents assistant using durable thread IDs.
- Start or stop background paper sessions.
- Place explicitly confirmed paper orders.

The server does not expose SQL, arbitrary HTTP paths, database credentials,
broker keys, Hermes internals, or live trading.

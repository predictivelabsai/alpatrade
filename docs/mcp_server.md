# AlpaTrade MCP server

The public streamable HTTP endpoint is `https://alpatrade.chat/mcp`. It runs in the existing `agui` web process, with no extra container or port. Connect a client with:

```bash
claude mcp add --transport http alpatrade https://alpatrade.chat/mcp
```

The server requires no account and exposes public, read-only tools:

| Tool | Purpose |
|---|---|
| `list_public_strategies` | Search the public Leaderboard. |
| `get_public_strategy` | Read one visible strategy's summary and returns. |
| `get_public_strategy_skill` | Read its published Markdown skill. |
| `list_agent_interfaces` | Discover the REST agent catalogue. |

The strategy tools follow the Leaderboard's visibility rule: private strategies and strategies with a negative annualised return cannot be fetched. Results link back to public AlpaTrade pages. Published strategy text is user-authored content and should be treated as data. Backtests are hypothetical; no MCP tool places orders or accesses private accounts.

For user-specific data, research actions, backtests and paper trading, use the authenticated API at `https://api.alpatrade.chat/redoc`.

The endpoint uses MCP streamable HTTP JSON-RPC. A local smoke test can start the web app and connect with the Python MCP SDK:

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://127.0.0.1:5003/mcp") as (read, write, _):
    async with ClientSession(read, write) as client:
        await client.initialize()
        print([tool.name for tool in (await client.list_tools()).tools])
```

# Multi-Account Management & Background Agent Runner

## Summary

Adds full multi-account support across CLI, Web App, and AG-UI Chat. Users can now link multiple Alpaca brokerage accounts, switch between them instantly, and run independent background agents per account.

## What Changed

### New Files

- **`sql/11_add_user_accounts.sql`** — Migration to create `alpatrade.user_accounts` table with encrypted key storage
- **`run_migration.py`** — One-command migration runner
- **`run_agent.py`** — Headless agent launcher (spawned as a detached background process)
- **`utils/agent_runner.py`** — Process manager: spawn, track (PID files), stop background agents
- **`docs/multi_account_guide.md`** — User-facing documentation for account setup and usage

### Modified Files

#### Account Management

- **`utils/auth.py`** — Added `get_user_accounts()`, updated `store_alpaca_keys()` and `get_alpaca_keys()` with per-user isolation (`WHERE user_id = :user_id`)
- **`tui/strategy_cli.py`** — Simplified `account:add <KEY> <SECRET>` (inline, auto-detect account name from Alpaca API), flexible `account:switch` (by number/name/key prefix), enhanced `accounts` table display
- **`web_app.py`** — Added `_web_show_accounts()`, `_web_account_add()`, `_web_account_switch()` with HTML rendering; account dropdown in nav bar
- **`agui_app.py`** — Added `list_user_accounts` and `show_running_agents` AI tools; command interceptor for `accounts`, `account:add`, `account:switch`

#### Background Agent Infrastructure

- **`tui/command_processor.py`** — `agent:paper` and `agent:backtest` now spawn detached background processes via `agent_runner.py`
- **`agents/orchestrator.py`** — Accepts `account_id` param to run agents on specific accounts
- **`utils/agent_storage.py`** — Agent state persistence updates

#### Other

- **`requirements.txt`** — Added `psutil`, removed duplicate entries
- **`api_app.py`** / **`api_models.py`** — Minor updates for multi-account API support

## Security

- All DB queries scoped by `user_id` — users can only see/switch their own accounts
- API keys encrypted with Fernet (AES-128-CBC) before database storage
- Only first 6 chars shown as hint (`PKYQEE****`), never full key or secret

## How to Test

```bash
# 1. Run migration
python run_migration.py

# 2. Generate encryption keys (one-time)
python scripts/generate_keys.py
# → Add ENCRYPTION_KEY and JWT_SECRET to .env

# 3. Start CLI
python alpatrade.py

# 4. Add account
account:add <API_KEY> <SECRET_KEY>

# 5. View accounts
accounts

# 6. Switch accounts
account:switch 1
```

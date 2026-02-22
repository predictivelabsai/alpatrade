# Authentication & User Management

AlpaTrade supports multi-user authentication with per-user Alpaca API key management.

## Setup

### 1. Generate Encryption Keys

```bash
python scripts/generate_keys.py
```

This outputs two keys to add to your `.env`:

```
ENCRYPTION_KEY=...    # Fernet key for encrypting Alpaca API keys at rest
JWT_SECRET=...        # Secret for signing API JWT tokens
```

### 2. Run Database Migrations

Execute the SQL migration scripts in order:

```bash
psql $DATABASE_URL -f sql/07_create_users_table.sql
psql $DATABASE_URL -f sql/08_add_user_id_columns.sql
psql $DATABASE_URL -f sql/09_migrate_existing_data.sql
```

- `07` creates the `alpatrade.users` table
- `08` adds `user_id` columns to `runs`, `trades`, `backtest_summaries`, `validations`
- `09` creates an admin user (`admin@alpatrade.dev`) and assigns all existing data to it

### 3. Install Dependencies

```bash
uv pip install -e ".[web]"
```

New dependencies: `passlib[bcrypt]`, `cryptography`, `PyJWT`

## Authentication Flows

### Web UI (FastHTML)

**Email/Password:**
- `GET /register` — signup form
- `POST /register` — creates user, sets session
- `GET /signin` — login form
- `POST /signin` — authenticates, sets session

**Google OAuth** (when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set):
- `GET /login` — redirects to Google
- `GET /auth/callback` — handles OAuth callback, creates/links user

**Profile & Keys:**
- `GET /profile` — view user info, Alpaca key status
- `POST /profile/keys` — encrypt and store Alpaca API keys

Session shape after login:
```python
session["user"] = {
    "user_id": "uuid-string",
    "email": "user@example.com",
    "display_name": "User Name",
}
```

### REST API (FastAPI)

**Registration:**
```bash
curl -X POST http://localhost:5001/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass", "display_name": "User"}'
```

**Login:**
```bash
curl -X POST http://localhost:5001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass"}'
```

Both return:
```json
{"token": "eyJ...", "user_id": "uuid", "email": "user@example.com"}
```

**Authenticated requests:**
```bash
curl -H "Authorization: Bearer eyJ..." http://localhost:5001/trades
```

All API endpoints accept optional JWT auth. Unauthenticated requests see all data (CLI-compatible). Authenticated requests filter to the user's own data.

### CLI

The CLI does not require authentication. It operates with `user_id=None`, which means:
- No user filtering on queries (sees all data)
- `NULL` stored in `user_id` column for new records
- Alpaca keys come from `.env` environment variables

## Per-User Alpaca Keys

Users can configure their own Alpaca paper trading keys via the web profile page. Keys are:

1. **Encrypted at rest** using Fernet symmetric encryption (`ENCRYPTION_KEY`)
2. **Stored as BYTEA** in `alpatrade.users.alpaca_api_key_enc` / `alpaca_secret_key_enc`
3. **Decrypted on demand** when the orchestrator or broker agent needs them

Resolution order:
1. Per-user keys from DB (if user is authenticated and has configured keys)
2. Environment variables (`ALPACA_PAPER_API_KEY`, `ALPACA_PAPER_SECRET_KEY`)

## Data Isolation

When `user_id` is set (web/API authenticated users):
- Backtests, paper trades, and validations are tagged with the user's ID
- Queries filter by `user_id` — users only see their own data
- The orchestrator resolves per-user Alpaca keys automatically

When `user_id` is `None` (CLI):
- No filtering applied to queries
- `NULL` stored in DB columns
- Compatible with pre-migration data

## Key Files

| File | Purpose |
|------|---------|
| `utils/auth.py` | Password hashing, key encryption, user CRUD, JWT |
| `sql/07_create_users_table.sql` | Users table schema |
| `sql/08_add_user_id_columns.sql` | Add user_id to existing tables |
| `sql/09_migrate_existing_data.sql` | Migrate data to admin user |
| `scripts/generate_keys.py` | Generate ENCRYPTION_KEY and JWT_SECRET |

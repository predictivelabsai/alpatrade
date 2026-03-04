# Multi-Account Guide

AlpaTrade supports multiple Alpaca brokerage accounts per user. You can add paper or live accounts, switch between them instantly, and run independent trading agents on each one.

---

## 1. One-Time Setup: Encryption Key

Before adding any accounts, you need a master **encryption key**. This key is used to securely scramble your Alpaca API keys before saving them in the database — so even if the database is compromised, your brokerage credentials stay safe.

### Generate the key

```bash
python scripts/generate_keys.py
```

This prints two keys:

```
ENCRYPTION_KEY=KGTPJ97Rt5X1Z669s3nV0ow8A57kwoCHuoVivhIkh5M=
JWT_SECRET=vamQnb3inJ5HI7uVCRoo20Y3O7-a9MCnt1oyl92Ah5gB7LjoNaAqgNMULsx8ECZn
```

### Add them to `.env`

Open your `.env` file and paste at the bottom:

```ini
# Application Security Keys
ENCRYPTION_KEY=<your generated key>
JWT_SECRET=<your generated key>
```

> **Important:** Do this only once. If you lose the `ENCRYPTION_KEY`, you won't be able to decrypt previously saved accounts.

---

## 2. Database Migration

Run the migration to create the `user_accounts` table:

```bash
python run_migration.py
```

This creates the table and migrates any existing Alpaca keys from the old `users` table into the new structure as a "Default Account".

---

## 3. Adding an Account (CLI)

In the CLI, use the **one-liner** command:

```
account:add <API_KEY> <SECRET_KEY>
```

**Example:**

```
raslen > account:add PKYQEEOELIVJJQY6VEGZKJIRUN ECp7ZgbqPurrLif14GYTdkD5DgAVnoJCXnGcyNEvHZZv
```

**What happens:**

1. AlpaTrade connects to Alpaca and verifies the keys are valid
2. It auto-detects the account number (e.g., `Paper-PA389YTF28CR`)
3. It encrypts and saves the keys to the database
4. It automatically switches you to the new account

---

## 4. Viewing Your Accounts

```
raslen > accounts
```

Shows a numbered table:

```
      Your Alpaca Accounts
┌───┬────────────────────┬────────────┬────────┐
│ # │ Name               │ API Key    │ Active │
├───┼────────────────────┼────────────┼────────┤
│ 1 │ Paper-PA389YTF28CR ◀│ PKYQEE**** │   ✓    │
│ 2 │ Paper-PA112233XXYY │ AKXXXX**** │   ✓    │
└───┴────────────────────┴────────────┴────────┘
```

The `◀` arrow shows which account is currently active.

---

## 5. Switching Accounts

You can switch by **number**, **name**, or **API key prefix**:

```bash
# By row number (easiest)
account:switch 1

# By partial name
account:switch Paper-PA389

# By API key prefix
account:switch PKYQEE
```

After switching, your prompt updates to show the active account, and all subsequent commands (backtests, paper trades, etc.) use that account's Alpaca keys.

---

## 6. Web App

In the FastHTML web app, the active account is shown as a **dropdown** in the top navigation bar. Simply select a different account from the dropdown to switch — no commands needed.

---

## 7. Security

- **Per-user isolation:** Each user can only see and switch to their own accounts. All database queries are scoped by `user_id`.
- **Encrypted storage:** API keys are encrypted with Fernet (AES-128-CBC) before being stored. The raw keys never appear in the database.
- **No key leakage:** The `accounts` table only shows the first 6 characters of each API key as a hint (`PKYQEE****`), never the full key or the secret.

---

## Quick Reference

| Command                              | Description              |
| ------------------------------------ | ------------------------ |
| `account:add <KEY> <SECRET>`         | Add a new Alpaca account |
| `accounts`                           | List all your accounts   |
| `account:switch <number\|name\|key>` | Switch active account    |

-- v0.43.0: securities excluded from P&L and all reporting (engine/reporting/exclusions.py).
-- scope 'global' applies to every account; 'account' applies to account_ref only
-- (Alpaca account number, e.g. PA3QUCXV3HJJ, or the internal account id).
CREATE TABLE IF NOT EXISTS alpatrade.excluded_securities (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'global' CHECK (scope IN ('global', 'account')),
    account_ref TEXT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    auto        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((scope = 'global' AND account_ref IS NULL) OR (scope = 'account' AND account_ref IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_excluded_securities
    ON alpatrade.excluded_securities (upper(symbol), scope, COALESCE(upper(account_ref), ''));

-- Alpaca asset status cache for the auto rule (inactive / not tradable), refreshed daily.
CREATE TABLE IF NOT EXISTS alpatrade.asset_status_cache (
    symbol     TEXT PRIMARY KEY,
    status     TEXT,
    tradable   BOOLEAN,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO alpatrade.excluded_securities (symbol, scope, account_ref, reason, auto)
VALUES ('BNBX', 'global', NULL, 'Leftover dust (zombie OTC position)', FALSE),
       ('CDTX', 'account', 'PA3QUCXV3HJJ', 'Not tradable / inactive on Alpaca (Kairi paper)', FALSE)
ON CONFLICT DO NOTHING;

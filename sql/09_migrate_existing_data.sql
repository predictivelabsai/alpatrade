-- Migrate existing data to admin user.
-- Creates admin@alpatrade.dev user and assigns all orphaned rows.

DO $$
DECLARE
    admin_uid UUID;
BEGIN
    -- Create admin user if not exists
    INSERT INTO alpatrade.users (email, display_name, is_admin)
    VALUES ('admin@alpatrade.dev', 'Admin', TRUE)
    ON CONFLICT (email) DO NOTHING;

    SELECT user_id INTO admin_uid
    FROM alpatrade.users
    WHERE email = 'admin@alpatrade.dev';

    -- Assign orphaned rows to admin
    UPDATE alpatrade.runs SET user_id = admin_uid WHERE user_id IS NULL;
    UPDATE alpatrade.trades SET user_id = admin_uid WHERE user_id IS NULL;
    UPDATE alpatrade.backtest_summaries SET user_id = admin_uid WHERE user_id IS NULL;
    UPDATE alpatrade.validations SET user_id = admin_uid WHERE user_id IS NULL;
END $$;

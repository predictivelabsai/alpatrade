-- Anonymous per-strategy counts for "Clone to Grok Bot" (no user / IP stored).
CREATE TABLE IF NOT EXISTS alpatrade.grokbot_template_clicks (
    strategy_id INTEGER NOT NULL,
    action      TEXT    NOT NULL,           -- open | share | copy_link | download | json
    day         DATE    NOT NULL DEFAULT CURRENT_DATE,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (strategy_id, action, day)
);

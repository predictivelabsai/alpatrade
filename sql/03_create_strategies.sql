-- Strategies Table
-- Stores strategy definitions and configurations

CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(255) UNIQUE NOT NULL,
    strategy_name VARCHAR(255) NOT NULL,
    strategy_type VARCHAR(100) NOT NULL,
    description TEXT,
    parameters JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_strategies_strategy_id ON strategies(strategy_id);
CREATE INDEX IF NOT EXISTS idx_strategies_strategy_type ON strategies(strategy_type);
CREATE INDEX IF NOT EXISTS idx_strategies_is_active ON strategies(is_active);
CREATE INDEX IF NOT EXISTS idx_strategies_created_at ON strategies(created_at DESC);

-- Insert default strategies
INSERT INTO strategies (strategy_id, strategy_name, strategy_type, description, parameters)
VALUES 
    ('buy-the-dip', 'Buy The Dip', 'momentum', 'Buy stocks when they dip below a certain threshold', 
     '{"dip_threshold": 0.02, "hold_period_days": 1}'::jsonb),
    ('vix-fear', 'VIX Fear Index', 'volatility', 'Buy when VIX exceeds threshold indicating high fear', 
     '{"vix_threshold": 20, "hold_overnight": true}'::jsonb)
ON CONFLICT (strategy_id) DO NOTHING;

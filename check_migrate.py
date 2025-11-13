#!/usr/bin/env python3
"""Migration validator - ensures core tables exist.

Creates tables if missing, otherwise reports status.
Run before first collector/scorer execution.
"""
import os, sys

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print('❌ DATABASE_URL not set')
    sys.exit(1)

SCHEMA_SQL = """
-- raw_trades table
CREATE TABLE IF NOT EXISTS raw_trades (
    id TEXT PRIMARY KEY,
    market_id TEXT,
    trader TEXT,
    outcome TEXT,
    side TEXT,
    amount_usdc NUMERIC,
    cost_usdc NUMERIC,
    price_before NUMERIC,
    price_after NUMERIC,
    timestamp TIMESTAMP,
    block_number BIGINT,
    pool_depth NUMERIC,
    raw_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_raw_trades_trader ON raw_trades(trader);
CREATE INDEX IF NOT EXISTS idx_raw_trades_timestamp ON raw_trades(timestamp DESC);

-- wallet_daily table
CREATE TABLE IF NOT EXISTS wallet_daily (
    wallet TEXT,
    day DATE,
    trades INT,
    wins INT,
    losses INT,
    win_rate NUMERIC,
    avg_roi NUMERIC,
    roi_std NUMERIC,
    total_volume NUMERIC,
    avg_ticket_size NUMERIC,
    median_ticket_size NUMERIC,
    unique_markets INT,
    concentration_index NUMERIC,
    mean_hold_time_seconds NUMERIC,
    max_drawdown NUMERIC,
    bait_score NUMERIC,
    insider_flag BOOLEAN,
    is_high_freq BOOLEAN,
    last_trade_at TIMESTAMP,
    PRIMARY KEY (wallet, day)
);
CREATE INDEX IF NOT EXISTS idx_wallet_daily_day ON wallet_daily(day DESC);

-- leaderboard table
CREATE TABLE IF NOT EXISTS leaderboard (
    rank_date DATE,
    rank INT,
    wallet TEXT,
    smartscore NUMERIC,
    reasons JSONB,
    PRIMARY KEY (rank_date, rank)
);
CREATE INDEX IF NOT EXISTS idx_leaderboard_date ON leaderboard(rank_date DESC);
"""

try:
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    print('🔧 Applying schema migrations...')
    cur.execute(SCHEMA_SQL)
    conn.commit()
    
    # Verify tables
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    tables = [r[0] for r in cur.fetchall()]
    print(f'✅ Schema ready. Tables: {", ".join(tables)}')
    
    # Check row counts
    for table in ['raw_trades', 'wallet_daily', 'leaderboard']:
        if table in tables:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            count = cur.fetchone()[0]
            print(f'   {table}: {count} rows')
    
    cur.close()
    conn.close()
    print('\n✅ Database initialized successfully!')
    
except Exception as e:
    print(f'❌ Migration failed: {e}')
    sys.exit(1)

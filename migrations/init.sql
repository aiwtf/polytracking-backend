-- Database schema initialization for PolyTracking
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

CREATE TABLE IF NOT EXISTS wallet_daily (
  wallet TEXT,
  day DATE,
  trades INT,
  wins INT,
  losses INT,
  win_rate FLOAT,
  avg_roi FLOAT,
  roi_std FLOAT,
  total_volume NUMERIC,
  avg_ticket_size NUMERIC,
  median_ticket_size NUMERIC,
  unique_markets INT,
  concentration_index FLOAT,
  mean_hold_time_seconds FLOAT,
  max_drawdown FLOAT,
  bait_score FLOAT,
  insider_flag BOOL,
  is_high_freq BOOL,
  last_trade_at TIMESTAMP,
  PRIMARY KEY (wallet, day)
);

CREATE TABLE IF NOT EXISTS leaderboard (
  rank_date DATE,
  rank INT,
  wallet TEXT,
  smartscore FLOAT,
  reasons JSONB,
  PRIMARY KEY (rank_date, rank)
);

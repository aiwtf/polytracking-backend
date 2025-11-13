# scripts/seed_demo.py
import os
import psycopg2
from datetime import datetime, date, timedelta
import json
import uuid

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise SystemExit("Please set DATABASE_URL in env before running seed_demo.py")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# insert sample raw_trades (needed for features to compute)
wallet1 = "0xTestWallet1234567890"
wallet2 = "0xAnotherWallet9876543210"
now = datetime.utcnow()
for i in range(80):  # 80 trades for wallet1
    tid = f"seed_{wallet1}_{uuid.uuid4()}"
    ts = now - timedelta(days=i//2, hours=i%24)
    cur.execute(
        """
        INSERT INTO raw_trades (id, market_id, trader, outcome, side, amount_usdc, cost_usdc, price_before, price_after, timestamp, block_number, pool_depth, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO NOTHING
        """,
        (tid, f'market_{i%5}', wallet1, 'Yes', 'buy', 100+i*10, 95+i*9, 0.45+i*0.001, 0.50+i*0.001, ts, 1000+i, 50000, json.dumps({'seed': True}))
    )

for i in range(100):  # 100 trades for wallet2
    tid = f"seed_{wallet2}_{uuid.uuid4()}"
    ts = now - timedelta(days=i//3, hours=i%12)
    cur.execute(
        """
        INSERT INTO raw_trades (id, market_id, trader, outcome, side, amount_usdc, cost_usdc, price_before, price_after, timestamp, block_number, pool_depth, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO NOTHING
        """,
        (tid, f'market_{i%8}', wallet2, 'No', 'sell', 150+i*5, 140+i*4.5, 0.55, 0.60, ts, 2000+i, 80000, json.dumps({'seed': True}))
    )

# insert wallet_daily demo
cur.execute(
    """
INSERT INTO wallet_daily (wallet, day, trades, wins, losses, win_rate, avg_roi, roi_std, total_volume, avg_ticket_size, median_ticket_size, unique_markets, concentration_index, mean_hold_time_seconds, max_drawdown, bait_score, insider_flag, is_high_freq, last_trade_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (wallet, day) DO UPDATE SET trades=EXCLUDED.trades, wins=EXCLUDED.wins, losses=EXCLUDED.losses, win_rate=EXCLUDED.win_rate, avg_roi=EXCLUDED.avg_roi, roi_std=EXCLUDED.roi_std, total_volume=EXCLUDED.total_volume, avg_ticket_size=EXCLUDED.avg_ticket_size, median_ticket_size=EXCLUDED.median_ticket_size, unique_markets=EXCLUDED.unique_markets, concentration_index=EXCLUDED.concentration_index, mean_hold_time_seconds=EXCLUDED.mean_hold_time_seconds, max_drawdown=EXCLUDED.max_drawdown, bait_score=EXCLUDED.bait_score, insider_flag=EXCLUDED.insider_flag, is_high_freq=EXCLUDED.is_high_freq, last_trade_at=EXCLUDED.last_trade_at
    """,
    (
        "0xTestWallet1234567890",
        date.today(),
        120,
        80,
        40,
        0.6667,
        0.12,
        0.05,
        5000,
        41.7,
        35.0,
        14,
        0.28,
        0.0,
        0.0,
        0.01,
        False,
        False,
        datetime.utcnow(),
    ),
)

# insert a leaderboard row
cur.execute("DELETE FROM leaderboard WHERE rank_date = %s", (date.today(),))
cur.execute(
    """
INSERT INTO leaderboard (rank_date, rank, wallet, smartscore, reasons)
VALUES (%s, %s, %s, %s, %s)
    """,
    (
        date.today(),
        1,
        "0xTestWallet1234567890",
        92.5,
        json.dumps({"win_rate": 0.6667, "avg_roi": 0.12, "bait_score": 0.01, "insider": False}),
    ),
)

conn.commit()
cur.close()
conn.close()
print("✅ Seed completed")

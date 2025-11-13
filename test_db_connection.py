#!/usr/bin/env python3
"""Quick DB connectivity check for PolyTracking.

Usage:
  export DATABASE_URL=postgresql://...
  python test_db_connection.py
"""
import os, sys

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print('❌ DATABASE_URL not set')
    sys.exit(1)

print(f'Testing connection to: {DATABASE_URL[:40]}...')

# Test with psycopg2 (sync)
try:
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute('SELECT version()')
    version = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM raw_trades')
    trade_count = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM wallet_daily')
    wallet_count = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM leaderboard WHERE rank_date = CURRENT_DATE')
    leaderboard_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f'✅ psycopg2 connected')
    print(f'   PostgreSQL: {version[:60]}...')
    print(f'   raw_trades rows: {trade_count}')
    print(f'   wallet_daily rows: {wallet_count}')
    print(f'   leaderboard (today): {leaderboard_count}')
except Exception as e:
    print(f'❌ psycopg2 connection failed: {e}')
    sys.exit(1)

# Test with asyncpg (async)
try:
    import asyncio, asyncpg
    async def test_async():
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            row = await conn.fetchrow('SELECT 1+1 AS result')
            print(f'✅ asyncpg connected (result: {row["result"]})')
        await pool.close()
    asyncio.run(test_async())
except Exception as e:
    print(f'⚠️  asyncpg test failed: {e}')

print('\n✅ Database is accessible and ready for PolyTracking MVP.')

import asyncio, asyncpg, os, json

async def test():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'])
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT rank, wallet, smartscore, reasons
            FROM leaderboard
            WHERE rank_date = CURRENT_DATE
            ORDER BY rank
            LIMIT 5
        """)
        print(f"Found {len(rows)} rows")
        for r in rows:
            print(f"  Rank {r['rank']}: {r['wallet'][:16]}... score={r['smartscore']}")
    await pool.close()

asyncio.run(test())

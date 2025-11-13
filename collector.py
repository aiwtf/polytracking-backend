"""Minimal Polymarket collector (MVP).

Polls the public /v4/markets endpoint with includeTrades every POLL_INTERVAL seconds
and inserts unique trades into raw_trades. Skips duplicates via ON CONFLICT.
Robust against transient HTTP or DB errors: never crashes loop.
"""
import os, time, json, requests
from datetime import datetime
from utils.db import get_conn

POLY_REST = os.environ.get('POLY_REST_URL', 'https://api.polymarket.com/v4/markets')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '45'))  # MVP default 45s
PAGE_LIMIT = int(os.environ.get('PAGE_LIMIT', '150'))  # number of markets per fetch


def fetch_markets():
    try:
        params = {
            'limit': PAGE_LIMIT,
            'includeTrades': 'true',
        }
        resp = requests.get(POLY_REST, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get('markets') or data.get('data') or []
        return data if isinstance(data, list) else []
    except Exception as e:
        print('[ERROR] fetch_markets failed:', e)
        return []


def process_and_store(markets):
    if not markets:
        return 0
    try:
        conn = get_conn(); cur = conn.cursor()
    except Exception as e:
        print('[ERROR] DB connection failed:', e)
        return 0
    inserted = 0
    for m in markets:
        if not isinstance(m, dict):
            continue
        pool_depth = (m.get('ammPoolState') or {}).get('liquidityUSD') or 0
        mid = m.get('id') or m.get('market_id') or m.get('slug') or ''
        for t in (m.get('trades') or []):
            tid = f"{t.get('txHash')}_{t.get('logIndex') or 0}"
            try:
                cur.execute(
                    """
                    INSERT INTO raw_trades (id, market_id, trader, outcome, side, amount_usdc, cost_usdc, price_before, price_after, timestamp, block_number, pool_depth, raw_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        tid,
                        mid,
                        t.get('trader') or t.get('creator') or t.get('taker') or t.get('maker'),
                        t.get('outcome'),
                        t.get('side'),
                        float(t.get('amount') or t.get('amountUSD') or 0),
                        float(t.get('cost') or t.get('costUSD') or 0),
                        float(t.get('priceBefore') or t.get('price_before') or 0),
                        float(t.get('priceAfter') or t.get('price_after') or 0),
                        datetime.utcfromtimestamp(int(t.get('time') or t.get('timestamp') or 0)),
                        int(t.get('block') or t.get('blockNumber') or 0),
                        float(pool_depth or 0),
                        json.dumps(t),
                    ),
                )
                inserted += cur.rowcount
            except Exception as e:
                print('[WARN] trade insert failed:', e)
    try:
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print('[ERROR] commit/close failed:', e)
    print(f"collector: stored {inserted} new trades from {len(markets)} markets")
    return inserted


def run():
    print('[START] collector loop (MVP)')
    while True:
        markets = fetch_markets()
        if markets:
            process_and_store(markets)
        else:
            print('[INFO] empty markets response')
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    run()

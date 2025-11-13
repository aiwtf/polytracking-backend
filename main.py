import os, sys, subprocess
from fastapi import FastAPI, Request, HTTPException
import asyncpg
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from utils.tg_notify import send_message, get_me

app = FastAPI(title="PolyTracking Backend (MVP)")
RUN_SECRET_KEY = os.environ.get("RUN_SECRET_KEY", "changeme")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        try:
            app.state.pool = await asyncpg.create_pool(db_url)
            print("[OK] asyncpg pool ready")
        except Exception as e:
            print("[ERROR] pool create failed:", e)

@app.get("/")
def root():
    return {"status": "PolyTracking MVP backend running"}

@app.get("/healthz")
def health():
    return {"ok": True}


# WebSocket removed in MVP

@app.post("/api/run_scorer")
async def run_scorer(request: Request):
    key = request.headers.get("X-Run-Key") or request.query_params.get("key")
    if key != RUN_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid key")
    try:
        subprocess.run([sys.executable, "features.py"], check=True)
        subprocess.run([sys.executable, "scorer.py"], check=True)
        return {"ok": True, "msg": "features + scorer completed"}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": str(e)}


# Removed promo / weekly endpoints in MVP



@app.post("/api/notify_smart_bets")
async def api_notify_smart_bets(request: Request):
    key = request.headers.get("X-Run-Key") or request.query_params.get("key")
    if key != RUN_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid key")
    pool = getattr(app.state, 'pool', None)
    if not pool:
        return {"ok": False, "error": "DB not ready"}
    sent = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.trader, r.market_id, r.side, r.amount_usdc, r.timestamp, l.smartscore, wd.bait_score
            FROM raw_trades r
            JOIN leaderboard l ON l.wallet = r.trader AND l.rank_date = CURRENT_DATE
            JOIN wallet_daily wd ON wd.wallet = r.trader AND wd.day = CURRENT_DATE
            WHERE l.smartscore > 70 AND r.timestamp >= NOW() - INTERVAL '5 minutes'
            ORDER BY r.timestamp DESC
            LIMIT 50
            """
        )
        for r in rows:
            msg = (
                "🚨 Smart Money Detected\n"
                f"Wallet: {r['trader'][:10]}...{r['trader'][-6:]}\n"
                f"Market: {r['market_id']}\n"
                f"Side: {r['side']}\n"
                f"Amount: ${float(r['amount_usdc'] or 0):,.0f}\n"
                f"Score: {float(r['smartscore']):.1f}"
            )
            try:
                send_message(msg)
                sent += 1
            except Exception as e:
                print('telegram send failed:', e)
    return {"ok": True, "sent": sent}


@app.post("/api/test_tg")
async def api_test_tg(request: Request):
    key = request.headers.get("X-Run-Key") or request.query_params.get("key")
    if key != RUN_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid key")
    no_thread = request.query_params.get("no_thread") in ("1", "true", "True")
    try:
        res = send_message(
            "🔔 PolyTracking Test Message\nIf you see this, Telegram bot works.",
            None if no_thread else None  # honor env default thread unless no_thread=1
        )
        return res if isinstance(res, dict) else {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/tg_debug")
async def api_tg_debug():
    info = get_me()
    return {
        "bot": info,
        "channel_env": os.environ.get("TG_CHANNEL"),
        "thread_env": os.environ.get("TG_THREAD_ID"),
    }

# /api/wallets removed in MVP

@app.get("/api/wallet/{address}")
async def api_wallet_detail(address: str):
    pool = getattr(app.state, 'pool', None)
    if not pool:
        return {}
    async with pool.acquire() as conn:
        hist = await conn.fetch(
            """
            SELECT day, avg_roi, win_rate, trades, total_volume
            FROM wallet_daily
            WHERE wallet = $1 AND day >= CURRENT_DATE - INTERVAL '90 days'
            ORDER BY day
            """,
            address,
        )
        trades = await conn.fetch(
            """
            SELECT market_id, side, amount_usdc, price_before, price_after, timestamp
            FROM raw_trades
            WHERE trader = $1
            ORDER BY timestamp DESC
            LIMIT 30
            """,
            address,
        )
        roi_history = [
            {
                'date': str(r['day']),
                'roi': float(r['avg_roi'] or 0.0) * 100.0,
                'trades': int(r['trades'] or 0),
                'win_rate': float(r['win_rate'] or 0.0) * 100.0,
                'volume': float(r['total_volume'] or 0.0),
            }
            for r in hist
        ]
        recent_trades = [
            {
                'market': rec['market_id'],
                'side': rec['side'],
                'amount': float(rec['amount_usdc'] or 0.0),
                'priceBefore': float(rec['price_before'] or 0.0),
                'priceAfter': float(rec['price_after'] or 0.0),
                'timestamp': rec['timestamp'].isoformat(),
            }
            for rec in trades
        ]
        return {
            'wallet': address,
            'roiHistory': roi_history,
            'recentTrades': recent_trades,
        }

@app.get("/api/trades/recent")
async def api_recent_trades(limit: int = 50):
    pool = getattr(app.state, 'pool', None)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT trader, market_id, side, amount_usdc, price_before, price_after, timestamp
            FROM raw_trades
            ORDER BY timestamp DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                'wallet': r['trader'],
                'market': r['market_id'],
                'side': r['side'],
                'amount': float(r['amount_usdc'] or 0.0),
                'priceBefore': float(r['price_before'] or 0.0),
                'priceAfter': float(r['price_after'] or 0.0),
                'timestamp': r['timestamp'].isoformat(),
            }
            for r in rows
        ]

# /api/summary removed in MVP
@app.get("/api/leaderboard")
async def api_leaderboard(limit: int = 100):
    pool = getattr(app.state, 'pool', None)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rank, wallet, smartscore, reasons
            FROM leaderboard
            WHERE rank_date = CURRENT_DATE
            ORDER BY rank
            LIMIT $1
            """,
            limit,
        )
        out = []
        for r in rows:
            info = r['reasons']
            try:
                import json as _j; info = _j.loads(info)
            except Exception:
                info = {}
            out.append({
                'rank': r['rank'],
                'wallet': r['wallet'],
                'smartscore': float(r['smartscore']),
                'win_rate': float(info.get('win_rate', 0)) * 100.0,
                'avg_roi': float(info.get('avg_roi', 0)) * 100.0,
                'entry_timing': float(info.get('entry_timing', 0)),
                'recent_volume': float(info.get('recent_volume', 0)),
            })
        return out

@app.get("/api/smartmoney")
async def api_smartmoney(limit: int = 50):
    pool = getattr(app.state, 'pool', None)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.trader AS wallet, r.market_id AS market, r.amount_usdc, r.side, r.timestamp, l.smartscore
            FROM raw_trades r
            JOIN leaderboard l ON l.wallet = r.trader AND l.rank_date = CURRENT_DATE
            WHERE l.rank <= 100
            ORDER BY r.timestamp DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                'wallet': r['wallet'],
                'market': r['market'],
                'amount_usdc': float(r['amount_usdc'] or 0.0),
                'side': r['side'],
                'timestamp': r['timestamp'].isoformat(),
                'smartscore': float(r['smartscore'] or 0.0),
            }
            for r in rows
        ]

# Subscription endpoint removed in MVP

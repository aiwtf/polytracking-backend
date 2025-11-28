<<<<<<< HEAD
import asyncio
import json
import logging
import os
import requests
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from py_clob_client.client import ClobClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.warning("DATABASE_URL not set. Defaulting to SQLite for local testing.")
    DATABASE_URL = "sqlite:///./markets.db"
elif DATABASE_URL.startswith("postgres://"):
    # Fix for SQLAlchemy expecting postgresql://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@Polytracking")
TELEGRAM_THREAD_ID = int(os.getenv("TELEGRAM_THREAD_ID", "4"))

# Thresholds
VOLATILITY_THRESHOLD = 0.10
WHALE_THRESHOLD_USDC = 10000

# --- Database Setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class WatchedMarket(Base):
    __tablename__ = "watched_markets"
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

# Create tables
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Models ---
class MarketCreate(BaseModel):
    asset_id: str
    title: str

class MarketResponse(BaseModel):
    asset_id: str
    title: str
    is_active: bool

    class Config:
        orm_mode = True

# --- Monitor Logic ---
class MarketMonitor:
    def __init__(self):
        self.markets = {} # asset_id -> title
        self.last_prices = {} # asset_id -> price
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137 # Polygon
        self.client = ClobClient(host=self.host, key="", chain_id=self.chain_id) 
        self.ws_connection = None
        self.should_reconnect = False
        self.running = False

    def load_markets(self):
        db = SessionLocal()
        try:
            markets = db.query(WatchedMarket).filter(WatchedMarket.is_active == True).all()
            return {m.asset_id: m.title for m in markets}
        finally:
            db.close()

    def send_telegram_alert(self, message):
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("Telegram Token not set. Skipping alert.")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "message_thread_id": TELEGRAM_THREAD_ID,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Telegram alert sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    async def refresh_subscriptions_loop(self):
        while self.running:
            await asyncio.sleep(60)
            logger.info("Checking for market updates...")
            new_markets = self.load_markets()
            
            if set(new_markets.keys()) != set(self.markets.keys()):
                logger.info("Market list changed. Triggering reconnection...")
                self.markets = new_markets
                self.should_reconnect = True
                if self.ws_connection:
                    await self.ws_connection.close()

    def trigger_reload(self):
        """Manually trigger a reload of markets (called by API)"""
        logger.info("Manual reload triggered via API.")
        self.markets = self.load_markets()
        self.should_reconnect = True
        # We can't easily close the WS from here if it's in a different loop context, 
        # but setting should_reconnect might be enough if the loop checks it, 
        # or we rely on the next message/timeout to catch it. 
        # Ideally, we'd signal the loop. For MVP, we'll let the 60s loop or next error handle it,
        # or we can try to close if we have access to the object.
        # Since this runs in the same process, we can try:
        if self.ws_connection and not self.ws_connection.closed:
            # Scheduling the close in the loop would be better, but let's just set the flag 
            # and wait for the refresh loop or the main loop to pick it up.
            # To make it instant, we really need to cancel the WS task or close the socket.
            # We'll leave it to the refresh loop for safety or implement a proper signal later.
            pass

    async def start(self):
        self.running = True
        self.markets = self.load_markets()
        logger.info(f"Starting Monitor. Watching {len(self.markets)} markets.")
        
        self.send_telegram_alert(f"🤖 **Monitor Started**\nWatching {len(self.markets)} markets.")
        
        asyncio.create_task(self.refresh_subscriptions_loop())
        
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        import websockets
        
        while self.running:
            self.should_reconnect = False
            asset_ids = list(self.markets.keys())
            
            if not asset_ids:
                logger.warning("No active markets to watch. Waiting...")
                await asyncio.sleep(10)
                # Check again
                self.markets = self.load_markets()
                continue

            try:
                async with websockets.connect(uri) as websocket:
                    self.ws_connection = websocket
                    logger.info(f"Connected to WS. Subscribing to {len(asset_ids)} assets.")
                    
                    await websocket.send(json.dumps({
                        "assets_ids": asset_ids,
                        "type": "market",
                        "channel": "level2"
                    }))
                    await websocket.send(json.dumps({
                        "assets_ids": asset_ids,
                        "type": "market",
                        "channel": "trades"
                    }))
                    
                    while not self.should_reconnect and self.running:
                        try:
                            message = await websocket.recv()
                            data = json.loads(message)
                            await self.process_message(data)
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WS Connection closed.")
                            break
                        except Exception as e:
                            logger.error(f"Error receiving message: {e}")
                            break
                        
            except Exception as e:
                if not self.should_reconnect:
                    logger.error(f"WS Error: {e}. Reconnecting in 5s...")
                    await asyncio.sleep(5)
                else:
                    logger.info("Reconnecting due to config change...")

    async def process_message(self, data):
        if "trades" in str(data): 
             for trade in data.get("data", []):
                 asset_id = trade.get("asset_id")
                 price = float(trade.get("price", 0))
                 size = float(trade.get("size", 0))
                 
                 if asset_id in self.markets:
                     self.check_whale(asset_id, size, price)
                     self.check_volatility(asset_id, price)

    def check_volatility(self, asset_id, new_price):
        last_price = self.last_prices.get(asset_id)
        if last_price is None:
            self.last_prices[asset_id] = new_price
            return
        if new_price <= 0: return

        change_pct = (new_price - last_price) / last_price
        if abs(change_pct) >= VOLATILITY_THRESHOLD:
            direction = "🔺" if change_pct > 0 else "🔻"
            title = self.markets.get(asset_id, "Unknown Event")
            msg = (
                f"🚨 **波動警報** 🚨\n"
                f"事件：{title}\n"
                f"變化：{last_price:.2f} ➔ {new_price:.2f} {direction} ({change_pct*100:.1f}%)\n"
                f"原因：賠率突變\n"
                f"ID: `{asset_id[:10]}...`"
            )
            logger.warning(msg)
            self.send_telegram_alert(msg)
        self.last_prices[asset_id] = new_price

    def check_whale(self, asset_id, size, price):
        volume_usdc = size * price
        if volume_usdc >= WHALE_THRESHOLD_USDC:
            title = self.markets.get(asset_id, "Unknown Event")
            msg = (
                f"🚨 **巨鯨警報** 🚨\n"
                f"事件：{title}\n"
                f"金額：{volume_usdc:,.2f} USDC\n"
                f"價格：{price:.2f}\n"
                f"原因：檢測到巨額買入\n"
                f"ID: `{asset_id[:10]}...`"
            )
            logger.warning(msg)
            self.send_telegram_alert(msg)

# --- FastAPI App ---
monitor = MarketMonitor()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up FastAPI...")
    asyncio.create_task(monitor.start())
    yield
    # Shutdown
    logger.info("Shutting down...")
    monitor.running = False
    if monitor.ws_connection:
        await monitor.ws_connection.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://polytracking.vercel.app", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "ok", "monitor_running": monitor.running}

@app.get("/api/markets")
def get_markets(db: Session = Depends(get_db)):
    markets = db.query(WatchedMarket).all()
    return [{"asset_id": m.asset_id, "title": m.title, "is_active": m.is_active} for m in markets]

@app.post("/api/markets")
def add_market(market: MarketCreate, db: Session = Depends(get_db)):
    existing = db.query(WatchedMarket).filter(WatchedMarket.asset_id == market.asset_id).first()
    if existing:
        existing.title = market.title
        existing.is_active = True
    else:
        new_market = WatchedMarket(asset_id=market.asset_id, title=market.title, is_active=True)
        db.add(new_market)
    
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Market added/updated"}

@app.delete("/api/markets/{asset_id}")
def delete_market(asset_id: str, db: Session = Depends(get_db)):
    market = db.query(WatchedMarket).filter(WatchedMarket.asset_id == asset_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    
    db.delete(market)
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Market deleted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
=======
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
>>>>>>> 11db5788de2a15efac177cdec7d3ba2b0219c043

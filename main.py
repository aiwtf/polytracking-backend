import asyncio
import json
from json import JSONDecodeError
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
# 測試用超低門檻 (Test Thresholds)
VOLATILITY_THRESHOLD = 0.001  # 0.1% (只要價格動一點點就通知)
WHALE_THRESHOLD_USDC = 10     # 10 USD (只要有人買便當就通知)

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
                            if not message:
                                continue
                            
                            try:
                                data = json.loads(message)
                                await self.process_message(data)
                            except JSONDecodeError:
                                logger.warning("Received non-JSON message")
                                continue
                                
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
            
            # Prevent rapid looping on failure
            await asyncio.sleep(5)

    async def process_message(self, data):
        # 兼容性處理：Polymarket 有時傳回 List，有時傳回 Dict
        if isinstance(data, list):
            for item in data:
                await self.process_single_msg(item)
        elif isinstance(data, dict):
            await self.process_single_msg(data)

    async def process_single_msg(self, msg):
        # 確保是交易數據 (Trades)
        if "trades" not in str(msg):
            return

        # 解析數據
        for trade in msg.get("data", []):
            asset_id = trade.get("asset_id")
            try:
                price = float(trade.get("price", 0))
                size = float(trade.get("size", 0))
            except (ValueError, TypeError):
                continue
            
            # 只有當這是我們監控的 ID 時才處理
            if asset_id in self.markets:
                # [DEBUG] 心跳日誌：證明程式有看到數據 (不會發 TG)
                logger.info(f"👁️ Seen trade | Price: {price:.4f} | Size: ${size*price:.2f}")
                
                # 執行檢查
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
    allow_origins=["*"],
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

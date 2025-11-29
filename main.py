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
WHALE_THRESHOLD_USDC = 50000

# --- Database Setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class WatchedMarket(Base):
    __tablename__ = "watched_markets_v2"
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    # Granular Notification Settings
    notify_1pct = Column(Boolean, default=False)
    notify_5pct = Column(Boolean, default=False)
    notify_10pct = Column(Boolean, default=False)

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
    notify_1pct: Optional[bool] = False
    notify_5pct: Optional[bool] = False
    notify_10pct: Optional[bool] = False

class MarketUpdate(BaseModel):
    title: Optional[str] = None
    is_active: Optional[bool] = None
    notify_1pct: Optional[bool] = None
    notify_5pct: Optional[bool] = None
    notify_10pct: Optional[bool] = None

class MarketResponse(BaseModel):
    asset_id: str
    title: str
    is_active: bool
    notify_1pct: bool
    notify_5pct: bool
    notify_10pct: bool

    class Config:
        orm_mode = True

# --- Monitor Logic ---
class MarketMonitor:
    def __init__(self):
        self.markets = {} # asset_id -> dict of settings
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
            return {
                m.asset_id: {
                    "title": m.title,
                    "notify_1pct": m.notify_1pct,
                    "notify_5pct": m.notify_5pct,
                    "notify_10pct": m.notify_10pct
                } 
                for m in markets
            }
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
            else:
                # Update settings even if keys didn't change
                self.markets = new_markets

    def trigger_reload(self):
        """Manually trigger a reload of markets (called by API)"""
        logger.info("Manual reload triggered via API.")
        self.markets = self.load_markets()
        self.should_reconnect = True
        if self.ws_connection and not self.ws_connection.closed:
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
                            
                            # [DEBUG] Log raw message to see what we are getting
                            if len(message) < 1000:
                                logger.info(f"RAW MSG: {message}")
                            else:
                                logger.info(f"RAW MSG (truncated): {message[:200]}...")

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
        # Polymarket 的 trade 事件通常包含 "data" 或 "trades" 列表
        data_list = msg.get("data", [])
        if not data_list and "trades" in msg:
            data_list = msg.get("trades", [])
            
        if not data_list:
            return

        for trade in data_list:
            asset_id = trade.get("asset_id")
            try:
                price = float(trade.get("price", 0))
                size = float(trade.get("size", 0))
            except (ValueError, TypeError):
                continue
            
            if asset_id in self.markets:
                logger.info(f"👁️ Seen trade | Price: {price:.4f} | Size: ${size*price:.2f}")
                self.check_whale(asset_id, size, price)
                self.check_volatility(asset_id, price)

    def check_volatility(self, asset_id, new_price):
        last_price = self.last_prices.get(asset_id)
        if last_price is None:
            self.last_prices[asset_id] = new_price
            return
        if new_price <= 0: return

        change_pct = (new_price - last_price) / last_price
        abs_change = abs(change_pct)
        
        settings = self.markets.get(asset_id, {})
        title = settings.get("title", "Unknown Event")
        
        should_alert = False
        alert_emoji = ""
        threshold_text = ""

        # Logic: Pick the highest priority alert
        if abs_change >= 0.10 and settings.get("notify_10pct"):
            should_alert = True
            alert_emoji = "🔥" # Fire for huge moves
            threshold_text = ">10%"
        elif abs_change >= 0.05 and settings.get("notify_5pct"):
            should_alert = True
            alert_emoji = "⚡" # Lightning for big moves
            threshold_text = ">5%"
        elif abs_change >= 0.01 and settings.get("notify_1pct"):
            should_alert = True
            alert_emoji = "🌊" # Wave for small moves
            threshold_text = ">1%"

        if should_alert:
            direction_emoji = "�" if change_pct > 0 else "�"
            trend_text = "SURGE" if change_pct > 0 else "DUMP"
            
            # 建立 Polymarket 連結 (如果有 slug 最好，沒有則連首頁或用 ID 搜尋)
            # 這裡我們用搜尋連結作為替代方案，因為沒有存 slug
            link = f"https://polymarket.com/"

            msg = (
                f"{alert_emoji} **{trend_text} ALERT** ({threshold_text})\n\n"
                f"🔮 **Event**: {title}\n"
                f"{direction_emoji} **Move**: {last_price:.3f} ➔ {new_price:.3f} ({change_pct*100:+.1f}%)\n"
                f"📊 **Price**: ${new_price:.3f}\n\n"
                f"[View on Polymarket ↗]({link})"
            )
            
            logger.warning(msg)
            self.send_telegram_alert(msg)
            
        self.last_prices[asset_id] = new_price

    def check_whale(self, asset_id, size, price):
        volume_usdc = size * price
        if volume_usdc >= WHALE_THRESHOLD_USDC:
            settings = self.markets.get(asset_id, {})
            title = settings.get("title", "Unknown Event")
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

@app.get("/api/markets", response_model=List[MarketResponse])
def get_markets(db: Session = Depends(get_db)):
    markets = db.query(WatchedMarket).all()
    return markets

@app.post("/api/markets")
def add_market(market: MarketCreate, db: Session = Depends(get_db)):
    existing = db.query(WatchedMarket).filter(WatchedMarket.asset_id == market.asset_id).first()
    if existing:
        existing.title = market.title
        existing.is_active = True
        # Update settings if provided (or keep existing? User request implies update)
        # For POST, usually we overwrite or set defaults. 
        # Let's update them to match the input.
        existing.notify_1pct = market.notify_1pct
        existing.notify_5pct = market.notify_5pct
        existing.notify_10pct = market.notify_10pct
    else:
        new_market = WatchedMarket(
            asset_id=market.asset_id, 
            title=market.title, 
            is_active=True,
            notify_1pct=market.notify_1pct,
            notify_5pct=market.notify_5pct,
            notify_10pct=market.notify_10pct
        )
        db.add(new_market)
    
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Market added/updated"}

@app.patch("/api/markets/{asset_id}")
def update_market(asset_id: str, market_update: MarketUpdate, db: Session = Depends(get_db)):
    market = db.query(WatchedMarket).filter(WatchedMarket.asset_id == asset_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    
    update_data = market_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(market, key, value)
    
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Market updated"}

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

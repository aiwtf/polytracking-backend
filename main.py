import asyncio
import json
from json import JSONDecodeError
import logging
import os
import requests
import uuid
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

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
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@Polytracking") # Fallback/Global channel
TELEGRAM_THREAD_ID = int(os.getenv("TELEGRAM_THREAD_ID", "4"))

# Thresholds
WHALE_THRESHOLD_USDC = 50000

# --- Database Setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users_v1"
    id = Column(Integer, primary_key=True, index=True)
    clerk_user_id = Column(String, unique=True, index=True, nullable=False)
    telegram_chat_id = Column(String, nullable=True)
    connection_token = Column(String, nullable=True)
    is_premium = Column(Boolean, default=False)
    
    subscriptions = relationship("Subscription", back_populates="user")

class Subscription(Base):
    __tablename__ = "subscriptions_v1"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users_v1.id'), nullable=False)
    asset_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    target_outcome = Column(String, nullable=True)
    
    # Thresholds
    notify_0_5pct = Column(Boolean, default=False) # >0.5%
    notify_2pct = Column(Boolean, default=False)   # >2%
    notify_5pct = Column(Boolean, default=False)   # >5%
    notify_whale_10k = Column(Boolean, default=False) # >10k USD
    notify_whale_50k = Column(Boolean, default=False) # >50k USD
    notify_liquidity = Column(Boolean, default=False) # Liquidity spike
    
    user = relationship("User", back_populates="subscriptions")

# Create tables
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Models ---
class ConnectTelegramRequest(BaseModel):
    clerk_user_id: str

class MarketCreate(BaseModel):
    clerk_user_id: str
    asset_id: str
    title: str
    target_outcome: Optional[str] = "Yes"
    notify_0_5pct: Optional[bool] = False
    notify_2pct: Optional[bool] = False
    notify_5pct: Optional[bool] = False
    notify_whale_10k: Optional[bool] = False
    notify_whale_50k: Optional[bool] = False
    notify_liquidity: Optional[bool] = False

class MarketResponse(BaseModel):
    asset_id: str
    title: str
    target_outcome: Optional[str]
    notify_0_5pct: bool
    notify_2pct: bool
    notify_5pct: bool
    notify_whale_10k: bool
    notify_whale_50k: bool
    notify_liquidity: bool

    class Config:
        orm_mode = True

# --- Monitor Logic ---
class MarketMonitor:
    def __init__(self):
        self.markets = {} # asset_id -> { "title": ..., "subscribers": [user_id, ...] } (Simplified for now)
        self.last_prices = {} # asset_id -> price
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137 # Polygon
        self.client = ClobClient(host=self.host, key="", chain_id=self.chain_id) 
        self.ws_connection = None
        self.should_reconnect = False
        self.running = False

    def load_markets(self):
        """
        Loads all unique asset_ids from Subscription table.
        Returns a dict: { asset_id: { 'title': title } }
        For MVP, we just need the list of assets to watch.
        """
        db = SessionLocal()
        try:
            # Query all subscriptions
            subs = db.query(Subscription).all()
            
            # Aggregate unique assets
            market_map = {}
            for sub in subs:
                if sub.asset_id not in market_map:
                    market_map[sub.asset_id] = {
                        "title": sub.title,
                        # We could store a list of interested users here for targeted alerts later
                        "subscribers": [] 
                    }
                market_map[sub.asset_id]["subscribers"].append(sub.user_id)
            
            return market_map
        finally:
            db.close()

    def send_telegram_alert(self, message, chat_id=None):
        target_chat_id = chat_id or TELEGRAM_CHAT_ID
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("Telegram Token not set. Skipping alert.")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        # Only use thread_id if sending to the main channel
        if target_chat_id == TELEGRAM_CHAT_ID:
             payload["message_thread_id"] = TELEGRAM_THREAD_ID

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Telegram alert sent successfully to {target_chat_id}.")
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
        
        # self.send_telegram_alert(f"🤖 **Monitor Started**\nWatching {len(self.markets)} markets.")
        
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
                            # if len(message) < 1000:
                            #     logger.info(f"RAW MSG: {message}")
                            
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
        
        # NOTE: For MVP, we are broadcasting to the main channel based on global thresholds.
        # In a full SaaS, we would iterate through `settings['subscribers']`, check their individual thresholds,
        # and send private messages to their `telegram_chat_id`.
        
        should_alert = False
        alert_emoji = ""
        threshold_text = ""

        # Simplified Logic for MVP: Alert if > 1% change (can be refined to check DB flags)
        if abs_change >= 0.10:
            should_alert = True
            alert_emoji = "🔥" 
            threshold_text = ">10%"
        elif abs_change >= 0.05:
            should_alert = True
            alert_emoji = "⚡" 
            threshold_text = ">5%"
        elif abs_change >= 0.02: # Changed from 1% to 2% as per new requirements
            should_alert = True
            alert_emoji = "🌊" 
            threshold_text = ">2%"
        elif abs_change >= 0.005: # 0.5%
             should_alert = True
             alert_emoji = "💧"
             threshold_text = ">0.5%"

        if should_alert:
            direction_emoji = "" if change_pct > 0 else ""
            trend_text = "SURGE" if change_pct > 0 else "DUMP"
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
        
        # Simplified Whale Logic
        if volume_usdc >= 10000: # 10k threshold
            settings = self.markets.get(asset_id, {})
            title = settings.get("title", "Unknown Event")
            
            emoji = "🐋" if volume_usdc >= 50000 else "🐟"
            
            msg = (
                f"{emoji} **巨鯨警報** {emoji}\n"
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

@app.post("/api/connect_telegram")
def connect_telegram(req: ConnectTelegramRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.clerk_user_id == req.clerk_user_id).first()
    if not user:
        user = User(clerk_user_id=req.clerk_user_id)
        db.add(user)
    
    # Generate a new connection token
    token = str(uuid.uuid4())
    user.connection_token = token
    db.commit()
    
    return {"status": "success", "connection_token": token}

@app.get("/api/markets", response_model=List[MarketResponse])
def get_markets(clerk_user_id: str, db: Session = Depends(get_db)):
    # Find user
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    if not user:
        return []
    
    return user.subscriptions

@app.post("/api/markets")
def add_market(market: MarketCreate, db: Session = Depends(get_db)):
    # Find or Create User
    user = db.query(User).filter(User.clerk_user_id == market.clerk_user_id).first()
    if not user:
        user = User(clerk_user_id=market.clerk_user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    # Check if subscription exists
    existing = db.query(Subscription).filter(
        Subscription.user_id == user.id,
        Subscription.asset_id == market.asset_id
    ).first()

    if existing:
        existing.title = market.title
        existing.target_outcome = market.target_outcome
        existing.notify_0_5pct = market.notify_0_5pct
        existing.notify_2pct = market.notify_2pct
        existing.notify_5pct = market.notify_5pct
        existing.notify_whale_10k = market.notify_whale_10k
        existing.notify_whale_50k = market.notify_whale_50k
        existing.notify_liquidity = market.notify_liquidity
    else:
        new_sub = Subscription(
            user_id=user.id,
            asset_id=market.asset_id, 
            title=market.title,
            target_outcome=market.target_outcome,
            notify_0_5pct=market.notify_0_5pct,
            notify_2pct=market.notify_2pct,
            notify_5pct=market.notify_5pct,
            notify_whale_10k=market.notify_whale_10k,
            notify_whale_50k=market.notify_whale_50k,
            notify_liquidity=market.notify_liquidity
        )
        db.add(new_sub)
    
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Subscription added/updated"}

@app.delete("/api/markets/{asset_id}")
def delete_market(asset_id: str, clerk_user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub = db.query(Subscription).filter(
        Subscription.user_id == user.id,
        Subscription.asset_id == asset_id
    ).first()
    
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    db.delete(sub)
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Subscription deleted"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON"}

    # Basic validation
    if "message" not in data:
        return {"status": "ignored"}
    
    message = data["message"]
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    
    if not chat_id or not text:
        return {"status": "ignored"}

    if text.startswith("/start"):
        parts = text.split()
        if len(parts) == 2:
            token = parts[1]
            
            # Find user with this token
            user = db.query(User).filter(User.connection_token == token).first()
            
            if user:
                user.telegram_chat_id = str(chat_id)
                user.connection_token = None # Invalidate token
                db.commit()
                
                monitor.send_telegram_alert(
                    "✅ 綁定成功！您現在可以在網頁上訂閱市場了。",
                    chat_id=chat_id
                )
            else:
                monitor.send_telegram_alert(
                    "❌ 綁定失敗，無效的連結或連結已過期。請從網頁重新點擊連結。",
                    chat_id=chat_id
                )
        else:
             # Just /start without token
             monitor.send_telegram_alert(
                "請從 PolyTracking 網頁點擊「綁定 Telegram」按鈕來啟動。",
                chat_id=chat_id
             )

    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

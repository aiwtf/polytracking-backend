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
    __tablename__ = "users_v3"
    id = Column(Integer, primary_key=True, index=True)
    clerk_user_id = Column(String, unique=True, index=True, nullable=False)
    telegram_chat_id = Column(String, nullable=True)
    connection_token = Column(String, nullable=True)
    is_premium = Column(Boolean, default=False)
    
    subscriptions = relationship("Subscription", back_populates="user")

class Subscription(Base):
    __tablename__ = "subscriptions_v3"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users_v3.id'), nullable=False)
    asset_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    target_outcome = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    
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

class SubscriptionCreate(BaseModel):
    clerk_user_id: str
    asset_id: str
    title: str
    target_outcome: Optional[str] = "Yes"
    image_url: Optional[str] = None
    notify_0_5pct: Optional[bool] = False
    notify_2pct: Optional[bool] = False
    notify_5pct: Optional[bool] = False
    notify_whale_10k: Optional[bool] = False
    notify_whale_50k: Optional[bool] = False
    notify_liquidity: Optional[bool] = False

class SubscriptionUpdate(BaseModel):
    notify_0_5pct: Optional[bool] = None
    notify_2pct: Optional[bool] = None
    notify_5pct: Optional[bool] = None
    notify_whale_10k: Optional[bool] = None
    notify_whale_50k: Optional[bool] = None
    notify_liquidity: Optional[bool] = None

class SubscriptionResponse(BaseModel):
    id: int
    asset_id: str
    title: str
    target_outcome: Optional[str]
    image_url: Optional[str]
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
        self.markets = {} 
        self.last_prices = {} 
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137 
        self.client = ClobClient(host=self.host, key="", chain_id=self.chain_id) 
        self.ws_connection = None
        self.should_reconnect = False
        self.running = False
        self.db_session = SessionLocal()

    def load_markets(self):
        db = SessionLocal()
        try:
            # Query all unique asset_ids
            asset_ids = db.query(Subscription.asset_id).distinct().all()
            # We also need to know which users to notify, but for MVP we check DB in check_volatility
            # So here we just return the keys to subscribe to.
            return {row[0]: {} for row in asset_ids}
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
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
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

    def trigger_reload(self):
        """Manually trigger a reload of markets (called by API)"""
        logger.info("Manual reload triggered via API.")
        self.markets = self.load_markets()
        self.should_reconnect = True
        # Loop will handle reconnection based on self.should_reconnect

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
                self.markets = new_markets

    async def start(self):
        self.running = True
        self.markets = self.load_markets()
        logger.info(f"Starting Monitor. Watching {len(self.markets)} markets.")
        
        asyncio.create_task(self.refresh_subscriptions_loop())
        # Start Polling Loop as Fallback
        asyncio.create_task(self.poll_markets_loop())
        
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
                    
                    # Subscribe to markets
                    # Polymarket CLOB WebSocket expects a list of asset IDs
                    # Format: {"type": "market", "assets_ids": ["id1", "id2"], "channel": "trades"}
                    # Note: "assets_ids" is the correct key based on documentation/examples
                    
                    sub_msg_trades = {
                        "assets_ids": asset_ids,
                        "type": "market",
                        "channel": "trades"
                    }
                    # We can also subscribe to level2 if needed, but trades is primary for price
                    # sub_msg_level2 = {
                    #     "assets_ids": asset_ids,
                    #     "type": "market",
                    #     "channel": "level2"
                    # }
                    
                    logger.info(f"Sending subscription: {json.dumps(sub_msg_trades)}")
                    await websocket.send(json.dumps(sub_msg_trades))
                    
                    while not self.should_reconnect and self.running:
                        try:
                            message = await websocket.recv()
                            if not message:
                                continue
                            
                            # Handle Ping/Pong (Polymarket might send raw strings)
                            if isinstance(message, str):
                                if "ping" in message.lower():
                                    await websocket.send("PONG")
                                    continue
                                if "pong" in message.lower():
                                    continue

                            try:
                                data = json.loads(message)
                                
                                # Check for error response
                                if isinstance(data, dict) and "error" in data:
                                    logger.error(f"WebSocket Error Response: {data}")
                                    continue
                                    
                                await self.process_message(data)
                            except JSONDecodeError:
                                logger.warning(f"Received non-JSON message: {message}")
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

    async def poll_markets_loop(self):
        """Fallback polling loop in case WS fails"""
        logger.info("Starting Polling Loop...")
        while self.running:
            try:
                await self.poll_markets()
            except Exception as e:
                logger.error(f"Polling Error: {e}")
            await asyncio.sleep(10) # Poll every 10s

    async def poll_markets(self):
        if not self.markets:
            return

        # We need to fetch prices for all subscribed assets
        # Gamma API allows fetching by clob_token_id, but maybe not in batch efficiently?
        # Let's try to fetch by market ID if we had it, but we only have asset_id.
        # For now, we iterate or find a batch endpoint. 
        # Actually, checking individual assets might be slow if many.
        # But for MVP with few subs, it's fine. 
        # Optimization: Fetch top markets or use a broader search?
        # Better: Use the /markets endpoint with clob_token_id param if it supports multiple?
        # It seems it might not.
        # Let's try to fetch individually for now, or group if possible.
        
        # To avoid rate limits, let's process in chunks or sequentially with small delay?
        # Or just do it.
        
        for asset_id in list(self.markets.keys()):
            try:
                # Use Gamma API to get market data
                url = "https://gamma-api.polymarket.com/markets"
                params = {"clob_token_id": asset_id}
                
                # Use async client if possible, but requests is sync. 
                # For this implementation, we'll use requests in a thread or just block briefly (not ideal for high load but ok here)
                # Better: Use aiohttp or run_in_executor
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, lambda: requests.get(url, params=params, timeout=5))
                
                if response.ok:
                    data = response.json()
                    if isinstance(data, list) and data:
                        market = data[0]
                        
                        # Extract price
                        clob_ids = market.get("clobTokenIds", [])
                        if isinstance(clob_ids, str): clob_ids = json.loads(clob_ids)
                        
                        outcome_prices = market.get("outcomePrices", [])
                        if isinstance(outcome_prices, str): outcome_prices = json.loads(outcome_prices)
                        
                        if asset_id in clob_ids and outcome_prices:
                            idx = clob_ids.index(asset_id)
                            if idx < len(outcome_prices):
                                try:
                                    price = float(outcome_prices[idx])
                                    logger.info(f"Polled {asset_id}: {price}")
                                    self.check_volatility(asset_id, price)
                                except ValueError:
                                    pass
            except Exception as e:
                logger.error(f"Error polling {asset_id}: {e}")
            
            await asyncio.sleep(0.1) # Rate limit protection

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
                # logger.info(f"👁️ Seen trade | Price: {price:.4f} | Size: ${size*price:.2f}")
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
        
        # Determine Alert Level
        alert_level = None
        if abs_change >= 0.05: alert_level = "5pct"
        elif abs_change >= 0.02: alert_level = "2pct"
        elif abs_change >= 0.005: alert_level = "0_5pct"
        
        if alert_level:
            db = SessionLocal()
            try:
                # Find subscribers for this asset
                subs = db.query(Subscription).filter(Subscription.asset_id == asset_id).all()
                
                for sub in subs:
                    # Check if user wants this alert
                    should_notify = False
                    if alert_level == "5pct" and sub.notify_5pct: should_notify = True
                    elif alert_level == "2pct" and sub.notify_2pct: should_notify = True
                    elif alert_level == "0_5pct" and sub.notify_0_5pct: should_notify = True
                    
                    # Fallback: Higher thresholds imply lower ones (optional, but good UX)
                    if not should_notify:
                         if alert_level == "5pct" and (sub.notify_2pct or sub.notify_0_5pct): should_notify = True
                         elif alert_level == "2pct" and sub.notify_0_5pct: should_notify = True

                    if should_notify and sub.user.telegram_chat_id:
                        direction_emoji = "📈" if change_pct > 0 else "📉"
                        trend_text = "SURGE" if change_pct > 0 else "DUMP"
                        link = f"https://polymarket.com/event/{sub.title.replace(' ', '-').lower()}" # Approximate link

                        msg = (
                            f"{direction_emoji} **{trend_text} ALERT** ({abs_change*100:.1f}%)\n\n"
                            f"🔮 **Event**: {sub.title}\n"
                            f"🎯 **Outcome**: {sub.target_outcome}\n"
                            f"💰 **Price**: {last_price:.3f} ➔ {new_price:.3f}\n\n"
                            f"[View Market]({link})"
                        )
                        self.send_telegram_alert(msg, chat_id=sub.user.telegram_chat_id)
            finally:
                db.close()
            
        self.last_prices[asset_id] = new_price

    def check_whale(self, asset_id, size, price):
        volume_usdc = size * price
        
        whale_level = None
        if volume_usdc >= 50000: whale_level = "50k"
        elif volume_usdc >= 10000: whale_level = "10k"
        
        if whale_level:
            db = SessionLocal()
            try:
                subs = db.query(Subscription).filter(Subscription.asset_id == asset_id).all()
                for sub in subs:
                    should_notify = False
                    if whale_level == "50k" and sub.notify_whale_50k: should_notify = True
                    elif whale_level == "10k" and sub.notify_whale_10k: should_notify = True
                    
                    # 50k implies 10k interest usually
                    if whale_level == "50k" and sub.notify_whale_10k: should_notify = True

                    if should_notify and sub.user.telegram_chat_id:
                        emoji = "🐋" if whale_level == "50k" else "🐟"
                        msg = (
                            f"{emoji} **WHALE ALERT** {emoji}\n\n"
                            f"🔮 **Event**: {sub.title}\n"
                            f"🎯 **Outcome**: {sub.target_outcome}\n"
                            f"💵 **Amount**: ${volume_usdc:,.0f}\n"
                            f"📊 **Price**: {price:.3f}"
                        )
                        self.send_telegram_alert(msg, chat_id=sub.user.telegram_chat_id)
            finally:
                db.close()

# --- FastAPI App ---
monitor = MarketMonitor()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up FastAPI...")
    logger.info("🚀 STARTING BACKEND V3 (Schema Fix + Test Endpoint) 🚀")
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

@app.get("/api/user/status")
def get_user_status(clerk_user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    if not user:
        return {"telegram_connected": False, "chat_id": None}
    
    return {
        "telegram_connected": bool(user.telegram_chat_id),
        "chat_id": user.telegram_chat_id
    }

@app.post("/api/disconnect_telegram")
def disconnect_telegram(req: ConnectTelegramRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.clerk_user_id == req.clerk_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.telegram_chat_id = None
    db.commit()
    return {"status": "success", "message": "Telegram disconnected"}

@app.get("/api/subscriptions", response_model=List[SubscriptionResponse])
def get_subscriptions(clerk_user_id: str, db: Session = Depends(get_db)):
    # Find user
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    if not user:
        return []
    
    return user.subscriptions

@app.post("/api/subscribe")
def subscribe(sub_data: SubscriptionCreate, db: Session = Depends(get_db)):
    logger.info(f"Received subscription request: {sub_data.dict()}")
    # Find or Create User
    user = db.query(User).filter(User.clerk_user_id == sub_data.clerk_user_id).first()
    if not user:
        logger.info(f"Creating new user for {sub_data.clerk_user_id}")
        user = User(clerk_user_id=sub_data.clerk_user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    # Check if subscription exists
    existing = db.query(Subscription).filter(
        Subscription.user_id == user.id,
        Subscription.asset_id == sub_data.asset_id
    ).first()

    if existing:
        logger.info(f"Updating existing subscription {existing.id}")
        # Update existing
        existing.title = sub_data.title
        existing.target_outcome = sub_data.target_outcome
        existing.notify_0_5pct = sub_data.notify_0_5pct
        existing.notify_2pct = sub_data.notify_2pct
        existing.notify_5pct = sub_data.notify_5pct
        existing.notify_whale_10k = sub_data.notify_whale_10k
        existing.notify_whale_50k = sub_data.notify_whale_50k
        existing.notify_liquidity = sub_data.notify_liquidity
        if sub_data.image_url:
            existing.image_url = sub_data.image_url
    else:
        logger.info("Creating new subscription")
        # Create new
        new_sub = Subscription(
            user_id=user.id,
            asset_id=sub_data.asset_id, 
            title=sub_data.title,
            target_outcome=sub_data.target_outcome,
            image_url=sub_data.image_url,
            notify_0_5pct=sub_data.notify_0_5pct,
            notify_2pct=sub_data.notify_2pct,
            notify_5pct=sub_data.notify_5pct,
            notify_whale_10k=sub_data.notify_whale_10k,
            notify_whale_50k=sub_data.notify_whale_50k,
            notify_liquidity=sub_data.notify_liquidity
        )
        db.add(new_sub)
    
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Subscription added/updated"}

@app.patch("/api/subscriptions/{id}")
def update_subscription(id: int, updates: SubscriptionUpdate, clerk_user_id: str, db: Session = Depends(get_db)):
    # Verify user owns this subscription
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub = db.query(Subscription).filter(Subscription.id == id, Subscription.user_id == user.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Apply updates
    update_data = updates.dict(exclude_unset=True)
    logger.info(f"Updating sub {id} with: {update_data}")
    
    for key, value in update_data.items():
        setattr(sub, key, value)
    
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Subscription updated"}

@app.delete("/api/subscriptions/{id}")
def delete_subscription(id: int, clerk_user_id: str, db: Session = Depends(get_db)):
    logger.info(f"Received delete request for sub {id} user {clerk_user_id}")
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    if not user:
        logger.warning(f"User not found for clerk_id: {clerk_user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    # Debug: Check if sub exists at all
    sub_check = db.query(Subscription).filter(Subscription.id == id).first()
    if sub_check:
        logger.info(f"Debug: Sub {id} exists. Owner: {sub_check.user_id}. Requesting User: {user.id}")
    else:
        logger.info(f"Debug: Sub {id} does NOT exist in DB.")

    sub = db.query(Subscription).filter(Subscription.id == id, Subscription.user_id == user.id).first()
    if not sub:
        logger.warning(f"Subscription {id} not found for user {user.id}")
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    db.delete(sub)
    db.commit()
    monitor.trigger_reload()
    return {"status": "success", "message": "Subscription deleted"}

# Keep legacy endpoints for compatibility during migration if needed, or redirect them
# For now, we assume frontend will be updated to use new endpoints.

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
                    "✅ 綁定成功！您已可接收客製化通知。\n\n💬 加入官方討論群：https://t.me/Polytracking/4",
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

@app.get("/api/proxy/search")
def search_markets(q: str):
    """
    Proxy to Polymarket Gamma API to search for markets.
    Uses /public-search endpoint for better keyword matching.
    Supports direct Polymarket event URLs.
    """
    if not q:
        return []
    
    # Use public-search endpoint
    url = "https://gamma-api.polymarket.com/public-search"
    
    # Check if input is a Polymarket URL
    if "polymarket.com/event/" in q:
        try:
            # Extract slug: https://polymarket.com/event/slug-name?params -> slug-name
            # Split by 'event/' and take the part after it
            slug_part = q.split("polymarket.com/event/")[1]
            # Split by '?' to remove query params and take the first part
            slug = slug_part.split("?")[0]
            # Remove any trailing slashes
            slug = slug.strip("/")
            
            params = {"slug": slug}
        except Exception:
            # Fallback to normal search if parsing fails
            params = {
                "limit": 100,
                "q": q
            }
    else:
        # Normal keyword search
        params = {
            "limit": 100,
            "q": q
        }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # public-search returns a dict with 'events' key
        events = data.get("events", []) if isinstance(data, dict) else data
        
        results = []
        
        for event in events:
            # Basic validation
            if not isinstance(event, dict):
                continue
                
            title = event.get("title", "")
            markets = event.get("markets", [])
            
            if not markets:
                continue
            
            # Filter out closed or resolved events if possible
            if event.get("closed") is True:
                continue

            # Extract valid markets
            valid_markets = []
            for market in markets:
                # Skip closed markets
                if market.get("closed") is True:
                    continue
                # Parse outcomePrices if it's a string
                outcome_prices = market.get("outcomePrices", [])
                if isinstance(outcome_prices, str):
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except:
                        outcome_prices = []

                # Parse clobTokenIds if it's a string
                clob_token_ids = market.get("clobTokenIds", [])
                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except:
                        clob_token_ids = []
                
                # Use the first token ID (usually "Yes" or primary outcome) as asset_id
                # Polymarket binary: [Yes_Token, No_Token] or similar. 
                # We need a valid asset_id to track.
                asset_id = clob_token_ids[0] if clob_token_ids and len(clob_token_ids) > 0 else None
                
                if not asset_id:
                    continue

                # Get the price
                current_price = 0.0
                if outcome_prices and len(outcome_prices) > 0:
                    try:
                        current_price = float(outcome_prices[0])
                    except:
                        pass
                
                # Fallback to bestAsk
                if current_price == 0 or current_price == 1:
                     best_ask = market.get("bestAsk")
                     if best_ask:
                         try:
                             current_price = float(best_ask)
                         except:
                             pass

                valid_markets.append({
                    "asset_id": asset_id,
                    "name": market.get("groupItemTitle") or market.get("question") or "Outcome",
                    "current_price": current_price
                })
            
            # Use the first market's image or event image
            image = event.get("image") or event.get("icon") or "https://polymarket.com/images/default-market.png"
            
            results.append({
                "title": title,
                "image": image,
                "options": valid_markets
            })
            
        return results

    except Exception as e:
        logger.error(f"Search API Error: {e}")
        return []

class TestNotificationRequest(BaseModel):
    subscription_id: int
    clerk_user_id: str

@app.post("/api/debug/test-notification")
def test_notification(req: TestNotificationRequest, db: Session = Depends(get_db)):
    # Verify user
    user = db.query(User).filter(User.clerk_user_id == req.clerk_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify subscription
    sub = db.query(Subscription).filter(Subscription.id == req.subscription_id, Subscription.user_id == user.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if not user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram not connected")

    # Send test message
    msg = (
        f"🧪 **TEST NOTIFICATION** 🧪\n\n"
        f"This is a test alert for:\n"
        f"🔮 **{sub.title}**\n"
        f"🎯 **{sub.target_outcome}**\n\n"
        f"If you see this, your Telegram alerts are working perfectly! ✅"
    )
    
    monitor.send_telegram_alert(msg, chat_id=user.telegram_chat_id)
    return {"status": "success", "message": "Test notification sent"}

class SimulateTradeRequest(BaseModel):
    asset_id: str
    price: float
    size: float

@app.post("/api/debug/simulate_trade")
def simulate_trade(req: SimulateTradeRequest):
    """
    Simulate a trade to trigger volatility and whale alerts.
    Forces a 100% price increase to ensure volatility trigger.
    """
    logger.info(f"🧪 SIMULATING TRADE: {req.dict()}")
    
    # 1. Force Volatility: Set previous price to 50% of new price
    # This ensures (new - old) / old = (1 - 0.5) / 0.5 = 1.0 (100% increase)
    monitor.last_prices[req.asset_id] = req.price * 0.5
    
    # 2. Trigger Checks
    # Check Whale first (independent of price history, just volume)
    monitor.check_whale(req.asset_id, req.size, req.price)
    
    # Check Volatility (will compare req.price against the 0.5*price we just set)
    monitor.check_volatility(req.asset_id, req.price)
    
    return {
        "status": "simulated", 
        "message": f"Simulated trade for {req.asset_id} at ${req.price} (Vol: ${req.size*req.price:,.2f})"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

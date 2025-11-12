from fastapi import FastAPI
import requests, asyncio, os
from telegram import Bot

app = FastAPI()

# ======= 你的設定區 =======
POLYMARKET_API = "https://gamma-api.polymarket.com/events"
TELEGRAM_BOT_TOKEN = "8273191300:AAH4m6RZwJnNccIAiXk2FStX8KgkueIyOyo"
TELEGRAM_CHAT_ID = "@Polytracking"
MESSAGE_THREAD_ID = 4  # 討論串 ID (https://t.me/Polytracking/4)
# ==========================

bot = Bot(token=TELEGRAM_BOT_TOKEN)

@app.get("/")
def root():
    return {"status": "PolyTracking backend is running."}

@app.get("/update")
def fetch_data():
    res = requests.get(POLYMARKET_API)
    data = res.json()
    if not data or "data" not in data:
        return {"error": "no data"}

    # 篩選出熱門市場前 3
    markets = sorted(data["data"], key=lambda x: x.get("liquidity", 0), reverse=True)[:3]
    msg = "🔥 Polymarket 熱門市場趨勢：\n\n"
    for m in markets:
        title = m.get("title")
        volume = round(m.get("volume", 0), 2)
        liquidity = round(m.get("liquidity", 0), 2)
        msg += f"📊 {title}\n💧 流動性: ${liquidity} | 交易量: ${volume}\n\n"

    # 發送到 Telegram 的特定討論串
    asyncio.run(bot.send_message(
        chat_id=TELEGRAM_CHAT_ID, 
        message_thread_id=MESSAGE_THREAD_ID,
        text=msg
    ))
    return {"message": "已更新並推送至 Telegram 討論串"}

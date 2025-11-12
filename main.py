from fastapi import FastAPI
import requests
import asyncio
import statistics
from datetime import datetime, timedelta
from typing import Dict, List
from telegram import Bot

# ===== 基本設定 =====
POLYMARKET_API = "https://gamma-api.polymarket.com/events"
ANALYSIS_INTERVAL_MIN = 10  # 幾分鐘分析一次
TELEGRAM_BOT_TOKEN = "8273191300:AAH4m6RZwJnNccIAiXk2FStX8KgkueIyOyo"
TELEGRAM_CHAT_ID = "@Polytracking"
MESSAGE_THREAD_ID = 4  # 討論串 ID (https://t.me/Polytracking/4)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
app = FastAPI()

# ====== 工具函式 ======
def fetch_markets(limit=50):
    try:
        res = requests.get(POLYMARKET_API, params={"limit": limit})
        res.raise_for_status()
        return res.json().get("data", [])
    except Exception as e:
        print("❌ Polymarket API 錯誤：", e)
        return []

def analyze_wallets(data: List[Dict]) -> Dict:
    wallets = {}

    for event in data:
        trades = event.get("markets", [])
        for m in trades:
            for t in m.get("trades", []):
                wallet = t.get("creator")
                if not wallet:
                    continue

                pnl = float(t.get("payout", 0)) - float(t.get("cost", 0))
                if wallet not in wallets:
                    wallets[wallet] = {"trades": 0, "profit": 0, "volume": 0}

                wallets[wallet]["trades"] += 1
                wallets[wallet]["profit"] += pnl
                wallets[wallet]["volume"] += float(t.get("cost", 0))

    # 計算統計結果
    analyzed = []
    for addr, info in wallets.items():
        roi = info["profit"] / info["volume"] * 100 if info["volume"] > 0 else 0
        analyzed.append({
            "wallet": addr,
            "trades": info["trades"],
            "volume": info["volume"],
            "profit": info["profit"],
            "roi": round(roi, 2)
        })

    # 排序找出頂尖與異常錢包
    analyzed.sort(key=lambda x: x["roi"], reverse=True)
    top_wallets = analyzed[:5]
    abnormal_wallets = [w for w in analyzed if abs(w["roi"]) > 300 or w["volume"] > 5000]

    return {
        "total_wallets": len(wallets),
        "top_wallets": top_wallets,
        "abnormal_wallets": abnormal_wallets
    }

async def notify_telegram(summary: Dict):
    msg = f"📈 Polymarket 智能錢包分析報告\n\n"
    msg += f"錢包總數：{summary['total_wallets']}\n\n"
    msg += "🏆 前 5 高 ROI 錢包：\n"
    for w in summary['top_wallets']:
        msg += f"🔹 {w['wallet'][:6]}...  ROI: {w['roi']}%  利潤: {round(w['profit'],2)} USDC\n"

    if summary['abnormal_wallets']:
        msg += "\n⚠️ 偵測到異常錢包：\n"
        for w in summary['abnormal_wallets']:
            msg += f"❗ {w['wallet'][:6]}... ROI {w['roi']}%, 投注 {round(w['volume'],2)}\n"

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            message_thread_id=MESSAGE_THREAD_ID,
            text=msg
        )
    except Exception as e:
        print("❌ Telegram 發送失敗：", e)

# ====== 定時任務 ======
async def periodic_analysis():
    while True:
        print(f"⏱ 分析中 ({datetime.utcnow().isoformat()}) ...")
        data = fetch_markets()
        if not data:
            print("⚠️ 無法取得資料")
        else:
            result = analyze_wallets(data)
            await notify_telegram(result)
        await asyncio.sleep(ANALYSIS_INTERVAL_MIN * 60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(periodic_analysis())

@app.get("/")
def root():
    return {"status": "PolyTracking backend running"}

@app.get("/healthz")
def health():
    return {"ok": True}

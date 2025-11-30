import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = "https://polytracking-backend-tv7j.onrender.com/telegram/webhook"

def check_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
    res = requests.get(url)
    print(f"Current Webhook Status: {res.json()}")
    return res.json()

def set_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    payload = {"url": WEBHOOK_URL}
    res = requests.post(url, json=payload)
    print(f"Set Webhook Result: {res.json()}")

if __name__ == "__main__":
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        exit(1)
        
    info = check_webhook()
    current_url = info.get("result", {}).get("url", "")
    
    if current_url != WEBHOOK_URL:
        print(f"Webhook URL mismatch. Current: '{current_url}', Expected: '{WEBHOOK_URL}'")
        print("Setting webhook...")
        set_webhook()
        check_webhook()
    else:
        print("Webhook is correctly set.")

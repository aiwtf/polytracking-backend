"""Minimal Telegram notification helper (MVP) - HTTP implementation.

Uses direct HTTPS requests to Telegram Bot API instead of python-telegram-bot
async coroutines (avoids need for async context in FastAPI utility code).

Environment variables:
  BOT_TOKEN       - Telegram bot token (required)
  TG_CHANNEL      - Channel/group username OR numeric chat id (e.g. @Polytracking or -1001234567890)
  TG_THREAD_ID    - Optional forum topic (message_thread_id)

Functions:
  send_message(msg: str, thread_id: Optional[int] = None)
  get_me() -> dict | None
"""
from __future__ import annotations
import os, json, requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("TG_CHANNEL", "@Polytracking")
THREAD_ENV = os.environ.get("TG_THREAD_ID")
DEFAULT_THREAD_ID = int(THREAD_ENV) if THREAD_ENV and THREAD_ENV.isdigit() else None

API_ROOT = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

def _post(method: str, payload: dict):
  if not API_ROOT:
    return None, "BOT_TOKEN missing"
  try:
    r = requests.post(f"{API_ROOT}/{method}", json=payload, timeout=10)
    try:
      data = r.json()
    except Exception:
      data = {"text": r.text}
    return data, None if r.ok else f"HTTP {r.status_code}"
  except Exception as e:
    return None, str(e)

def send_message(msg: str, thread_id: int | None = None):
  if not BOT_TOKEN:
    print('[TG] BOT_TOKEN missing, not sending.')
    return
  final_thread = thread_id if thread_id is not None else DEFAULT_THREAD_ID
  payload = {
    "chat_id": CHANNEL,
    "text": msg,
    "disable_web_page_preview": True,
  }
  if final_thread is not None:
    payload["message_thread_id"] = final_thread
  data, err = _post('sendMessage', payload)
  if err:
    print('[TG] send failed:', err, data)
    return {"ok": False, "error": err, "data": data}
  mid = data.get('result', {}).get('message_id') if isinstance(data, dict) else None
  print(f"[TG] Sent message id={mid} thread={final_thread}")
  return {"ok": True, "message_id": mid, "data": data}

def get_me():
  if not BOT_TOKEN:
    return None
  data, err = _post('getMe', {})
  if err:
    print('[TG] getMe failed:', err)
    return None
  return data


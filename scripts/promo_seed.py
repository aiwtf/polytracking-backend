"""
Promo seed script: post a marketing message to Telegram.
- Uses utils.tg_notify.send_message
- One-off execution; schedule via Render Cron (2x/day) if needed.

Usage:
  python scripts/promo_seed.py --market "Will BTC > $100k by 2026?"
  python scripts/promo_seed.py --message "Custom message here"
Env:
  BOT_TOKEN required, TG_CHANNEL optional
"""
import argparse
import os
from datetime import datetime
from pathlib import Path

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from utils.tg_notify import send_message

DEFAULT_URL = os.environ.get("PUBLIC_SIGNALS_URL", "https://polytracking.vercel.app/signals")

def build_default_message(market: str | None = None) -> str:
    title = market or "a high-signal market"
    return (
        "🚨 Smart Money on Polymarket just moved!\n"
        f"Top Wallets now betting on {title}.\n\n"
        f"Visit {DEFAULT_URL}\n"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", type=str, default=None, help="Market name to highlight")
    p.add_argument("--message", type=str, default=None, help="Override full message")
    args = p.parse_args()

    msg = args.message or build_default_message(args.market)

    if not os.environ.get("BOT_TOKEN"):
        print("[WARN] BOT_TOKEN not set; printing message only:\n\n" + msg)
        return

    send_message(msg)
    print("[OK] Promo message sent at", datetime.utcnow().isoformat(), "UTC")


if __name__ == "__main__":
    main()

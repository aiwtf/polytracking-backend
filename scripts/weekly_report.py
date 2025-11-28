"""
Weekly report generator
- Summarizes: new wallets tracked this week, avg SmartScore, VIP/Free signal counts, Telegram subscriber growth
- Outputs to logs/weekly_report.txt and posts to Telegram channel

Run:
  python scripts/weekly_report.py

Requires env:
  DATABASE_URL (PostgreSQL) and optional BOT_TOKEN/TG_CHANNEL for posting
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import os
import sqlite3

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.tg_notify import send_message, DB_PATH


LOG_DIR = Path(__file__).resolve().parents[1] / 'logs'
LOG_DIR.mkdir(exist_ok=True)
OUT_FILE = LOG_DIR / 'weekly_report.txt'


def pg_query_one(db_url: str, sql: str, params=()):
    psycopg2 = __import__('psycopg2')
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


ess = os.environ.get('DATABASE_URL')


def compute_weekly_stats(db_url: str):
    today = date.today()
    week_ago = today - timedelta(days=7)

    # New wallets in last 7 days (first seen this week)
    new_wallets_sql = (
        """
        WITH first_seen AS (
          SELECT wallet, MIN(day) AS first_day
          FROM wallet_daily
          GROUP BY wallet
        )
        SELECT COUNT(*) FROM first_seen WHERE first_day >= CURRENT_DATE - INTERVAL '7 days'
        """
    )
    new_wallets = int(pg_query_one(db_url, new_wallets_sql)[0])

    # Avg SmartScore over last 7 days
    avg_score_sql = (
        """
        SELECT COALESCE(AVG(smartscore),0) FROM leaderboard
        WHERE rank_date >= CURRENT_DATE - INTERVAL '7 days'
        """
    )
    avg_smart = float(pg_query_one(db_url, avg_score_sql)[0])

    # SQLite: VIP/Free counts in last 7 days and subscriber growth
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notif_log WHERE mode='vip' AND sent_at >= datetime('now','-7 days')")
    vip_cnt = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM notif_log WHERE mode='free' AND sent_at >= datetime('now','-7 days')")
    free_cnt = int(cur.fetchone()[0])

    cur.execute("SELECT COUNT(*) FROM subscribers")
    subs_now = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM subscribers WHERE subscribed_at <= datetime('now','-7 days')")
    subs_week_ago = int(cur.fetchone()[0])
    conn.close()

    return {
        'period': f"{(week_ago).isoformat()} → {today.isoformat()}",
        'new_wallets': new_wallets,
        'avg_smartscore': avg_smart,
        'signals_vip': vip_cnt,
        'signals_free': free_cnt,
        'subs_now': subs_now,
        'subs_week_ago': subs_week_ago,
        'subs_growth': subs_now - subs_week_ago,
    }


def build_report(stats: dict) -> str:
    return (
        "📅 Weekly Ops & Performance Report\n\n"
        f"Period: {stats['period']}\n\n"
        f"👥 New Tracked Wallets: {stats['new_wallets']}\n"
        f"⭐ Avg SmartScore (7d): {stats['avg_smartscore']:.1f}\n\n"
        f"📣 Signals Sent (7d)\n"
        f"  • VIP: {stats['signals_vip']}\n"
        f"  • Free: {stats['signals_free']}\n\n"
        f"📈 Telegram Subscribers\n"
        f"  • Now: {stats['subs_now']}\n"
        f"  • 7d Ago: {stats['subs_week_ago']}\n"
        f"  • Growth: {stats['subs_growth']}\n"
    )


def main():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print('[ERROR] DATABASE_URL not set')
        return
    stats = compute_weekly_stats(db_url)
    report = build_report(stats)
    OUT_FILE.write_text(report, encoding='utf-8')
    # Post to Telegram channel if possible
    try:
        send_message(report)
        print('[OK] Weekly report sent and saved to', OUT_FILE)
    except Exception as e:
        print('[WARN] send report failed:', e)
        print(report)


if __name__ == '__main__':
    main()

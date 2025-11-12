#!/usr/bin/env bash
set -e  # 有錯誤就中止

echo "🚀 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Starting Uvicorn server..."
exec python -m uvicorn main:app --host 0.0.0.0 --port 10000

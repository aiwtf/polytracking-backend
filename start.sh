#!/usr/bin/env bash
set -e

echo "✅ Starting Uvicorn server with correct environment..."

python --version || which python
pip show uvicorn || echo "⚠️ uvicorn not installed in this environment."

# 強制使用同一個環境的 python
exec python -m uvicorn main:app --host 0.0.0.0 --port 10000

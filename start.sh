#!/usr/bin/env bash
set -e

echo "✅ Starting Uvicorn server..."

# 找到 render 預設的 python 執行路徑
PYTHON_PATH=$(which python || which python3)

# 顯示當前 python 版本與套件路徑（方便除錯）
$PYTHON_PATH --version
$PYTHON_PATH -m pip list | grep uvicorn || echo "⚠️ uvicorn not found in this environment."

# 直接使用 python -m 呼叫 uvicorn（確保使用同一個環境）
exec $PYTHON_PATH -m uvicorn main:app --host 0.0.0.0 --port 10000

#!/usr/bin/env bash
set -e

echo "🚀 Starting backend on Python environment..."

# 確保環境中的 python3 存在，若無則報錯
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found in environment!"
    exit 1
fi

PYTHON=$(command -v python3)
echo "✅ Using Python: $PYTHON"
$PYTHON --version

# 使用相同的 python 環境執行 uvicorn
exec $PYTHON -m uvicorn main:app --host 0.0.0.0 --port 10000

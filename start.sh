#!/usr/bin/env bash
set -e

echo "✅ Starting Uvicorn server (Python3)..."

PYTHON_PATH=$(which python3)
echo "Using Python: $PYTHON_PATH"
$PYTHON_PATH --version

# 執行服務
exec $PYTHON_PATH -m uvicorn main:app --host 0.0.0.0 --port 10000

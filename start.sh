#!/usr/bin/env bash
set -e

echo "🚀 Starting PolyTracking backend (MVP)..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found in environment!"
    exit 1
fi

PYTHON=$(command -v python3)
echo "✅ Using Python: $PYTHON"
$PYTHON --version

# Start collector in background
echo "📡 Starting collector in background..."
$PYTHON collector.py &
COLLECTOR_PID=$!
echo "   Collector PID: $COLLECTOR_PID"

# Cleanup function to kill collector on exit
cleanup() {
    echo "⏹ Shutting down collector (PID $COLLECTOR_PID)..."
    kill $COLLECTOR_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Start FastAPI server (this will block until terminated)
echo "🌐 Starting FastAPI server on 0.0.0.0:10000..."
exec $PYTHON -m uvicorn main:app --host 0.0.0.0 --port 10000

#!/usr/bin/env bash
set -e

echo "✅ Starting Uvicorn server..."
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 10000

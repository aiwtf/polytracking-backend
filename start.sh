#!/usr/bin/env bash
# 安裝依賴並啟動伺服器
pip install --upgrade pip
pip install -r requirements.txt
exec python -m uvicorn main:app --host 0.0.0.0 --port 10000

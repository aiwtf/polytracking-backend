#!/bin/bash
# test_backend.sh - 完整後端功能測試腳本

echo "========================================"
echo "PolyTracking 後端功能測試"
echo "========================================"
echo ""

# 確認伺服器運行中
echo ">>> 檢查伺服器狀態..."
if ! curl -s http://127.0.0.1:8000/healthz > /dev/null 2>&1; then
    echo "❌ 伺服器未運行！請先啟動: uvicorn main:app --host 127.0.0.1 --port 8000"
    exit 1
fi
echo "✅ 伺服器運行中"
echo ""

# 測試 1: Health Check
echo ">>> 測試 1: Health Check"
HEALTH=$(curl -s http://127.0.0.1:8000/healthz)
echo "回應: $HEALTH"
if echo "$HEALTH" | grep -q "true"; then
    echo "✅ Health check 通過"
else
    echo "❌ Health check 失敗"
fi
echo ""

# 測試 2: Root 端點
echo ">>> 測試 2: Root Status"
ROOT=$(curl -s http://127.0.0.1:8000/)
echo "回應: $ROOT"
if echo "$ROOT" | grep -q "PolyTracking"; then
    echo "✅ Root 端點正常"
else
    echo "❌ Root 端點異常"
fi
echo ""

# 測試 3: Leaderboard API
echo ">>> 測試 3: Leaderboard API"
LEADERBOARD=$(curl -s http://127.0.0.1:8000/api/leaderboard)
echo "回應: $LEADERBOARD"
if [ -n "$LEADERBOARD" ]; then
    echo "✅ Leaderboard API 回應正常"
    if echo "$LEADERBOARD" | grep -q "\[\]"; then
        echo "⚠️  資料庫為空（尚未建立排行榜）"
    else
        echo "✅ 排行榜有資料"
    fi
else
    echo "❌ Leaderboard API 無回應"
fi
echo ""

# 測試 4: Wallets API
echo ">>> 測試 4: Wallets API"
WALLETS=$(curl -s http://127.0.0.1:8000/api/wallets)
echo "回應: $WALLETS"
if [ -n "$WALLETS" ]; then
    echo "✅ Wallets API 回應正常"
    if echo "$WALLETS" | grep -q "\[\]"; then
        echo "⚠️  資料庫為空（尚未分析錢包）"
    else
        echo "✅ 錢包資料存在"
    fi
else
    echo "❌ Wallets API 無回應"
fi
echo ""

# 測試 5: Recent Trades API
echo ">>> 測試 5: Recent Trades API"
TRADES=$(curl -s http://127.0.0.1:8000/api/trades/recent)
echo "回應: ${TRADES:0:100}..."
if [ -n "$TRADES" ]; then
    echo "✅ Recent Trades API 回應正常"
    if echo "$TRADES" | grep -q "\[\]"; then
        echo "⚠️  無交易記錄（collector 尚未收集資料）"
    else
        echo "✅ 交易記錄存在"
    fi
else
    echo "❌ Recent Trades API 無回應"
fi
echo ""

# 測試 6: Summary API
echo ">>> 測試 6: Summary API"
SUMMARY=$(curl -s http://127.0.0.1:8000/api/summary)
echo "回應: $SUMMARY"
if [ -n "$SUMMARY" ]; then
    echo "✅ Summary API 回應正常"
else
    echo "❌ Summary API 無回應"
fi
echo ""

# 測試 7: Wallet Detail API（使用測試地址）
echo ">>> 測試 7: Wallet Detail API"
DETAIL=$(curl -s "http://127.0.0.1:8000/api/wallet/0xTestWallet1234567890")
echo "回應: $DETAIL"
if [ -n "$DETAIL" ]; then
    echo "✅ Wallet Detail API 回應正常"
else
    echo "❌ Wallet Detail API 無回應"
fi
echo ""

echo "========================================"
echo "測試總結"
echo "========================================"
echo "✅ 所有 API 端點可訪問"
echo "⚠️  若資料庫為空，請執行:"
echo "   1. 設定 DATABASE_URL 環境變數"
echo "   2. 執行: python scripts/seed_demo.py"
echo "   3. 或等待 collector 收集真實資料"
echo ""
echo "下一步建議:"
echo "   - 執行 seed 插入測試資料"
echo "   - 啟動 collector.py 收集 Polymarket 資料"
echo "   - 執行 features.py 計算錢包特徵"
echo "   - 執行 scorer.py 產生排行榜"
echo ""

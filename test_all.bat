@echo off
REM Windows batch script to run all tests

echo ========================================
echo PolyTracking Backend Test Suite
echo ========================================
echo.

REM Test 1: Health
echo [1/7] Testing Health Check...
curl -s http://127.0.0.1:8000/healthz
echo.
echo.

REM Test 2: Root
echo [2/7] Testing Root Endpoint...
curl -s http://127.0.0.1:8000/
echo.
echo.

REM Test 3: Leaderboard
echo [3/7] Testing Leaderboard API...
curl -s http://127.0.0.1:8000/api/leaderboard
echo.
echo.

REM Test 4: Wallets
echo [4/7] Testing Wallets API...
curl -s http://127.0.0.1:8000/api/wallets
echo.
echo.

REM Test 5: Trades
echo [5/7] Testing Recent Trades API...
curl -s "http://127.0.0.1:8000/api/trades/recent?limit=5"
echo.
echo.

REM Test 6: Summary
echo [6/7] Testing Summary API...
curl -s http://127.0.0.1:8000/api/summary
echo.
echo.

REM Test 7: Wallet Detail
echo [7/7] Testing Wallet Detail API...
curl -s http://127.0.0.1:8000/api/wallet/0xTest123
echo.
echo.

echo ========================================
echo Tests Complete
echo ========================================

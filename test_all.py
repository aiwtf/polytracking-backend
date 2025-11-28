"""MVP endpoint test script.

Run AFTER starting backend & having some data (collector + scorer).
"""
import requests, json, sys, os

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
RUN_KEY = os.environ.get("RUN_SECRET_KEY", "changeme")

def get(name, path):
    url = f"{BASE_URL}{path}"
    print(f"\n[GET] {name}: {url}")
    try:
        r = requests.get(url, timeout=10)
        print(" status:", r.status_code)
        data = r.json() if r.headers.get('content-type','').startswith('application/json') else r.text
        print(" snippet:", str(data)[:180], "...")
        return r.status_code == 200, data
    except Exception as e:
        print("  ERROR:", e); return False, None

def post(name, path):
    url = f"{BASE_URL}{path}"
    print(f"\n[POST] {name}: {url}")
    try:
        r = requests.post(url, timeout=20)
        print(" status:", r.status_code)
        data = r.json() if r.headers.get('content-type','').startswith('application/json') else r.text
        print(" snippet:", str(data)[:160], "...")
        return r.status_code == 200, data
    except Exception as e:
        print("  ERROR:", e); return False, None

def main():
    results = {}
    ok, data = get("Health", "/healthz"); results['health']= ok and isinstance(data, dict) and data.get('ok')
    ok, data = get("Root", "/"); results['root']= ok
    # Run scorer (optional)
    ok_run, run_resp = post("Run Scorer", f"/api/run_scorer?key={RUN_KEY}"); results['run_scorer']= ok_run and isinstance(run_resp, dict) and run_resp.get('ok')
    ok, lb = get("Leaderboard", "/api/leaderboard"); results['leaderboard']= ok
    ok, sm = get("SmartMoney Trades", "/api/smartmoney"); results['smartmoney']= ok
    ok, rt = get("Recent Trades", "/api/trades/recent?limit=20"); results['recent_trades']= ok
    # Wallet detail (sample first wallet if any)
    wallet_addr = lb[0]['wallet'] if isinstance(lb, list) and lb else '0xTestWallet123'
    ok, wd = get("Wallet Detail", f"/api/wallet/{wallet_addr}"); results['wallet_detail']= ok
    # Telegram test (may be skipped if no BOT_TOKEN set)
    ok, tg = post("Telegram Test", f"/api/test_tg?key={RUN_KEY}"); results['test_tg']= ok

    print("\n=== SUMMARY ===")
    passed = [k for k,v in results.items() if v]
    failed = [k for k,v in results.items() if not v]
    print("Passed:", passed)
    print("Failed:", failed)
    if failed:
        print("\nHint: Ensure collector has inserted trades and scorer ran before leaderboard non-empty.")
    return 0 if not failed else 1

if __name__ == '__main__':
    sys.exit(main())

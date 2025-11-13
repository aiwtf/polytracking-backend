"""test_mvp.py - Focused MVP validation script.

Sequence:
 1. Health & root
 2. Optional scorer run
 3. Leaderboard presence
 4. Smart money trades
 5. Recent trades
 6. Sample wallet detail
 7. Optional notify_smart_bets (may send Telegram alerts)

Environment variables:
  TEST_BASE_URL (default http://127.0.0.1:8000)
  RUN_SECRET_KEY (must match server)
  SKIP_NOTIFY=1 to skip sending real alerts
"""
import os, sys, time, requests, json

BASE = os.environ.get('TEST_BASE_URL','http://127.0.0.1:8000')
RUN_KEY = os.environ.get('RUN_SECRET_KEY','changeme')
SKIP_NOTIFY = os.environ.get('SKIP_NOTIFY') == '1'

def p(*a):
    print(*a)

def get(path):
    url = BASE + path
    try:
        r = requests.get(url, timeout=15)
        data = r.json() if 'application/json' in r.headers.get('content-type','') else r.text
        p('[GET]', path, r.status_code, str(data)[:160])
        return r.status_code, data
    except Exception as e:
        p('[GET][ERR]', path, e); return 0, None

def post(path):
    url = BASE + path
    try:
        r = requests.post(url, timeout=30)
        data = r.json() if 'application/json' in r.headers.get('content-type','') else r.text
        p('[POST]', path, r.status_code, str(data)[:160])
        return r.status_code, data
    except Exception as e:
        p('[POST][ERR]', path, e); return 0, None

def main():
    status = {}
    code,data = get('/healthz'); status['health'] = (code==200 and isinstance(data,dict) and data.get('ok'))
    code,data = get('/'); status['root'] = code==200

    # Run scorer (ensures leaderboard populated using fresh wallet_daily rows)
    code,data = post(f'/api/run_scorer?key={RUN_KEY}'); status['run_scorer'] = (code==200 and isinstance(data,dict) and data.get('ok'))

    code,lb = get('/api/leaderboard'); status['leaderboard'] = code==200 and isinstance(lb,list)
    sample_wallet = lb[0]['wallet'] if status['leaderboard'] and lb else '0xSample'

    code,sm = get('/api/smartmoney'); status['smartmoney'] = code==200 and isinstance(sm,list)
    code,rt = get('/api/trades/recent?limit=20'); status['recent_trades'] = code==200 and isinstance(rt,list)
    code,wd = get(f'/api/wallet/{sample_wallet}'); status['wallet_detail'] = code==200 and isinstance(wd,dict)

    # Telegram test
    code,tg = post(f'/api/test_tg?key={RUN_KEY}'); status['test_tg'] = code==200

    # Optional alert trigger
    if not SKIP_NOTIFY:
        code,noti = post(f'/api/notify_smart_bets?key={RUN_KEY}'); status['notify_smart_bets'] = code==200 and isinstance(noti,dict)
    else:
        status['notify_smart_bets'] = True

    p('\n==== SUMMARY ====')
    passed = [k for k,v in status.items() if v]
    failed = [k for k,v in status.items() if not v]
    p('Passed:', passed)
    p('Failed:', failed)
    if failed:
        if 'leaderboard' in failed:
            p('Hint: Ensure collector inserted trades AND run scorer after some data accumulated.')
        if 'test_tg' in failed:
            p('Hint: Check BOT_TOKEN / TG_CHANNEL / TG_THREAD_ID environment variables.')
    return 0 if not failed else 1

if __name__ == '__main__':
    sys.exit(main())

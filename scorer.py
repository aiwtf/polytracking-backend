# scorer.py (MVP SmartScore v1)
import os, json
import pandas as pd
from datetime import date
from utils.db import get_conn

# SmartScore v1 weights
W_ROI = 0.40
W_WIN = 0.30
W_ENTRY = 0.20
W_VOL = 0.10


def fetch_today_wallets():
    conn = get_conn()
    cur = conn.cursor()
    # Use Python's date.today() to match features.py logic
    today = date.today()
    cur.execute("SELECT * FROM wallet_daily WHERE day = %s", (today,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return pd.DataFrame(rows)


def normalize(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    lo = s.quantile(0.01)
    hi = s.quantile(0.99)
    s2 = s.clip(lo, hi)
    return (s2 - lo) / (hi - lo + 1e-9)


def score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute SmartScore v1 using minimal required metrics."""
    if df.empty:
        return df
    for col in ['win_rate', 'avg_roi', 'bait_score', 'total_volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['n_roi'] = normalize(df['avg_roi'])
    df['n_win'] = normalize(df['win_rate'])
    df['n_entry'] = df['bait_score'].fillna(0.0).clip(0, 1)
    df['n_vol'] = normalize(df['total_volume'])
    df['smartscore'] = (
        W_ROI * df['n_roi']
        + W_WIN * df['n_win']
        + W_ENTRY * df['n_entry']
        + W_VOL * df['n_vol']
    ) * 100.0
    return df


def write_leaderboard(df: pd.DataFrame):
    conn = get_conn(); cur = conn.cursor(); rdate = date.today()
    cur.execute("DELETE FROM leaderboard WHERE rank_date = %s", (rdate,))
    for idx, r in df.iterrows():
        cur.execute(
            """
            INSERT INTO leaderboard (rank_date, rank, wallet, smartscore, reasons)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                rdate,
                int(idx) + 1,
                r['wallet'],
                float(r['smartscore']),
                json.dumps({
                    'win_rate': float(r['win_rate']),
                    'avg_roi': float(r['avg_roi']),
                    'entry_timing': float(r.get('bait_score', 0.0)),
                    'recent_volume': float(r.get('total_volume', 0.0)),
                }),
            ),
        )
    conn.commit(); cur.close(); conn.close()
    print('Leaderboard stored:', len(df))


def main():
    df = fetch_today_wallets()
    if df.empty:
        print('No wallet_daily rows for today.')
        return
    scored = score(df).sort_values('smartscore', ascending=False).head(100).reset_index(drop=True)
    write_leaderboard(scored)
    print('SmartScore v1 updated.')


if __name__ == '__main__':
    main()

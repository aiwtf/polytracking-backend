# features.py (MVP aggregation)
import os
import pandas as pd
from datetime import datetime, timedelta, date
from utils.db import get_conn

# Minimum trades to include wallet in daily stats (MVP keeps low threshold)
MIN_TRADES_90D = int(os.environ.get('MIN_TRADES_90D', '5'))


def load_raw_since(days=365):
    conn = get_conn()
    cur = conn.cursor()
    since = datetime.utcnow() - timedelta(days=days)
    cur.execute("SELECT * FROM raw_trades WHERE timestamp >= %s", (since,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return pd.DataFrame(rows)


def compute_wallet_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute minimal daily wallet features needed for MVP SmartScore.

    Fields produced:
      win_rate, avg_roi, trades, total_volume, avg_ticket_size,
      concentration_index (HHI), entry_timing_score (stored in bait_score),
      insider_flag (simple ROI z-score > 2), last_trade_at.
    """
    if df.empty:
        return pd.DataFrame([])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    for col in ['price_before', 'price_after', 'amount_usdc', 'cost_usdc']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    cutoff = datetime.utcnow() - timedelta(days=90)
    df90 = df[df['timestamp'] >= cutoff].copy()
    try:
        market_start = df90.groupby('market_id')['timestamp'].min().to_dict()
    except Exception:
        market_start = {}
    wallets = []
    raw_entry_timings = []
    for wallet, g in df90.groupby('trader'):
        n = len(g)
        if n < MIN_TRADES_90D:
            continue
        # ROI proxy using price change
        denom = g['price_before'].replace(0, 1)
        g['roi'] = (g['price_after'] - g['price_before']) / denom
        wins = (g['roi'] > 0).sum()
        win_rate = wins / n
        avg_roi = g['roi'].mean()
        total_vol = g['amount_usdc'].sum()
        avg_ticket = g['amount_usdc'].mean()
        unique_markets = g['market_id'].nunique()
        mvol = g.groupby('market_id')['amount_usdc'].sum()
        shares = mvol / max(1e-9, mvol.sum())
        hhi = float((shares ** 2).sum()) if not shares.empty else 0.0
        # Entry timing raw seconds from market start
        try:
            deltas = g.apply(lambda r: (r['timestamp'] - market_start.get(r['market_id'], r['timestamp'])).total_seconds(), axis=1)
            entry_timing_raw = float(deltas.mean()) if len(deltas) > 0 else 0.0
        except Exception:
            entry_timing_raw = 0.0
        raw_entry_timings.append((wallet, entry_timing_raw))
        wallets.append({
            'wallet': wallet,
            'day': date.today(),
            'trades': int(n),
            'wins': int(wins),
            'losses': int(n - wins),
            'win_rate': float(win_rate),
            'avg_roi': float(avg_roi or 0.0),
            'roi_std': 0.0,  # not used in MVP
            'total_volume': float(total_vol or 0.0),
            'avg_ticket_size': float(avg_ticket or 0.0),
            'median_ticket_size': 0.0,
            'unique_markets': int(unique_markets or 0),
            'concentration_index': float(hhi),
            'mean_hold_time_seconds': 0.0,
            'max_drawdown': 0.0,
            'bait_score': 0.0,  # filled later
            'insider_flag': False,  # filled later
            'is_high_freq': False,
            'last_trade_at': g['timestamp'].max(),
        })
    dfw = pd.DataFrame(wallets)
    if dfw.empty:
        return dfw
    # Entry timing normalization (earlier -> higher score)
    et_map = {w: v for w, v in raw_entry_timings}
    dfw['entry_timing_raw'] = dfw['wallet'].map(et_map).fillna(0.0)
    lo = dfw['entry_timing_raw'].quantile(0.01)
    hi = dfw['entry_timing_raw'].quantile(0.99)
    clipped = dfw['entry_timing_raw'].clip(lo, hi)
    norm = (clipped - lo) / (hi - lo + 1e-9)
    dfw['bait_score'] = (1.0 - norm).astype(float)
    # Insider flag via ROI z-score > 2
    roi_mean = dfw['avg_roi'].mean()
    roi_std = dfw['avg_roi'].std() if len(dfw) > 1 else 0.0
    if roi_std <= 0:
        dfw['insider_flag'] = False
    else:
        dfw['insider_flag'] = (dfw['avg_roi'] - roi_mean) / roi_std > 2.0
    return dfw


def upsert_wallet_daily(df: pd.DataFrame):
    if df.empty:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    for _, r in df.iterrows():
        cur.execute(
            """
            INSERT INTO wallet_daily (wallet, day, trades, wins, losses, win_rate, avg_roi, roi_std, total_volume, avg_ticket_size, median_ticket_size, unique_markets, concentration_index, mean_hold_time_seconds, max_drawdown, bait_score, insider_flag, is_high_freq, last_trade_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (wallet, day) DO UPDATE SET
              trades=EXCLUDED.trades, wins=EXCLUDED.wins, losses=EXCLUDED.losses, win_rate=EXCLUDED.win_rate, avg_roi=EXCLUDED.avg_roi, roi_std=EXCLUDED.roi_std, total_volume=EXCLUDED.total_volume, avg_ticket_size=EXCLUDED.avg_ticket_size, median_ticket_size=EXCLUDED.median_ticket_size, unique_markets=EXCLUDED.unique_markets, concentration_index=EXCLUDED.concentration_index, mean_hold_time_seconds=EXCLUDED.mean_hold_time_seconds, max_drawdown=EXCLUDED.max_drawdown, bait_score=EXCLUDED.bait_score, insider_flag=EXCLUDED.insider_flag, is_high_freq=EXCLUDED.is_high_freq, last_trade_at=EXCLUDED.last_trade_at
            """,
            (
                r['wallet'], r['day'], int(r['trades']), int(r['wins']), int(r['losses']), float(r['win_rate']),
                float(r['avg_roi']), float(r['roi_std'] or 0.0), float(r['total_volume'] or 0.0), float(r['avg_ticket_size'] or 0.0),
                float(r['median_ticket_size'] or 0.0), int(r['unique_markets']), float(r['concentration_index'] or 0.0), float(r['mean_hold_time_seconds'] or 0.0), float(r['max_drawdown'] or 0.0),
                float(r['bait_score'] or 0.0), bool(r['insider_flag']), bool(r['is_high_freq']), r['last_trade_at'],
            ),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(df)


if __name__ == '__main__':
    df_raw = load_raw_since(365)
    feats = compute_wallet_features(df_raw)
    n = upsert_wallet_daily(feats)
    print('features rows upserted:', n)

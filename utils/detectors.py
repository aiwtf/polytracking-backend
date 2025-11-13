# utils/detectors.py - v1 精簡版：僅保留 insider 偵測
import pandas as pd
from datetime import timedelta


def detect_insider(wallet_trades: pd.DataFrame, event_time, window_hours=24, baseline_days=30):
    """
    Insider 偵測：比較事件前 window_hours 內的交易量 vs 過去 baseline_days 的日均量。
    
    參數:
        wallet_trades: 該錢包的所有交易記錄 (DataFrame)
        event_time: 事件時間 (datetime)
        window_hours: 事件前觀察窗口 (小時)
        baseline_days: 基準期天數
    
    回傳:
        dict: {'zscore': float, 'flag': bool}
        zscore > 3 視為可疑 insider
    """
    if wallet_trades.empty:
        return {'zscore': 0.0, 'flag': False}

    # 事件前 window_hours 的交易量
    pre_window = wallet_trades[
        (wallet_trades['timestamp'] >= event_time - timedelta(hours=window_hours)) &
        (wallet_trades['timestamp'] < event_time)
    ]
    
    # 基準期：event_time 前 baseline_days 天的交易
    baseline_start = event_time - timedelta(days=baseline_days) - timedelta(hours=window_hours)
    baseline_end = event_time - timedelta(days=baseline_days)
    baseline = wallet_trades[
        (wallet_trades['timestamp'] >= baseline_start) &
        (wallet_trades['timestamp'] < baseline_end)
    ]

    # 計算交易量
    pre_vol = pre_window['amount_usdc'].sum() if not pre_window.empty else 0.0
    
    # 基準期日均量
    if not baseline.empty:
        baseline_daily = baseline.groupby(baseline['timestamp'].dt.date)['amount_usdc'].sum()
        base_mean = baseline_daily.mean() if len(baseline_daily) > 0 else 0.0
        base_std = baseline_daily.std() if len(baseline_daily) > 1 else 1.0
    else:
        base_mean = 0.0
        base_std = 1.0

    # Z-score 計算
    z = (pre_vol - base_mean) / (base_std if base_std > 0 else 1.0)
    
    return {
        'zscore': float(z),
        'flag': bool(z > 3.0)
    }

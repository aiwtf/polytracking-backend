"""
Signal formatter for SmartSignal Pro v2.1

Computes lightweight metrics from existing data without DB schema changes:
- alpha_score = (smartscore / 100.0) * entry_timing
- confidence = (win_rate + entry_timing * 0.5) / 1.5  # scaled 0..1
- strength = smartscore * 0.6 + (win_rate * 100.0) * 0.4  # 0..100
- risk_label from roi_std thresholds: <0.05 Low, <0.15 Moderate, else High
- target_roi = avg_roi * 1.2  # simple estimate

All inputs should be in natural scales:
- smartscore: 0..100
- win_rate: 0..1
- entry_timing: 0..1
- avg_roi: daily or average ROI as fraction (0..1 typical)
- roi_std: standard deviation of ROI (fraction)
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeInfo:
    wallet: str
    market_name: str
    side: str
    amount_usdc: float
    timestamp_utc: datetime
    smartscore: float
    entry_timing: float
    rank: int | None = None


@dataclass
class WalletMetrics:
    win_rate: float  # 0..1
    avg_roi: float   # fraction
    roi_std: float   # fraction (stddev over ~90d)
    volume: float | None = None
    trades_count: int | None = None
    pnl: float | None = None
    first_seen_date: str | None = None


def compute_alpha(smartscore: float, entry_timing: float) -> float:
    return max(0.0, (smartscore / 100.0) * entry_timing)


def compute_confidence(win_rate: float, entry_timing: float) -> float:
    # (WinRate + EntryTiming × 50%) / 1.5
    return max(0.0, min(1.0, (win_rate + entry_timing * 0.5) / 1.5))


def compute_strength(smartscore: float, win_rate: float) -> float:
    return max(0.0, min(100.0, smartscore * 0.6 + (win_rate * 100.0) * 0.4))


def risk_label_from_std(roi_std: float) -> str:
    if roi_std < 0.05:
        return "Low"
    if roi_std < 0.15:
        return "Moderate"
    return "High"


def estimate_target_roi(avg_roi: float) -> float:
    # Simple uplift x1.2, output in percent
    return (avg_roi * 1.2) * 100.0


def format_signal(trade: TradeInfo, w: WalletMetrics) -> tuple[str, dict]:
    """Return (html_message, metrics_dict) for Telegram and API usage.

    metrics_dict keys: alpha_score, confidence, strength, risk_label, target_roi
    """
    alpha = compute_alpha(trade.smartscore, trade.entry_timing)
    conf = compute_confidence(w.win_rate, trade.entry_timing)
    strength = compute_strength(trade.smartscore, w.win_rate)
    risk = risk_label_from_std(w.roi_std)
    target_roi = estimate_target_roi(w.avg_roi)

    metrics = {
        "alpha_score": alpha,
        "confidence": conf * 100.0,  # present as percent
        "strength": strength,
        "risk_label": risk,
        "target_roi": target_roi,
    }

    # HTML formatted message per template
    rank_str = f"#{trade.rank}" if trade.rank is not None else "—"
    msg = (
        "<b>🚨 SmartSignal Pro™ — v2.1</b>\n\n"
        "⚡ <b>Smart Money Detected on Polymarket</b>\n\n"
        f"🏆 Rank {rank_str} — <b>SmartScore:</b> {trade.smartscore:.1f} /100\n"
        f"🧠 <b>Alpha Index:</b> {alpha*100:.0f} | <b>Entry Timing:</b> {trade.entry_timing*100:.0f}%\n\n"
        f"🎯 <b>Market:</b> {escape_html(trade.market_name)}\n"
        f"🔵 <b>Side:</b> {escape_html(trade.side)} | 💰 <b>Size:</b> ${trade.amount_usdc:,.0f}\n"
        f"📈 <b>Target ROI:</b> +{target_roi:.0f}%\n"
        f"🕒 <b>Time:</b> {trade.timestamp_utc.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "📊 <b>Wallet Summary</b>\n"
        f"💚 ROI: {w.avg_roi*100:.0f}% | 🎯 WinRate: {w.win_rate*100:.0f}% | ⚡ Confidence: {conf*100:.0f}%\n"
        f"📉 Risk Level: {risk} | 📈 Volume: ${float(w.volume or 0):,.0f} | 🧩 Trades: {int(w.trades_count or 0)}\n\n"
        "🧠 <b>Actions</b>\n"
        f"<a href='https://polymarket.com/trader/{trade.wallet}'>🧩 Wallet Profile</a> | "
        f"<a href='https://polymarket.com/'>📈 View Market</a> | "
        f"<a href='https://polytracking.vercel.app/dashboard-new'>🔄 Backtest</a>\n"
    )
    return msg, metrics


def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

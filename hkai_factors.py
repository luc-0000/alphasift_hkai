"""Factor computation for HK stocks — pure price/volume based.

Replaces alphasift's PE/PB/market_cap factors (not available via hk_ai MCP)
with K-line-derived factors: momentum, RSI, MA position, volume ratio.

HK.AI throwaway — remove after 2026-08-01.
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def compute_factors(bars: list[dict]) -> dict[str, float]:
    """Compute all factors from a list of OHLCV bars (oldest→newest).

    Returns dict with keys:
        rsi_14, ma_5, ma_10, ma_20, momentum_20d, vol_ratio_1d_5d,
        pct_change_1d, pct_change_5d, pct_change_20d, dist_to_ma20,
        above_ma5, above_ma10, above_ma20
    """
    if len(bars) < 5:
        return {}

    df = pd.DataFrame(bars)
    if "close" not in df.columns or df["close"].isna().all():
        return {}

    close = df["close"].astype(float)
    volume = df.get("volume", pd.Series([0] * len(df))).astype(float)

    factors: dict[str, Any] = {}

    # Moving averages
    factors["ma_5"] = _safe_round(close.tail(5).mean())
    factors["ma_10"] = _safe_round(close.tail(10).mean()) if len(close) >= 10 else None
    factors["ma_20"] = _safe_round(close.tail(20).mean()) if len(close) >= 20 else None

    last_close = float(close.iloc[-1])
    factors["above_ma5"] = bool(last_close > factors["ma_5"]) if factors["ma_5"] else None
    factors["above_ma10"] = bool(last_close > factors["ma_10"]) if factors["ma_10"] else None
    factors["above_ma20"] = bool(last_close > factors["ma_20"]) if factors["ma_20"] else None

    # Distance to MA20 (percent)
    if factors["ma_20"]:
        factors["dist_to_ma20_pct"] = _safe_round(
            (last_close - factors["ma_20"]) / factors["ma_20"] * 100
        )

    # RSI(14)
    factors["rsi_14"] = _rsi(close, period=14)

    # Momentum: N-day percent change
    factors["pct_change_1d"] = _pct_change(close, 1)
    factors["pct_change_5d"] = _pct_change(close, 5)
    factors["pct_change_20d"] = _pct_change(close, 20)
    factors["momentum_20d"] = factors["pct_change_20d"]

    # Volume ratio: today vs 5-day average
    if len(volume) >= 6 and volume.iloc[-5:].mean() > 0:
        factors["vol_ratio_1d_5d"] = _safe_round(
            volume.iloc[-1] / volume.iloc[-5:].mean()
        )
    else:
        factors["vol_ratio_1d_5d"] = None

    # Volatility (20d std of returns)
    if len(close) >= 21:
        returns = close.pct_change().dropna().tail(20)
        factors["volatility_20d"] = _safe_round(returns.std() * (252 ** 0.5))  # annualized
    else:
        factors["volatility_20d"] = None

    return factors


def score_candidate(factors: dict, weights: dict[str, float]) -> float:
    """Weighted sum of normalized factors → 0..100 score.

    Simplified alphasift-style scoring. Each factor is gated to a sensible
    range before weighting.
    """
    if not factors:
        return 0.0

    contributions: list[float] = []
    total_w = 0.0

    for key, weight in weights.items():
        val = factors.get(key)
        if val is None or not isinstance(val, (int, float)):
            continue
        normalized = _normalize_factor(key, val)
        contributions.append(normalized * weight)
        total_w += weight

    if total_w == 0:
        return 0.0

    raw = sum(contributions) / total_w
    return _safe_round(raw * 100)


def _normalize_factor(key: str, val: float) -> float:
    """Map raw factor value to 0..1 contribution."""
    if key == "rsi_14":
        # Oversold (RSI<30) is bullish for reversal; >70 is bearish
        if val < 30:
            return 1.0
        if val > 70:
            return 0.0
        return (70 - val) / 40
    if key == "momentum_20d":
        # Positive momentum good, but cap at +20%
        return max(0.0, min(1.0, val / 20.0))
    if key == "pct_change_5d":
        return max(0.0, min(1.0, val / 10.0))
    if key == "vol_ratio_1d_5d":
        # 1.5x is ideal; >4 is speculative
        if val < 1.0:
            return val / 1.0 * 0.5
        if val <= 2.0:
            return 0.5 + (val - 1.0) / 1.0 * 0.5
        return max(0.0, 1.0 - (val - 2.0) / 2.0 * 0.5)
    if key in ("above_ma5", "above_ma10", "above_ma20"):
        return 1.0 if val else 0.0
    if key == "dist_to_ma20_pct":
        # Slightly above MA20 is good; far above = overbought
        if val < 0:
            return max(0.0, 1.0 + val / 10.0)  # dip = bullish
        if val <= 5:
            return 1.0
        return max(0.0, 1.0 - (val - 5) / 15.0)
    if key == "volatility_20d":
        # Moderate vol good; extreme vol bad
        if val < 0.1:
            return 0.4
        if val < 0.3:
            return 1.0
        return max(0.0, 1.0 - (val - 0.3) / 0.5)
    return 0.5


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    """RSI via Wilder's smoothing."""
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.tail(period).mean()
    avg_loss = loss.tail(period).mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return _safe_round(100 - (100 / (1 + rs)))


def _pct_change(close: pd.Series, n: int) -> float | None:
    if len(close) < n + 1:
        return None
    old = float(close.iloc[-n - 1])
    new = float(close.iloc[-1])
    if old == 0:
        return None
    return _safe_round((new - old) / old * 100)


def _safe_round(val: float, digits: int = 4) -> float:
    if val != val:  # NaN
        return 0.0
    return round(float(val), digits)

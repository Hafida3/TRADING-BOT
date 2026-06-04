"""
Layer 2 – Analysis: RSI and MACD calculations on price series.

All functions return raw indicator values plus a normalised [0, 1] score
where 1 = strong buy signal, 0 = strong sell signal, 0.5 = neutral.
"""

import math
from typing import Optional

import numpy as np
import pandas as pd


# ── RSI ───────────────────────────────────────────────────────────────────────

def calculate_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI on a list of close prices. Returns latest value."""
    if len(prices) < period + 1:
        return None

    series = pd.Series(prices, dtype=float)
    delta = series.diff()

    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    # Wilder smoothing ≡ EWM with com = period - 1
    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    val = rsi.iloc[-1]
    return None if math.isnan(val) else float(val)


def normalize_rsi(rsi: float, oversold: float = 30, overbought: float = 70) -> float:
    """
    Map RSI to [0, 1].
      RSI <= oversold  → 1.0 (strong buy)
      RSI >= overbought → 0.0 (strong sell)
      Linear in between.
    """
    if rsi <= oversold:
        return 1.0
    if rsi >= overbought:
        return 0.0
    return 1.0 - (rsi - oversold) / (overbought - oversold)


# ── MACD ─────────────────────────────────────────────────────────────────────

def calculate_macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Standard MACD.
    Returns (macd_line, signal_line, histogram).
    """
    if len(prices) < slow + signal_period:
        return None, None, None

    series = pd.Series(prices, dtype=float)
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    m, s, h = float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])
    if any(math.isnan(v) for v in (m, s, h)):
        return None, None, None
    return m, s, h


def normalize_macd(histogram: float) -> float:
    """
    Map MACD histogram to [0, 1] via tanh.
      histogram > 0 → score > 0.5 (bullish)
      histogram < 0 → score < 0.5 (bearish)
    """
    return (math.tanh(histogram * 0.08) + 1.0) / 2.0

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


# ── MA Crossover ──────────────────────────────────────────────────────────────

def calculate_ma_crossover(
    prices: list[float], fast: int = 50, slow: int = 200,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Moving-average crossover. Returns (ma_fast, ma_slow, score 0–1).
    fast > slow → bullish (0.70–1.0); fast < slow → bearish (0.0–0.30).
    Returns (None, None, None) until len(prices) >= slow.
    """
    if len(prices) < slow:
        return None, None, None
    series = pd.Series(prices, dtype=float)
    ma_fast = float(series.rolling(fast).mean().iloc[-1])
    ma_slow = float(series.rolling(slow).mean().iloc[-1])
    if math.isnan(ma_fast) or math.isnan(ma_slow):
        return None, None, None
    pct = (ma_fast - ma_slow) / ma_slow
    if ma_fast > ma_slow:
        score = min(1.0, 0.70 + pct * 10.0)
    else:
        score = max(0.0, 0.30 + pct * 10.0)
    return ma_fast, ma_slow, score


# ── Stochastic RSI ────────────────────────────────────────────────────────────

def calculate_stoch_rsi(
    prices: list[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Stochastic RSI. Returns (%K, %D, score 0–1).
    %K <= 20 → oversold (score ≈ 1.0); %K >= 80 → overbought (score ≈ 0.0).
    """
    if len(prices) < rsi_period + stoch_period + k_smooth + d_smooth:
        return None, None, None

    series = pd.Series(prices, dtype=float)
    delta    = series.diff()
    avg_gain = delta.clip(lower=0.0).ewm(com=rsi_period - 1, min_periods=rsi_period, adjust=False).mean()
    avg_loss = (-delta).clip(lower=0.0).ewm(com=rsi_period - 1, min_periods=rsi_period, adjust=False).mean()
    rs         = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))

    rsi_min = rsi_series.rolling(stoch_period).min()
    rsi_max = rsi_series.rolling(stoch_period).max()
    stoch   = 100.0 * (rsi_series - rsi_min) / (rsi_max - rsi_min + 1e-10)

    k_series = stoch.rolling(k_smooth).mean()
    d_series = k_series.rolling(d_smooth).mean()

    k_val = float(k_series.iloc[-1])
    d_val = float(d_series.iloc[-1])
    if math.isnan(k_val) or math.isnan(d_val):
        return None, None, None

    if k_val <= 20:
        score = 1.0 - (k_val / 20.0) * 0.3          # 0 → 1.0, 20 → 0.7
    elif k_val >= 80:
        score = 0.3 * (1.0 - (k_val - 80.0) / 20.0)  # 80 → 0.3, 100 → 0.0
    else:
        score = 0.70 - (k_val - 20.0) / 60.0 * 0.40  # linear 0.7 → 0.3

    return k_val, d_val, max(0.0, min(1.0, score))


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def calculate_bollinger_bands(
    prices: list[float], period: int = 20, std_dev: float = 2.0,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Bollinger Bands. Returns (upper, middle, lower, score 0–1).
    Price at lower band → 1.0 (oversold/buy); at upper band → 0.0 (overbought/sell).
    """
    if len(prices) < period:
        return None, None, None, None
    series = pd.Series(prices, dtype=float)
    middle = series.rolling(period).mean()
    std    = series.rolling(period).std()
    upper  = middle + std_dev * std
    lower  = middle - std_dev * std

    u, m, lo = float(upper.iloc[-1]), float(middle.iloc[-1]), float(lower.iloc[-1])
    if any(math.isnan(v) for v in (u, m, lo)):
        return None, None, None, None

    band_width = u - lo
    if band_width <= 0:
        return u, m, lo, 0.5

    position = (prices[-1] - lo) / band_width
    score    = 1.0 - max(0.0, min(1.0, position))
    return u, m, lo, score

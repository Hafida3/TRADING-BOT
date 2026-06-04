"""
Layer 2 – Analysis: Market regime detection.

Uses close-price approximations of ATR and ADX (no OHLCV required):
  - True Range  ≈ |close[i] − close[i−1]|
  - ±DM         ≈ upward / downward close-to-close moves
  - ATR / ADX   via Wilder smoothing (same approach as indicators.py)

Regime rules:
  trending : ADX > 25  AND  ATR trending up (rising over last 3 bars)
  choppy   : ADX < 20  AND  ATR above its rolling mean (volatile but directionless)
  ranging  : ADX < 20  AND  ATR at or below mean (calm, mean-reverting)
  unknown  : insufficient data (<28 prices)

Transition buffer: raw label must repeat CONFIRM_BARS times before the
published regime changes, preventing flapping on borderline readings.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

ATR_PERIOD    = 14
ADX_PERIOD    = 14
ATR_MA_PERIOD = 28   # rolling window for "ATR high" reference
ATR_TREND_LAG = 3    # bars back to compare for "ATR trending up"
CONFIRM_BARS  = 3    # consecutive confirmations before regime flips

# Module-level persistent state
_pending_regime: str       = "unknown"   # raw label accumulating
_pending_count:  int       = 0           # how many bars it has held
_current_regime: str       = "unknown"   # published (buffered) regime


def _compute_atr_adx(prices: list[float]) -> tuple[pd.Series, pd.Series]:
    """Return (ATR series, ADX series) from a close-price list."""
    s   = pd.Series(prices, dtype=float)
    diff = s.diff()

    # True Range (close-only)
    tr = diff.abs()

    # Directional movement (close-only)
    plus_dm  = diff.clip(lower=0.0)
    minus_dm = (-diff).clip(lower=0.0)

    kw = dict(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False)
    atr       = tr.ewm(**kw).mean()
    plus_dm_s = plus_dm.ewm(**kw).mean()
    minus_dm_s = minus_dm.ewm(**kw).mean()

    safe_atr = atr.replace(0.0, np.nan)
    plus_di  = 100.0 * plus_dm_s / safe_atr
    minus_di = 100.0 * minus_dm_s / safe_atr

    di_sum  = (plus_di + minus_di).replace(0.0, np.nan)
    dx      = (100.0 * (plus_di - minus_di).abs() / di_sum).fillna(0.0)

    adx = dx.ewm(**kw).mean()
    return atr, adx


def _classify(adx: float, atr: float, atr_mean: float, atr_trending_up: bool) -> str:
    atr_high = atr > atr_mean
    if adx > 25 and atr_trending_up:
        return "trending"
    if adx < 20 and atr_high:
        return "choppy"
    return "ranging"


def detect_regime(prices: list[float]) -> dict:
    """
    Compute the current market regime from a close-price history.

    Returns a dict suitable for logging and data.json:
      regime          : "trending" | "ranging" | "choppy" | "unknown"
      adx             : float
      atr             : float
      atr_trending_up : bool
    """
    global _pending_regime, _pending_count, _current_regime

    min_needed = ATR_PERIOD * 2 + ATR_TREND_LAG + 1
    if len(prices) < min_needed:
        return {
            "regime":          "unknown",
            "adx":             None,
            "atr":             None,
            "atr_trending_up": False,
        }

    atr_s, adx_s = _compute_atr_adx(prices)

    # Take the latest finite values
    adx_val = float(adx_s.dropna().iloc[-1])
    atr_val = float(atr_s.dropna().iloc[-1])

    if math.isnan(adx_val) or math.isnan(atr_val):
        return {
            "regime":          "unknown",
            "adx":             None,
            "atr":             None,
            "atr_trending_up": False,
        }

    # ATR rolling mean for "high ATR" comparison
    recent_atr = atr_s.dropna().iloc[-ATR_MA_PERIOD:]
    atr_mean   = float(recent_atr.mean()) if len(recent_atr) >= 2 else atr_val

    # ATR trending up: latest > value ATR_TREND_LAG bars ago
    atr_series_clean = atr_s.dropna()
    if len(atr_series_clean) > ATR_TREND_LAG:
        atr_trending_up = float(atr_series_clean.iloc[-1]) > float(atr_series_clean.iloc[-1 - ATR_TREND_LAG])
    else:
        atr_trending_up = False

    raw = _classify(adx_val, atr_val, atr_mean, atr_trending_up)

    # Transition buffer
    if raw == _pending_regime:
        _pending_count += 1
    else:
        _pending_regime = raw
        _pending_count  = 1

    if _pending_count >= CONFIRM_BARS:
        _current_regime = _pending_regime

    return {
        "regime":          _current_regime,
        "adx":             round(adx_val, 2),
        "atr":             round(atr_val, 4),
        "atr_trending_up": atr_trending_up,
    }

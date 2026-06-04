"""
Layer 1 – Data: SOL/USDC price feed via CoinGecko free API.
"""

import time
import requests
from typing import Optional

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_HEADERS = {"Accept": "application/json"}
_TIMEOUT = 12

_price_cache: tuple[float, float] = (0.0, 0.0)  # (price, fetched_at)
CACHE_TTL = 30  # seconds


def get_sol_price(use_cache: bool = True) -> Optional[float]:
    """Return current SOL/USD price. Cached for CACHE_TTL seconds."""
    global _price_cache
    if use_cache and time.time() - _price_cache[1] < CACHE_TTL:
        return _price_cache[0]

    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": "solana", "vs_currencies": "usd"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        price = float(resp.json()["solana"]["usd"])
        _price_cache = (price, time.time())
        return price
    except Exception as exc:
        print(f"[PriceFeed] get_sol_price error: {exc}")
        return _price_cache[0] or None  # return stale value if available


def get_sol_ohlcv(days: int = 7) -> list[dict]:
    """
    Fetch SOL OHLCV candles from CoinGecko.

    Granularity returned by CoinGecko:
      days <= 2   → ~30-min candles
      days <= 90  → 4-hour candles
      days > 90   → daily candles

    Returns list of dicts with keys: timestamp, open, high, low, close.
    """
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/solana/ohlc",
            params={"vs_currency": "usd", "days": str(days)},
            headers=_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()
        return [
            {
                "timestamp": c[0] / 1000.0,
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
            }
            for c in raw
        ]
    except Exception as exc:
        print(f"[PriceFeed] get_sol_ohlcv error: {exc}")
        return []


def bootstrap_price_history(target_len: int = 60) -> list[float]:
    """
    Fetch recent close prices to seed the indicator window before the
    main loop has collected enough live ticks.
    """
    candles = get_sol_ohlcv(days=7)
    closes = [c["close"] for c in candles]
    return closes[-target_len:]

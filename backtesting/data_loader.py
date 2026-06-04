"""
Backtesting – data loader: fetch historical SOL OHLCV from CoinGecko.

CoinGecko free-tier granularity:
  days <= 90   → 4-hour candles
  days <= 365  → daily candles
  days > 365   → weekly candles (not supported here)
"""

import time
import requests
from typing import Optional

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def fetch_historical_ohlcv(days: int = 90) -> list[dict]:
    """
    Return a list of OHLCV dicts sorted ascending by timestamp.
    Caller controls granularity via `days` (max 365 for daily bars).
    """
    days = min(days, 365)
    url = f"{COINGECKO_BASE}/coins/solana/ohlc"
    try:
        print(f"[DataLoader] Fetching {days}-day OHLCV from CoinGecko…")
        resp = requests.get(
            url,
            params={"vs_currency": "usd", "days": str(days)},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        candles = [
            {
                "timestamp": c[0] / 1000.0,
                "open":  float(c[1]),
                "high":  float(c[2]),
                "low":   float(c[3]),
                "close": float(c[4]),
            }
            for c in raw
        ]
        candles.sort(key=lambda c: c["timestamp"])
        print(f"[DataLoader] Got {len(candles)} candles.")
        time.sleep(1)
        return candles
    except Exception as exc:
        print(f"[DataLoader] Error: {exc}")
        return []


def fetch_market_chart(days: int = 365) -> list[dict]:
    """
    Alternative: fetch daily close prices from /market_chart endpoint.
    Returns [{"timestamp": float, "close": float}, …].
    """
    url = f"{COINGECKO_BASE}/coins/solana/market_chart"
    try:
        resp = requests.get(
            url,
            params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        prices = data.get("prices", [])
        candles = [{"timestamp": p[0] / 1000.0, "close": float(p[1])} for p in prices]
        candles.sort(key=lambda c: c["timestamp"])
        time.sleep(1)
        return candles
    except Exception as exc:
        print(f"[DataLoader] market_chart error: {exc}")
        return []

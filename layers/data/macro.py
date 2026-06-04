"""
Layer 1 – Data: Macro market context signals.

Fetches two CoinGecko metrics:
  - BTC 24h price change   → price momentum signal
  - BTC market dominance   → alt-coin relative strength signal

When BTC is up and dominance is falling (alts gaining), SOL tends to
outperform. When BTC is down or dominance is rising (flight to BTC),
SOL tends to underperform.

Returns a composite macro_score in [0, 1].
"""

import math
import time
from typing import Optional

import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CACHE_TTL = 120  # 2 minutes

_cache: tuple[dict, float] = ({}, 0.0)


def _btc_change_to_score(change_pct: float) -> float:
    """
    Map BTC 24h % change → [0, 1] via tanh.
    Scale factor 10 → ±10% change gives score ~0.85 / ~0.15.
    """
    return (math.tanh(change_pct / 10.0) + 1.0) / 2.0


def _dominance_to_score(dominance_pct: float) -> float:
    """
    Map BTC market dominance % → [0, 1].
    High dominance (>60%) = alts losing = bearish for SOL → score → 0.
    Low dominance (<40%)  = alts gaining = bullish for SOL → score → 1.
    Linear interpolation over [35%, 65%] range.
    """
    return 1.0 - max(0.0, min(1.0, (dominance_pct - 35.0) / 30.0))


def get_macro_signal(use_cache: bool = True) -> dict:
    """
    Return macro context signals derived from BTC data.

    Returns dict with:
        btc_price_usd      : float
        btc_24h_change_pct : float   (e.g. 2.5 means +2.5%)
        btc_dominance_pct  : float   (e.g. 55.0 means 55%)
        btc_change_score   : float   [0,1]
        btc_dominance_score: float   [0,1]
        macro_score        : float   [0,1]  composite
    """
    global _cache

    if use_cache and time.time() - _cache[1] < CACHE_TTL and _cache[1] > 0:
        return dict(_cache[0])

    result = {
        "btc_price_usd": 0.0,
        "btc_24h_change_pct": 0.0,
        "btc_dominance_pct": 50.0,
        "btc_change_score": 0.5,
        "btc_dominance_score": 0.5,
        "macro_score": 0.5,
    }

    try:
        # BTC price + 24h change
        resp = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=12,
        )
        resp.raise_for_status()
        btc = resp.json()["bitcoin"]
        result["btc_price_usd"] = float(btc.get("usd", 0))
        result["btc_24h_change_pct"] = float(btc.get("usd_24h_change", 0))
    except Exception as exc:
        print(f"[Macro] BTC price error: {exc}")

    try:
        # BTC market dominance
        resp2 = requests.get(f"{COINGECKO_BASE}/global", timeout=12)
        resp2.raise_for_status()
        dom = resp2.json()["data"]["market_cap_percentage"].get("btc", 50.0)
        result["btc_dominance_pct"] = float(dom)
    except Exception as exc:
        print(f"[Macro] Dominance error: {exc}")

    change_score = _btc_change_to_score(result["btc_24h_change_pct"])
    dom_score = _dominance_to_score(result["btc_dominance_pct"])

    result["btc_change_score"] = change_score
    result["btc_dominance_score"] = dom_score
    # BTC price direction (65%) weighted over dominance (35%)
    result["macro_score"] = change_score * 0.65 + dom_score * 0.35

    _cache = (result, time.time())

    print(
        f"[Macro] BTC {result['btc_24h_change_pct']:+.2f}% | "
        f"Dom {result['btc_dominance_pct']:.1f}% | "
        f"macro_score={result['macro_score']:.3f}"
    )
    return result

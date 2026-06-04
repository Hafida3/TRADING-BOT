"""
Layer 1 – Data: Crypto Fear & Greed Index from alternative.me.

Contrarian normalization — extreme fear is a buy signal, extreme greed a sell:
  score  0 (Extreme Fear) → normalized 0.85
  score 50 (Neutral)      → normalized 0.50
  score 100 (Extreme Greed) → normalized 0.15

Caching: 30-minute in-process cache (index updates once a day).
"""

import time

import requests

FEAR_GREED_URL = "https://api.alternative.me/fng/"
CACHE_TTL      = 1800  # 30 minutes

_cache: tuple[dict, float] = ({}, 0.0)


def _normalize(score: int) -> float:
    """Contrarian: fear=bullish (high score), greed=bearish (low score)."""
    return round(0.85 - (score / 100) * 0.70, 4)


def get_fear_greed(use_cache: bool = True) -> dict:
    """
    Fetch the current Crypto Fear & Greed Index.

    Returns:
        score      : int 0-100 (raw index value)
        normalized : float 0-1  (contrarian, 0.85=extreme fear buy, 0.15=extreme greed sell)
        label      : str  e.g. "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
        cached     : bool
    """
    global _cache

    if use_cache and _cache[1] > 0 and time.time() - _cache[1] < CACHE_TTL:
        result = dict(_cache[0])
        result["cached"] = True
        return result

    try:
        resp = requests.get(FEAR_GREED_URL, params={"limit": 1}, timeout=10)
        resp.raise_for_status()
        entry      = resp.json()["data"][0]
        raw_score  = int(entry["value"])
        label      = entry.get("value_classification", "Unknown")
        normalized = _normalize(raw_score)

        print(f"[FearGreed] score={raw_score} | {label} | normalized={normalized:.3f}")

        result = {
            "score":      raw_score,
            "normalized": normalized,
            "label":      label,
            "cached":     False,
        }
        _cache = (result, time.time())
        return result

    except Exception as exc:
        print(f"[FearGreed] API error: {exc}")
        return {
            "score":      50,
            "normalized": 0.50,
            "label":      "Neutral",
            "cached":     False,
        }

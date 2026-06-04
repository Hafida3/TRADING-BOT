"""
Layer 1 – Data: Crypto news sentiment scored by VADER.

Flow:
  1. Fetch last 24h crypto headlines from NewsAPI (free tier: 100 req/day).
  2. Score each headline locally with VADER (no external API needed).
  3. Average compound scores → float in [-1, +1].
  4. Return normalised score in [0, 1] for the signal engine.

Caching: 30-min in-process cache (≤48 NewsAPI calls/day).
Install:  pip install vaderSentiment
"""

import time

import requests

NEWSAPI_BASE   = "https://newsapi.org/v2/everything"
NEWS_CACHE_TTL = 1800  # 30 minutes

_SEARCH_QUERY = (
    "crypto OR bitcoin OR solana OR ethereum OR cryptocurrency OR "
    "blockchain OR DeFi OR stablecoin"
)

_sentiment_cache: tuple[dict, float] = ({}, 0.0)

# Lazy-loaded so import doesn't fail before vaderSentiment is installed
_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def _fetch_headlines(api_key: str, max_articles: int = 20) -> list[str]:
    # Note: NewsAPI free tier does not support the 'from' date filter;
    # sortBy=publishedAt gives the most recent articles anyway.
    try:
        resp = requests.get(
            NEWSAPI_BASE,
            params={
                "q":        _SEARCH_QUERY,
                "sortBy":   "publishedAt",
                "pageSize": max_articles,
                "language": "en",
                "apiKey":   api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            a["title"]
            for a in articles
            if a.get("title") and a["title"] != "[Removed]"
        ]
    except Exception as exc:
        print(f"[NewsSentiment] NewsAPI error: {exc}")
        return []


def _score_with_vader(headlines: list[str]) -> tuple[float, str]:
    """Score headlines locally with VADER. Returns (score -1..+1, reason)."""
    if not headlines:
        return 0.0, "no headlines"

    analyzer = _get_analyzer()
    scores   = [analyzer.polarity_scores(h)["compound"] for h in headlines]
    avg      = sum(scores) / len(scores)

    if avg >= 0.05:
        reason = "bullish sentiment"
    elif avg <= -0.05:
        reason = "bearish sentiment"
    else:
        reason = "neutral sentiment"

    print(
        f"[NewsSentiment] VADER score={avg:.3f} | {reason} | "
        f"{len(headlines)} headlines"
    )
    return avg, reason


def get_news_sentiment(newsapi_key: str, use_cache: bool = True) -> dict:
    """
    Fetch and score crypto news sentiment via VADER.

    Returns:
        score         : float in [-1, +1]
        normalized    : float in [0, 1]
        reason        : short description of dominant theme
        headline_count: int
        cached        : bool
    """
    global _sentiment_cache

    if (
        use_cache
        and _sentiment_cache[1] > 0
        and time.time() - _sentiment_cache[1] < NEWS_CACHE_TTL
    ):
        cached = dict(_sentiment_cache[0])
        cached["cached"] = True
        return cached

    if not newsapi_key:
        return {
            "score":          0.0,
            "normalized":     0.5,
            "reason":         "API key not configured",
            "headline_count": 0,
            "cached":         False,
        }

    headlines        = _fetch_headlines(newsapi_key)
    score, reason    = _score_with_vader(headlines)
    normalized       = (score + 1.0) / 2.0  # [-1, +1] → [0, 1]

    result = {
        "score":          score,
        "normalized":     normalized,
        "reason":         reason,
        "headline_count": len(headlines),
        "cached":         False,
    }
    _sentiment_cache = (result, time.time())
    return result

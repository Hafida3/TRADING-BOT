"""
Layer 1 – Data: Trump Truth Social RSS sentiment monitor.

Flow:
  1. Fetch https://truthsocial.com/@realDonaldTrump.rss (stdlib urllib only).
  2. Filter items published within the last 60 minutes.
  3. Score title + description with VADER and boost/penalise based on
     geopolitical keywords known to move crypto markets.
  4. Return normalised score in [0, 1] (0.5 = neutral / no data).

Caching: 5-minute in-process cache.
"""

import re
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

# macOS Python ships without the system CA bundle; fall back to unverified
# context for this public RSS endpoint when verification fails.
_SSL_CTX = ssl.create_default_context()
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode    = ssl.CERT_NONE

FEED_URL        = "https://truthsocial.com/@realDonaldTrump.rss"
CACHE_TTL       = 300   # 5 minutes
RECENCY_WINDOW  = 3600  # 60 minutes

_BEARISH_KEYWORDS = {
    "war", "attack", "sanctions", "tariff", "conflict",
    "military", "strike", "threat", "iran", "china", "russia",
}
_BULLISH_KEYWORDS = {
    "deal", "peace", "agreement", "ceasefire", "bitcoin",
    "crypto", "cut", "great", "beautiful", "winning",
}

_cache: tuple[dict, float] = ({}, 0.0)
_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def _parse_pub_date(date_str: str) -> Optional[datetime]:
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


def _fetch_recent_posts() -> list[str]:
    """Return text of Truth Social posts published in the last 60 minutes."""
    try:
        req = urllib.request.Request(
            FEED_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            xml_data = resp.read()

        root    = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=RECENCY_WINDOW)
        texts: list[str] = []

        for item in channel.findall("item"):
            pub_el = item.find("pubDate")
            if pub_el is None or not pub_el.text:
                continue
            pub_date = _parse_pub_date(pub_el.text.strip())
            if pub_date is None or pub_date < cutoff:
                continue

            parts: list[str] = []
            title_el = item.find("title")
            desc_el  = item.find("description")
            if title_el is not None and title_el.text:
                parts.append(title_el.text.strip())
            if desc_el is not None and desc_el.text:
                clean = _strip_html(desc_el.text)
                if clean:
                    parts.append(clean)
            if parts:
                texts.append(" ".join(parts))

        return texts

    except ET.ParseError:
        return []
    except Exception as exc:
        print(f"[TrumpSignal] RSS fetch error: {exc}")
        return []


def _score_posts(texts: list[str]) -> tuple[float, str]:
    """Score posts with VADER + geopolitical keyword boost.
    Returns (score in [-1, +1], reason string).
    """
    if not texts:
        return 0.0, "no recent posts"

    analyzer     = _get_analyzer()
    scored: list[float] = []
    bearish_hits: list[str] = []
    bullish_hits: list[str] = []

    for text in texts:
        lower      = text.lower()
        vader_raw  = analyzer.polarity_scores(text)["compound"]
        boost      = 0.0

        for kw in _BEARISH_KEYWORDS:
            if kw in lower:
                boost -= 0.15
                bearish_hits.append(kw)
        for kw in _BULLISH_KEYWORDS:
            if kw in lower:
                boost += 0.15
                bullish_hits.append(kw)

        scored.append(max(-1.0, min(1.0, vader_raw + boost)))

    avg = max(-1.0, min(1.0, sum(scored) / len(scored)))

    unique_bearish = sorted(set(bearish_hits))
    unique_bullish = sorted(set(bullish_hits))

    if unique_bearish:
        reason = "bearish: " + ", ".join(unique_bearish[:3])
    elif unique_bullish:
        reason = "bullish: " + ", ".join(unique_bullish[:3])
    elif avg >= 0.05:
        reason = "bullish tone"
    elif avg <= -0.05:
        reason = "bearish tone"
    else:
        reason = "neutral"

    print(f"[TrumpSignal] {len(texts)} post(s) | score={avg:.3f} | {reason}")
    return avg, reason


def get_trump_signal(use_cache: bool = True) -> dict:
    """
    Fetch and score Trump Truth Social posts from the last 60 minutes.

    Returns:
        score      : float in [-1, +1]  (0 = neutral)
        normalized : float in [0, 1]   (0.5 = neutral)
        reason     : short description
        post_count : int
        cached     : bool
    """
    global _cache

    if use_cache and _cache[1] > 0 and time.time() - _cache[1] < CACHE_TTL:
        cached = dict(_cache[0])
        cached["cached"] = True
        return cached

    texts          = _fetch_recent_posts()
    score, reason  = _score_posts(texts)
    normalized     = (score + 1.0) / 2.0 if texts else 0.5

    result = {
        "score":      score,
        "normalized": normalized,
        "reason":     reason,
        "post_count": len(texts),
        "cached":     False,
    }
    _cache = (result, time.time())
    return result

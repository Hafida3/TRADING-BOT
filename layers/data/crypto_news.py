"""
Layer 1 – Data: Multi-source crypto news aggregator.

Sources (no API key required):
  RSS feeds: CoinDesk, CryptoPanic, Cointelegraph, Bitcoin Magazine,
             Decrypt, The Block, Coinbase Blog
  Contextual: DuckDuckGo instant answers for trigger keywords

Flow:
  1. Fetch RSS feeds concurrently (best-effort, failed sources skipped)
  2. DuckDuckGo search for geopolitical/macro keywords when detected
  3. Deduplicate by headline fingerprint
  4. Score all headlines with VADER
  5. Return composite score + top 3 headlines + source count

Cache: 15 minutes (900 s)
"""

import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

_CACHE_TTL = 900  # 15 min

_cache: dict = {"ts": 0.0, "result": None}

_RSS_SOURCES: list[tuple[str, str]] = [
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CryptoPanic",      "https://cryptopanic.com/news/rss/"),
    ("Cointelegraph",    "https://cointelegraph.com/rss"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/feed"),
    ("Decrypt",          "https://decrypt.co/feed"),
    ("The Block",        "https://www.theblock.co/rss.xml"),
    ("Coinbase Blog",    "https://blog.coinbase.com/feed"),
]

_DDG_KEYWORDS = ["iran", "tariff", "fed", "war", "bitcoin ETF"]
_DDG_URL      = "https://api.duckduckgo.com/"
_HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}


# ── RSS helpers ───────────────────────────────────────────────────────────────

def _parse_rss(content: bytes) -> list[str]:
    """Extract item/entry titles from RSS 2.0 or Atom XML."""
    try:
        root  = ET.fromstring(content)
        ns    = "{http://www.w3.org/2005/Atom}"
        items = list(root.iter("item")) or list(root.iter(f"{ns}entry"))
        titles: list[str] = []
        for item in items[:25]:
            el = item.find("title") or item.find(f"{ns}title")
            if el is not None and el.text:
                titles.append(el.text.strip())
        return titles
    except ET.ParseError:
        return []


def _fetch_rss(name: str, url: str) -> list[tuple[str, str]]:
    """Returns list of (source_name, headline) pairs."""
    try:
        r = requests.get(url, timeout=8, headers=_HEADERS)
        r.raise_for_status()
        return [(name, t) for t in _parse_rss(r.content)]
    except Exception as exc:
        print(f"[CryptoNews] {name} RSS error: {exc}")
        return []


# ── DuckDuckGo contextual search ─────────────────────────────────────────────

def _fetch_ddg(keyword: str) -> list[tuple[str, str]]:
    """DuckDuckGo instant answer snippets for a crypto keyword."""
    try:
        r = requests.get(
            _DDG_URL,
            params={"q": f"{keyword} crypto", "format": "json", "no_html": "1"},
            timeout=5,
            headers=_HEADERS,
        )
        topics = r.json().get("RelatedTopics", [])
        results = []
        for t in topics:
            if isinstance(t, dict) and t.get("Text"):
                results.append(("DuckDuckGo", t["Text"][:120]))
        return results[:4]
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_crypto_news() -> dict:
    """
    Aggregate crypto news from RSS + DuckDuckGo. 15-minute cache.

    Returns:
        score         : float [-1, +1]  — VADER composite
        normalized    : float [0, 1]
        top_headlines : list of {source, title, score}  — top 3 by |sentiment|
        sources_count : int  — number of RSS sources that responded
        cached        : bool
    """
    now = time.time()
    if _cache["result"] and now - _cache["ts"] < _CACHE_TTL:
        return {**_cache["result"], "cached": True}

    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()
    except ImportError:
        return {
            "score": 0.0, "normalized": 0.5,
            "top_headlines": [], "sources_count": 0, "cached": False,
        }

    # Collect headlines from all RSS sources
    all_pairs: list[tuple[str, str]] = []
    sources_hit = 0
    for name, url in _RSS_SOURCES:
        pairs = _fetch_rss(name, url)
        if pairs:
            sources_hit += 1
            all_pairs.extend(pairs)

    # DuckDuckGo for geo/macro keywords
    for kw in _DDG_KEYWORDS:
        all_pairs.extend(_fetch_ddg(kw))

    # Deduplicate by first 60 chars lowercase
    seen:   set[str]              = set()
    unique: list[tuple[str, str]] = []
    for src, title in all_pairs:
        key = title.lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append((src, title))

    if not unique:
        return {
            "score": 0.0, "normalized": 0.5,
            "top_headlines": [], "sources_count": sources_hit, "cached": False,
        }

    # VADER score every headline
    scored: list[tuple[float, str, str]] = []
    for src, title in unique:
        compound = vader.polarity_scores(title)["compound"]
        scored.append((compound, src, title))

    avg        = sum(s[0] for s in scored) / len(scored)
    normalized = (avg + 1.0) / 2.0

    # Top 3 by absolute sentiment strength
    scored.sort(key=lambda x: abs(x[0]), reverse=True)
    top_headlines = [
        {"source": s, "title": t, "score": round(c, 3)}
        for c, s, t in scored[:3]
    ]

    print(
        f"[CryptoNews] {len(unique)} headlines from {sources_hit} sources | "
        f"avg_score={avg:+.3f} | norm={normalized:.3f}"
    )

    result = {
        "score":         round(avg, 4),
        "normalized":    round(normalized, 4),
        "top_headlines": top_headlines,
        "sources_count": sources_hit,
        "cached":        False,
    }
    _cache["ts"]     = now
    _cache["result"] = result
    return result

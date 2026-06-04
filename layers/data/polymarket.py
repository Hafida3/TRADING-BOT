"""
Layer 1 – Data: Polymarket prediction market sentiment.

Root-cause of the 0.500 stall (two bugs fixed):
  1. Real liquid markets use `outcomePrices` (JSON string array), not `tokens[].price`.
  2. The API has no keyword filter; scanning 100 markets rarely hit crypto markets.

Fix: fetch two specific high-liquidity event groups by slug, parse outcomePrices.

Signal sources
──────────────
  Fed rate cuts 2026  (60%)  — macro risk-on/off proxy
    slug: how-many-fed-rate-cuts-in-2026   volume ~$4.5M
    Score: expected cuts / 4.0  (0 cuts = 0.0 bearish, 4+ cuts = 1.0 bullish)

  BTC $150k by Dec 31, 2026  (40%)  — crypto directional proxy
    slug: when-will-bitcoin-hit-150k       volume ~$23.8M
    Score: P(YES) / 0.50  capped at 1.0   (50% prob = fully bullish)

Cache: 15 minutes (these markets move slowly).
"""

from __future__ import annotations

import json
import re
import time

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
CACHE_TTL  = 900  # 15 minutes

_cache: tuple[float, float] = (0.5, 0.0)


# ── Price extraction ──────────────────────────────────────────────────────────

def _yes_price(market: dict) -> float | None:
    """
    Return the YES-outcome probability for a market.
    Tries outcomePrices first (order-book markets), then tokens[] (AMM markets),
    then lastTradePrice as a last resort.
    """
    op = market.get("outcomePrices")
    if op:
        try:
            prices = json.loads(op) if isinstance(op, str) else list(op)
            p = float(prices[0])
            if 0.0 < p < 1.0:   # exclude already-resolved markets (0 or 1)
                return p
        except (ValueError, IndexError, TypeError):
            pass

    for tok in (market.get("tokens") or []):
        if (tok.get("outcome") or "").lower() == "yes":
            try:
                return float(tok["price"])
            except (KeyError, TypeError, ValueError):
                pass

    ltp = market.get("lastTradePrice")
    if ltp is not None:
        try:
            p = float(ltp)
            if 0.0 < p < 1.0:
                return p
        except (ValueError, TypeError):
            pass

    return None


# ── Event fetcher ─────────────────────────────────────────────────────────────

def _fetch_event(slug: str) -> list[dict]:
    """Return the markets list for an event slug, or []."""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/events",
            params={"slug": slug},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data[0].get("markets") or []
    except Exception as exc:
        print(f"[Polymarket] Error fetching '{slug}': {exc}")
    return []


# ── Signal scorers ────────────────────────────────────────────────────────────

def _fed_score(markets: list[dict]) -> float | None:
    """
    Derive a 0-1 bullish score from the Fed rate cuts probability distribution.

    Expected cuts = Σ n × P(exactly n cuts).
    Normalised: expected_cuts / 4.0  (0 = bearish, 1 = bullish).
    """
    cut_probs: dict[int, float] = {}

    for m in markets:
        q = m.get("question", "").lower()
        p = _yes_price(m)
        if p is None:
            continue

        if "no fed rate" in q:
            cut_probs[0] = p
            continue

        hit = re.search(r"will\s+(\d+)\s+fed", q)
        if hit:
            cut_probs[int(hit.group(1))] = p

    if not cut_probs:
        return None

    expected = sum(n * p for n, p in cut_probs.items())
    score    = min(expected / 4.0, 1.0)
    print(f"[Polymarket] Fed rate cuts: expected={expected:.3f} → score={score:.3f} "
          f"({len(cut_probs)} markets parsed)")
    return score


def _btc_score(markets: list[dict]) -> float | None:
    """
    P(BTC hits $150k by Dec 31, 2026) → 0-1 bullish score.
    Scaling: P=0.50 maps to score=1.0 (linear).
    Skips already-resolved markets (outcomePrices = ["0","1"]).
    """
    target_price = None

    # Prefer the Dec 31 2026 market; fall back to any active unresolved market
    for m in markets:
        q = m.get("question", "").lower()
        p = _yes_price(m)
        if p is None:
            continue
        if "december 31, 2026" in q or "dec 31, 2026" in q:
            target_price = p
            break

    if target_price is None:
        active = [(m, _yes_price(m)) for m in markets]
        active = [(m, p) for m, p in active if p is not None]
        if active:
            target_price = max(active, key=lambda x: x[1])[1]

    if target_price is None:
        return None

    score = min(target_price / 0.50, 1.0)
    print(f"[Polymarket] BTC $150k: p_yes={target_price:.4f} → score={score:.3f}")
    return score


# ── Public interface ──────────────────────────────────────────────────────────

def get_sol_sentiment(use_cache: bool = True) -> float:
    """
    Return a 0-1 sentiment score from Polymarket's most liquid crypto-relevant
    prediction markets.  1 = strongly bullish, 0.5 = neutral, 0 = strongly bearish.
    """
    global _cache

    if use_cache and time.time() - _cache[1] < CACHE_TTL:
        return _cache[0]

    weighted: list[tuple[float, float]] = []   # (score, weight)

    fed_markets = _fetch_event("how-many-fed-rate-cuts-in-2026")
    if fed_markets:
        s = _fed_score(fed_markets)
        if s is not None:
            weighted.append((s, 0.60))

    btc_markets = _fetch_event("when-will-bitcoin-hit-150k")
    if btc_markets:
        s = _btc_score(btc_markets)
        if s is not None:
            weighted.append((s, 0.40))

    if not weighted:
        print("[Polymarket] No data fetched — using cached/neutral")
        return _cache[0]

    total_w   = sum(w for _, w in weighted)
    composite = sum(s * w for s, w in weighted) / total_w

    print(f"[Polymarket] sentiment={composite:.4f} "
          f"({'  '.join(f'sig={s:.3f}@{w}' for s,w in weighted)})")

    _cache = (composite, time.time())
    return composite

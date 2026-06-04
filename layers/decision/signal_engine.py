"""
Layer 3 – Decision: Weighted composite signal from all 7 data sources.

Signal weights (redistributed proportionally when a source is unavailable):
  RSI            15%  — price momentum oversold/overbought
  MACD           15%  — trend direction and histogram momentum
  Polymarket     10%  — prediction market probabilities across SOL/BTC/Fed/ETF
  News NLP       20%  — VADER sentiment on last 24h crypto headlines
  Macro BTC      10%  — BTC 24h change + BTC dominance
  Trump/Geo      10%  — Truth Social RSS geopolitical sentiment
  Fear & Greed   10%  — Contrarian crypto sentiment index (alternative.me)
  (Regime is observation-only, not included in composite)
"""

from dataclasses import dataclass, field
from typing import Optional

import config

_WEIGHTS: dict[str, float] = {
    "rsi":        0.15,
    "macd":       0.15,
    "polymarket": 0.10,
    "news":       0.20,
    "macro":      0.10,
    "trump":      0.10,
    "fear_greed": 0.10,
}


@dataclass
class Signal:
    action: str                    # "BUY" | "SELL" | "HOLD"
    score: float                   # composite 0–1
    rsi_raw: Optional[float]
    macd_raw: Optional[float]
    macd_signal_raw: Optional[float]
    macd_hist_raw: Optional[float]
    polymarket_sentiment: Optional[float]
    news_score: Optional[float]
    news_reason: str
    macro_score: Optional[float]
    trump_score:      Optional[float]
    trump_reason:     str
    fear_greed_score: Optional[int]
    fear_greed_label: str
    reason: str
    weights_used: dict[str, float] = field(default_factory=dict)


def generate_signal(
    rsi_score: Optional[float],
    macd_score: Optional[float],
    polymarket_score: Optional[float],
    news_score: Optional[float],
    macro_score: Optional[float],
    *,
    rsi_raw: Optional[float] = None,
    macd_raw: Optional[float] = None,
    macd_signal_raw: Optional[float] = None,
    macd_hist_raw: Optional[float] = None,
    news_reason: str = "",
    trump_score: Optional[float] = None,
    trump_reason: str = "",
    fear_greed_score: Optional[float] = None,
    fear_greed_raw: Optional[int] = None,
    fear_greed_label: str = "",
) -> Signal:
    """
    Aggregate normalised 0-1 scores from all available sources into a
    single BUY / SELL / HOLD signal.
    """
    source_map: dict[str, Optional[float]] = {
        "rsi":        rsi_score,
        "macd":       macd_score,
        "polymarket": polymarket_score,
        "news":       news_score,
        "macro":      macro_score,
        "trump":      trump_score,
        "fear_greed": fear_greed_score,
    }

    active = {k: v for k, v in source_map.items() if v is not None}

    if not active:
        return Signal(
            action="HOLD",
            score=0.5,
            rsi_raw=rsi_raw,
            macd_raw=macd_raw,
            macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw,
            polymarket_sentiment=polymarket_score,
            news_score=news_score,
            news_reason=news_reason,
            macro_score=macro_score,
            trump_score=trump_score,
            trump_reason=trump_reason,
            fear_greed_score=fear_greed_raw,
            fear_greed_label=fear_greed_label,
            reason="No data yet",
        )

    # Redistribute weights for missing sources
    raw_total   = sum(_WEIGHTS[k] for k in active)
    eff_weights = {k: _WEIGHTS[k] / raw_total for k in active}

    composite = sum(active[k] * eff_weights[k] for k in active)

    # Build human-readable reason string
    parts: list[str] = []
    if rsi_raw is not None:
        parts.append(f"RSI={rsi_raw:.1f}")
    if macd_hist_raw is not None:
        trend = "▲" if macd_hist_raw > 0 else "▼"
        parts.append(f"hist={macd_hist_raw:.3f}{trend}")
    if polymarket_score is not None:
        parts.append(f"PM={polymarket_score:.2f}")
    if news_score is not None:
        parts.append(f"news={news_score:.2f}")
    if macro_score is not None:
        parts.append(f"macro={macro_score:.2f}")
    if trump_score is not None:
        parts.append(f"trump={trump_score:.2f}")
    if fear_greed_score is not None:
        parts.append(f"fg={fear_greed_score:.2f}")
    parts.append(f"→{composite:.3f}")

    if composite >= config.BUY_THRESHOLD:
        action = "BUY"
    elif composite <= config.SELL_THRESHOLD:
        action = "SELL"
    else:
        action = "HOLD"

    return Signal(
        action=action,
        score=composite,
        rsi_raw=rsi_raw,
        macd_raw=macd_raw,
        macd_signal_raw=macd_signal_raw,
        macd_hist_raw=macd_hist_raw,
        polymarket_sentiment=polymarket_score,
        news_score=news_score,
        news_reason=news_reason,
        macro_score=macro_score,
        trump_score=trump_score,
        trump_reason=trump_reason,
        fear_greed_score=fear_greed_raw,
        fear_greed_label=fear_greed_label,
        reason=" | ".join(parts),
        weights_used=eff_weights,
    )

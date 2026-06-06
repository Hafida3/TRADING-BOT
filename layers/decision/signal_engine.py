"""
Layer 3 – Decision: LLM ReAct decision engine with tiered fallback.

Priority:
  1. Claude API  (claude-3-haiku-20240307) — primary ReAct agent
  2. Groq API    (llama-3.1-8b-instant)    — secondary LLM fallback
  3. Weighted composite score              — final offline fallback

Signal weights (normalised proportionally when a source is absent):
  News NLP    25%
  MACD        13%
  RSI         12%
  Polymarket  10%
  Macro BTC   10%
  Trump/Geo   10%
  Fear&Greed  10%
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import requests

import config

_WEIGHTS: dict[str, float] = {
    "news":       0.25,
    "macd":       0.13,
    "rsi":        0.12,
    "polymarket": 0.10,
    "macro":      0.10,
    "trump":      0.10,
    "fear_greed": 0.10,
}

_GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"


@dataclass
class Signal:
    action:               str
    score:                float          # composite weighted score (always computed)
    rsi_raw:              Optional[float]
    macd_raw:             Optional[float]
    macd_signal_raw:      Optional[float]
    macd_hist_raw:        Optional[float]
    polymarket_sentiment: Optional[float]
    news_score:           Optional[float]
    news_reason:          str
    macro_score:          Optional[float]
    trump_score:          Optional[float]
    trump_reason:         str
    fear_greed_score:     Optional[int]
    fear_greed_label:     str
    reason:               str            # compact score breakdown for logs
    reasoning:            str  = ""      # LLM natural-language explanation
    llm_used:             bool = False
    weights_used:         dict[str, float] = field(default_factory=dict)


# ── Composite score ───────────────────────────────────────────────────────────

def _composite(
    rsi_score, macd_score, polymarket_score,
    news_score, macro_score, trump_score, fear_greed_score,
) -> tuple[float, dict[str, float]]:
    source_map = {
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
        return 0.5, {}
    raw_total   = sum(_WEIGHTS[k] for k in active)
    eff_weights = {k: _WEIGHTS[k] / raw_total for k in active}
    composite   = sum(active[k] * eff_weights[k] for k in active)
    return composite, eff_weights


# ── Claude (primary) ──────────────────────────────────────────────────────────

def _call_claude(
    price:           float,
    rsi_raw:         Optional[float],
    macd_hist_raw:   Optional[float],
    polymarket_score: Optional[float],
    news_score:      Optional[float],
    macro_score:     Optional[float],
    fear_greed_raw:  Optional[int],
    fear_greed_label: str,
    regime:          str,
    top_headline:    str,
) -> tuple[str, str] | None:
    """Call Claude claude-3-haiku-20240307. Returns (action, reasoning) or None."""
    if not config.ANTHROPIC_API_KEY:
        return None

    def fmt(v, d=3):
        return f"{v:.{d}f}" if v is not None else "N/A"

    prompt = (
        f"You are an autonomous crypto trading agent. "
        f"Given these market signals: "
        f"RSI={fmt(rsi_raw,1)}, MACD={fmt(macd_hist_raw,4)}, "
        f"Polymarket={fmt(polymarket_score)}, "
        f"News={fmt(news_score)} ({top_headline or 'no headline'}), "
        f"Macro={fmt(macro_score)}, Fear&Greed={fear_greed_raw}/100 ({fear_greed_label}), "
        f"Regime={regime}. "
        f"Your soul: protect capital, generate asymmetric gains. "
        f"Decide: BUY / SELL / HOLD and explain why in one sentence."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text.strip()
        m = re.search(r'\b(BUY|SELL|HOLD)\b', content.upper())
        action = m.group(1) if m else "HOLD"
        return action, content[:400]
    except Exception as exc:
        print(f"[Claude] Error: {exc}")
        return None


# ── Groq (secondary) ─────────────────────────────────────────────────────────

def _call_groq(
    price:                 float,
    rsi_raw:               Optional[float],
    macd_hist_raw:         Optional[float],
    polymarket_score:      Optional[float],
    news_score:            Optional[float],
    news_reason:           str,
    macro_score:           Optional[float],
    trump_score:           Optional[float],
    trump_reason:          str,
    fear_greed_raw:        Optional[int],
    fear_greed_normalized: Optional[float],
    fear_greed_label:      str,
    regime:                str,
    recent_trades:         list,
    composite_score:       float,
    top_headline:          str,
) -> tuple[str, float, str] | None:
    """Call Groq llama-3.1-8b-instant. Returns (action, confidence, reasoning) or None."""
    if not config.GROQ_API_KEY:
        return None

    def fmt(v, d=3):
        return f"{v:.{d}f}" if v is not None else "N/A"

    trades_text = "  No closed trades yet."
    if recent_trades:
        lines = []
        for t in recent_trades[-5:]:
            pnl = t.get("pnl_usdc", 0) or 0
            lines.append(
                f"  {t.get('direction','long').upper()} "
                f"entry=${t.get('entry_price',0):.2f} "
                f"exit=${t.get('exit_price',0):.2f} "
                f"pnl=${pnl:+.2f}"
            )
        trades_text = "\n".join(lines)

    headline_ctx = f" Top headline: {top_headline}" if top_headline else ""
    user_content = f"""Analyze SOL/USDC signals and decide BUY, SELL, or HOLD.

SOL Price: ${price:.4f}
RSI(14): {fmt(rsi_raw,1)} | MACD Hist: {fmt(macd_hist_raw,4)}
Polymarket: {fmt(polymarket_score)} | News: {fmt(news_score)}{headline_ctx}
Macro BTC: {fmt(macro_score)} | Trump: {fmt(trump_score)} ({trump_reason or 'no posts'})
Fear&Greed: {fear_greed_raw}/100 ({fear_greed_label}) → contrarian={fmt(fear_greed_normalized)}
Regime: {regime} | Composite: {composite_score:.3f} [BUY≥{config.BUY_THRESHOLD}/SELL≤{config.SELL_THRESHOLD}]

Recent trades:
{trades_text}

Reply ONLY with JSON: {{"action":"BUY"|"SELL"|"HOLD","confidence":0.0-1.0,"reasoning":"1-2 sentences"}}"""

    try:
        resp = requests.post(
            _GROQ_URL,
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":    config.GROQ_MODEL,
                "messages": [
                    {
                        "role":    "system",
                        "content": (
                            "You are a quantitative crypto trading engine. "
                            "Output a single JSON object with keys: action, confidence, reasoning."
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                "temperature":     0.1,
                "max_tokens":      200,
                "response_format": {"type": "json_object"},
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            parsed = json.loads(m.group()) if m else {}

        action     = str(parsed.get("action", "HOLD")).upper()
        if action not in ("BUY", "SELL", "HOLD"):
            action = "HOLD"
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        reasoning  = str(parsed.get("reasoning", "")).strip()[:400]
        return action, confidence, reasoning

    except Exception as exc:
        print(f"[Groq] Error: {exc}")
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def generate_signal(
    rsi_score:        Optional[float],
    macd_score:       Optional[float],
    polymarket_score: Optional[float],
    news_score:       Optional[float],
    macro_score:      Optional[float],
    *,
    rsi_raw:          Optional[float] = None,
    macd_raw:         Optional[float] = None,
    macd_signal_raw:  Optional[float] = None,
    macd_hist_raw:    Optional[float] = None,
    news_reason:      str = "",
    trump_score:      Optional[float] = None,
    trump_reason:     str = "",
    fear_greed_score: Optional[float] = None,
    fear_greed_raw:   Optional[int]   = None,
    fear_greed_label: str = "",
    price:            Optional[float] = None,
    regime:           str = "unknown",
    recent_trades:    Optional[list]  = None,
    top_headline:     str = "",
) -> Signal:

    # Step 1: composite (always — needed for display bars + fallback)
    composite, eff_weights = _composite(
        rsi_score, macd_score, polymarket_score,
        news_score, macro_score, trump_score, fear_greed_score,
    )

    # Step 2: compact score reason for logs
    parts: list[str] = []
    if rsi_raw         is not None: parts.append(f"RSI={rsi_raw:.1f}")
    if macd_hist_raw   is not None:
        parts.append(f"hist={macd_hist_raw:.3f}{'▲' if macd_hist_raw > 0 else '▼'}")
    if polymarket_score is not None: parts.append(f"PM={polymarket_score:.2f}")
    if news_score       is not None: parts.append(f"news={news_score:.2f}")
    if macro_score      is not None: parts.append(f"macro={macro_score:.2f}")
    if trump_score      is not None: parts.append(f"trump={trump_score:.2f}")
    if fear_greed_score is not None: parts.append(f"fg={fear_greed_score:.2f}")
    parts.append(f"→{composite:.3f}")
    score_reason = " | ".join(parts)

    # Step 3: score-based action (final fallback)
    if composite >= config.BUY_THRESHOLD:
        fallback_action = "BUY"
    elif composite <= config.SELL_THRESHOLD:
        fallback_action = "SELL"
    else:
        fallback_action = "HOLD"

    if not eff_weights:
        return Signal(
            action="HOLD", score=0.5,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            trump_score=trump_score, trump_reason=trump_reason,
            fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
            reason="No data yet", reasoning="No signal data available.",
        )

    if price is None:
        # Can't call any LLM without price context
        return Signal(
            action=fallback_action, score=composite,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            trump_score=trump_score, trump_reason=trump_reason,
            fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
            reason=score_reason,
            reasoning=f"Score-based: composite={composite:.3f}, regime={regime}.",
            weights_used=eff_weights,
        )

    # Step 4: Claude (primary)
    claude_result = _call_claude(
        price=price,
        rsi_raw=rsi_raw,
        macd_hist_raw=macd_hist_raw,
        polymarket_score=polymarket_score,
        news_score=news_score,
        macro_score=macro_score,
        fear_greed_raw=fear_greed_raw,
        fear_greed_label=fear_greed_label,
        regime=regime,
        top_headline=top_headline,
    )

    if claude_result:
        action, reasoning = claude_result
        print(f"[Claude] → {action} | {reasoning[:80]}…")
        return Signal(
            action=action, score=composite,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            trump_score=trump_score, trump_reason=trump_reason,
            fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
            reason=score_reason, reasoning=reasoning,
            llm_used=True, weights_used=eff_weights,
        )

    # Step 5: Groq (secondary)
    groq_result = _call_groq(
        price=price,
        rsi_raw=rsi_raw,
        macd_hist_raw=macd_hist_raw,
        polymarket_score=polymarket_score,
        news_score=news_score,
        news_reason=news_reason,
        macro_score=macro_score,
        trump_score=trump_score,
        trump_reason=trump_reason,
        fear_greed_raw=fear_greed_raw,
        fear_greed_normalized=fear_greed_score,
        fear_greed_label=fear_greed_label,
        regime=regime,
        recent_trades=recent_trades or [],
        composite_score=composite,
        top_headline=top_headline,
    )

    if groq_result:
        action, _conf, reasoning = groq_result
        print(f"[Groq] → {action} | {reasoning[:80]}…")
        return Signal(
            action=action, score=composite,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            trump_score=trump_score, trump_reason=trump_reason,
            fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
            reason=score_reason, reasoning=reasoning,
            llm_used=True, weights_used=eff_weights,
        )

    # Step 6: weighted score fallback
    print(f"[Signal] Fallback → {fallback_action} (composite={composite:.3f})")
    return Signal(
        action=fallback_action, score=composite,
        rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
        macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
        news_score=news_score, news_reason=news_reason, macro_score=macro_score,
        trump_score=trump_score, trump_reason=trump_reason,
        fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
        reason=score_reason,
        reasoning=f"LLMs unavailable — composite={composite:.3f}, regime={regime}.",
        llm_used=False, weights_used=eff_weights,
    )

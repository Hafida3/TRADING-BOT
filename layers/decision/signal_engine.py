"""
Layer 3 – Decision: LLM ReAct decision engine with tiered fallback.

Priority:
  1. Claude API  (claude-haiku-4-5)        — primary ReAct agent
  2. Groq API    (llama-3.1-8b-instant)    — secondary LLM fallback
  3. Weighted composite score              — final offline fallback

Signal weights (normalised proportionally when a source is absent):
  News NLP    20%
  RSI         15%
  MACD        15%
  MA Cross    13%
  Stoch RSI   10%
  Bollinger   10%
  Polymarket   7%
  Macro BTC    5%
  Fear&Greed   5%
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import requests

import config

_WEIGHTS: dict[str, float] = {
    "news":       0.20,
    "rsi":        0.15,
    "macd":       0.15,
    "ma":         0.13,
    "stoch":      0.10,
    "bb":         0.13,
    "polymarket": 0.07,
    "macro":      0.05,
    "fear_greed": 0.02,
}

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


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
    ma_score:             Optional[float]
    stoch_score:          Optional[float]
    bb_score:             Optional[float]
    fear_greed_score:     Optional[int]
    fear_greed_label:     str
    reason:               str            # compact score breakdown for logs
    reasoning:            str  = ""      # LLM natural-language explanation
    llm_used:             bool = False
    weights_used:         dict[str, float] = field(default_factory=dict)


# ── Composite score ───────────────────────────────────────────────────────────

def _composite(
    rsi_score, macd_score, polymarket_score,
    news_score, macro_score, ma_score, stoch_score, bb_score, fear_greed_score,
) -> tuple[float, dict[str, float]]:
    source_map = {
        "rsi":        rsi_score,
        "macd":       macd_score,
        "polymarket": polymarket_score,
        "news":       news_score,
        "macro":      macro_score,
        "ma":         ma_score,
        "stoch":      stoch_score,
        "bb":         bb_score,
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

def _zone(score: float) -> str:
    if score < config.SELL_THRESHOLD:
        return "SELL ZONE"
    if score > config.BUY_THRESHOLD:
        return "BUY ZONE"
    return "NEUTRAL ZONE"


def _call_claude(
    price:            float,
    rsi_raw:          Optional[float],
    macd_hist_raw:    Optional[float],
    polymarket_score: Optional[float],
    news_score:       Optional[float],
    macro_score:      Optional[float],
    ma_fast:          Optional[float],
    ma_slow:          Optional[float],
    stoch_k:          Optional[float],
    bb_score:         Optional[float],
    fear_greed_raw:   Optional[int],
    fear_greed_label: str,
    regime:           str,
    top_headline:     str,
    composite_score:  float = 0.5,
    agent_memory:     str = "",
    agent_soul:       str = "",
) -> tuple[str, str] | None:
    """Call claude-haiku-4-5. Returns (action, reasoning) or None."""
    if not config.ANTHROPIC_API_KEY:
        return None

    def fmt(v, d=3):
        return f"{v:.{d}f}" if v is not None else "N/A"

    zone     = _zone(composite_score)
    ma_trend = "bull" if ma_fast and ma_slow and ma_fast > ma_slow else "bear"
    memory_ctx = (
        f"\n\nYour past trade lessons:\n{agent_memory[-800:]}"
        if agent_memory else ""
    )
    prompt = (
        f"You are an autonomous crypto trading agent. "
        f"Given these market signals: "
        f"RSI={fmt(rsi_raw,1)}, MACD={fmt(macd_hist_raw,4)}, "
        f"MA50/200={fmt(ma_fast,2)}/{fmt(ma_slow,2)} ({ma_trend}), "
        f"StochK={fmt(stoch_k,1)}, BB={fmt(bb_score)}, "
        f"Polymarket={fmt(polymarket_score)}, "
        f"News={fmt(news_score)} ({top_headline or 'no headline'}), "
        f"Macro={fmt(macro_score)}, Fear&Greed={fear_greed_raw}/100 ({fear_greed_label}), "
        f"Regime={regime}. "
        + (f"\n\nYour governing rules and identity:\n{agent_soul}\n" if agent_soul else "Your soul: protect capital, generate asymmetric gains.")
        + f"{memory_ctx}\n\n"
        f"Composite score: {composite_score:.3f} "
        f"(BUY threshold: {config.BUY_THRESHOLD}, SELL threshold: {config.SELL_THRESHOLD})\n"
        f"Current signal zone: {zone}\n"
        f"Note: if you return HOLD while score is in SELL ZONE, no short position will open.\n"
        f"Be decisive — HOLD is only appropriate in the NEUTRAL ZONE "
        f"({config.SELL_THRESHOLD}–{config.BUY_THRESHOLD}).\n\n"
        f"Respond in this exact order:\n"
        f"Line 1: ACTION — one word only: BUY, SELL, or HOLD\n"
        f"Line 2: TUNE: KEY=value (reason) — only if an adjustment is needed after "
        f"3+ consecutive losses or a regime shift. Omit entirely if not needed.\n"
        f"  Allowed keys: BUY_THRESHOLD(0.42-0.65), SELL_THRESHOLD(0.35-0.55), "
        f"STOP_LOSS_PCT(0.008-0.03), TAKE_PROFIT_PCT(0.016-0.06).\n"
        f"Remaining lines: your detailed reasoning."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text.strip()
        m = re.search(r'\b(BUY|SELL|HOLD)\b', content.upper())
        action = m.group(1) if m else "HOLD"
        return action, content[:2000]
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
    ma_fast:               Optional[float],
    ma_slow:               Optional[float],
    stoch_k:               Optional[float],
    stoch_d:               Optional[float],
    bb_score:              Optional[float],
    fear_greed_raw:        Optional[int],
    fear_greed_normalized: Optional[float],
    fear_greed_label:      str,
    regime:                str,
    recent_trades:         list,
    composite_score:       float,
    top_headline:          str,
    agent_memory:          str = "",
    agent_soul:            str = "",
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

    zone         = _zone(composite_score)
    headline_ctx = f" Top headline: {top_headline}" if top_headline else ""
    memory_ctx   = f"\n\nPast trade lessons:\n{agent_memory[-600:]}" if agent_memory else ""
    ma_trend     = "bull" if ma_fast and ma_slow and ma_fast > ma_slow else "bear"
    user_content = f"""Analyze SOL/USDC signals and decide BUY, SELL, or HOLD.

SOL Price: ${price:.4f}
RSI(14): {fmt(rsi_raw,1)} | MACD Hist: {fmt(macd_hist_raw,4)}
MA50: {fmt(ma_fast,2)} / MA200: {fmt(ma_slow,2)} ({ma_trend}) | StochK: {fmt(stoch_k,1)} D: {fmt(stoch_d,1)} | BB: {fmt(bb_score)}
Polymarket: {fmt(polymarket_score)} | News: {fmt(news_score)}{headline_ctx}
Macro BTC: {fmt(macro_score)} | Fear&Greed: {fear_greed_raw}/100 ({fear_greed_label}) → contrarian={fmt(fear_greed_normalized)}
Regime: {regime} | Composite: {composite_score:.3f} [BUY≥{config.BUY_THRESHOLD}/SELL≤{config.SELL_THRESHOLD}]

Composite score: {composite_score:.3f} (BUY threshold: {config.BUY_THRESHOLD}, SELL threshold: {config.SELL_THRESHOLD})
Current signal zone: {zone}
Note: if you return HOLD while score is in SELL ZONE, no short position will open.
Be decisive — HOLD is only appropriate in the NEUTRAL ZONE ({config.SELL_THRESHOLD}–{config.BUY_THRESHOLD}).

Recent trades:
{trades_text}

Reply ONLY with JSON: {{"action":"BUY"|"SELL"|"HOLD","confidence":0.0-1.0,"reasoning":"[Optional first line: TUNE: KEY=value (reason) if adjustment needed after 3+ losses or regime shift — BUY_THRESHOLD(0.42-0.65), SELL_THRESHOLD(0.35-0.55), STOP_LOSS_PCT(0.008-0.03), TAKE_PROFIT_PCT(0.016-0.06).] Then 1-2 sentences of reasoning."}}{memory_ctx}"""

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
                            + (f"\n\nGoverning rules:\n{agent_soul}" if agent_soul else "")
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                "temperature":     0.1,
                "max_tokens":      600,
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
        reasoning  = str(parsed.get("reasoning", "")).strip()[:2000]
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
    ma_score:         Optional[float] = None,
    stoch_score:      Optional[float] = None,
    bb_score:         Optional[float] = None,
    rsi_raw:          Optional[float] = None,
    macd_raw:         Optional[float] = None,
    macd_signal_raw:  Optional[float] = None,
    macd_hist_raw:    Optional[float] = None,
    news_reason:      str = "",
    ma_fast:          Optional[float] = None,
    ma_slow:          Optional[float] = None,
    stoch_k:          Optional[float] = None,
    stoch_d:          Optional[float] = None,
    bb_upper:         Optional[float] = None,
    bb_lower:         Optional[float] = None,
    fear_greed_score: Optional[float] = None,
    fear_greed_raw:   Optional[int]   = None,
    fear_greed_label: str = "",
    price:            Optional[float] = None,
    regime:           str = "unknown",
    recent_trades:    Optional[list]  = None,
    top_headline:     str = "",
    agent_memory:     str = "",
    agent_soul:       str = "",
) -> Signal:

    # Step 1: composite (always — needed for display bars + fallback)
    composite, eff_weights = _composite(
        rsi_score, macd_score, polymarket_score,
        news_score, macro_score, ma_score, stoch_score, bb_score, fear_greed_score,
    )

    # Step 2: compact score reason for logs
    parts: list[str] = []
    if rsi_raw          is not None: parts.append(f"RSI={rsi_raw:.1f}")
    if macd_hist_raw    is not None:
        parts.append(f"hist={macd_hist_raw:.3f}{'▲' if macd_hist_raw > 0 else '▼'}")
    if ma_score         is not None: parts.append(f"ma={ma_score:.2f}")
    if stoch_score      is not None: parts.append(f"stoch={stoch_score:.2f}")
    if bb_score         is not None: parts.append(f"bb={bb_score:.2f}")
    if polymarket_score is not None: parts.append(f"PM={polymarket_score:.2f}")
    if news_score       is not None: parts.append(f"news={news_score:.2f}")
    if macro_score      is not None: parts.append(f"macro={macro_score:.2f}")
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
            ma_score=ma_score, stoch_score=stoch_score, bb_score=bb_score,
            fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
            reason="No data yet", reasoning="No signal data available.",
        )

    if price is None:
        return Signal(
            action=fallback_action, score=composite,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            ma_score=ma_score, stoch_score=stoch_score, bb_score=bb_score,
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
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        stoch_k=stoch_k,
        bb_score=bb_score,
        fear_greed_raw=fear_greed_raw,
        fear_greed_label=fear_greed_label,
        regime=regime,
        top_headline=top_headline,
        composite_score=composite,
        agent_memory=agent_memory,
        agent_soul=agent_soul,
    )

    if claude_result:
        action, reasoning = claude_result
        print(f"[Claude] → {action} | {reasoning[:80]}…")
        return Signal(
            action=action, score=composite,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            ma_score=ma_score, stoch_score=stoch_score, bb_score=bb_score,
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
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        bb_score=bb_score,
        fear_greed_raw=fear_greed_raw,
        fear_greed_normalized=fear_greed_score,
        fear_greed_label=fear_greed_label,
        regime=regime,
        recent_trades=recent_trades or [],
        composite_score=composite,
        top_headline=top_headline,
        agent_memory=agent_memory,
        agent_soul=agent_soul,
    )

    if groq_result:
        action, _conf, reasoning = groq_result
        print(f"[Groq] → {action} | {reasoning[:80]}…")
        return Signal(
            action=action, score=composite,
            rsi_raw=rsi_raw, macd_raw=macd_raw, macd_signal_raw=macd_signal_raw,
            macd_hist_raw=macd_hist_raw, polymarket_sentiment=polymarket_score,
            news_score=news_score, news_reason=news_reason, macro_score=macro_score,
            ma_score=ma_score, stoch_score=stoch_score, bb_score=bb_score,
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
        ma_score=ma_score, stoch_score=stoch_score, bb_score=bb_score,
        fear_greed_score=fear_greed_raw, fear_greed_label=fear_greed_label,
        reason=score_reason,
        reasoning=f"LLMs unavailable — composite={composite:.3f}, regime={regime}.",
        llm_used=False, weights_used=eff_weights,
    )

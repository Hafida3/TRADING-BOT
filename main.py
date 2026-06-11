#!/usr/bin/env python3
"""
SOL / USDC Autonomous Trading Bot
──────────────────────────────────
Entry points:
  python main.py                      live/paper loop (DRY_RUN from .env)
  python main.py --backtest 90        run 90-day backtest and exit
  python main.py --generate-wallet    create a new hot wallet and exit
"""

import csv
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from alerts.telegram import TelegramAlerter
from dashboard.server import start_dashboard
from layers.data.database import init_db, save_signal, get_recent_trades, get_signal_prices
from layers.analysis.indicators import (
    calculate_macd,
    calculate_rsi,
    normalize_macd,
    normalize_rsi,
    calculate_ma_crossover,
    calculate_stoch_rsi,
    calculate_bollinger_bands,
)
from layers.analysis.regime import detect_regime
from layers.data.crypto_news import get_crypto_news
from layers.data.macro import get_macro_signal
from layers.data.news_sentiment import get_news_sentiment
from layers.data.fear_greed import get_fear_greed
from layers.data.polymarket import get_sol_sentiment
from layers.data.price_feed import get_sol_price, bootstrap_price_history
from layers.decision.signal_engine import generate_signal
from layers.execution.grid_bot import GridBot
from layers.execution.jupiter import buy_sol_with_usdc, sell_sol_for_usdc
from layers.execution.wallet import load_keypair
from layers.risk.risk_manager import RiskManager

DATA_JSON   = Path(__file__).parent / "data.json"
SELL_LOG    = Path(__file__).parent / "sell_signals.csv"
SOUL_FILE   = Path(__file__).parent / "soul.md"
MEMORY_FILE = Path(__file__).parent / "memory.md"
MAX_PRICE_HISTORY = 200


def log(msg: str = "") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")

_SELL_LOG_FIELDS = [
    "timestamp", "score", "price",
    "rsi", "macd_histogram", "news_normalized",
    "polymarket_sentiment", "macro_score", "regime",
]


def log_sell_signal(
    ts: datetime,
    score: float,
    price: float,
    rsi: float | None,
    macd_hist: float | None,
    news_normalized: float | None,
    polymarket: float | None,
    macro_score: float | None,
    regime: str,
) -> None:
    """Append one row to sell_signals.csv whenever score <= SELL_THRESHOLD."""
    write_header = not SELL_LOG.exists() or os.path.getsize(SELL_LOG) == 0
    with SELL_LOG.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SELL_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp":           ts.isoformat(),
            "score":               round(score, 6),
            "price":               price,
            "rsi":                 round(rsi, 4)            if rsi            is not None else "",
            "macd_histogram":      round(macd_hist, 6)      if macd_hist      is not None else "",
            "news_normalized":     round(news_normalized, 4) if news_normalized is not None else "",
            "polymarket_sentiment": round(polymarket, 4)    if polymarket     is not None else "",
            "macro_score":         round(macro_score, 4)    if macro_score    is not None else "",
            "regime":              regime,
        })


# ── State ─────────────────────────────────────────────────────────────────────

price_history: list[float] = []


def write_state(state: dict):
    try:
        DATA_JSON.write_text(json.dumps(state, indent=2, default=str))
    except Exception as exc:
        log(f"[Main] data.json write error: {exc}")


def append_memory_lesson(
    trade:       dict,
    exit_price:  float,
    regime:      str,
    rsi:         float | None,
    polymarket:  float | None,
    fg_raw:      int | None,
) -> str:
    """Append one trade lesson to memory.md. Returns the lesson line."""
    pnl = (trade.get("net_pnl") if trade.get("net_pnl") is not None else trade.get("pnl_usdc", 0)) or 0
    win       = pnl > 0
    direction = trade.get("direction", "long").upper()
    entry     = trade.get("entry_price", 0)
    outcome   = "WIN" if win else "LOSS"
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rsi_str = f"RSI={rsi:.1f}" if rsi is not None else "RSI=?"
    pm_str  = f"PM={polymarket:.2f}" if polymarket is not None else "PM=?"
    fg_str  = f"F&G={fg_raw}" if fg_raw is not None else "F&G=?"

    if win:
        lesson = (
            f"Signal confluence confirmed in {regime} regime; "
            f"entry at ${entry:.2f} rewarded."
        )
    else:
        lesson = (
            f"Stop triggered in {regime} regime from ${entry:.2f}; "
            f"await stronger signal alignment before next entry."
        )

    line = (
        f"- **{date_str}**: {direction} at ${entry:.2f} → {outcome} "
        f"(exit ${exit_price:.2f}, PnL ${pnl:+.2f}). "
        f"Signals: {rsi_str}, {pm_str}, {fg_str}. "
        f"Lesson: {lesson}"
    )
    try:
        with MEMORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        log(f"[Memory] {'✓ WIN' if win else '✗ LOSS'} lesson appended (PnL ${pnl:+.2f})")
    except Exception as exc:
        log(f"[Memory] Write error: {exc}")
    return line


def _memory_context(lessons: list[str]) -> str:
    """Return last 8 lessons formatted for LLM context."""
    if not lessons:
        return ""
    return "Recent trade lessons:\n" + "\n".join(lessons[-8:])


def run_weekly_reflection(memory_lessons: list[str]) -> None:
    """Call claude-sonnet-4-5 to analyse last 50 trades and append findings to memory.md."""
    try:
        from layers.data.database import get_recent_trades as _get_trades
        trades = _get_trades(50)
        if not trades:
            log("[Reflect] No trades to analyse yet.")
            return

        lines = []
        for t in trades:
            pnl = t.get("pnl_usdc", 0) or 0
            lines.append(
                f"  {t.get('direction','long').upper()} "
                f"entry=${t.get('entry_price',0):.2f} "
                f"exit=${t.get('exit_price',0):.2f} "
                f"pnl=${pnl:+.2f} "
                f"regime={t.get('regime','?')}"
            )
        trades_text = "\n".join(lines)

        prompt = (
            f"You are a quantitative trading analyst reviewing {len(trades)} recent SOL/USDC trades.\n\n"
            f"Trade history:\n{trades_text}\n\n"
            f"Analyse this data and answer:\n"
            f"1. Which market regime (trending/ranging/choppy/unknown) produced the best win rate?\n"
            f"2. What was the average PnL for winning vs losing trades?\n"
            f"3. Which signal context (direction of entry — long vs short) performed better?\n"
            f"4. What is the single most important lesson from this period?\n\n"
            f"Reply in 4 concise bullet points, one per question. Be specific with numbers."
        )

        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = msg.content[0].text.strip()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d UTC")

        lesson = (
            f"\n### Weekly Reflection — {date_str} ({len(trades)} trades analysed)\n"
            + "\n".join(f"  {l}" for l in analysis.splitlines())
            + "\n"
        )
        with MEMORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(lesson)
        memory_lessons.append(lesson.strip())
        log(f"[Reflect] Weekly Sonnet reflection appended to memory.md")
        log(f"[Reflect] {analysis[:120]}…")
    except Exception as exc:
        log(f"[Reflect] Error: {exc}")


def build_state(
    price: float,
    rsi: float | None,
    macd: float | None,
    macd_hist: float | None,
    pm: float | None,
    news: dict | None,
    macro: dict | None,
    fear_greed: dict | None,
    grid: "GridBot | None",
    signal_action: str,
    signal_score: float,
    risk: RiskManager,
    iteration: int,
    regime: dict | None = None,
    llm_reasoning: str = "",
    llm_used: bool = False,
    llm_source: str = "",
    news_sources_count: int = 0,
    top_headline: str = "",
    top_headline_source: str = "",
    ma_score: float | None = None,
    stoch_score: float | None = None,
    bb_score: float | None = None,
    ma_fast: float | None = None,
    ma_slow: float | None = None,
    stoch_k: float | None = None,
    stoch_d: float | None = None,
) -> dict:
    upnl = 0.0
    if risk.position and price:
        upnl = risk.position.unrealized_pnl(price)

    short_upnl = 0.0
    if risk.short_position and price:
        short_upnl = (risk.short_position.entry_price - price) * risk.short_position.sol_amount

    return {
        "timestamp":            datetime.now(timezone.utc).isoformat(),
        "price":                price,
        "rsi":                  rsi,
        "macd":                 macd,
        "macd_histogram":       macd_hist,
        "polymarket_sentiment": pm,
        "news_score":           news.get("score") if news else None,
        "news_normalized":      news.get("normalized") if news else None,
        "news_reason":          news.get("reason", "") if news else "",
        "news_headline_count":  news.get("headline_count", 0) if news else 0,
        "macro_score":          macro.get("macro_score") if macro else None,
        "btc_24h_change_pct":   macro.get("btc_24h_change_pct") if macro else None,
        "btc_dominance_pct":    macro.get("btc_dominance_pct") if macro else None,
        "ma_score":             ma_score,
        "stoch_score":          stoch_score,
        "bb_score":             bb_score,
        "ma_fast":              ma_fast,
        "ma_slow":              ma_slow,
        "stoch_k":              stoch_k,
        "stoch_d":              stoch_d,
        "fear_greed_score":     fear_greed.get("score") if fear_greed else None,
        "fear_greed_normalized": fear_greed.get("normalized") if fear_greed else None,
        "fear_greed_label":     fear_greed.get("label", "") if fear_greed else "",
        "grid":                 grid.get_state(price) if grid else None,
        "regime":               (regime or {}).get("regime", "unknown"),
        "regime_adx":           (regime or {}).get("adx"),
        "regime_atr":           (regime or {}).get("atr"),
        "signal":               signal_action,
        "signal_score":         signal_score,
        "llm_reasoning":        llm_reasoning,
        "llm_used":             llm_used,
        "llm_source":           llm_source,
        "news_sources_count":   news_sources_count,
        "top_headline":         top_headline,
        "top_headline_source":  top_headline_source,
        "portfolio_value":      risk.portfolio_value(price),
        "initial_capital":      risk.initial_capital,
        "realized_pnl":         risk.realized_pnl,
        "unrealized_pnl":       upnl + short_upnl,
        "total_pnl":            risk.realized_pnl + upnl + short_upnl,
        "position": {
            "entry_price": risk.position.entry_price,
            "size_usdc":   risk.position.size_usdc,
            "sol_amount":  risk.position.sol_amount,
        } if risk.position else None,
        "short_position": {
            "entry_price":    risk.short_position.entry_price,
            "size_usdc":      risk.short_position.size_usdc,
            "sol_amount":     risk.short_position.sol_amount,
            "unrealized_pnl": round(short_upnl, 4),
        } if risk.short_position else None,
        "trades":               risk.trades[-20:],
        "price_history":        price_history[-100:],
        "dry_run":              config.DRY_RUN,
        "iteration":            iteration,
    }


# ── Wallet setup ──────────────────────────────────────────────────────────────

def setup_keypair():
    if config.DRY_RUN:
        return None  # wallet not needed in paper mode

    if not config.WALLET_PRIVATE_KEY_ENCRYPTED or not config.WALLET_ENCRYPTION_KEY:
        print(
            "[Main] LIVE mode requires WALLET_PRIVATE_KEY_ENCRYPTED and "
            "WALLET_ENCRYPTION_KEY in .env\n"
            "       Run: python generate_wallet.py"
        )
        sys.exit(1)

    kp = load_keypair(config.WALLET_PRIVATE_KEY_ENCRYPTED, config.WALLET_ENCRYPTION_KEY)
    if not kp:
        print("[Main] Failed to decrypt wallet. Check .env values.")
        sys.exit(1)

    print(f"[Wallet] Public key: {kp.pubkey()}")
    return kp


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    banner = "PAPER TRADING (DRY_RUN)" if config.DRY_RUN else "⚡ LIVE TRADING"
    print(f"\n{'═'*60}")
    print(f"  SOL/USDC TRADING BOT  –  {banner}")
    print(f"  Interval : {config.LOOP_INTERVAL_SECONDS}s")
    print(f"  Capital  : ${config.INITIAL_CAPITAL_USDC:.2f} USDC")
    print(f"  Buy ≥    : {config.BUY_THRESHOLD}  |  Sell ≤ : {config.SELL_THRESHOLD}")
    print(f"{'═'*60}\n")

    # Load agent soul
    soul = ""
    if SOUL_FILE.exists():
        soul = SOUL_FILE.read_text(encoding="utf-8")
        mission_line = next(
            (l.strip() for l in soul.splitlines() if l.startswith("Protect")), ""
        )
        log(f"[Soul] Loaded — Mission: {mission_line}")
    else:
        log("[Soul] Warning: soul.md not found — agent running without identity")

    # Load agent memory (Trade Lessons section)
    memory_lessons: list[str] = []
    if MEMORY_FILE.exists():
        try:
            mem_content = MEMORY_FILE.read_text(encoding="utf-8")
            if "## Trade Lessons" in mem_content:
                section = mem_content.split("## Trade Lessons")[1]
                memory_lessons = [
                    l.strip() for l in section.splitlines()
                    if l.strip().startswith("-")
                ]
            log(f"[Memory] Loaded: {len(memory_lessons)} trade lesson(s)")
        except Exception as exc:
            log(f"[Memory] Load error: {exc}")
    else:
        log("[Memory] Warning: memory.md not found")

    keypair  = setup_keypair()
    telegram = TelegramAlerter(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    # Split capital 50/50: signal bot gets half, grid bot gets half
    signal_capital = config.INITIAL_CAPITAL_USDC / 2
    grid_capital   = config.INITIAL_CAPITAL_USDC / 2
    risk = RiskManager(initial_capital_usdc=signal_capital)

    init_db()
    saved = get_recent_trades(100)
    if saved:
        risk.trades.extend(saved)
        risk.realized_pnl = sum(
            (t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl_usdc", 0)) or 0
            for t in saved
        )
        log(f"[DB] Loaded {len(saved)} historical trades (realized PnL ${risk.realized_pnl:+.2f})")

    start_dashboard(config.DASHBOARD_PORT)
    telegram.send_startup(config.DRY_RUN, config.LOOP_INTERVAL_SECONDS, config.INITIAL_CAPITAL_USDC)

    # Restore price history from DB; fall back to CoinGecko bootstrap only if needed
    _24H = 86_400
    log("[Main] Restoring price history…")
    try:
        db_prices = get_signal_prices(200)
    except Exception as exc:
        log(f"[PriceRestore] DB query failed: {exc} — will bootstrap")
        db_prices = []

    if db_prices:
        oldest_ts, newest_ts = db_prices[0][0], db_prices[-1][0]
        span_s = newest_ts - oldest_ts
        span_h = span_s / 3600

        if span_h <= 24:
            price_history.extend(p for _, p in db_prices)
            log(
                f"[PriceRestore] Loaded {len(price_history)} prices from DB "
                f"spanning {span_h:.1f}h — bootstrap skipped"
            )
        else:
            cutoff = time.time() - _24H
            recent = [(ts, p) for ts, p in db_prices if ts >= cutoff]
            price_history.extend(p for _, p in recent)
            log(
                f"[PriceRestore] {len(db_prices)} DB rows span {span_h:.1f}h "
                f"(gap detected) — loaded {len(price_history)} prices from last 24h"
            )
    else:
        log("[PriceRestore] No prices in DB")

    if len(price_history) < 60:
        before = len(price_history)
        price_history.extend(bootstrap_price_history(target_len=60))
        if len(price_history) > MAX_PRICE_HISTORY:
            price_history[:] = price_history[-MAX_PRICE_HISTORY:]
        log(
            f"[PriceRestore] Topped up {before} → {len(price_history)} prices "
            f"via CoinGecko bootstrap"
        )
    else:
        if len(price_history) > MAX_PRICE_HISTORY:
            price_history[:] = price_history[-MAX_PRICE_HISTORY:]
        log(f"[PriceRestore] Ready: {len(price_history)} prices — no bootstrap needed")

    # Grid bot — initialized lazily on first price tick
    grid: GridBot | None = None

    running   = True
    iteration = 0

    def _shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    pnl_report_every = max(1, 3600 // config.LOOP_INTERVAL_SECONDS)  # ~hourly

    while running:
        iteration += 1
        now = datetime.now(timezone.utc)
        print()
        log(f"── Iteration #{iteration} ──────────")

        try:
            # ── 1. Price ──────────────────────────────────────────────────
            price = get_sol_price(use_cache=False)
            if price is None:
                log("[Main] Price unavailable – skipping iteration.")
                time.sleep(30)
                continue

            price_history.append(price)
            if len(price_history) > MAX_PRICE_HISTORY:
                price_history.pop(0)
            log(f"  Price   : ${price:,.4f}")

            # ── 2. Polymarket ─────────────────────────────────────────────
            pm_sentiment = get_sol_sentiment()
            log(f"  Polym.  : {pm_sentiment:.3f}")

            # ── 3. News sentiment (VADER local NLP, 30-min cache) ────────
            news = get_news_sentiment(config.NEWSAPI_KEY)
            cached_tag = " (cached)" if news.get("cached") else f" [{news.get('headline_count', 0)} headlines]"
            log(f"  News    : {news['score']:+.3f} → norm={news['normalized']:.3f}{cached_tag} | '{news['reason']}'")

            # ── 4. Macro BTC signals (2-min cache) ────────────────────────
            macro = get_macro_signal()

            # ── 4a. Multi-source crypto news (15-min cache) ───────────────
            crypto_news = get_crypto_news()
            top_hl      = crypto_news["top_headlines"][0] if crypto_news.get("top_headlines") else {}
            top_headline = top_hl.get("title", "")
            if top_headline:
                log(f"  TopNews : [{top_hl.get('source','')}] {top_headline[:70]}")

            # ── 4c. Fear & Greed Index (30-min cache) ─────────────────────
            fear_greed = get_fear_greed()
            fg_tag = " (cached)" if fear_greed.get("cached") else ""
            log(f"  F&G     : {fear_greed['score']} ({fear_greed['label']}) → norm={fear_greed['normalized']:.3f}{fg_tag}")

            # ── 4d. Grid bot: initialize on first tick, then update ────────
            if grid is None:
                if config.GRID_LOW_PRICE is not None and config.GRID_HIGH_PRICE is not None:
                    g_low  = config.GRID_LOW_PRICE
                    g_high = config.GRID_HIGH_PRICE
                else:
                    hist = price_history if len(price_history) >= 5 else []
                    if hist:
                        g_low  = min(hist) * 0.99
                        g_high = max(hist) * 1.01
                    else:
                        g_low  = price * 0.95
                        g_high = price * 1.05
                grid = GridBot(grid_capital, g_low, g_high, num_levels=config.GRID_NUM_LEVELS)
                log(f"  [Grid] Init range=${g_low:.2f}–${g_high:.2f} | capital=${grid_capital:.2f}")
            grid.update(price)


            # ── 5. Technical indicators ───────────────────────────────────
            rsi = calculate_rsi(price_history, config.RSI_PERIOD)
            macd_line, sig_line, hist = calculate_macd(
                price_history, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL_PERIOD
            )

            rsi_score  = normalize_rsi(rsi, config.RSI_OVERSOLD, config.RSI_OVERBOUGHT) if rsi  is not None else None
            macd_score = normalize_macd(hist) if hist is not None else None

            rsi_str  = f"{rsi:.1f}"  if rsi       is not None else "warming up"
            macd_str = f"{macd_line:.4f}" if macd_line is not None else "warming up"
            hist_str = f"{hist:.4f}" if hist       is not None else "—"
            log(f"  RSI     : {rsi_str}  |  MACD: {macd_str}  |  hist: {hist_str}")

            # ── 5b. Additional technical indicators ───────────────────────
            ma_fast_val, ma_slow_val, ma_score_val = calculate_ma_crossover(price_history)
            stoch_k_val, stoch_d_val, stoch_score_val = calculate_stoch_rsi(price_history)
            bb_upper_val, _bb_mid, bb_lower_val, bb_score_val = calculate_bollinger_bands(price_history)

            ma_str    = f"MA50={ma_fast_val:.2f}/MA200={ma_slow_val:.2f}" if ma_score_val is not None else "warming up"
            stoch_str = f"{stoch_k_val:.1f}" if stoch_k_val is not None else "—"
            bb_str    = f"{bb_score_val:.3f}" if bb_score_val is not None else "—"
            log(f"  MA/Stch : {ma_str}  StochK={stoch_str}  BB={bb_str}")

            # ── 5b. Regime detection (observation only) ───────────────────
            regime_info = detect_regime(price_history)
            r = regime_info["regime"]
            adx_str = f"{regime_info['adx']:.1f}" if regime_info["adx"] is not None else "—"
            atr_str = f"{regime_info['atr']:.4f}" if regime_info["atr"] is not None else "—"
            atr_up  = "↑" if regime_info["atr_trending_up"] else "→"
            log(f"  Regime  : {r.upper()} (ADX={adx_str}  ATR={atr_str}{atr_up})")

            # ── 6. Signal ─────────────────────────────────────────────────
            sig = generate_signal(
                rsi_score, macd_score, pm_sentiment,
                news.get("normalized"), macro.get("macro_score"),
                ma_score=ma_score_val,
                stoch_score=stoch_score_val,
                bb_score=bb_score_val,
                rsi_raw=rsi, macd_raw=macd_line,
                macd_signal_raw=sig_line, macd_hist_raw=hist,
                news_reason=news.get("reason", ""),
                ma_fast=ma_fast_val,
                ma_slow=ma_slow_val,
                stoch_k=stoch_k_val,
                stoch_d=stoch_d_val,
                bb_upper=bb_upper_val,
                bb_lower=bb_lower_val,
                fear_greed_score=fear_greed.get("normalized"),
                fear_greed_raw=fear_greed.get("score"),
                fear_greed_label=fear_greed.get("label", ""),
                price=price,
                regime=regime_info.get("regime", "unknown"),
                recent_trades=get_recent_trades(5),
                top_headline=top_headline,
                agent_memory=_memory_context(memory_lessons),
                agent_soul=soul,
            )
            log(f"  Signal  : {sig.action} ({sig.score:.3f}) | {sig.reason}")

            # ── 6a. Apply any LLM self-tune directives ────────────────────
            if sig.reasoning:
                from layers.decision.parameter_tuner import parse_tune_directives, update_parameter
                for t_key, t_val, t_reason in parse_tune_directives(sig.reasoning):
                    ok, msg = update_parameter(t_key, t_val, t_reason)
                    log(f"  [Tuner] {msg}")

            # ── 6c. Persist signal to DB ──────────────────────────────────
            try:
                save_signal(
                    timestamp=now.timestamp(),
                    signal=sig.action,
                    score=sig.score,
                    rsi=rsi,
                    macd=macd_line,
                    polymarket=pm_sentiment,
                    news=news.get("normalized"),
                    macro=macro.get("macro_score"),
                    fear_greed=fear_greed.get("normalized"),
                    regime=regime_info["regime"],
                    price=price,
                    llm_reasoning=sig.reasoning,
                    ma_score=ma_score_val,
                    stoch_score=stoch_score_val,
                    bb_score=bb_score_val,
                )
            except Exception:
                pass

            # ── 6b. SELL signal observation log ───────────────────────────
            if sig.score <= config.SELL_THRESHOLD:
                log_sell_signal(
                    ts=now,
                    score=sig.score,
                    price=price,
                    rsi=rsi,
                    macd_hist=hist,
                    news_normalized=news.get("normalized"),
                    polymarket=pm_sentiment,
                    macro_score=macro.get("macro_score"),
                    regime=regime_info["regime"],
                )
                log(f"  [SellLog] score={sig.score:.4f} → logged to sell_signals.csv")

            # ── 7. Stop-loss / Take-profit checks (long + short) ─────────
            long_exit  = risk.check_sl_tp(price, regime=regime_info["regime"])
            short_exit = risk.check_short_sl_tp(price, regime=regime_info["regime"])

            if long_exit and risk.position:
                trade = risk.close_position(price)
                trade["regime"] = regime_info["regime"]
                risk.last_trade_tick      = iteration
                risk.last_trade_direction = "long"
                pnl = trade["net_pnl"]
                log(f"  {long_exit} triggered (LONG) | gross ${trade['gross_pnl']:+.2f} fee ${trade['fee_usdc']:.4f} net ${pnl:+.2f}")
                memory_lessons.append(append_memory_lesson(
                    trade, price, regime_info["regime"], rsi, pm_sentiment, fear_greed.get("score")
                ))

                if not config.DRY_RUN and keypair:
                    sell_sol_for_usdc(
                        trade["sol_amount"], keypair,
                        config.SOLANA_RPC_URL, dry_run=False,
                    )
                telegram.send_trade(long_exit, price, trade["size_usdc"],
                                    pnl=pnl, dry_run=config.DRY_RUN)

            elif short_exit and risk.short_position:
                trade = risk.close_short_position(price)
                trade["regime"] = regime_info["regime"]
                risk.last_trade_tick      = iteration
                risk.last_trade_direction = "short"
                pnl = trade["net_pnl"]
                log(f"  {short_exit} triggered (SHORT) | gross ${trade['gross_pnl']:+.2f} fee ${trade['fee_usdc']:.4f} net ${pnl:+.2f}")
                memory_lessons.append(append_memory_lesson(
                    trade, price, regime_info["regime"], rsi, pm_sentiment, fear_greed.get("score")
                ))
                telegram.send_trade(short_exit, price, trade["size_usdc"],
                                    pnl=pnl, dry_run=config.DRY_RUN)

            # ── 8. Signal-driven trades ───────────────────────────────────
            elif sig.action == "BUY":
                if risk.short_position:
                    # Cover the short on a BUY signal
                    trade = risk.close_short_position(price)
                    trade["regime"] = regime_info["regime"]
                    risk.last_trade_tick      = iteration
                    risk.last_trade_direction = "short"
                    pnl = trade["net_pnl"]
                    log(f"  Covering SHORT @ ${price} | gross ${trade['gross_pnl']:+.2f} fee ${trade['fee_usdc']:.4f} net ${pnl:+.2f}")
                    memory_lessons.append(append_memory_lesson(
                        trade, price, regime_info["regime"], rsi, pm_sentiment, fear_greed.get("score")
                    ))
                    telegram.send_trade("COVER", price, trade["size_usdc"],
                                        pnl=pnl, dry_run=config.DRY_RUN)
                else:
                    if sig.score < config.BUY_THRESHOLD:
                        log(
                            f"[CONSENSUS_BLOCK] LLM=BUY composite={sig.score:.3f} "
                            f"< BUY_THRESHOLD={config.BUY_THRESHOLD} — no LONG opened"
                        )
                    else:
                        check = risk.check_trade(
                            "BUY", price, config.TRADE_AMOUNT_USDC,
                            current_tick=iteration,
                            regime=regime_info.get("regime", "unknown"),
                            macro_score=sig.macro_score,
                        )
                        if check.approved:
                            log(f"  Executing BUY  size=${check.adjusted_size_usdc:.2f} USDC")
                            if not config.DRY_RUN and keypair:
                                result = buy_sol_with_usdc(
                                    check.adjusted_size_usdc, keypair,
                                    config.SOLANA_RPC_URL, dry_run=False,
                                )
                                if result["success"]:
                                    risk.open_position(price, check.adjusted_size_usdc)
                                    telegram.send_trade("BUY", price, check.adjusted_size_usdc,
                                                        dry_run=False, reason=sig.reason)
                                    log(f"  TX: {result['tx_signature']}")
                                else:
                                    log(f"  BUY failed: {result.get('error')}")
                            else:
                                risk.open_position(price, check.adjusted_size_usdc)
                                telegram.send_trade("BUY", price, check.adjusted_size_usdc,
                                                    dry_run=True, reason=sig.reason)
                        elif check.reason.startswith("RULE_VETO:"):
                            log(
                                f"[RULE_VETO] LONG blocked | regime={regime_info.get('regime')} "
                                f"macro={sig.macro_score:.3f} composite={sig.score:.3f} "
                                f"LLM={sig.action}"
                            )
                        else:
                            log(f"  BUY blocked: {check.reason}")

            elif sig.action == "SELL":
                if risk.position:
                    # Close long position
                    check = risk.check_trade("SELL", price, 0.0)
                    if check.approved:
                        trade = risk.close_position(price)
                        trade["regime"] = regime_info["regime"]
                        risk.last_trade_tick      = iteration
                        risk.last_trade_direction = "long"
                        pnl = trade["net_pnl"]
                        log(f"  Executing SELL | gross ${trade['gross_pnl']:+.2f} fee ${trade['fee_usdc']:.4f} net ${pnl:+.2f}")
                        memory_lessons.append(append_memory_lesson(
                            trade, price, regime_info["regime"], rsi, pm_sentiment, fear_greed.get("score")
                        ))
                        if not config.DRY_RUN and keypair:
                            sell_sol_for_usdc(
                                trade["sol_amount"], keypair,
                                config.SOLANA_RPC_URL, dry_run=False,
                            )
                        telegram.send_trade("SELL", price, trade["size_usdc"],
                                            pnl=pnl, dry_run=config.DRY_RUN,
                                            reason=sig.reason)
                    else:
                        log(f"  SELL blocked: {check.reason}")

                elif config.DRY_RUN and not risk.short_position:
                    # Open simulated short (paper trading only)
                    if sig.score > config.SELL_THRESHOLD:
                        log(
                            f"[CONSENSUS_BLOCK] LLM=SELL composite={sig.score:.3f} "
                            f"> SELL_THRESHOLD={config.SELL_THRESHOLD} — no SHORT opened"
                        )
                    else:
                        check = risk.check_trade("SHORT", price, config.TRADE_AMOUNT_USDC,
                                                 current_tick=iteration)
                        if check.approved:
                            risk.open_short_position(price, check.adjusted_size_usdc)
                            log(f"  Opening SHORT @ ${price} | size=${check.adjusted_size_usdc:.2f} USDC"
                                  f" | TP={config.SHORT_TAKE_PROFIT_PCT:.1%} SL={config.SHORT_STOP_LOSS_PCT:.1%}")
                            telegram.send_trade("SHORT", price, check.adjusted_size_usdc,
                                                dry_run=True, reason=sig.reason)
                        else:
                            log(f"  SHORT blocked: {check.reason}")

            # ── 9. Portfolio summary ──────────────────────────────────────
            upnl       = risk.position.unrealized_pnl(price) if risk.position else 0.0
            short_upnl = ((risk.short_position.entry_price - price)
                          * risk.short_position.sol_amount) if risk.short_position else 0.0
            pv = risk.portfolio_value(price)
            pos_str = ""
            if risk.position:
                pos_str = f"  LONG uPnL ${upnl:+.2f}"
            elif risk.short_position:
                pos_str = f"  SHORT uPnL ${short_upnl:+.2f}"
            log(f"  Portfolio: ${pv:.2f}  realized ${risk.realized_pnl:+.2f}{pos_str}")

            # ── 10. Dashboard data ────────────────────────────────────────
            write_state(build_state(
                price, rsi, macd_line, hist, pm_sentiment,
                news, macro, fear_greed, grid,
                sig.action, sig.score, risk, iteration,
                regime=regime_info,
                llm_reasoning=sig.reasoning,
                llm_used=sig.llm_used,
                llm_source=sig.llm_source,
                news_sources_count=crypto_news.get("sources_count", 0),
                top_headline=top_headline,
                top_headline_source=top_hl.get("source", ""),
                ma_score=ma_score_val,
                stoch_score=stoch_score_val,
                bb_score=bb_score_val,
                ma_fast=ma_fast_val,
                ma_slow=ma_slow_val,
                stoch_k=stoch_k_val,
                stoch_d=stoch_d_val,
            ))

            # ── 11. Hourly PnL report ─────────────────────────────────────
            if iteration % pnl_report_every == 0:
                telegram.send_pnl_report(
                    portfolio_value=pv,
                    realized_pnl=risk.realized_pnl,
                    unrealized_pnl=upnl,
                    initial_capital=risk.initial_capital,
                    trade_count=len(risk.trades),
                    win_rate=risk.win_rate,
                )

            # ── 12. Weekly Sonnet reflection (every 2016 ticks ≈ 7 days) ──
            if iteration % 2016 == 0:
                run_weekly_reflection(memory_lessons)

        except Exception as exc:
            log(f"[Main] Unhandled error: {exc}")
            telegram.send_alert(str(exc), level="ERROR")

        if running:
            log(f"  Sleeping {config.LOOP_INTERVAL_SECONDS}s…")
            time.sleep(config.LOOP_INTERVAL_SECONDS)

    # ── Shutdown ──────────────────────────────────────────────────────────
    current_price = get_sol_price() or 0.0
    upnl = risk.position.unrealized_pnl(current_price) if risk.position else 0.0
    pv   = risk.portfolio_value(current_price)
    telegram.send_shutdown(pv, risk.realized_pnl + upnl, len(risk.trades))
    log("[Main] Stopped cleanly.")


# ── CLI dispatch ──────────────────────────────────────────────────────────────

def cmd_backtest(argv: list[str]):
    from backtesting.data_loader import fetch_historical_ohlcv, fetch_market_chart
    from backtesting.engine import run_backtest

    idx = argv.index("--backtest")
    days = int(argv[idx + 1]) if len(argv) > idx + 1 and argv[idx + 1].isdigit() else 90

    candles = fetch_historical_ohlcv(days=days)

    # CoinGecko free OHLC returns sparse weekly bars for long ranges —
    # fall back to daily market_chart data when we don't have enough candles.
    if len(candles) < config.MIN_CANDLES_REQUIRED:
        print(
            f"[Backtest] Only {len(candles)} OHLCV candles received "
            f"(need {config.MIN_CANDLES_REQUIRED}). "
            f"Falling back to daily market_chart endpoint…"
        )
        candles = fetch_market_chart(days=days)

    if not candles:
        print("[Backtest] No data received.")
        sys.exit(1)

    run_backtest(candles, initial_capital=config.INITIAL_CAPITAL_USDC)


def cmd_generate_wallet():
    from layers.execution.wallet import generate_wallet
    pub, enc, key = generate_wallet()
    print("\nNew Solana wallet generated.")
    print(f"Public key: {pub}")
    print(f"\nAdd these to your .env file:")
    print(f"  WALLET_PUBLIC_KEY={pub}")
    print(f"  WALLET_PRIVATE_KEY_ENCRYPTED={enc}")
    print(f"  WALLET_ENCRYPTION_KEY={key}")
    print("\nKeep WALLET_ENCRYPTION_KEY secret – without it your funds are unrecoverable!")


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        cmd_backtest(sys.argv)
    elif "--generate-wallet" in sys.argv:
        cmd_generate_wallet()
    else:
        run()

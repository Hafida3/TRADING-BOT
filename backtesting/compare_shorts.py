#!/usr/bin/env python3
"""
365-day comparison backtest: long-only vs long+short vs buy-and-hold.

Signals use RSI + MACD only (weights redistribute 50/50) because
news/polymarket/macro data is unavailable in backtest. Both strategies
use identical signal logic so the short-side delta is isolated cleanly.

Short mechanics
───────────────
  Entry  : score <= SELL_THRESHOLD (0.38) and position is flat
  TP     : price drops >= TAKE_PROFIT_PCT  (6%) from entry
  SL     : price rises >= STOP_LOSS_PCT    (3%) from entry
  Size   : TRADE_AMOUNT_USDC ($10) per trade
  SL/TP  : checked against candle high/low when available (realistic),
           worst-case tie-break → SL

Usage
─────
  python -m backtesting.compare_shorts          # 365 days
  python -m backtesting.compare_shorts --days 180
"""

from __future__ import annotations

import math
import statistics
import sys
from datetime import datetime

import config
from backtesting.data_loader import fetch_historical_ohlcv, fetch_market_chart
from layers.analysis.indicators import (
    calculate_macd,
    calculate_rsi,
    normalize_macd,
    normalize_rsi,
)
from layers.decision.signal_engine import generate_signal


def _date(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")


# ── Core simulation ────────────────────────────────────────────────────────────

def _run_sim(
    candles: list[dict],
    *,
    allow_shorts: bool,
    initial_capital: float,
    trade_size: float,
    buy_thresh: float,
    sell_thresh: float,
    tp_pct: float,
    sl_pct: float,
) -> dict:
    """
    Replay candles with long-only or long+short logic.
    Returns a stats dict with the same shape for both modes.
    """
    free_usdc = initial_capital
    position: dict | None = None   # {"side", "entry_price", "sol_amount", "size_usdc"}
    trades: list[dict]    = []
    equity: list[float]   = []     # portfolio value at each candle close
    closes: list[float]   = []

    # ── Portfolio value (mark-to-market) ──────────────────────────────
    def pv(price: float) -> float:
        if position is None:
            return free_usdc
        if position["side"] == "long":
            return free_usdc + position["sol_amount"] * price
        # short: margin was deducted; unrealised PnL = (entry - current) * sol_amount
        float_pnl = (position["entry_price"] - price) * position["sol_amount"]
        return free_usdc + position["size_usdc"] + float_pnl

    # ── Close helpers ──────────────────────────────────────────────────
    def close_long(exit_price: float, reason: str) -> None:
        nonlocal free_usdc, position
        pos       = position
        proceeds  = pos["sol_amount"] * exit_price
        pnl       = proceeds - pos["size_usdc"]
        free_usdc += proceeds
        trades.append({
            "side":        "long",
            "entry_price": pos["entry_price"],
            "exit_price":  exit_price,
            "size_usdc":   pos["size_usdc"],
            "pnl_usdc":    round(pnl, 4),
            "pnl_pct":     round(pnl / pos["size_usdc"], 6),
            "reason":      reason,
        })
        position = None

    def close_short(exit_price: float, reason: str) -> None:
        nonlocal free_usdc, position
        pos       = position
        float_pnl = (pos["entry_price"] - exit_price) * pos["sol_amount"]
        free_usdc += pos["size_usdc"] + float_pnl
        trades.append({
            "side":        "short",
            "entry_price": pos["entry_price"],
            "exit_price":  exit_price,
            "size_usdc":   pos["size_usdc"],
            "pnl_usdc":    round(float_pnl, 4),
            "pnl_pct":     round(float_pnl / pos["size_usdc"], 6),
            "reason":      reason,
        })
        position = None

    # ── Main replay loop ───────────────────────────────────────────────
    for candle in candles:
        close = candle["close"]
        hi    = candle.get("high", close)
        lo    = candle.get("low",  close)
        ts    = candle["timestamp"]
        closes.append(close)

        if len(closes) < config.MIN_CANDLES_REQUIRED:
            equity.append(pv(close))
            continue

        rsi                 = calculate_rsi(closes, config.RSI_PERIOD)
        macd, sig_ln, hist  = calculate_macd(
            closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL_PERIOD
        )
        rsi_score  = normalize_rsi(rsi, config.RSI_OVERSOLD, config.RSI_OVERBOUGHT) if rsi  is not None else None
        macd_score = normalize_macd(hist) if hist is not None else None

        signal = generate_signal(
            rsi_score, macd_score, None, None, None,
            rsi_raw=rsi, macd_raw=macd,
            macd_signal_raw=sig_ln, macd_hist_raw=hist,
        )

        # ── SL / TP on open position ───────────────────────────────────
        if position is not None:
            if position["side"] == "long":
                tp_px = position["entry_price"] * (1.0 + tp_pct)
                sl_px = position["entry_price"] * (1.0 - sl_pct)
                if lo <= sl_px and hi >= tp_px:
                    close_long(sl_px, "STOP_LOSS")         # worst-case tie
                elif hi >= tp_px:
                    close_long(tp_px, "TAKE_PROFIT")
                elif lo <= sl_px:
                    close_long(sl_px, "STOP_LOSS")
                elif signal.action == "SELL":
                    close_long(close, "SELL_SIGNAL")

            else:  # short
                tp_px = position["entry_price"] * (1.0 - tp_pct)  # price fell 6%
                sl_px = position["entry_price"] * (1.0 + sl_pct)  # price rose 3%
                if hi >= sl_px and lo <= tp_px:
                    close_short(sl_px, "STOP_LOSS")        # worst-case tie
                elif lo <= tp_px:
                    close_short(tp_px, "TAKE_PROFIT")
                elif hi >= sl_px:
                    close_short(sl_px, "STOP_LOSS")
                elif signal.action == "BUY":
                    close_short(close, "BUY_SIGNAL")

        # ── Open new position if flat ──────────────────────────────────
        if position is None and free_usdc >= trade_size * 0.99:
            size = min(trade_size, free_usdc)
            if signal.action == "BUY":
                free_usdc -= size
                position = {
                    "side":        "long",
                    "entry_price": close,
                    "sol_amount":  size / close,
                    "size_usdc":   size,
                }
            elif allow_shorts and signal.action == "SELL":
                free_usdc -= size          # deduct as margin
                position = {
                    "side":        "short",
                    "entry_price": close,
                    "sol_amount":  size / close,
                    "size_usdc":   size,
                }

        equity.append(pv(close))

    # Force-close any open position at the final bar
    if position is not None:
        final_price = candles[-1]["close"]
        if position["side"] == "long":
            close_long(final_price, "END")
        else:
            close_short(final_price, "END")
        equity[-1] = pv(final_price)

    # ── Statistics ────────────────────────────────────────────────────
    final_val = equity[-1] if equity else initial_capital

    # Max drawdown from full equity curve (more accurate than trade-only)
    peak   = initial_capital
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Annualised Sharpe from daily equity returns
    if len(equity) > 2:
        rets   = [(equity[i] - equity[i-1]) / equity[i-1] for i in range(1, len(equity))]
        mu     = statistics.mean(rets)
        sigma  = statistics.stdev(rets) or 1e-9
        sharpe = (mu / sigma) * math.sqrt(252)
    else:
        sharpe = 0.0

    n       = len(trades)
    wins    = [t for t in trades if t["pnl_usdc"] > 0]
    losses  = [t for t in trades if t["pnl_usdc"] <= 0]
    avg_win = sum(t["pnl_usdc"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_los = sum(t["pnl_usdc"] for t in losses) / len(losses) if losses else 0.0
    pf      = abs(avg_win / avg_los) if avg_los else float("inf")

    return {
        "final_value":   final_val,
        "total_pnl":     final_val - initial_capital,
        "total_pnl_pct": (final_val - initial_capital) / initial_capital,
        "n_trades":      n,
        "n_long":        sum(1 for t in trades if t["side"] == "long"),
        "n_short":       sum(1 for t in trades if t["side"] == "short"),
        "win_rate":      len(wins) / n if n else 0.0,
        "avg_win_usdc":  avg_win,
        "avg_loss_usdc": avg_los,
        "profit_factor": pf,
        "max_drawdown":  max_dd,
        "sharpe_ratio":  sharpe,
        "trades":        trades,
    }


# ── Comparison runner ──────────────────────────────────────────────────────────

def run_comparison(days: int = 365) -> None:
    candles = fetch_historical_ohlcv(days=days)
    if len(candles) < config.MIN_CANDLES_REQUIRED:
        print(f"[Compare] OHLCV sparse ({len(candles)} candles), falling back to market_chart…")
        candles = fetch_market_chart(days=days)

    if not candles:
        print("[Compare] No data received. Aborting.")
        return

    bh_entry  = candles[0]["close"]
    bh_exit   = candles[-1]["close"]
    bh_ret    = (bh_exit - bh_entry) / bh_entry
    bh_pnl    = config.INITIAL_CAPITAL_USDC * bh_ret

    SEP  = "═" * 64
    SEP2 = "─" * 64

    print(f"\n{SEP}")
    print(f"  SHORTS COMPARISON BACKTEST  —  {days} days")
    print(f"  Candles : {len(candles)}   Capital : ${config.INITIAL_CAPITAL_USDC:.2f} USDC")
    print(f"  Period  : {_date(candles[0]['timestamp'])} → {_date(candles[-1]['timestamp'])}")
    print(f"  Config  : BUY≥{config.BUY_THRESHOLD}  SELL≤{config.SELL_THRESHOLD}  "
          f"TP={config.TAKE_PROFIT_PCT:.0%}  SL={config.STOP_LOSS_PCT:.0%}  "
          f"Size=${config.TRADE_AMOUNT_USDC:.0f}")
    print(f"  Signals : RSI + MACD only (50/50 weight — news/poly/macro unavailable)")
    print(SEP)

    sim_kwargs = dict(
        initial_capital=config.INITIAL_CAPITAL_USDC,
        trade_size=config.TRADE_AMOUNT_USDC,
        buy_thresh=config.BUY_THRESHOLD,
        sell_thresh=config.SELL_THRESHOLD,
        tp_pct=config.TAKE_PROFIT_PCT,
        sl_pct=config.STOP_LOSS_PCT,
    )

    print("\n  [1/2] Simulating long-only…")
    lo = _run_sim(candles, allow_shorts=False, **sim_kwargs)
    print("  [2/2] Simulating long + short…")
    ls = _run_sim(candles, allow_shorts=True,  **sim_kwargs)
    print()

    # ── Trade logs ────────────────────────────────────────────────────
    for label, results in [
        ("LONG ONLY  — trade log", lo),
        ("LONG+SHORT — trade log", ls),
    ]:
        print(f"  {SEP2[2:]}")
        print(f"  {label}")
        print(f"  {SEP2[2:]}")
        if not results["trades"]:
            print("  (no trades)")
        for t in results["trades"]:
            mark = "✅" if t["pnl_usdc"] > 0 else "❌"
            side = t["side"].upper()
            print(
                f"  {side:5s}  "
                f"${t['entry_price']:>8.2f} → ${t['exit_price']:>8.2f}  "
                f"PnL {mark} ${t['pnl_usdc']:>+6.3f} ({t['pnl_pct']:>+.1%})"
                f"  [{t['reason']}]"
            )
        print()

    # ── Side-by-side summary table ────────────────────────────────────
    C = 20   # column width

    def row(label: str, lo_v, ls_v, fmt: str) -> None:
        print(f"  {label:<26} {fmt.format(lo_v):>{C}} {fmt.format(ls_v):>{C}}")

    print(SEP)
    print("  SIDE-BY-SIDE SUMMARY")
    print(SEP2)
    print(f"  {'':26} {'LONG ONLY':>{C}} {'LONG+SHORT':>{C}}")
    print(SEP2)

    row("Final portfolio value",  lo["final_value"],   ls["final_value"],   "${:,.4f}")
    row("Strategy return",        lo["total_pnl_pct"], ls["total_pnl_pct"], "{:+.2%}")
    row("Strategy PnL",           lo["total_pnl"],     ls["total_pnl"],     "${:+.4f}")

    bh_str = f"{bh_ret:+.2%} (${bh_pnl:+.2f})"
    print(f"  {'Buy & hold (reference)':<26} {'─':>{C}} {bh_str:>{C}}")
    print(SEP2)

    row("Total trades",           lo["n_trades"],      ls["n_trades"],      "{:d}")
    row("  └ Long trades",        lo["n_long"],        ls["n_long"],        "{:d}")
    row("  └ Short trades",       lo["n_short"],       ls["n_short"],       "{:d}")
    row("Win rate",               lo["win_rate"],      ls["win_rate"],      "{:.1%}")
    row("Avg win",                lo["avg_win_usdc"],  ls["avg_win_usdc"],  "${:+.3f}")
    row("Avg loss",               lo["avg_loss_usdc"], ls["avg_loss_usdc"], "${:.3f}")
    row("Profit factor",          lo["profit_factor"], ls["profit_factor"], "{:.2f}x")
    row("Max drawdown",           lo["max_drawdown"],  ls["max_drawdown"],  "{:.2%}")
    row("Sharpe (annualised)",    lo["sharpe_ratio"],  ls["sharpe_ratio"],  "{:.3f}")

    print(SEP)

    # ── Verdict ───────────────────────────────────────────────────────
    delta = ls["total_pnl"] - lo["total_pnl"]
    if delta > 0.001:
        print(f"\n  VERDICT ✅  Long+Short outperforms by ${delta:+.4f} "
              f"({ls['total_pnl_pct'] - lo['total_pnl_pct']:+.2%}).")
        print(f"             Adding shorts appears beneficial at these settings.")
    elif delta < -0.001:
        print(f"\n  VERDICT ❌  Long-only outperforms by ${-delta:.4f} "
              f"({lo['total_pnl_pct'] - ls['total_pnl_pct']:+.2%}).")
        print(f"             Shorts detract from performance at these settings.")
    else:
        print(f"\n  VERDICT ➡  Negligible difference (${delta:+.4f}). Shorts are neutral.")

    if ls["n_short"] == 0:
        print(f"\n  NOTE: no short trades were triggered. "
              f"Score never hit ≤{config.SELL_THRESHOLD} during the period "
              f"(RSI+MACD only weighting likely kept scores higher).")

    dd_delta = ls["max_drawdown"] - lo["max_drawdown"]
    if dd_delta > 0.02:
        print(f"\n  ⚠  Drawdown increases {lo['max_drawdown']:.2%} → {ls['max_drawdown']:.2%} "
              f"(+{dd_delta:.2%}) with shorts. Factor this into the go/no-go decision.")

    print()


if __name__ == "__main__":
    days = 365
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass
    run_comparison(days)

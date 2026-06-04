"""
Backtesting engine — replays historical candles through the exact same
indicator → signal → risk pipeline used in live trading.

Usage:
    python main.py --backtest 90       # 90-day backtest
    python main.py --backtest 365      # 1-year backtest
"""

import math
import time
from datetime import datetime

import config
from layers.analysis.indicators import (
    calculate_rsi, calculate_macd,
    normalize_rsi, normalize_macd,
)
from layers.decision.signal_engine import generate_signal
from layers.risk.risk_manager import RiskManager


def _date(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def run_backtest(
    candles: list[dict],
    initial_capital: float = 1000.0,
    verbose: bool = True,
) -> dict:
    """
    Simulate trading on `candles`.

    Parameters
    ----------
    candles : list of dicts with keys timestamp, open, high, low, close
    initial_capital : starting USDC
    verbose : print every trade

    Returns
    -------
    dict with summary statistics
    """
    if not candles:
        print("[Backtest] No candles to replay.")
        return {}

    risk = RiskManager(initial_capital_usdc=initial_capital)
    closes: list[float] = []
    buy_hold_entry: float = candles[0]["close"]

    sep = "─" * 62
    if verbose:
        print(f"\n{sep}")
        print(f"  BACKTEST  |  {len(candles)} candles  |  capital=${initial_capital:,.2f}")
        print(f"  Period: {_date(candles[0]['timestamp'])} → {_date(candles[-1]['timestamp'])}")
        print(sep)

    for candle in candles:
        price = candle["close"]
        ts    = candle["timestamp"]
        closes.append(price)

        if len(closes) < config.MIN_CANDLES_REQUIRED:
            continue

        # Indicators
        rsi  = calculate_rsi(closes, config.RSI_PERIOD)
        macd, sig_line, hist = calculate_macd(
            closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL_PERIOD
        )

        rsi_score  = normalize_rsi(rsi, config.RSI_OVERSOLD, config.RSI_OVERBOUGHT) if rsi is not None else None
        macd_score = normalize_macd(hist) if hist is not None else None

        signal = generate_signal(
            rsi_score, macd_score, None,          # no Polymarket in backtest
            rsi_raw=rsi, macd_raw=macd,
            macd_signal_raw=sig_line, macd_hist_raw=hist,
        )

        # Auto-exit before checking new signals
        auto = risk.check_sl_tp(price)
        if auto and risk.position:
            trade = risk.close_position(price)
            pnl   = trade["pnl_usdc"]
            if verbose:
                mark = "✅" if pnl > 0 else "❌"
                print(f"  {_date(ts)} | {auto:12s} SELL @ ${price:>8.2f} | "
                      f"PnL {mark} ${pnl:+.2f} ({trade['pnl_pct']:+.1%})")
            continue

        if signal.action == "BUY":
            check = risk.check_trade("BUY", price, config.TRADE_AMOUNT_USDC)
            if check.approved:
                risk.open_position(price, check.adjusted_size_usdc)
                if verbose:
                    print(f"  {_date(ts)} | BUY        @ ${price:>8.2f} | "
                          f"Size=${check.adjusted_size_usdc:.2f} score={signal.score:.3f}")

        elif signal.action == "SELL":
            check = risk.check_trade("SELL", price, 0.0)
            if check.approved:
                trade = risk.close_position(price)
                pnl   = trade["pnl_usdc"]
                if verbose:
                    mark = "✅" if pnl > 0 else "❌"
                    print(f"  {_date(ts)} | SELL       @ ${price:>8.2f} | "
                          f"PnL {mark} ${pnl:+.2f} ({trade['pnl_pct']:+.1%})")

    # Close any open position at last bar
    if risk.position and closes:
        final = closes[-1]
        trade = risk.close_position(final)
        if verbose:
            pnl = trade["pnl_usdc"]
            print(f"  [{_date(candles[-1]['timestamp'])}] FORCED CLOSE @ ${final:.2f} "
                  f"PnL ${pnl:+.2f}")

    # ── Statistics ────────────────────────────────────────────────────────
    final_value = risk.free_usdc
    total_pnl   = final_value - initial_capital
    pnl_pct     = total_pnl / initial_capital
    n_trades    = len(risk.trades)
    wins        = [t for t in risk.trades if t["pnl_usdc"] > 0]
    losses      = [t for t in risk.trades if t["pnl_usdc"] <= 0]
    win_rate    = len(wins) / n_trades if n_trades else 0.0
    avg_win     = (sum(t["pnl_usdc"] for t in wins)   / len(wins))   if wins   else 0.0
    avg_loss    = (sum(t["pnl_usdc"] for t in losses)  / len(losses)) if losses else 0.0
    profit_factor = abs(avg_win / avg_loss) if avg_loss else float("inf")

    # Max drawdown
    peak  = initial_capital
    trough = initial_capital
    running_cap = initial_capital
    max_dd = 0.0
    for t in risk.trades:
        running_cap += t["pnl_usdc"]
        if running_cap > peak:
            peak = running_cap
        dd = (peak - running_cap) / peak
        if dd > max_dd:
            max_dd = dd

    # Buy & hold comparison
    bh_return = (closes[-1] - buy_hold_entry) / buy_hold_entry if closes else 0.0
    bh_pnl    = initial_capital * bh_return

    # Simplified Sharpe (daily returns from trade PnLs)
    if len(risk.trades) > 1:
        import statistics
        daily_pnls = [t["pnl_usdc"] for t in risk.trades]
        mean_r = statistics.mean(daily_pnls)
        std_r  = statistics.stdev(daily_pnls) or 1e-9
        sharpe = (mean_r / std_r) * math.sqrt(252)  # annualised
    else:
        sharpe = 0.0

    results = {
        "initial_capital":  initial_capital,
        "final_value":      final_value,
        "total_pnl":        total_pnl,
        "total_pnl_pct":    pnl_pct,
        "n_trades":         n_trades,
        "win_rate":         win_rate,
        "avg_win_usdc":     avg_win,
        "avg_loss_usdc":    avg_loss,
        "profit_factor":    profit_factor,
        "max_drawdown":     max_dd,
        "sharpe_ratio":     sharpe,
        "buy_hold_pct":     bh_return,
        "buy_hold_pnl":     bh_pnl,
        "trades":           risk.trades,
    }

    if verbose:
        _print_summary(results)

    return results


def _print_summary(r: dict):
    sep = "─" * 62
    win = r["win_rate"]
    pf  = r["profit_factor"]
    print(f"\n{sep}")
    print("  BACKTEST RESULTS")
    print(sep)
    print(f"  Final value:     ${r['final_value']:>10,.2f}  (started ${r['initial_capital']:,.2f})")
    print(f"  Strategy PnL:    ${r['total_pnl']:>+10.2f}  ({r['total_pnl_pct']:>+.1%})")
    print(f"  Buy & hold:      ${r['buy_hold_pnl']:>+10.2f}  ({r['buy_hold_pct']:>+.1%})")
    print(f"  Trades:          {r['n_trades']}")
    print(f"  Win rate:        {win:.1%}")
    print(f"  Avg win:         ${r['avg_win_usdc']:>+.2f}")
    print(f"  Avg loss:        ${r['avg_loss_usdc']:>+.2f}")
    print(f"  Profit factor:   {pf:.2f}")
    print(f"  Max drawdown:    {r['max_drawdown']:.1%}")
    print(f"  Sharpe (ann.):   {r['sharpe_ratio']:.2f}")
    print(sep + "\n")

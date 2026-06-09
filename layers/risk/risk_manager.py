"""
Layer 4 – Risk: Position sizing, drawdown guard, stop-loss / take-profit.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import config
from layers.data.database import save_trade as _db_save_trade


@dataclass
class Position:
    entry_price: float
    size_usdc: float          # USDC spent to open
    sol_amount: float         # SOL received (computed at open)
    entry_time: float = field(default_factory=time.time)

    @property
    def side(self) -> str:
        return "LONG"

    def unrealized_pnl(self, current_price: float) -> float:
        return self.sol_amount * current_price - self.size_usdc

    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price


@dataclass
class RiskCheck:
    approved: bool
    reason: str
    adjusted_size_usdc: float = 0.0


class RiskManager:
    def __init__(self, initial_capital_usdc: float = 100.0):
        self.initial_capital      = initial_capital_usdc
        self.free_usdc            = initial_capital_usdc   # liquid USDC available
        self.peak_usdc            = initial_capital_usdc
        self.position:            Optional[Position] = None   # long slot
        self.short_position:      Optional[Position] = None   # short slot
        self.trades:              list[dict] = []
        self.realized_pnl:        float = 0.0
        self.last_trade_tick:     Optional[int] = None   # iteration when last position closed
        self.last_trade_direction: Optional[str] = None  # 'long' or 'short'

    # ── Portfolio metrics ──────────────────────────────────────────────────

    def portfolio_value(self, current_price: float) -> float:
        val = self.free_usdc
        if self.position:
            val += self.position.sol_amount * current_price
        if self.short_position:
            # Margin was deducted at open; add it back ± floating PnL
            short_pnl = (self.short_position.entry_price - current_price) * self.short_position.sol_amount
            val += self.short_position.size_usdc + short_pnl
        return val

    def drawdown(self, current_price: float) -> float:
        """Current drawdown from peak (0 → no drawdown, 1 → 100% loss)."""
        pv = self.portfolio_value(current_price)
        if pv > self.peak_usdc:
            self.peak_usdc = pv
        return max(0.0, (self.peak_usdc - pv) / self.peak_usdc)

    # ── Trade guards ───────────────────────────────────────────────────────

    def check_trade(
        self, action: str, price: float, requested_usdc: float,
        current_tick: Optional[int] = None,
    ) -> RiskCheck:
        if action == "BUY":
            if self.position:
                return RiskCheck(False, "Long position already open")
            if self.short_position:
                return RiskCheck(False, "Short position already open")
            if (current_tick is not None and self.last_trade_tick is not None
                    and self.last_trade_direction == "short"
                    and current_tick - self.last_trade_tick < config.REVERSAL_COOLDOWN_TICKS):
                left = config.REVERSAL_COOLDOWN_TICKS - (current_tick - self.last_trade_tick)
                return RiskCheck(False, f"Reversal cooldown: {left} tick(s) remaining after short close")

            dd = self.drawdown(price)
            if dd >= config.MAX_DRAWDOWN_PCT:
                return RiskCheck(False, f"Max drawdown breached ({dd:.1%})")

            max_allowed = self.free_usdc * config.MAX_POSITION_SIZE_PCT
            size = min(requested_usdc, max_allowed, self.free_usdc)
            if size < 0.50:
                return RiskCheck(False, f"Trade size too small (${size:.2f})")
            return RiskCheck(True, "OK", size)

        elif action == "SELL":
            if not self.position:
                return RiskCheck(False, "No open long position to sell")
            return RiskCheck(True, "OK", 0.0)

        elif action == "SHORT":
            if self.position:
                return RiskCheck(False, "Long position already open")
            if self.short_position:
                return RiskCheck(False, "Short position already open")
            if (current_tick is not None and self.last_trade_tick is not None
                    and self.last_trade_direction == "long"
                    and current_tick - self.last_trade_tick < config.REVERSAL_COOLDOWN_TICKS):
                left = config.REVERSAL_COOLDOWN_TICKS - (current_tick - self.last_trade_tick)
                return RiskCheck(False, f"Reversal cooldown: {left} tick(s) remaining after long close")

            dd = self.drawdown(price)
            if dd >= config.MAX_DRAWDOWN_PCT:
                return RiskCheck(False, f"Max drawdown breached ({dd:.1%})")

            max_allowed = self.free_usdc * config.MAX_POSITION_SIZE_PCT
            size = min(requested_usdc, max_allowed, self.free_usdc)
            if size < 0.50:
                return RiskCheck(False, f"Trade size too small (${size:.2f})")
            return RiskCheck(True, "OK", size)

        return RiskCheck(False, f"Unknown action: {action}")

    def check_sl_tp(self, current_price: float, regime: str = "unknown") -> Optional[str]:
        """Return 'STOP_LOSS', 'TAKE_PROFIT', or None for the long position."""
        if not self.position:
            return None
        sl, tp = config.STOP_LOSS_PCT, config.TAKE_PROFIT_PCT
        pct = self.position.pnl_pct(current_price)
        if pct <= -sl:
            return "STOP_LOSS"
        if pct >= tp:
            return "TAKE_PROFIT"
        return None

    def check_short_sl_tp(self, current_price: float, regime: str = "unknown") -> Optional[str]:
        """Return 'STOP_LOSS', 'TAKE_PROFIT', or None for the short position.
        Short TP: price fell >= tp below entry.
        Short SL: price rose >= sl above entry.
        """
        if not self.short_position:
            return None
        sl, tp = config.SHORT_STOP_LOSS_PCT, config.SHORT_TAKE_PROFIT_PCT
        pct = (current_price - self.short_position.entry_price) / self.short_position.entry_price
        if pct >= sl:   # price rose — loss for short
            return "STOP_LOSS"
        if pct <= -tp:  # price fell — profit for short
            return "TAKE_PROFIT"
        return None

    # ── State transitions ──────────────────────────────────────────────────

    def open_position(self, price: float, size_usdc: float) -> Position:
        sol_amount = size_usdc / price
        self.free_usdc -= size_usdc
        self.position = Position(
            entry_price=price,
            size_usdc=size_usdc,
            sol_amount=sol_amount,
        )
        return self.position

    def close_position(self, price: float) -> dict:
        if not self.position:
            return {}
        pos = self.position
        usdc_returned = pos.sol_amount * price
        pnl = usdc_returned - pos.size_usdc
        pnl_pct = pnl / pos.size_usdc

        self.free_usdc += usdc_returned
        self.realized_pnl += pnl
        pv = self.free_usdc
        if pv > self.peak_usdc:
            self.peak_usdc = pv

        trade = {
            "direction":   "long",
            "entry_price": pos.entry_price,
            "exit_price":  price,
            "size_usdc":   pos.size_usdc,
            "sol_amount":  pos.sol_amount,
            "pnl_usdc":    round(pnl, 4),
            "pnl_pct":     round(pnl_pct, 6),
            "entry_time":  pos.entry_time,
            "exit_time":   time.time(),
        }
        self.trades.append(trade)
        self.position = None
        try:
            _db_save_trade(trade)
        except Exception:
            pass
        return trade

    def open_short_position(self, price: float, size_usdc: float) -> Position:
        sol_amount     = size_usdc / price
        self.free_usdc -= size_usdc          # deduct as margin
        self.short_position = Position(
            entry_price=price,
            size_usdc=size_usdc,
            sol_amount=sol_amount,
        )
        return self.short_position

    def close_short_position(self, price: float) -> dict:
        if not self.short_position:
            return {}
        pos       = self.short_position
        float_pnl = (pos.entry_price - price) * pos.sol_amount
        pnl_pct   = float_pnl / pos.size_usdc

        self.free_usdc    += pos.size_usdc + float_pnl   # return margin ± PnL
        self.realized_pnl += float_pnl
        pv = self.free_usdc
        if pv > self.peak_usdc:
            self.peak_usdc = pv

        trade = {
            "direction":   "short",
            "entry_price": pos.entry_price,
            "exit_price":  price,
            "size_usdc":   pos.size_usdc,
            "sol_amount":  pos.sol_amount,
            "pnl_usdc":    round(float_pnl, 4),
            "pnl_pct":     round(pnl_pct, 6),
            "entry_time":  pos.entry_time,
            "exit_time":   time.time(),
        }
        self.trades.append(trade)
        self.short_position = None
        try:
            _db_save_trade(trade)
        except Exception:
            pass
        return trade

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t["pnl_usdc"] > 0)
        return wins / len(self.trades)

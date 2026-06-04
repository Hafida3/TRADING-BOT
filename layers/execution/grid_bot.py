"""
Grid Bot – Paper-trading grid strategy.

Capital is split evenly across `num_levels` price levels.
- When price falls through a level (going down) → virtual BUY at that level.
- When price rises through a level (going up) and a position is held → virtual SELL.

Only used in DRY_RUN mode.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from layers.data.database import save_grid_trade as _db_save_grid_trade


@dataclass
class GridLevel:
    index: int
    price: float
    has_position: bool  = False
    sol_amount:   float = 0.0
    entry_price:  float = 0.0
    entry_time:   float = 0.0

    def unrealized_pnl(self, current_price: float) -> float:
        if not self.has_position:
            return 0.0
        return (current_price - self.entry_price) * self.sol_amount


class GridBot:
    def __init__(
        self,
        capital_usdc: float,
        low_price:    float,
        high_price:   float,
        num_levels:   int = 5,
    ):
        self.total_capital     = capital_usdc
        self.free_usdc         = capital_usdc
        self.low               = low_price
        self.high              = high_price
        self.num_levels        = num_levels
        self.realized_pnl:     float = 0.0
        self.trades:           list[dict] = []
        self.last_price:       Optional[float] = None
        self.capital_per_level = capital_usdc / num_levels

        step = (high_price - low_price) / (num_levels - 1)
        self.levels: list[GridLevel] = [
            GridLevel(index=i, price=round(low_price + i * step, 4))
            for i in range(num_levels)
        ]

    # ── Tick update ───────────────────────────────────────────────────────

    def update(self, current_price: float) -> list[dict]:
        """Check price against all grid levels; execute virtual buys/sells.
        Returns list of execution dicts for the current tick.
        """
        if self.last_price is None:
            self.last_price = current_price
            return []

        prev     = self.last_price
        executed: list[dict] = []

        for lvl in self.levels:
            # Price fell through level → BUY
            if prev > lvl.price >= current_price and not lvl.has_position:
                spend = min(self.capital_per_level, self.free_usdc)
                if spend < 0.50:
                    continue
                sol_amt          = spend / current_price
                self.free_usdc  -= spend
                lvl.has_position = True
                lvl.sol_amount   = sol_amt
                lvl.entry_price  = current_price
                lvl.entry_time   = time.time()
                ev = {
                    "action":      "BUY",
                    "level":       lvl.index,
                    "level_price": lvl.price,
                    "exec_price":  current_price,
                    "size_usdc":   round(spend, 4),
                    "sol_amount":  round(sol_amt, 6),
                    "time":        lvl.entry_time,
                }
                executed.append(ev)
                self.trades.append(ev)
                print(
                    f"[Grid] BUY  lvl {lvl.index} (${lvl.price:.2f}) "
                    f"exec ${current_price:.4f} | ${spend:.2f} → {sol_amt:.5f} SOL"
                )

            # Price rose through level → SELL if holding
            elif prev < lvl.price <= current_price and lvl.has_position:
                usdc_out        = lvl.sol_amount * current_price
                pnl             = usdc_out - lvl.sol_amount * lvl.entry_price
                self.free_usdc += usdc_out
                self.realized_pnl += pnl
                ev = {
                    "action":        "SELL",
                    "level":         lvl.index,
                    "level_price":   lvl.price,
                    "exec_price":    current_price,
                    "sol_amount":    round(lvl.sol_amount, 6),
                    "usdc_received": round(usdc_out, 4),
                    "pnl_usdc":      round(pnl, 4),
                    "entry_price":   lvl.entry_price,
                    "time":          time.time(),
                }
                executed.append(ev)
                self.trades.append(ev)
                try:
                    _db_save_grid_trade(lvl.index, lvl.entry_price, current_price, round(pnl, 4))
                except Exception:
                    pass
                print(
                    f"[Grid] SELL lvl {lvl.index} (${lvl.price:.2f}) "
                    f"exec ${current_price:.4f} | PnL ${pnl:+.4f}"
                )
                lvl.has_position = False
                lvl.sol_amount   = 0.0
                lvl.entry_price  = 0.0

        self.last_price = current_price
        return executed

    # ── Portfolio ─────────────────────────────────────────────────────────

    def portfolio_value(self, current_price: float) -> float:
        val = self.free_usdc
        for lvl in self.levels:
            if lvl.has_position:
                val += lvl.sol_amount * current_price
        return val

    def unrealized_pnl(self, current_price: float) -> float:
        return sum(lvl.unrealized_pnl(current_price) for lvl in self.levels)

    # ── State snapshot for data.json / dashboard ──────────────────────────

    def get_state(self, current_price: float) -> dict:
        return {
            "low":               self.low,
            "high":              self.high,
            "num_levels":        self.num_levels,
            "capital_total":     self.total_capital,
            "capital_per_level": round(self.capital_per_level, 4),
            "free_usdc":         round(self.free_usdc, 4),
            "realized_pnl":      round(self.realized_pnl, 4),
            "unrealized_pnl":    round(self.unrealized_pnl(current_price), 4),
            "portfolio_value":   round(self.portfolio_value(current_price), 4),
            "levels": [
                {
                    "index":          lvl.index,
                    "price":          lvl.price,
                    "has_position":   lvl.has_position,
                    "sol_amount":     round(lvl.sol_amount, 6) if lvl.has_position else 0.0,
                    "entry_price":    lvl.entry_price if lvl.has_position else None,
                    "unrealized_pnl": round(lvl.unrealized_pnl(current_price), 4),
                }
                for lvl in self.levels
            ],
        }

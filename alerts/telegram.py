"""
Telegram alerter — sends HTML-formatted messages to a configured chat.

All sends are best-effort: failures are logged but never raise exceptions
so the bot loop is never interrupted by a Telegram outage.
"""

from typing import Optional
import requests


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self._base = f"https://api.telegram.org/bot{token}/sendMessage"

    def _send(self, text: str) -> bool:
        if not self.enabled:
            print(f"[Telegram-disabled] {text}")
            return False
        try:
            resp = requests.post(
                self._base,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            if not resp.ok:
                print(f"[Telegram] HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.ok
        except Exception as exc:
            print(f"[Telegram] send error: {exc}")
            return False

    # ── High-level helpers ────────────────────────────────────────────────

    def send_startup(self, dry_run: bool, interval_s: int, capital: float):
        mode = "PAPER TRADING" if dry_run else "LIVE TRADING"
        icon = "📝" if dry_run else "⚡"
        self._send(
            f"{icon} <b>Bot started – {mode}</b>\n"
            f"Capital: <b>${capital:,.2f} USDC</b>\n"
            f"Interval: <b>{interval_s}s</b>"
        )

    def send_trade(
        self,
        action: str,
        price: float,
        size_usdc: float,
        pnl: Optional[float] = None,
        dry_run: bool = True,
        reason: str = "",
    ):
        mode = "PAPER" if dry_run else "LIVE"
        icons = {"BUY": "🟢", "SELL": "🔴", "STOP_LOSS": "🛑", "TAKE_PROFIT": "✅"}
        icon = icons.get(action, "⚪")
        lines = [
            f"{icon} <b>[{mode}] {action}</b>",
            f"Price:  <b>${price:,.2f}</b>",
            f"Size:   <b>${size_usdc:.2f} USDC</b>",
        ]
        if pnl is not None:
            p_icon = "✅" if pnl >= 0 else "❌"
            lines.append(f"PnL:    {p_icon} <b>${pnl:+.2f}</b>")
        if reason:
            lines.append(f"Signal: <i>{reason}</i>")
        self._send("\n".join(lines))

    def send_pnl_report(
        self,
        portfolio_value: float,
        realized_pnl: float,
        unrealized_pnl: float,
        initial_capital: float,
        trade_count: int,
        win_rate: float,
    ):
        total = realized_pnl + unrealized_pnl
        pct = total / initial_capital
        icon = "📈" if total >= 0 else "📉"
        self._send(
            f"{icon} <b>PnL Report</b>\n"
            f"Portfolio:    <b>${portfolio_value:,.2f}</b>\n"
            f"Realized:     <b>${realized_pnl:+.2f}</b>\n"
            f"Unrealized:   <b>${unrealized_pnl:+.2f}</b>\n"
            f"Total PnL:    <b>${total:+.2f} ({pct:+.1%})</b>\n"
            f"Trades:       {trade_count}  |  Win rate: {win_rate:.0%}"
        )

    def send_alert(self, message: str, level: str = "INFO"):
        icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🚨"}
        self._send(f"{icons.get(level, 'ℹ️')} <b>[{level}]</b> {message}")

    def send_shutdown(
        self,
        portfolio_value: float,
        total_pnl: float,
        trade_count: int,
    ):
        icon = "📈" if total_pnl >= 0 else "📉"
        self._send(
            f"🛑 <b>Bot stopped</b>\n"
            f"Final portfolio: <b>${portfolio_value:,.2f}</b>\n"
            f"Total PnL:       {icon} <b>${total_pnl:+.2f}</b>\n"
            f"Total trades:    {trade_count}"
        )

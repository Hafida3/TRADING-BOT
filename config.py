import os
from dotenv import load_dotenv

load_dotenv()

# ── Trading Mode ──────────────────────────────────────────────────────────────
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
LOOP_INTERVAL_SECONDS: int = int(os.getenv("LOOP_INTERVAL_SECONDS", "300"))
TRADE_AMOUNT_USDC: float = float(os.getenv("TRADE_AMOUNT_USDC", "10.0"))
INITIAL_CAPITAL_USDC: float = float(os.getenv("INITIAL_CAPITAL_USDC", "100.0"))

# ── Solana ────────────────────────────────────────────────────────────────────
SOLANA_RPC_URL: str = os.getenv(
    "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
)
WALLET_PUBLIC_KEY: str = os.getenv("WALLET_PUBLIC_KEY", "")
WALLET_PRIVATE_KEY_ENCRYPTED: str = os.getenv("WALLET_PRIVATE_KEY_ENCRYPTED", "")
WALLET_ENCRYPTION_KEY: str = os.getenv("WALLET_ENCRYPTION_KEY", "")

# Token mint addresses (Solana mainnet)
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8080"))

# ── Risk ──────────────────────────────────────────────────────────────────────
MAX_POSITION_SIZE_PCT: float = float(os.getenv("MAX_POSITION_SIZE_PCT", "0.25"))
MAX_DRAWDOWN_PCT: float = float(os.getenv("MAX_DRAWDOWN_PCT", "0.15"))
STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "0.004"))
TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.008"))

SHORT_TAKE_PROFIT_PCT: float = float(os.getenv("SHORT_TAKE_PROFIT_PCT", "0.008"))
SHORT_STOP_LOSS_PCT: float = float(os.getenv("SHORT_STOP_LOSS_PCT", "0.004"))

# Minimum ticks between closing a position and opening in the opposite direction
REVERSAL_COOLDOWN_TICKS: int = int(os.getenv("REVERSAL_COOLDOWN_TICKS", "3"))

# ── Signal Thresholds ─────────────────────────────────────────────────────────
BUY_THRESHOLD: float = float(os.getenv("BUY_THRESHOLD", "0.62"))
SELL_THRESHOLD: float = float(os.getenv("SELL_THRESHOLD", "0.38"))

# ── External API Keys ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")

# ── Indicator Parameters ──────────────────────────────────────────────────────
RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "30"))
RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))

MACD_FAST: int = int(os.getenv("MACD_FAST", "12"))
MACD_SLOW: int = int(os.getenv("MACD_SLOW", "26"))
MACD_SIGNAL_PERIOD: int = int(os.getenv("MACD_SIGNAL_PERIOD", "9"))

# Minimum candles needed before indicators are reliable
MIN_CANDLES_REQUIRED: int = MACD_SLOW + MACD_SIGNAL_PERIOD + 5

# ── Grid Bot ──────────────────────────────────────────────────────────────────
_grid_low  = os.getenv("GRID_LOW_PRICE")
_grid_high = os.getenv("GRID_HIGH_PRICE")
GRID_LOW_PRICE:  float | None = float(_grid_low)  if _grid_low  else None
GRID_HIGH_PRICE: float | None = float(_grid_high) if _grid_high else None
GRID_NUM_LEVELS: int = int(os.getenv("GRID_NUM_LEVELS", "5"))

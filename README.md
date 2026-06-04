# SOL / USDC Autonomous Trading Bot

Modular Solana trading bot with RSI/MACD analysis, Polymarket prediction
signals, Jupiter DEX execution, Telegram alerts and a local HTML dashboard.

---

## Architecture — 5 Layers

```
Layer 1  data/       price_feed.py    CoinGecko SOL/USDC prices
                     polymarket.py    Free Polymarket sentiment signal
Layer 2  analysis/   indicators.py    RSI (Wilder) + MACD
Layer 3  decision/   signal_engine.py Weighted signal → BUY/SELL/HOLD
Layer 4  risk/       risk_manager.py  Position sizing, SL/TP, drawdown guard
Layer 5  execution/  wallet.py        Encrypted Solana hot wallet
                     jupiter.py       Jupiter v6 SOL⟷USDC swaps
```

**Signal weights:** RSI 35% · MACD 35% · Polymarket 30%

---

## Quick Start

### 1. Install dependencies

```bash
cd TRADING-BOT
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — Telegram tokens are optional; bot runs fine without them.
```

### 3. Run in paper-trading mode (default, no wallet needed)

```bash
python main.py
```

Open **http://localhost:8080** for the live dashboard.

---

## Live Trading Setup

> **Warning:** Live trading involves real funds. Test thoroughly in paper mode first.

### Step 1 — Generate a hot wallet

```bash
python generate_wallet.py
```

Copy the three lines it prints into `.env`:

```env
WALLET_PUBLIC_KEY=...
WALLET_PRIVATE_KEY_ENCRYPTED=...
WALLET_ENCRYPTION_KEY=...
```

### Step 2 — Fund the wallet

Send USDC (and a small amount of SOL for gas ~0.01 SOL) to the `WALLET_PUBLIC_KEY` address.

### Step 3 — Enable live mode

```env
DRY_RUN=false
TRADE_AMOUNT_USDC=10.0
```

### Step 4 — Start the bot

```bash
python main.py
```

---

## Preset Modes

Two named configurations are documented in `.env`. Uncomment the block you want.

### LIVE_MODE — aggressive · 60s tick trading

High-frequency, tight stops. Built for live loops where the bot evaluates
every 60 seconds and price moves are sub-dollar. **Do not use with daily
backtest data** — the tiny SL/TP bands will be gapped through by daily candles.

```env
LOOP_INTERVAL_SECONDS=60
BUY_THRESHOLD=0.45
SELL_THRESHOLD=0.55
STOP_LOSS_PCT=0.001      # −0.1%
TAKE_PROFIT_PCT=0.002    # +0.2%
```

To backtest while on LIVE_MODE, override inline so `.env` stays untouched:

```bash
TAKE_PROFIT_PCT=0.06 STOP_LOSS_PCT=0.03 python3 main.py --backtest 365
```

### CONSERVATIVE_MODE — proven · 5-min intervals · daily-candle safe

Validated on a 365-day backtest (May 2025 → May 2026, a −52% SOL bear market):

| Metric | Result |
|---|---|
| Strategy PnL | **+0.3%** |
| Buy & hold | −52.6% |
| Profit factor | **2.49** |
| Win rate | 30% |
| Max drawdown | **2.3%** |
| Sharpe (ann.) | 0.44 |

```env
LOOP_INTERVAL_SECONDS=300
BUY_THRESHOLD=0.58
SELL_THRESHOLD=0.38
STOP_LOSS_PCT=0.03       # −3%
TAKE_PROFIT_PCT=0.06     # +6%
```

**To switch modes:** in `.env`, comment out the active block and uncomment
the other, then restart the bot.

---

## Backtesting

```bash
# 90-day backtest (default)
python main.py --backtest 90

# 1-year backtest
python main.py --backtest 365
```

Output includes: strategy PnL vs buy-and-hold, win rate, profit factor,
max drawdown, and annualised Sharpe ratio.

---

## Telegram Alerts

1. Message **@BotFather** on Telegram → `/newbot` → copy the token.
2. Message **@userinfobot** → copy your numeric chat ID.
3. Add to `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
```

The bot sends: startup notification · every trade · hourly PnL report · shutdown summary.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `true` | Paper trading (no real swaps) |
| `LOOP_INTERVAL_SECONDS` | `300` | Evaluation frequency |
| `TRADE_AMOUNT_USDC` | `10.0` | USDC per trade |
| `INITIAL_CAPITAL_USDC` | `100.0` | Paper portfolio size |
| `STOP_LOSS_PCT` | `0.05` | Exit at −5% |
| `TAKE_PROFIT_PCT` | `0.12` | Exit at +12% |
| `MAX_DRAWDOWN_PCT` | `0.15` | Halt trading at −15% portfolio |
| `BUY_THRESHOLD` | `0.62` | Composite score ≥ this → BUY |
| `SELL_THRESHOLD` | `0.38` | Composite score ≤ this → SELL |
| `RSI_PERIOD` | `14` | RSI lookback |
| `RSI_OVERSOLD` | `30` | RSI buy zone |
| `RSI_OVERBOUGHT` | `70` | RSI sell zone |
| `MACD_FAST` | `12` | MACD fast EMA |
| `MACD_SLOW` | `26` | MACD slow EMA |
| `MACD_SIGNAL_PERIOD` | `9` | MACD signal EMA |

---

## Dashboard

The bot writes `data.json` after every iteration. The dashboard polls it
every 5 seconds. No build step required — it's vanilla HTML served by
Python's built-in HTTP server.

**http://localhost:8080**

---

## File Layout

```
TRADING-BOT/
├── main.py                   # Orchestrator + CLI entry point
├── config.py                 # Env-var config (loaded once at import)
├── generate_wallet.py        # One-shot wallet generator
├── requirements.txt
├── .env.example              # Template — copy to .env
├── data.json                 # Live state (written by bot, read by dashboard)
│
├── layers/
│   ├── data/
│   │   ├── price_feed.py     # CoinGecko SOL price + OHLCV
│   │   └── polymarket.py     # Polymarket Gamma API sentiment
│   ├── analysis/
│   │   └── indicators.py     # RSI, MACD, normalisation
│   ├── decision/
│   │   └── signal_engine.py  # Weighted signal aggregation
│   ├── risk/
│   │   └── risk_manager.py   # Position, SL/TP, drawdown
│   └── execution/
│       ├── wallet.py         # Fernet-encrypted keypair
│       └── jupiter.py        # Jupiter v6 quote + swap
│
├── alerts/
│   └── telegram.py           # Telegram Bot API messages
│
├── dashboard/
│   ├── server.py             # Threaded HTTP server (port 8080)
│   └── index.html            # Dark-theme dashboard (Chart.js)
│
└── backtesting/
    ├── data_loader.py        # Historical OHLCV from CoinGecko
    └── engine.py             # Replay engine + statistics
```

---

## Disclaimer

This software is for educational purposes only. Cryptocurrency trading
involves substantial risk of loss. Past performance during backtests does
not guarantee future results. Never trade more than you can afford to lose.

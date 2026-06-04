# TRADING-BOT — Project Reference

Autonomous SOL/USDC trading bot. Paper-trades by default (`DRY_RUN=true`). Can execute live trades on Solana mainnet via Jupiter v6. Runs as a continuous loop with a configurable interval.

---

## Quick Start

```bash
python3 main.py                  # paper-trading loop
python3 main.py --backtest 90    # 90-day historical backtest
python3 main.py --generate-wallet
```

Dashboard: http://localhost:8080  
Stats API: http://localhost:8080/stats  
DB file:   `trading_bot.db` (SQLite, project root)

---

## Architecture — 5 Layers

```
Layer 1  DATA        price_feed, news_sentiment, polymarket, macro,
                     trump_signal, fear_greed, database
Layer 2  ANALYSIS    indicators (RSI, MACD), regime detection
Layer 3  DECISION    signal_engine — weighted composite signal
Layer 4  RISK        risk_manager — position sizing, SL/TP, drawdown guard
Layer 5  EXECUTION   jupiter (swap), wallet (keypair), grid_bot
```

Supporting modules: `alerts/telegram.py`, `dashboard/server.py`, `backtesting/`, `config.py`, `main.py`.

---

## Capital Split

Total capital is split 50/50 at startup:
- **Signal bot** gets 50% — managed by `RiskManager`
- **Grid bot** gets 50% — managed by `GridBot`

Both run concurrently every tick. The split was chosen so neither strategy dominates and each can be evaluated independently.

---

## File-by-File Reference

### `main.py`
Entry point and main loop. Each tick (default 300s):
1. Fetch SOL price
2. Fetch Polymarket, news, macro, Trump signal, Fear & Greed
3. Update grid bot
4. Calculate RSI + MACD
5. Detect market regime
6. Generate composite signal
7. Persist signal to SQLite (`save_signal`)
8. Check SL/TP for open positions
9. Execute trades (signal-driven)
10. Write `data.json` for dashboard
11. Send hourly Telegram PnL report

On startup: calls `init_db()`, loads last 100 trades from SQLite into `risk.trades` and restores `realized_pnl` so the session appears continuous after restart.

Handles `SIGINT`/`SIGTERM` for clean shutdown.

### `config.py`
All parameters loaded from `.env` with sane defaults. Never hardcode values — always go through `config.*`. See the Parameters section below.

### `layers/data/price_feed.py`
CoinGecko free API. `get_sol_price()` — 30s in-process cache. `bootstrap_price_history()` fetches 7 days of OHLCV on startup to seed the indicator window so RSI/MACD fire on tick 1 instead of warming up for 26+ ticks.

### `layers/data/news_sentiment.py`
NewsAPI (100 req/day free tier) + local VADER scoring. 30-min cache keeps usage well under limit. Returns `score` (−1 to +1), `normalized` (0 to 1), `reason`, `headline_count`. Searches: crypto, bitcoin, solana, ethereum, blockchain, DeFi, stablecoin.

### `layers/data/polymarket.py`
Queries Polymarket Gamma API for two specific high-liquidity event slugs:
- `how-many-fed-rate-cuts-in-2026` (weight 60%) — Fed rate cut expectations as macro risk-on/off proxy
- `when-will-bitcoin-hit-150k` (weight 40%) — BTC directional proxy

Uses `outcomePrices` field (JSON string array), not `tokens[].price` — this was a bug fix; the old approach returned stale 0.500 because liquid markets use order-book prices, not AMM tokens. 15-min cache.

### `layers/data/macro.py`
Two CoinGecko metrics, 2-min cache:
- BTC 24h % change → score via tanh (scale 10: ±10% → ~0.85/0.15)
- BTC dominance % → score linearly over [35%, 65%] (high dominance = alts losing = bearish for SOL)
- Composite: 65% BTC direction + 35% dominance

### `layers/data/trump_signal.py`
Fetches Truth Social RSS feed (`https://truthsocial.com/@realDonaldTrump.rss`). Filters posts from the last 60 minutes. Scores with VADER then applies keyword boosts (±0.15 each): bearish keywords = war, sanctions, tariff, iran, china, russia; bullish keywords = deal, peace, bitcoin, crypto, cut. 5-min cache. Falls back to `normalized=0.5` when no recent posts.

### `layers/data/fear_greed.py`
Crypto Fear & Greed Index from alternative.me. 30-min cache (index updates once daily). **Contrarian normalization**: `normalized = 0.85 − (score/100) × 0.70`. Extreme fear (0) → 0.85 (buy signal). Extreme greed (100) → 0.15 (sell signal). Neutral (50) → 0.50.

### `layers/data/database.py`
SQLite persistence, `trading_bot.db`. Three tables:

| Table | Purpose |
|---|---|
| `trades` | Every closed trade (signal bot + short positions) |
| `signal_history` | Every tick's signal data |
| `grid_trades` | Every grid level SELL completion |

Key functions:
- `init_db()` — creates tables if missing (idempotent, call at startup)
- `save_trade(trade_dict)` — called by `RiskManager` on every close
- `save_signal(...)` — called by `main.py` every tick
- `save_grid_trade(level, entry, exit, pnl)` — called by `GridBot` on SELL
- `get_recent_trades(n=20)` — returns list of dicts, ordered chronologically
- `get_stats()` — `{total_trades, win_rate, best_trade, worst_trade, total_pnl}` computed from full DB history

All DB calls in hot paths are wrapped in `try/except` so a write failure never crashes the trading loop.

### `layers/analysis/indicators.py`
- `calculate_rsi(prices, period=14)` — Wilder's RSI via pandas EWM
- `normalize_rsi(rsi, oversold=30, overbought=70)` — linear map: ≤30 → 1.0, ≥70 → 0.0
- `calculate_macd(prices, fast=12, slow=26, signal=9)` — standard MACD returning (line, signal, histogram)
- `normalize_macd(histogram)` — tanh with scale 0.08 (tuned for SOL $100–300 range); positive histogram → score > 0.5

### `layers/analysis/regime.py`
Detects market regime from close-price history only (no OHLCV required). Approximates ATR and ADX using close-to-close differences + Wilder smoothing.

| Regime | Rule |
|---|---|
| `trending` | ADX > 25 AND ATR trending up |
| `choppy` | ADX < 20 AND ATR above rolling mean |
| `ranging` | ADX < 20 AND ATR at/below mean |
| `unknown` | < 29 prices |

**Transition buffer**: raw regime must repeat 3 consecutive bars before the published label changes. This prevents rapid flapping on borderline readings. Regime is **observation-only** — it is logged and shown in the dashboard but does not influence the composite signal score.

### `layers/decision/signal_engine.py`
Produces a single `Signal(action, score, reason)` from all data sources.

**Weights (sum to 1.0):**
| Source | Weight | Rationale |
|---|---|---|
| News NLP | 20% | Largest weight — real-time crypto sentiment has strong short-term predictive value |
| RSI | 15% | Classic momentum indicator |
| MACD | 15% | Trend direction + histogram momentum |
| Polymarket | 10% | Market-priced macro expectations |
| Macro BTC | 10% | BTC leads alts |
| Trump/Geo | 10% | Geopolitical events move crypto rapidly |
| Fear & Greed | 10% | Contrarian mean-reversion signal |

If any source is unavailable (returns `None`), its weight is redistributed proportionally among active sources. Score is a weighted average of normalized [0,1] values.

Thresholds: score ≥ 0.62 → BUY, score ≤ 0.38 → SELL, else HOLD.

### `layers/risk/risk_manager.py`
Manages one long slot and one short slot simultaneously.

Key safeguards:
- `MAX_POSITION_SIZE_PCT` (25%) — max fraction of free USDC per trade
- `MAX_DRAWDOWN_PCT` (15%) — halts new trades if portfolio drawdown exceeds this
- `STOP_LOSS_PCT` (0.4%) / `TAKE_PROFIT_PCT` (0.8%) — long position exits
- `SHORT_STOP_LOSS_PCT` (0.4%) / `SHORT_TAKE_PROFIT_PCT` (0.8%) — short exits
- `REVERSAL_COOLDOWN_TICKS` (3) — prevents immediately entering a position in the opposite direction after a close; reduces whipsaw losses

Every `close_position()` and `close_short_position()` call writes to SQLite via `save_trade()`.

Short positions are paper-trading only (`DRY_RUN=true`). In live mode, only long positions are executed via Jupiter.

### `layers/execution/jupiter.py`
Jupiter v6 aggregator. `buy_sol_with_usdc()` and `sell_sol_for_usdc()` both accept `dry_run=True` which fetches a real quote but skips transaction building. In live mode: get quote → POST to `/v6/swap` to build VersionedTransaction → sign with keypair → broadcast via JSON-RPC `sendTransaction`. Slippage: 50 bps (0.5%).

### `layers/execution/wallet.py`
Loads a `solders` keypair from an AES-encrypted private key stored in `.env`. The encryption key is separate from the encrypted value — both required to decrypt. `generate_wallet()` creates a fresh keypair, encrypts the private key, and prints the `.env` values to add.

### `layers/execution/grid_bot.py`
Paper-trading grid strategy. Capital is divided across `num_levels=5` price levels spanning the observed price range. Price falling through a level → virtual BUY. Price rising through a level when holding → virtual SELL + records PnL to SQLite. Grid range is set once on the first tick using the bootstrapped price history (min × 0.99 to max × 1.01). Does not re-range automatically.

### `dashboard/server.py`
Single-threaded daemon HTTP server. Serves `dashboard/index.html` as root. Endpoints:
- `GET /data.json` — reads and streams `data.json` from project root (written every tick by `main.py`)
- `GET /stats` — queries SQLite `get_stats()` and returns JSON

### `alerts/telegram.py`
Best-effort Telegram notifier. Never raises — all failures are printed and swallowed. Sends on: startup, every trade (BUY/SELL/STOP_LOSS/TAKE_PROFIT), hourly PnL report, shutdown. Disabled silently if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are empty.

### `backtesting/engine.py`
Replays historical candles through the same indicator → signal → risk pipeline (RSI + MACD only; no live API calls). Reports: final value, strategy PnL vs. buy-and-hold, win rate, avg win/loss, profit factor, max drawdown, annualized Sharpe. Backtest does NOT write to the trade database.

### `backtesting/data_loader.py`
Fetches historical OHLCV from CoinGecko. Falls back from `/ohlc` (sparse for long ranges) to `/market_chart` (daily data) when fewer than `MIN_CANDLES_REQUIRED` candles are returned.

---

## Configuration Parameters

All values come from `.env` (see `config.py` for defaults):

```
# Trading mode
DRY_RUN=true                     # false for live execution
LOOP_INTERVAL_SECONDS=300        # tick interval (5 min)
INITIAL_CAPITAL_USDC=100.0       # total capital (split 50/50 with grid)
TRADE_AMOUNT_USDC=10.0           # requested size per signal trade

# Risk
MAX_POSITION_SIZE_PCT=0.25       # max 25% of free USDC per trade
MAX_DRAWDOWN_PCT=0.15            # halt new trades at 15% portfolio drawdown
STOP_LOSS_PCT=0.004              # 0.4% stop-loss on longs
TAKE_PROFIT_PCT=0.008            # 0.8% take-profit on longs
SHORT_STOP_LOSS_PCT=0.004        # 0.4% stop-loss on shorts
SHORT_TAKE_PROFIT_PCT=0.008      # 0.8% take-profit on shorts
REVERSAL_COOLDOWN_TICKS=3        # ticks to wait before reversing direction

# Signal thresholds
BUY_THRESHOLD=0.62
SELL_THRESHOLD=0.38

# Indicators
RSI_PERIOD=14
RSI_OVERSOLD=30
RSI_OVERBOUGHT=70
MACD_FAST=12
MACD_SLOW=26
MACD_SIGNAL_PERIOD=9

# Infra
DASHBOARD_PORT=8080
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

# API keys (required for full functionality)
NEWSAPI_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...            # unused in core loop, present for future use

# Wallet (live mode only)
WALLET_PUBLIC_KEY=...
WALLET_PRIVATE_KEY_ENCRYPTED=...
WALLET_ENCRYPTION_KEY=...
```

---

## Key Design Decisions

**Why proportional weight redistribution when a signal is missing?**  
If Polymarket is down, its 10% weight is distributed to the other active sources rather than defaulting to neutral (0.5). This means the bot uses all available information at full resolution rather than diluting every signal with phantom neutral votes.

**Why is regime observation-only?**  
Early versions modified signal weights based on regime (e.g., suppressing MACD in choppy markets). This introduced a parameter explosion and made backtesting hard to reproduce. Regime is now logged for analysis but left out of the composite so signal weights remain stable and the relationship between regime and performance can be studied post-hoc.

**Why 0.4% SL / 0.8% TP at 5-minute intervals?**  
SOL can move 0.5–1% in a single 5-minute candle. Tight SL/TP means quick exits on wrong calls, preserving capital for the next signal. The 2:1 TP/SL ratio means a 33% win rate breaks even — the bot needs to win more than 1-in-3 trades. This is intentionally conservative for initial paper-trading calibration.

**Why contrarian normalization on Fear & Greed?**  
Extreme Fear historically marks capitulation lows; Extreme Greed marks euphoria peaks. The contrarian mapping (fear=bullish) exploits mean-reversion in sentiment rather than chasing momentum, which the RSI and MACD signals already cover.

**Why separate grid bot running in parallel?**  
The signal bot fires rarely (threshold-gated). The grid bot generates smaller but more frequent PnL from oscillation within a range. Together they cover both trending and ranging regimes without needing the regime signal to gate strategy selection.

**Why SQLite instead of a file or in-memory list?**  
`risk.trades` (in-memory list) is lost on every restart. `data.json` is overwritten every tick. SQLite is zero-dependency, persistent across restarts, and queryable. The `get_recent_trades()` result is loaded into `risk.trades` on startup so `realized_pnl` and the dashboard's Recent Trades panel are correct immediately.

**Why wrap all DB writes in try/except?**  
A disk-full error or locked DB must never interrupt a live trade execution. The trade still happens and gets recorded to the in-memory `risk.trades`; only the persistence silently fails.

---

## Data Flow (one tick)

```
get_sol_price()
    ↓
get_sol_sentiment() | get_news_sentiment() | get_macro_signal()
get_trump_signal()  | get_fear_greed()
    ↓
grid.update(price)                         ← grid trades → SQLite
    ↓
calculate_rsi() | calculate_macd()
    ↓
detect_regime()
    ↓
generate_signal()                          ← composite 0-1 score
    ↓
save_signal() → SQLite                     ← every tick
    ↓
check_sl_tp() / check_short_sl_tp()
    ↓ (if exit triggered)
close_position() → save_trade() → SQLite
    ↓ (if signal fires)
check_trade() → open/close position → save_trade() → SQLite
    ↓
write_state() → data.json                  ← dashboard reads this
```

---

## Runtime Files

| File | Purpose |
|---|---|
| `trading_bot.db` | SQLite — trades, signals, grid trades (persistent) |
| `data.json` | Dashboard state snapshot (overwritten every tick) |
| `sell_signals.csv` | Legacy CSV log of sell signal rows |
| `.env` | All secrets and config overrides |

---

## Dependencies

```
requests          HTTP client
python-dotenv     .env loading
pandas            RSI / MACD / ADX series calculations
numpy             Numeric operations
cryptography      AES wallet encryption
solders           Solana keypair + VersionedTransaction
anthropic         Claude API (present, not yet used in core loop)
vaderSentiment    Local NLP sentiment (installed separately: pip install vaderSentiment)
```

`vaderSentiment` is not in `requirements.txt` — install manually: `pip install vaderSentiment`. The module lazy-loads it so startup won't crash if it's missing; news and Trump scores will default to 0.5.

---

## Current Status (as of 2026-06-03)

- Paper trading only (`DRY_RUN=true`)
- SQLite persistence live — trades survive restarts
- All 7 signal sources wired and active
- Dashboard at port 8080 with `/stats` endpoint
- Grid bot running in parallel with signal bot
- Regime detection active (observation only)
- Live execution code path complete but untested with real funds

---

## Known Limitations / Next Steps

1. **Grid bot does not re-range** — initialized once from first tick's price history. If price moves significantly outside the initial range, the grid becomes ineffective. Add periodic re-ranging logic.

2. **Backtest uses only RSI + MACD** — no Polymarket, news, macro, trump, or fear/greed in backtest (those require live APIs). Backtest results understate performance of the full signal engine.

3. **No position for short in live mode** — shorts are paper-only. Live short execution would require a lending protocol integration.

4. **vaderSentiment not in requirements.txt** — should be added so `pip install -r requirements.txt` covers everything.

5. **Signal weights are fixed** — weights (news 20%, RSI 15%, MACD 15%, etc.) are hardcoded. A future improvement is to tune them against backtest results or use a simple rolling Sharpe per signal.

6. **Trump RSS feed can be rate-limited** — Truth Social occasionally returns non-200 responses; the module fails silently to neutral. No retry logic.

7. **Dashboard trades panel shows only in-memory trades** — after adding SQLite persistence, `data.json` is still populated from `risk.trades` (which is seeded from DB on startup). If the in-memory list grows beyond 20, older trades are truncated in the dashboard view. The full history is always in the DB.

8. **No alerting on DB errors** — silent `except` blocks mean a DB that stops accepting writes would go unnoticed until the next restart.

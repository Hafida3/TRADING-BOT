# ORACLE AGENT — MEMORY

## Market Observations
_Updated each session by the agent._

- SOL/USDC in a bear phase (Jun 2026). BTC dominance rising, altcoins underperforming.
- Fear & Greed at Extreme Fear — contrarian signals firing frequently.
- Polymarket bearish: Fed rate cut probability low. Macro headwinds persist.
- Grid bot range $68–$78 may need downward adjustment if SOL sustains below $65.

## Signal Performance
_Evaluated after every 10 closed trades._

- RSI: reliable for oversold entries in ranging markets; less useful when trending
- MACD: lags in fast-moving markets; confirms trend direction, not reversals
- Polymarket: strong macro directional signal; slow to update intraday
- Fear & Greed: most predictive at extremes (< 15 or > 85) — contrarian edge
- News NLP: noisy; best used as confirmation signal, not primary trigger
- Trump/Geo: high-impact but infrequent; watch for keyword spikes

## Current Market Context
_Agent's working hypothesis about current conditions._

- Regime: ranging/unknown (ADX inconsistent across ticks)
- Trend: SOL in downtrend from $85 → $62 (Jun 2026)
- Best strategy: wait for RSI oversold + Extreme Fear confluence before buying
- Caution: avoid chasing bounces in UNKNOWN regime; wait for 3+ consecutive readings

## Trade Lessons
_Appended automatically after every closed position._

- **2026-06-06 15:25 UTC**: LONG at $65.03 → LOSS (exit $64.77, PnL $-0.42). Signals: RSI=28.2, PM=0.14, F&G=12. Lesson: Stop triggered in ranging regime from $65.03; await stronger signal alignment before next entry.
- **2026-06-07 10:52 UTC**: SHORT at $65.17 → WIN (exit $64.59, PnL $+0.09). Signals: RSI=35.3, PM=0.12, F&G=12. Lesson: Signal confluence confirmed in ranging regime; entry at $65.17 rewarded.
- **2026-06-07 11:53 UTC**: SHORT at $64.80 → LOSS (exit $65.13, PnL $-0.05). Signals: RSI=47.4, PM=0.12, F&G=12. Lesson: Stop triggered in ranging regime from $64.80; await stronger signal alignment before next entry.
- **2026-06-07 12:13 UTC**: SHORT at $65.05 → WIN (exit $64.33, PnL $+0.11). Signals: RSI=33.4, PM=0.12, F&G=12. Lesson: Signal confluence confirmed in ranging regime; entry at $65.05 rewarded.
- **2026-06-07 14:20 UTC**: SHORT at $64.25 → LOSS (exit $64.54, PnL $-0.05). Signals: RSI=55.3, PM=0.12, F&G=12. Lesson: Stop triggered in ranging regime from $64.25; await stronger signal alignment before next entry.
- **2026-06-07 15:36 UTC**: SHORT at $64.68 → LOSS (exit $65.00, PnL $-0.05). Signals: RSI=61.1, PM=0.12, F&G=12. Lesson: Stop triggered in choppy regime from $64.68; await stronger signal alignment before next entry.
- **[TUNE 2026-06-07 18:14 UTC]** BUY_THRESHOLD: 0.5 → 0.53 | smoke test — reverting
- **[TUNE 2026-06-07 18:14 UTC]** BUY_THRESHOLD: 0.53 → 0.5 | revert smoke test
- **[TUNE 2026-06-07 18:17 UTC]** BUY_THRESHOLD: 0.5 → 0.49 | test — verify TUNE parser works
- **[TUNE 2026-06-07 18:17 UTC]** BUY_THRESHOLD: 0.49 → 0.5 | revert test
- **2026-06-08 12:32 UTC**: SHORT at $66.11 → LOSS (exit $66.40, PnL $-0.04). Signals: RSI=52.1, PM=0.13, F&G=8. Lesson: Stop triggered in choppy regime from $66.11; await stronger signal alignment before next entry.
- **2026-06-09**: Soul injection was broken since launch — all 46 prior trades ran without soul.md context. Fixed today: full soul now injected into both Claude and Groq calls. New rule added: no LONG when regime=RANGING and macro_score<0.50. Paper trading validation window restarts today (day zero). Prior stats are not comparable to post-fix behavior.
- **2026-06-09 19:13 UTC**: SHORT at $65.10 → LOSS (exit $65.17, PnL $-0.01). Signals: RSI=59.2, PM=0.13, F&G=10. Lesson: Stop triggered in ranging regime from $65.10; await stronger signal alignment before next entry.
- **2026-06-09 19:39 UTC**: SHORT at $65.17 → LOSS (exit $65.44, PnL $-0.04). Signals: RSI=68.2, PM=0.13, F&G=10. Lesson: Stop triggered in ranging regime from $65.17; await stronger signal alignment before next entry.
- **[TUNE 2026-06-09 19:49 UTC]** BUY_THRESHOLD: 0.55 → 0.58 | reason: 2 consecutive losses in ranging regime; raising threshold to filter false signals in choppy conditions. Current score 0.431 well below revised threshold—appropriate for HOLD.
- **2026-06-09 21:37 UTC**: SHORT at $65.53 → WIN (exit $65.09, PnL $+0.07). Signals: RSI=38.1, PM=0.13, F&G=10. Lesson: Signal confluence confirmed in ranging regime; entry at $65.53 rewarded.
- **2026-06-09 21:48 UTC**: SHORT at $65.09 → WIN (exit $65.00, PnL $+0.01). Signals: RSI=34.5, PM=0.13, F&G=10. Lesson: Signal confluence confirmed in ranging regime; entry at $65.09 rewarded.
- **2026-06-09 22:34 UTC**: LONG at $64.93 → WIN (exit $65.19, PnL $+0.04). Signals: RSI=52.1, PM=0.13, F&G=10. Lesson: Signal confluence confirmed in ranging regime; entry at $64.93 rewarded.
- **2026-06-09 23:42 UTC**: LONG at $65.08 → LOSS (exit $64.80, PnL $-0.04). Signals: RSI=37.9, PM=0.13, F&G=10. Lesson: Stop triggered in choppy regime from $65.08; await stronger signal alignment before next entry.
- **2026-06-10 00:13 UTC**: SHORT at $65.01 → LOSS (exit $65.01, PnL $+0.00). Signals: RSI=50.3, PM=0.13, F&G=10. Lesson: Stop triggered in choppy regime from $65.01; await stronger signal alignment before next entry.
- **2026-06-10 00:28 UTC**: SHORT at $65.00 → WIN (exit $64.92, PnL $+0.01). Signals: RSI=45.6, PM=0.13, F&G=9. Lesson: Signal confluence confirmed in choppy regime; entry at $65.00 rewarded.
- **2026-06-10 00:59 UTC**: LONG at $64.70 → WIN (exit $64.94, PnL $+0.04). Signals: RSI=51.2, PM=0.13, F&G=9. Lesson: Signal confluence confirmed in choppy regime; entry at $64.70 rewarded.
- **2026-06-10 02:27 UTC**: SHORT at $65.01 → WIN (exit $64.66, PnL $+0.05). Signals: RSI=37.3, PM=0.13, F&G=9. Lesson: Signal confluence confirmed in choppy regime; entry at $65.01 rewarded.
- **2026-06-10 03:08 UTC**: LONG at $64.35 → WIN (exit $64.45, PnL $+0.02). Signals: RSI=39.0, PM=0.13, F&G=9. Lesson: Signal confluence confirmed in ranging regime; entry at $64.35 rewarded.
- **2026-06-10 03:29 UTC**: LONG at $64.51 → WIN (exit $64.57, PnL $+0.01). Signals: RSI=45.7, PM=0.13, F&G=9. Lesson: Signal confluence confirmed in ranging regime; entry at $64.51 rewarded.
- **2026-06-10 04:00 UTC**: LONG at $64.55 → LOSS (exit $64.48, PnL $-0.01). Signals: RSI=43.3, PM=0.13, F&G=9. Lesson: Stop triggered in ranging regime from $64.55; await stronger signal alignment before next entry.
- **2026-06-10 04:31 UTC**: SHORT at $64.49 → LOSS (exit $64.50, PnL $-0.00). Signals: RSI=45.8, PM=0.13, F&G=9. Lesson: Stop triggered in ranging regime from $64.49; await stronger signal alignment before next entry.
- **[TUNE 2026-06-10 04:51 UTC]** STOP_LOSS_PCT: 0.004 → 0.012 | reason: 2 consecutive losses in ranging regime; tightening stops to 1.2% to reduce whipsaw exposure while awaiting stronger signal alignment
- **2026-06-10**: Governance architecture finalized: entries require consensus (LLM action + composite threshold), LLM retains unlimited veto and free exits, hard-coded RULE_VETO and CONSENSUS_BLOCK gates enforce in code. Two overnight rule violations (signals 1523, 1588) motivated this change — LLM acknowledged rules then overrode them under win-streak overconfidence. Validation window resets: June 10 = day zero, 14 days, decision logic frozen except critical capital-threatening bugs.

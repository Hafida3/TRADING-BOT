"""
SQLite persistence layer for trades, signals, and grid trades.
Database file: trading_bot.db in project root.
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent.parent / "trading_bot.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema creation."""
    existing_sig = {row[1] for row in conn.execute("PRAGMA table_info(signal_history)")}
    if "llm_reasoning" not in existing_sig:
        conn.execute("ALTER TABLE signal_history ADD COLUMN llm_reasoning TEXT")
    if "ma_score" not in existing_sig:
        conn.execute("ALTER TABLE signal_history ADD COLUMN ma_score REAL")
    if "stoch_score" not in existing_sig:
        conn.execute("ALTER TABLE signal_history ADD COLUMN stoch_score REAL")
    if "bb_score" not in existing_sig:
        conn.execute("ALTER TABLE signal_history ADD COLUMN bb_score REAL")

    existing_tr = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
    if "gross_pnl" not in existing_tr:
        conn.execute("ALTER TABLE trades ADD COLUMN gross_pnl REAL")
    if "fee_usdc" not in existing_tr:
        conn.execute("ALTER TABLE trades ADD COLUMN fee_usdc REAL")
    if "net_pnl" not in existing_tr:
        conn.execute("ALTER TABLE trades ADD COLUMN net_pnl REAL")

    existing_gt = {row[1] for row in conn.execute("PRAGMA table_info(grid_trades)")}
    if "gross_pnl" not in existing_gt:
        conn.execute("ALTER TABLE grid_trades ADD COLUMN gross_pnl REAL")
    if "fee_usdc" not in existing_gt:
        conn.execute("ALTER TABLE grid_trades ADD COLUMN fee_usdc REAL")
    if "net_pnl" not in existing_gt:
        conn.execute("ALTER TABLE grid_trades ADD COLUMN net_pnl REAL")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   REAL NOT NULL,
                direction   TEXT NOT NULL,
                entry_price REAL,
                exit_price  REAL,
                size_usdc   REAL,
                sol_amount  REAL,
                pnl_usdc    REAL,
                pnl_pct     REAL,
                regime      TEXT,
                signal_score REAL,
                fear_greed  REAL,
                trump_score REAL
            );

            CREATE TABLE IF NOT EXISTS signal_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     REAL NOT NULL,
                signal        TEXT,
                score         REAL,
                rsi           REAL,
                macd          REAL,
                polymarket    REAL,
                news          REAL,
                macro         REAL,
                trump         REAL,
                fear_greed    REAL,
                regime        TEXT,
                price         REAL,
                llm_reasoning TEXT
            );

            CREATE TABLE IF NOT EXISTS grid_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   REAL NOT NULL,
                level       INTEGER,
                entry_price REAL,
                exit_price  REAL,
                pnl_usdc    REAL
            );
        """)
        _migrate(conn)


def save_trade(
    trade: dict,
    signal_score: float = None,
    fear_greed: float = None,
    trump_score: float = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO trades
               (timestamp, direction, entry_price, exit_price, size_usdc,
                sol_amount, pnl_usdc, pnl_pct, regime, signal_score, fear_greed, trump_score,
                gross_pnl, fee_usdc, net_pnl)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade.get("exit_time", time.time()),
                trade.get("direction", ""),
                trade.get("entry_price"),
                trade.get("exit_price"),
                trade.get("size_usdc"),
                trade.get("sol_amount"),
                trade.get("pnl_usdc"),
                trade.get("pnl_pct"),
                trade.get("regime"),
                signal_score,
                fear_greed,
                trump_score,
                trade.get("gross_pnl"),
                trade.get("fee_usdc"),
                trade.get("net_pnl"),
            ),
        )


def save_signal(
    timestamp: float,
    signal: str,
    score: float,
    rsi: Optional[float],
    macd: Optional[float],
    polymarket: Optional[float],
    news: Optional[float],
    macro: Optional[float],
    fear_greed: Optional[float],
    regime: Optional[str],
    price: Optional[float],
    llm_reasoning: Optional[str] = None,
    ma_score: Optional[float] = None,
    stoch_score: Optional[float] = None,
    bb_score: Optional[float] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO signal_history
               (timestamp, signal, score, rsi, macd, polymarket, news, macro,
                trump, fear_greed, regime, price, llm_reasoning,
                ma_score, stoch_score, bb_score)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (timestamp, signal, score, rsi, macd, polymarket, news, macro,
             None, fear_greed, regime, price, llm_reasoning,
             ma_score, stoch_score, bb_score),
        )


def save_grid_trade(
    level: int,
    entry_price: float,
    exit_price: float,
    pnl_usdc: float,
    gross_pnl: float = None,
    fee_usdc: float = None,
    net_pnl: float = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO grid_trades
               (timestamp, level, entry_price, exit_price, pnl_usdc, gross_pnl, fee_usdc, net_pnl)
               VALUES (?,?,?,?,?,?,?,?)""",
            (time.time(), level, entry_price, exit_price, pnl_usdc,
             gross_pnl, fee_usdc, net_pnl),
        )


def get_signal_prices(n: int = 200) -> list[tuple[float, float]]:
    """Return up to n (timestamp, price) pairs from signal_history, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, price FROM signal_history "
            "WHERE price IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [(r["timestamp"], r["price"]) for r in reversed(rows)]


def get_recent_trades(n: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_stats() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT COALESCE(net_pnl, pnl_usdc) AS effective_pnl FROM trades"
        ).fetchall()

    if not rows:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "total_pnl": 0.0,
        }

    pnls = [r["effective_pnl"] for r in rows if r["effective_pnl"] is not None]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "total_trades": len(pnls),
        "win_rate":     round(wins / len(pnls), 4) if pnls else 0.0,
        "best_trade":   round(max(pnls), 4) if pnls else 0.0,
        "worst_trade":  round(min(pnls), 4) if pnls else 0.0,
        "total_pnl":    round(sum(pnls), 4) if pnls else 0.0,
    }

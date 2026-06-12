"""
v0.45a — Schema correction (pre-Coinbase).

Two changes, both required before any non-Binance connector writes to `trades`:

1. trades.trade_id (INTEGER) -> trades.exchange_trade_id (TEXT)
   Rationale: trade_id is an opaque exchange-native identifier, not an internal
   key. Binance uses integers; Coinbase uses strings. The internal PK is `id`
   (autoincrement) and is unaffected. SQLite can't ALTER a column's type/name
   in place, so this rebuilds the table: create trades_new with the corrected
   schema, copy all rows (casting trade_id -> TEXT), drop old trades, rename
   trades_new -> trades, recreate the index.

2. symbol_registry: add `instrument` column.
   BTC-USDT (Binance) and BTC-USD (Coinbase) are related but distinct pairs
   (different quote currencies -> basis risk exists and must stay visible).
   `instrument` groups pairs that share a base asset for cross-exchange
   analysis, without claiming they're the same canonical_symbol.

Idempotent-ish: checks current schema before acting; safe to re-run, but the
table rebuild step (1) is skipped if exchange_trade_id already exists.

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v045a_schema_correction.py
"""

import sqlite3
import time

DB_PATH = "kerno.db"

CREATE_TRADES_NEW_SQL = """
CREATE TABLE trades_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange_trade_id TEXT,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    event_time_ms INTEGER NOT NULL,
    ingest_time_ms INTEGER NOT NULL,
    raw TEXT,
    UNIQUE (exchange, symbol, exchange_trade_id)
);
"""

COPY_SQL = """
INSERT INTO trades_new
    (id, exchange, symbol, exchange_trade_id, price, quantity, side,
     event_time_ms, ingest_time_ms, raw)
SELECT
    id, exchange, symbol, CAST(trade_id AS TEXT), price, quantity, side,
    event_time_ms, ingest_time_ms, raw
FROM trades;
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
ON trades (symbol, event_time_ms);
"""


def migrate_trades(con: sqlite3.Connection):
    cur = con.cursor()
    cur.execute("PRAGMA table_info(trades)")
    cols = {row[1] for row in cur.fetchall()}

    if "exchange_trade_id" in cols:
        print("trades already has exchange_trade_id — skipping table rebuild.")
        return

    if "trade_id" not in cols:
        raise RuntimeError(
            "trades has neither trade_id nor exchange_trade_id — unexpected schema, aborting."
        )

    print("Rebuilding trades table (trade_id INTEGER -> exchange_trade_id TEXT)...")
    cur.execute("SELECT COUNT(*) FROM trades")
    before_count = cur.fetchone()[0]
    print(f"trades row count before: {before_count}")

    cur.execute("DROP TABLE IF EXISTS trades_new")
    cur.execute(CREATE_TRADES_NEW_SQL)

    t0 = time.time()
    cur.execute(COPY_SQL)
    con.commit()
    elapsed = time.time() - t0

    cur.execute("SELECT COUNT(*) FROM trades_new")
    after_count = cur.fetchone()[0]
    print(f"trades_new row count after copy: {after_count} (took {elapsed:.1f}s)")

    if after_count != before_count:
        raise RuntimeError(
            f"Row count mismatch after copy: before={before_count} after={after_count}. "
            "Aborting before dropping original trades table."
        )

    cur.execute("DROP TABLE trades")
    cur.execute("ALTER TABLE trades_new RENAME TO trades")
    cur.execute(CREATE_INDEX_SQL)
    con.commit()
    print("trades table rebuilt successfully.")


def migrate_symbol_registry(con: sqlite3.Connection):
    cur = con.cursor()
    cur.execute("PRAGMA table_info(symbol_registry)")
    cols = {row[1] for row in cur.fetchall()}

    if "instrument" in cols:
        print("symbol_registry already has instrument — skipping.")
        return

    print("Adding symbol_registry.instrument column...")
    cur.execute("ALTER TABLE symbol_registry ADD COLUMN instrument TEXT")
    con.commit()

    # Backfill existing rows: BTC-USDT -> BTC, ETH-USDT -> ETH
    # (derived from asset_base, which already exists per v0.25 seed)
    cur.execute("UPDATE symbol_registry SET instrument = asset_base WHERE instrument IS NULL")
    con.commit()

    cur.execute("SELECT canonical_symbol, exchange, asset_base, instrument FROM symbol_registry")
    for row in cur.fetchall():
        print(row)


def main():
    con = sqlite3.connect(DB_PATH)

    print("=== Step 1: trades schema correction ===")
    migrate_trades(con)

    print("\n=== Step 2: symbol_registry.instrument ===")
    migrate_symbol_registry(con)

    # Final sanity check
    cur = con.cursor()
    cur.execute("PRAGMA table_info(trades)")
    print("\nFinal trades schema:")
    for row in cur.fetchall():
        print(row)

    cur.execute("SELECT side, COUNT(*) FROM trades GROUP BY side")
    print("side distribution:", cur.fetchall())

    con.close()


if __name__ == "__main__":
    main()

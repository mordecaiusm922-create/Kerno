"""
v0.25 Market Schema migration.

Creates the canonical `trades` table (per docs/schemas.md Trade schema) and
backfills it from `market_events`. Idempotent: safe to re-run, will not duplicate
rows (uses INSERT OR IGNORE keyed on exchange+trade_id+symbol).

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v025_trades.py
"""

import sqlite3
import time

DB_PATH = "kerno.db"

CREATE_TRADES_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_id INTEGER,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    event_time_ms INTEGER NOT NULL,
    ingest_time_ms INTEGER NOT NULL,
    raw TEXT,
    UNIQUE (exchange, symbol, trade_id)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
ON trades (symbol, event_time_ms);
"""

BACKFILL_SQL = """
INSERT OR IGNORE INTO trades
    (exchange, symbol, trade_id, price, quantity, side, event_time_ms, ingest_time_ms, raw)
SELECT
    'binance' AS exchange,
    symbol,
    trade_id,
    price,
    quantity,
    CASE WHEN is_buyer_maker = 1 THEN 'sell' ELSE 'buy' END AS side,
    event_time_ms,
    ingest_time_ms,
    raw
FROM market_events
WHERE event_type = 'trade'
  AND trade_id IS NOT NULL;
"""


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("Creating trades table...")
    cur.execute(CREATE_TRADES_SQL)
    cur.execute(CREATE_INDEX_SQL)
    con.commit()

    cur.execute("SELECT COUNT(*) FROM market_events WHERE event_type = 'trade' AND trade_id IS NOT NULL")
    source_count = cur.fetchone()[0]
    print(f"Source rows (market_events, event_type='trade', trade_id NOT NULL): {source_count}")

    print("Backfilling...")
    t0 = time.time()
    cur.execute(BACKFILL_SQL)
    con.commit()
    elapsed = time.time() - t0

    cur.execute("SELECT COUNT(*) FROM trades")
    dest_count = cur.fetchone()[0]
    print(f"trades row count after backfill: {dest_count} (took {elapsed:.1f}s)")

    if dest_count != source_count:
        print(
            f"WARNING: row count mismatch. source={source_count} dest={dest_count}. "
            "This is expected only if some market_events rows have event_type != 'trade' "
            "or NULL trade_id (already excluded by WHERE clause), or if re-running after "
            "a partial previous run (INSERT OR IGNORE dedupes)."
        )
    else:
        print("OK: row counts match.")

    # sanity check: side distribution
    cur.execute("SELECT side, COUNT(*) FROM trades GROUP BY side")
    print("side distribution:", cur.fetchall())

    # sanity check: symbol distribution
    cur.execute("SELECT symbol, COUNT(*) FROM trades GROUP BY symbol")
    print("symbol distribution:", cur.fetchall())

    con.close()


if __name__ == "__main__":
    main()
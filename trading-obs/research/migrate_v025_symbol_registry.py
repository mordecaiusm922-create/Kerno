"""
v0.25 Market Schema - SymbolRegistry.

Creates the symbol_registry table (per docs/schemas.md) and seeds it with the
two symbols currently ingested: BTCUSDT and ETHUSDT on Binance spot/perp.

Idempotent: INSERT OR IGNORE keyed on (canonical_symbol, exchange).

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v025_symbol_registry.py
"""

import sqlite3

DB_PATH = "kerno.db"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS symbol_registry (
    canonical_symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    native_symbol TEXT NOT NULL,
    asset_base TEXT NOT NULL,
    asset_quote TEXT NOT NULL,
    instrument_type TEXT NOT NULL CHECK (instrument_type IN ('spot', 'perp', 'future')),
    tick_size REAL,
    lot_size REAL,
    PRIMARY KEY (canonical_symbol, exchange)
);
"""

# Note: ingestor.py currently connects to Binance's spot trade stream
# (wss://stream.binance.com) for BTCUSDT/ETHUSDT. instrument_type is set to
# 'spot' to match. If/when a perp feed is added, add separate rows with
# instrument_type='perp' and a distinct canonical_symbol
# (e.g. 'BTC-USDT-PERP' vs 'BTC-USDT').
SEED_ROWS = [
    ("BTC-USDT", "binance", "BTCUSDT", "BTC", "USDT", "spot", 0.01, 0.00001),
    ("ETH-USDT", "binance", "ETHUSDT", "ETH", "USDT", "spot", 0.01, 0.0001),
]

INSERT_SQL = """
INSERT OR IGNORE INTO symbol_registry
    (canonical_symbol, exchange, native_symbol, asset_base, asset_quote, instrument_type, tick_size, lot_size)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("Creating symbol_registry table...")
    cur.execute(CREATE_SQL)
    con.commit()

    print("Seeding rows...")
    cur.executemany(INSERT_SQL, SEED_ROWS)
    con.commit()

    cur.execute("SELECT * FROM symbol_registry")
    for row in cur.fetchall():
        print(row)

    con.close()


if __name__ == "__main__":
    main()

"""
v0.45c — symbol_registry: add Coinbase BTC-USD.

Resolves CHECK 2 (symbol registry resolution) from the v0.45 validation run:
coinbase/BTC-USD was UNRESOLVED because symbol_registry only had Binance rows.

Idempotent: INSERT OR IGNORE keyed on (canonical_symbol, exchange).

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v045c_coinbase_symbol.py
"""

import sqlite3

DB_PATH = "kerno.db"

# BTC-USD is a distinct pair from BTC-USDT (different quote currency -> basis
# risk between USDT and USD, confirmed measurable at ~0.05% in the v0.45
# validation run). It gets its own canonical_symbol, grouped under
# instrument='BTC' alongside BTC-USDT for cross-exchange queries.
INSERT_SQL = """
INSERT OR IGNORE INTO symbol_registry
    (canonical_symbol, exchange, native_symbol, asset_base, asset_quote, instrument, instrument_type, tick_size, lot_size)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

SEED_ROW = ("BTC-USD", "coinbase", "BTC-USD", "BTC", "USD", "BTC", "spot", 0.01, 0.00000001)


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(INSERT_SQL, SEED_ROW)
    con.commit()

    cur.execute("SELECT canonical_symbol, exchange, native_symbol, asset_base, asset_quote, instrument FROM symbol_registry")
    for row in cur.fetchall():
        print(row)

    con.close()


if __name__ == "__main__":
    main()
"""
v0.55a — symbol_registry: add Bybit BTCUSDT linear perpetual.

Per Finding #2 (docs/connectors.md): Bybit's linear perpetual uses the same
native symbol string "BTCUSDT" as Binance spot. To keep trades.symbol
collision-safe by construction, the perpetual is registered (and written to
trades by BybitConnector) as canonical_symbol/symbol="BTC-USDT-PERP" /
"BTCUSDT-PERP" respectively, distinct from Binance spot's "BTC-USDT"/"BTCUSDT".

native_symbol retains the true exchange-native value ("BTCUSDT") for reference
and for constructing API/WS calls to Bybit.

Idempotent: INSERT OR IGNORE keyed on (canonical_symbol, exchange).

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v055a_bybit_symbol.py
"""

import sqlite3

DB_PATH = "kerno.db"

INSERT_SQL = """
INSERT OR IGNORE INTO symbol_registry
    (canonical_symbol, exchange, native_symbol, asset_base, asset_quote, instrument, instrument_type, tick_size, lot_size)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

# tick_size/lot_size from Bybit's official BTCUSDT linear perpetual instrument info
# (priceFilter.tickSize=0.10, lotSizeFilter.qtyStep=0.001)
SEED_ROW = ("BTC-USDT-PERP", "bybit", "BTCUSDT", "BTC", "USDT", "BTC", "perp", 0.10, 0.001)


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(INSERT_SQL, SEED_ROW)
    con.commit()

    cur.execute("SELECT canonical_symbol, exchange, native_symbol, instrument, instrument_type FROM symbol_registry")
    for row in cur.fetchall():
        print(row)

    con.close()


if __name__ == "__main__":
    main()
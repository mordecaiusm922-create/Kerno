"""
v0.65a — symbol_registry: add OKX BTC-USDT spot.

Decision: OKX's BTC-USDT spot shares canonical_symbol="BTC-USDT" with Binance's
BTC-USDT spot (already in symbol_registry from v0.25). This differs from the
Bybit case (v0.55a), where BTCUSDT-PERP got its own canonical_symbol because it's
a structurally different instrument (perpetual vs spot) with real basis risk.
Here, OKX and Binance BTC-USDT are the same instrument type (spot) with the same
quote currency (USDT) — no basis risk to preserve, so a shared canonical_symbol is
correct: it's a clean spot-vs-spot cross-exchange comparison, same pattern as
Coinbase's BTC-USD except here both venues share the same quote currency too.

trades.symbol stays collision-safe by construction regardless: OKX's native
instId "BTC-USDT" (hyphenated) never collides with Binance's native "BTCUSDT"
(no hyphen) as a string, so no suffix is needed for OKX.

Idempotent: INSERT OR IGNORE keyed on (canonical_symbol, exchange).

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v065a_okx_symbol.py
"""

import sqlite3

DB_PATH = "kerno.db"

INSERT_SQL = """
INSERT OR IGNORE INTO symbol_registry
    (canonical_symbol, exchange, native_symbol, asset_base, asset_quote, instrument, instrument_type, tick_size, lot_size)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

# tick_size/lot_size from OKX BTC-USDT spot instrument info (tickSz=0.1, lotSz=0.00000001)
# canonical_symbol="BTC-USDT" shared with Binance's spot entry (same instrument type, same quote ccy)
SEED_ROW = ("BTC-USDT", "okx", "BTC-USDT", "BTC", "USDT", "BTC", "spot", 0.1, 0.00000001)


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(INSERT_SQL, SEED_ROW)
    con.commit()

    cur.execute("""
        SELECT canonical_symbol, exchange, native_symbol, instrument, instrument_type
        FROM symbol_registry
        ORDER BY canonical_symbol, exchange
    """)
    for row in cur.fetchall():
        print(row)

    con.close()


if __name__ == "__main__":
    main()

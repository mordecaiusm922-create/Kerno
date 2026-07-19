"""
v0.75a — basis_log table.

Stores periodic samples of the spot-vs-perp basis (Binance BTCUSDT vs Bybit
BTCUSDT-PERP), the first repeated pattern Kerno has observed (perp trading at
a small discount to spot, measured independently twice: -0.0387% on the v0.55
validation run, -0.0380% on the v0.65 run).

Two data points aren't a pattern yet — this table is what turns them into one.
Populated by research/basis_logger.py, a long-running script (not a fixed-
duration validation run).

Includes an optional OKX spot cross-check column: OKX and Binance are both
spot/BTC-USDT (near-zero basis expected between them, confirmed at v0.65), so
a divergence there would flag a Binance-specific pricing glitch rather than a
real spot-vs-perp signal.

Run from the project root (where kerno.db lives):
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\migrate_v075a_basis_log.py
"""

import sqlite3

DB_PATH = "kerno.db"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS basis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    spot_price REAL NOT NULL,
    spot_ts_ms INTEGER NOT NULL,
    perp_price REAL NOT NULL,
    perp_ts_ms INTEGER NOT NULL,
    basis_pct REAL NOT NULL,
    okx_price REAL,
    okx_ts_ms INTEGER
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_basis_log_ts ON basis_log (ts_ms);
"""


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(CREATE_SQL)
    cur.execute(CREATE_INDEX_SQL)
    con.commit()

    cur.execute("PRAGMA table_info(basis_log)")
    for row in cur.fetchall():
        print(row)

    con.close()


if __name__ == "__main__":
    main()

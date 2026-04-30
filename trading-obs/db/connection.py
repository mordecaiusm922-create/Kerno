"""
Database connection — SQLite para desarrollo local.
Swap a asyncpg/PostgreSQL en producción cambiando solo este archivo.
"""
import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "kerno.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Crea tablas e índices si no existen."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            price           REAL NOT NULL,
            quantity        REAL NOT NULL,
            event_time_ms   INTEGER NOT NULL,
            ingest_time_ms  INTEGER NOT NULL,
            trade_id        INTEGER,
            is_buyer_maker  INTEGER,
            raw             TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_symbol_time
            ON market_events (symbol, event_time_ms DESC);

        CREATE INDEX IF NOT EXISTS idx_event_time
            ON market_events (event_time_ms DESC);
    """)
    conn.commit()
    conn.close()
    print(f"[DB] Kerno inicializado en {DB_PATH}")

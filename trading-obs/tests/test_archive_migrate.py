import sqlite3
from dataclasses import replace

import pytest

from kerno.archive import DAY_MS, archive
from kerno.config import Settings
from kerno.ingest import write_trades
from kerno.migrate_sqlite import migrate
from tests.conftest import make_trades


def test_archive_then_delete(db, tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    old = make_trades(1200, start_ms=1_600_000_000_000)  # 2020: well past any cutoff
    write_trades(db, old, store_raw=False)
    settings = replace(Settings(), archive_dir=tmp_path / "arch", s3_bucket="")
    with pytest.raises(ValueError):
        archive(db, settings, before_days=0, delete=True)
    done = archive(db, settings, before_days=7, delete=True)
    assert sum(d["rows"] for d in done) == 1200
    files = list((tmp_path / "arch").rglob("*.parquet"))
    assert sum(pq.ParquetFile(f).metadata.num_rows for f in files) == 1200
    table = pq.read_table(files[0])
    assert table.column("event_time_ms").to_pylist() == sorted(table.column("event_time_ms").to_pylist())
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM trades") == 0
        assert c.scalar("SELECT SUM(rows) FROM archive_manifest") == 1200
    # idempotent
    assert archive(db, settings, before_days=7, delete=True) == []


def test_archive_keeps_recent(db, tmp_path):
    pytest.importorskip("pyarrow")
    import time

    recent = make_trades(100, start_ms=int(time.time() * 1000) - DAY_MS)
    write_trades(db, recent, store_raw=False)
    assert archive(db, replace(Settings(), archive_dir=tmp_path), before_days=7, delete=True) == []
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM trades") == 100


def _legacy_db(path):
    src = sqlite3.connect(path)
    src.executescript("""
        CREATE TABLE market_events (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, event_type TEXT, price REAL,
            quantity REAL, event_time_ms INTEGER, ingest_time_ms INTEGER, trade_id INTEGER, is_buyer_maker INTEGER, raw TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, exchange TEXT, symbol TEXT, exchange_trade_id TEXT,
            price REAL, quantity REAL, side TEXT, event_time_ms INTEGER, ingest_time_ms INTEGER, raw TEXT);
        CREATE TABLE symbol_registry (canonical_symbol TEXT, exchange TEXT, native_symbol TEXT, asset_base TEXT,
            asset_quote TEXT, instrument_type TEXT, tick_size REAL, lot_size REAL, instrument TEXT);
        CREATE TABLE basis_log (id INTEGER PRIMARY KEY, ts_ms INTEGER, spot_price REAL, spot_ts_ms INTEGER,
            perp_price REAL, perp_ts_ms INTEGER, basis_pct REAL, okx_price REAL, okx_ts_ms INTEGER);
        CREATE TABLE signal_outcomes (id INTEGER PRIMARY KEY);
    """)
    src.executemany("INSERT INTO market_events (symbol, event_type, price, quantity, event_time_ms, ingest_time_ms, "
                    "trade_id, is_buyer_maker, raw) VALUES (?, 'trade', ?, 1, ?, ?, ?, ?, '{}')",
                    [("BTCUSDT", 100 + i, 1000 + i, 1001 + i, i, i % 2) for i in range(50)])
    # the same trades were backfilled into `trades` in v0.25 -> must not duplicate
    src.executemany("INSERT INTO trades (exchange, symbol, exchange_trade_id, price, quantity, side, event_time_ms, "
                    "ingest_time_ms) VALUES ('binance', 'BTCUSDT', ?, ?, 1, ?, ?, ?)",
                    [(str(i), 100 + i, "sell" if i % 2 else "buy", 1000 + i, 1001 + i) for i in range(50)])
    src.execute("INSERT INTO trades (exchange, symbol, exchange_trade_id, price, quantity, side, event_time_ms, "
                "ingest_time_ms) VALUES ('okx', 'BTC-USDT', 'x', -5, 1, 'buy', 1, 1)")  # invalid, skipped
    src.execute("INSERT INTO symbol_registry VALUES ('BTC-USD','coinbase','BTC-USD','BTC','USD','spot',0.01,1e-8,'BTC')")
    src.execute("INSERT INTO basis_log VALUES (1, 5, 100, 5, 99, 5, -1, NULL, NULL)")
    src.commit()
    src.close()


def test_migrate_legacy_sqlite(db, tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_db(path)
    report = migrate(path, db)
    assert report["skipped_invalid"] == 1
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM trades") == 50
        assert c.scalar("SELECT COUNT(*) FROM trades WHERE side = 'sell'") == 25
        assert c.scalar("SELECT COUNT(*) FROM basis_log") == 1
    migrate(path, db)  # re-runnable
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM trades") == 50


def test_migrate_v1_sqlite_signals(db, tmp_path):
    from kerno.db import Database
    from kerno.engine import SignalEngine, process_range
    from kerno.validator import validate_pending
    from tests.conftest import make_trades

    local = Database(f"sqlite:///{tmp_path / 'v1.db'}")
    local.migrate()
    write_trades(local, make_trades(3000), store_raw=False)
    process_range(local, SignalEngine("binance", "BTCUSDT"), (0, ""), 2**62)
    validate_pending(local, 10, 250)
    with local.connect() as c:
        expected = c.fetchall("SELECT exchange_trade_id, status, pnl_10s_bps, features FROM signals ORDER BY id")
    report = migrate(tmp_path / "v1.db", db)
    assert report["signals"] == len(expected) > 0 and report["trades"] == 3000
    with db.connect() as c:
        got = c.fetchall("SELECT exchange_trade_id, status, pnl_10s_bps, features FROM signals ORDER BY event_time_ms")
    assert got == expected
